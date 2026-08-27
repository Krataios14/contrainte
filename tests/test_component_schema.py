from __future__ import annotations

import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from contrainte.canonical import loads_strict
from contrainte.cli import main
from contrainte.component import (
    COMPONENT_SCHEMA,
    COMPONENT_SCHEMA_V1,
    COMPONENT_SCHEMA_V3,
    COMPONENT_SCHEMA_V4,
    ArtifactRole,
    ComponentManifest,
    InterfaceAttachmentKind,
    InterfaceAttachmentRole,
    InterfaceDirection,
    InterfaceKind,
    LifecycleState,
    Qualification,
)
from contrainte.component_schema import (
    JSON_SCHEMA_DIALECT,
    SUPPORTED_COMPONENT_MANIFEST_SCHEMA_VERSIONS,
    component_manifest_json_schema,
    component_manifest_json_schema_text,
    export_component_manifest_json_schema,
)
from contrainte.errors import InputError

try:
    from jsonschema import Draft202012Validator
except ImportError:  # The runtime and base test environment are dependency-free.
    Draft202012Validator = None  # type: ignore[assignment,misc]


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FIXTURES = {
    COMPONENT_SCHEMA_V1: ROOT / "schemas" / "component-manifest-0.1.schema.json",
    COMPONENT_SCHEMA: ROOT / "schemas" / "component-manifest-0.2.schema.json",
    COMPONENT_SCHEMA_V3: ROOT / "schemas" / "component-manifest-0.3.schema.json",
    COMPONENT_SCHEMA_V4: ROOT / "schemas" / "component-manifest-0.4.schema.json",
}
_BUNDLE_DIGEST = "sha256:" + "1" * 64


def _manifest_v1() -> dict:
    return {
        "schema_version": COMPONENT_SCHEMA_V1,
        "component_id": "component.schema.fixture",
        "revision": "A",
        "title": "Schema fixture",
        "lifecycle_state": "concept",
        "qualification": "unqualified_demonstration",
        "source_bundle_digest": _BUNDLE_DIGEST,
        "artifacts": [
            {
                "artifact_id": "engineering-bundle",
                "role": "engineering_bundle",
                "media_type": "application/json",
                "digest": _BUNDLE_DIGEST,
                "locator": "fixtures/source.bundle.json",
            }
        ],
        "interfaces": [
            {
                "interface_id": "mount",
                "kind": "mechanical",
                "direction": "bidirectional",
                "medium": "bolted_joint",
                "properties": {"datum": "base"},
            }
        ],
        "capabilities": ["mount"],
        "metadata": {"data_class": "synthetic"},
    }


def _bounds() -> dict:
    return {
        "frame": "engineering_bundle",
        "unit": "mm",
        "minimum": {"x": "-10", "y": "-5", "z": "0"},
        "maximum": {"x": "10", "y": "5", "z": "2"},
    }


def _frame() -> dict:
    return {
        "reference": "engineering_bundle",
        "unit": "mm",
        "origin": {"x": "0", "y": "0", "z": "2"},
        "basis": {
            "x_axis": {"x": "1", "y": "0", "z": "0"},
            "y_axis": {"x": "0", "y": "1", "z": "0"},
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        },
    }


def _manifest_v2() -> dict:
    document = _manifest_v1()
    document["schema_version"] = COMPONENT_SCHEMA
    document["geometry_bounds"] = _bounds()
    return document


def _manifest_v3() -> dict:
    document = _manifest_v2()
    document["schema_version"] = COMPONENT_SCHEMA_V3
    document["interfaces"][0]["frame"] = _frame()
    return document


def _manifest_v4() -> dict:
    document = _manifest_v3()
    document["schema_version"] = COMPONENT_SCHEMA_V4
    document["interfaces"][0]["attachment"] = {
        "selector": {
            "kind": "prismatic_stock_face",
            "feature_id": "stock",
            "role": "positive_z",
        },
        "evidence": {
            "source_feature_digest": "sha256:" + "2" * 64,
            "matched_face_count": 1,
            "surface_type": "plane",
            "origin_on_surface": True,
            "orientation_matches": True,
            "characteristic_point_mm": {"x": "0", "y": "0", "z": "2"},
            "direction": {"x": "0", "y": "0", "z": "1"},
        },
    }
    return document


def _manifests() -> dict[str, dict]:
    return {
        COMPONENT_SCHEMA_V1: _manifest_v1(),
        COMPONENT_SCHEMA: _manifest_v2(),
        COMPONENT_SCHEMA_V3: _manifest_v3(),
        COMPONENT_SCHEMA_V4: _manifest_v4(),
    }


def _negative_documents() -> tuple[tuple[str, str, dict], ...]:
    unknown = _manifest_v1()
    unknown["future_claim"] = True
    v1_bounds = _manifest_v1()
    v1_bounds["geometry_bounds"] = _bounds()
    v2_frame = _manifest_v2()
    v2_frame["interfaces"][0]["frame"] = _frame()
    v3_missing_frame = _manifest_v3()
    del v3_missing_frame["interfaces"][0]["frame"]
    v4_missing_evidence = _manifest_v4()
    del v4_missing_evidence["interfaces"][0]["attachment"]["evidence"]
    bad_digest = _manifest_v4()
    bad_digest["artifacts"][0]["digest"] = "SHA256:not-a-digest"
    return (
        ("unknown field", COMPONENT_SCHEMA_V1, unknown),
        ("v1 geometry bounds", COMPONENT_SCHEMA_V1, v1_bounds),
        ("v2 interface frame", COMPONENT_SCHEMA, v2_frame),
        ("v3 missing frame", COMPONENT_SCHEMA_V3, v3_missing_frame),
        ("v4 missing evidence", COMPONENT_SCHEMA_V4, v4_missing_evidence),
        ("bad digest", COMPONENT_SCHEMA_V4, bad_digest),
    )


class ComponentManifestSchemaTests(unittest.TestCase):
    def test_supported_versions_are_explicit_and_ordered(self) -> None:
        self.assertEqual(
            SUPPORTED_COMPONENT_MANIFEST_SCHEMA_VERSIONS,
            (
                COMPONENT_SCHEMA_V1,
                COMPONENT_SCHEMA,
                COMPONENT_SCHEMA_V3,
                COMPONENT_SCHEMA_V4,
            ),
        )

    def test_each_parser_round_trip_matches_its_exported_shape(self) -> None:
        for schema_version, document in _manifests().items():
            with self.subTest(schema_version=schema_version):
                parsed = ComponentManifest.from_dict(document)
                canonical = parsed.as_dict()
                self.assertEqual(canonical, document)
                self.assertEqual(
                    ComponentManifest.from_dict(canonical).as_dict(), canonical
                )
                schema = component_manifest_json_schema(schema_version)
                self.assertEqual(schema["$schema"], JSON_SCHEMA_DIALECT)
                self.assertEqual(
                    schema["properties"]["schema_version"]["const"], schema_version
                )
                if Draft202012Validator is not None:
                    Draft202012Validator(schema).validate(canonical)

    def test_parser_and_schema_reject_version_specific_negative_documents(self) -> None:
        for label, schema_version, document in _negative_documents():
            with self.subTest(label=label):
                with self.assertRaises(InputError):
                    ComponentManifest.from_dict(document)
                if Draft202012Validator is not None:
                    errors = list(
                        Draft202012Validator(
                            component_manifest_json_schema(schema_version)
                        ).iter_errors(document)
                    )
                    self.assertTrue(errors)

    @unittest.skipIf(
        Draft202012Validator is None,
        "jsonschema is optional and is not a Contrainte runtime dependency",
    )
    def test_exports_are_valid_draft_2020_12_schemas(self) -> None:
        assert Draft202012Validator is not None
        for schema_version in SUPPORTED_COMPONENT_MANIFEST_SCHEMA_VERSIONS:
            with self.subTest(schema_version=schema_version):
                Draft202012Validator.check_schema(
                    component_manifest_json_schema(schema_version)
                )

    def test_committed_fixtures_match_deterministic_export(self) -> None:
        self.assertEqual(set(SCHEMA_FIXTURES), set(_manifests()))
        for schema_version, fixture in SCHEMA_FIXTURES.items():
            with self.subTest(schema_version=schema_version):
                expected = component_manifest_json_schema_text(schema_version)
                committed = fixture.read_text(encoding="utf-8").replace("\r\n", "\n")
                self.assertEqual(committed, expected)
                self.assertEqual(loads_strict(committed), loads_strict(expected))

    def test_schema_results_are_fresh_and_deterministic(self) -> None:
        expected = component_manifest_json_schema_text(COMPONENT_SCHEMA_V4)
        first = component_manifest_json_schema(COMPONENT_SCHEMA_V4)
        first["title"] = "caller mutation"
        first["$defs"]["exact_interface_frame"]["properties"]["basis"]["properties"][
            "x_axis"
        ]["properties"]["x"]["not"]["const"] = "caller mutation"
        second = component_manifest_json_schema(COMPONENT_SCHEMA_V4)

        self.assertNotEqual(first, second)
        self.assertEqual(
            component_manifest_json_schema_text(COMPONENT_SCHEMA_V4), expected
        )

    def test_unsupported_schema_version_fails_closed(self) -> None:
        for value in ("contrainte.component-manifest/0.5", "0.4", None):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(InputError, "unsupported"),
            ):
                component_manifest_json_schema(value)  # type: ignore[arg-type]

    def test_parser_enums_match_frozen_public_schemas(self) -> None:
        v1 = component_manifest_json_schema(COMPONENT_SCHEMA_V1)
        properties = v1["properties"]
        interface = v1["$defs"]["interface"]["properties"]
        artifact = v1["$defs"]["artifact"]["properties"]

        self.assertEqual(
            artifact["role"]["enum"], [member.value for member in ArtifactRole]
        )
        self.assertEqual(
            interface["kind"]["enum"], [member.value for member in InterfaceKind]
        )
        self.assertEqual(
            interface["direction"]["enum"],
            [member.value for member in InterfaceDirection],
        )
        self.assertEqual(
            properties["lifecycle_state"]["enum"],
            [member.value for member in LifecycleState],
        )
        self.assertEqual(
            properties["qualification"]["enum"],
            [member.value for member in Qualification],
        )

        selector_branches = component_manifest_json_schema(COMPONENT_SCHEMA_V4)[
            "$defs"
        ]["attachment_selector"]["oneOf"]
        self.assertEqual(
            [branch["properties"]["kind"]["const"] for branch in selector_branches],
            [member.value for member in InterfaceAttachmentKind],
        )
        exported_roles = set(selector_branches[0]["properties"]["role"]["enum"])
        exported_roles.add(selector_branches[1]["properties"]["role"]["const"])
        self.assertEqual(
            exported_roles, {member.value for member in InterfaceAttachmentRole}
        )

    def test_runtime_only_semantic_invariants_are_named_and_enforced(self) -> None:
        schema = component_manifest_json_schema(COMPONENT_SCHEMA_V4)
        invariants = schema["x-contrainte-runtime-only-semantic-invariants"]
        invariant_ids = {item["id"] for item in invariants}
        self.assertEqual(len(invariant_ids), len(invariants))
        self.assertIn("component.source-bundle-linkage", invariant_ids)
        self.assertIn("component.frame-basis-orthonormal-right-handed", invariant_ids)
        self.assertIn("component.attachment-evidence-frame-binding", invariant_ids)
        self.assertTrue(all(item["description"] for item in invariants))

        duplicate_id = _manifest_v1()
        duplicate_artifact = copy.deepcopy(duplicate_id["artifacts"][0])
        duplicate_artifact["role"] = "drawing"
        duplicate_artifact["locator"] = "fixtures/drawing.svg"
        duplicate_artifact["digest"] = "sha256:" + "3" * 64
        duplicate_id["artifacts"].append(duplicate_artifact)
        with self.assertRaisesRegex(InputError, "artifact identifiers must be unique"):
            ComponentManifest.from_dict(duplicate_id)

        non_unit = _manifest_v3()
        non_unit["interfaces"][0]["frame"]["basis"]["x_axis"] = {
            "x": "1",
            "y": "1",
            "z": "0",
        }
        with self.assertRaisesRegex(InputError, "exact unit vector"):
            ComponentManifest.from_dict(non_unit)

        if Draft202012Validator is not None:
            Draft202012Validator(
                component_manifest_json_schema(COMPONENT_SCHEMA_V1)
            ).validate(duplicate_id)
            Draft202012Validator(
                component_manifest_json_schema(COMPONENT_SCHEMA_V3)
            ).validate(non_unit)

    def test_api_and_cli_write_identical_schema_bytes(self) -> None:
        expected = component_manifest_json_schema_text(COMPONENT_SCHEMA_V4)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(
                main(["component", "schema", COMPONENT_SCHEMA_V4]),
                0,
            )
        self.assertEqual(stdout.getvalue(), expected)

        with tempfile.TemporaryDirectory() as temporary:
            api_path = Path(temporary) / "api.schema.json"
            cli_path = Path(temporary) / "cli.schema.json"
            self.assertEqual(
                export_component_manifest_json_schema(COMPONENT_SCHEMA_V4, api_path),
                api_path,
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(
                    main(
                        [
                            "component",
                            "schema",
                            COMPONENT_SCHEMA_V4,
                            "--output",
                            str(cli_path),
                        ]
                    ),
                    0,
                )
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(api_path.read_bytes(), expected.encode("utf-8"))
            self.assertEqual(cli_path.read_bytes(), expected.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
