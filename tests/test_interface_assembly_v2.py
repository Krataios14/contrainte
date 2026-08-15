from __future__ import annotations

import copy
import importlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import contrainte
from contrainte.canonical import digest, loads_strict
from contrainte.cli import main as cli_main
from contrainte.errors import ContrainteError, InputError
from contrainte.interface_assembly import (
    INTERFACE_ASSEMBLY_RESULT_SCHEMA,
    INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2,
    INTERFACE_ASSEMBLY_SCHEMA,
    INTERFACE_ASSEMBLY_SCHEMA_V2,
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    InterfaceAssembly,
    InterfaceAssemblyResult,
    InterfaceEvidenceSummary,
    InterfaceOccurrenceV2,
    ParticipantEvidenceSummary,
    ProtectedReferenceParticipant,
    ReleasedComponentParticipant,
    SolveStatus,
    solve_interface_assembly,
    verify_interface_assembly_result,
)
from contrainte.reference_component import (
    EvidenceAuthority,
    ReferenceComponentManifest,
    project_design_around,
    seal_design_around_request,
    seal_reference_component,
)

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PAYLOAD = ROOT / "examples" / "reference-motor-payload.json"
REQUEST_PAYLOAD = ROOT / "examples" / "reference-motor-design-around-payload.json"
MIXED_EXAMPLE = ROOT / "examples" / "mixed-reference-motor-interface.json"
DIGEST = "sha256:" + "1" * 64


def identity_transform() -> dict[str, object]:
    return {
        "schema_version": "contrainte.exact-rigid-transform/0.1",
        "unit": "mm",
        "translation": {"x": "0", "y": "0", "z": "0"},
        "basis": {
            "x_axis": {"x": "1", "y": "0", "z": "0"},
            "y_axis": {"x": "0", "y": "1", "z": "0"},
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        },
    }


def released_component() -> dict[str, object]:
    return {
        "schema_version": "contrainte.component-manifest/0.3",
        "component_id": "surrounding-bracket",
        "revision": "A",
        "title": "Synthetic surrounding bracket",
        "lifecycle_state": "concept",
        "qualification": "unqualified_demonstration",
        "source_bundle_digest": DIGEST,
        "artifacts": [
            {
                "artifact_id": "bundle",
                "role": "engineering_bundle",
                "media_type": "application/json",
                "digest": DIGEST,
                "locator": "bundle.json",
            }
        ],
        "interfaces": [
            {
                "interface_id": "mount",
                "kind": "mechanical",
                "direction": "bidirectional",
                "medium": "bolted-flange",
                "properties": {"bolt-pattern": "4xM8-PCD100"},
                "frame": {
                    "reference": "engineering_bundle",
                    "unit": "mm",
                    "origin": {"x": "0", "y": "0", "z": "0"},
                    "basis": identity_transform()["basis"],
                },
            }
        ],
        "capabilities": [],
        "geometry_bounds": {
            "frame": "engineering_bundle",
            "unit": "mm",
            "minimum": {"x": "-10", "y": "-10", "z": "-10"},
            "maximum": {"x": "10", "y": "10", "z": "10"},
        },
        "metadata": {},
    }


def protected_documents(
    *,
    observational: bool = False,
    add_unrequested: bool = False,
    mount_x: str = "0",
    attach_authorized: bool = True,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    component_payload = loads_strict(REFERENCE_PAYLOAD.read_bytes())
    component_payload["reference_frames"][0]["transform"]["translation"]["x"] = mount_x
    if observational:
        component_payload["evidence"][0]["kind"] = "gaussian_splat"
        component_payload["evidence"][0]["authority"] = "observation"
    if add_unrequested:
        extra = copy.deepcopy(component_payload["reference_frames"][0])
        extra["frame_id"] = "unused"
        component_payload["reference_frames"].append(extra)
        component_payload["reference_frames"].sort(key=lambda item: item["frame_id"])
        component_payload["evidence"][0]["supports"].append("/reference_frames/unused")
        component_payload["evidence"][0]["supports"].sort()
    if not attach_authorized:
        component_payload["allowed_operations"].remove("attach_at_declared_interface")
    component_document = seal_reference_component(component_payload)
    component = ReferenceComponentManifest.from_dict(component_document)

    request_payload = loads_strict(REQUEST_PAYLOAD.read_bytes())
    request_payload["reference_component_digest"] = component.content_digest
    request_document = seal_design_around_request(request_payload)
    from contrainte.reference_component import DesignAroundRequest

    request = DesignAroundRequest.from_dict(request_document)
    projection = project_design_around(component, request).as_dict()
    return component_document, request_document, projection


def v2_assembly_document(
    *,
    observational: bool = False,
    add_unrequested: bool = False,
    mount_x: str = "0",
    attach_authorized: bool = True,
) -> dict[str, object]:
    component, request, projection = protected_documents(
        observational=observational,
        add_unrequested=add_unrequested,
        mount_x=mount_x,
        attach_authorized=attach_authorized,
    )
    return {
        "schema_version": INTERFACE_ASSEMBLY_SCHEMA_V2,
        "occurrences": [
            {
                "occurrence_id": "surrounding-bracket",
                "participant": {
                    "kind": "released_component",
                    "component": released_component(),
                },
            },
            {
                "occurrence_id": "traction-motor",
                "participant": {
                    "kind": "protected_reference",
                    "reference_component": component,
                    "design_around_request": request,
                    "design_around_projection": projection,
                },
                "anchor_transform": identity_transform(),
            },
        ],
        "mates": [
            {
                "mate_id": "motor-mount",
                "first": {
                    "occurrence_id": "traction-motor",
                    "interface_id": "mount",
                },
                "second": {
                    "occurrence_id": "surrounding-bracket",
                    "interface_id": "mount",
                },
                "property_keys": ["bolt-pattern"],
                "alternatives": [
                    {
                        "alternative_id": "coincident",
                        "preference_rank": 0,
                        "second_interface_in_first_interface": identity_transform(),
                    }
                ],
            }
        ],
        "candidate_budget": 1,
    }


def v2_cycle_document(*, two_cycle_alternatives: bool) -> dict[str, object]:
    def cycle_component(component_id: str, interface_ids: tuple[str, str]):
        document = released_component()
        document["component_id"] = component_id
        document["title"] = component_id
        source_interface = document["interfaces"][0]
        document["interfaces"] = []
        for interface_id in interface_ids:
            item = copy.deepcopy(source_interface)
            item["interface_id"] = interface_id
            document["interfaces"].append(item)
        return document

    closing_alternatives = [
        {
            "alternative_id": "contradiction",
            "preference_rank": 0,
            "second_interface_in_first_interface": {
                **identity_transform(),
                "translation": {"x": "1", "y": "0", "z": "0"},
            },
        }
    ]
    if two_cycle_alternatives:
        closing_alternatives.append(
            {
                "alternative_id": "closure",
                "preference_rank": 1,
                "second_interface_in_first_interface": identity_transform(),
            }
        )
    return {
        "schema_version": INTERFACE_ASSEMBLY_SCHEMA_V2,
        "occurrences": [
            {
                "occurrence_id": occurrence_id,
                "participant": {
                    "kind": "released_component",
                    "component": cycle_component(component_id, interface_ids),
                },
                **(
                    {"anchor_transform": identity_transform()}
                    if occurrence_id == "a"
                    else {}
                ),
            }
            for occurrence_id, component_id, interface_ids in (
                ("a", "cycle-a", ("ab", "ac")),
                ("b", "cycle-b", ("ba", "bc")),
                ("c", "cycle-c", ("ca", "cb")),
            )
        ],
        "mates": [
            {
                "mate_id": "ab",
                "first": {"occurrence_id": "a", "interface_id": "ab"},
                "second": {"occurrence_id": "b", "interface_id": "ba"},
                "property_keys": [],
                "alternatives": [
                    {
                        "alternative_id": "identity",
                        "preference_rank": 0,
                        "second_interface_in_first_interface": identity_transform(),
                    }
                ],
            },
            {
                "mate_id": "ac",
                "first": {"occurrence_id": "a", "interface_id": "ac"},
                "second": {"occurrence_id": "c", "interface_id": "ca"},
                "property_keys": [],
                "alternatives": closing_alternatives,
            },
            {
                "mate_id": "bc",
                "first": {"occurrence_id": "b", "interface_id": "bc"},
                "second": {"occurrence_id": "c", "interface_id": "cb"},
                "property_keys": [],
                "alternatives": [
                    {
                        "alternative_id": "identity",
                        "preference_rank": 0,
                        "second_interface_in_first_interface": identity_transform(),
                    }
                ],
            },
        ],
        "candidate_budget": 1,
    }


class InterfaceAssemblyV2Tests(unittest.TestCase):
    def test_public_participant_types_are_exported(self) -> None:
        self.assertIs(contrainte.InterfaceOccurrenceV2, InterfaceOccurrenceV2)
        self.assertIs(
            contrainte.ProtectedReferenceParticipant,
            ProtectedReferenceParticipant,
        )
        self.assertIs(
            contrainte.ReleasedComponentParticipant,
            ReleasedComponentParticipant,
        )
        self.assertIs(contrainte.InterfaceEvidenceSummary, InterfaceEvidenceSummary)
        self.assertIs(
            contrainte.ParticipantEvidenceSummary,
            ParticipantEvidenceSummary,
        )

    def test_checked_in_mixed_motor_example_solves_and_replays(self) -> None:
        assembly = InterfaceAssembly.from_dict(loads_strict(MIXED_EXAMPLE.read_bytes()))
        result = solve_interface_assembly(assembly)
        self.assertTrue(verify_interface_assembly_result(assembly, result))

    def test_mixed_participants_parse_solve_and_bind_input_digest(self) -> None:
        assembly = InterfaceAssembly.from_dict(v2_assembly_document())
        self.assertEqual(assembly.schema_version, INTERFACE_ASSEMBLY_SCHEMA_V2)
        self.assertIsInstance(assembly.occurrences[0], InterfaceOccurrenceV2)
        self.assertIsInstance(
            assembly.occurrences[0].participant, ReleasedComponentParticipant
        )
        self.assertIsInstance(
            assembly.occurrences[1].participant, ProtectedReferenceParticipant
        )
        with self.assertRaisesRegex(InputError, "not accepted by component-assembly"):
            _ = assembly.occurrences[0].component
        with self.assertRaisesRegex(InputError, "not accepted by component-assembly"):
            _ = assembly.occurrences[1].component

        result = solve_interface_assembly(assembly)

        self.assertEqual(result.schema_version, INTERFACE_ASSEMBLY_RESULT_SCHEMA_V2)
        self.assertEqual(result.assembly_digest, digest(assembly.as_dict()))
        self.assertIs(result.release_eligible, False)
        self.assertEqual(
            tuple(item.occurrence_id for item in result.participant_evidence),
            ("surrounding-bracket", "traction-motor"),
        )
        self.assertTrue(verify_interface_assembly_result(assembly, result))

    def test_physical_reference_interface_requires_attach_authority(self) -> None:
        with self.assertRaisesRegex(
            InputError, "attach_at_declared_interface authority"
        ):
            InterfaceAssembly.from_dict(v2_assembly_document(attach_authorized=False))

    def test_v2_round_trip_is_canonical(self) -> None:
        first = InterfaceAssembly.from_dict(v2_assembly_document())
        second = InterfaceAssembly.from_dict(first.as_dict())
        self.assertEqual(second.as_dict(), first.as_dict())
        result = solve_interface_assembly(first)
        self.assertEqual(
            InterfaceAssemblyResult.from_dict(result.as_dict()).as_dict(),
            result.as_dict(),
        )

    def test_protected_exact_frame_drives_the_solved_world_pose(self) -> None:
        assembly = InterfaceAssembly.from_dict(v2_assembly_document(mount_x="25/2"))
        result = solve_interface_assembly(assembly)
        bracket = next(
            item
            for item in result.occurrence_transforms
            if item.occurrence_id == "surrounding-bracket"
        )
        self.assertEqual(bracket.transform.translation.x.numerator, 25)
        self.assertEqual(bracket.transform.translation.x.denominator, 2)
        self.assertTrue(verify_interface_assembly_result(assembly, result))

    def test_v1_example_serialization_and_result_shape_remain_unchanged(self) -> None:
        source = loads_strict(
            (ROOT / "examples" / "motor-design-around-interface.json").read_bytes()
        )
        assembly = InterfaceAssembly.from_dict(source)
        result = solve_interface_assembly(assembly)
        self.assertEqual(assembly.schema_version, INTERFACE_ASSEMBLY_SCHEMA)
        self.assertEqual(result.schema_version, INTERFACE_ASSEMBLY_RESULT_SCHEMA)
        self.assertNotIn("participant", assembly.as_dict()["occurrences"][0])
        self.assertNotIn("assembly_digest", result.as_dict())
        self.assertTrue(verify_interface_assembly_result(assembly, result))

    def test_result_digest_rejects_otherwise_compatible_input(self) -> None:
        assembly = InterfaceAssembly.from_dict(v2_assembly_document())
        result = solve_interface_assembly(assembly)
        changed = copy.deepcopy(assembly.as_dict())
        changed["occurrences"][0]["participant"]["component"]["title"] = "Changed"
        other = InterfaceAssembly.from_dict(changed)
        self.assertFalse(verify_interface_assembly_result(other, result))

        result_document = result.as_dict()
        result_document["assembly_digest"] = DIGEST
        rebound = InterfaceAssemblyResult.from_dict(result_document)
        self.assertFalse(verify_interface_assembly_result(assembly, rebound))

    def test_v2_digest_binding_covers_unsatisfiable_and_inconclusive_results(
        self,
    ) -> None:
        unsatisfiable = InterfaceAssembly.from_dict(
            v2_cycle_document(two_cycle_alternatives=False)
        )
        unsatisfiable_result = solve_interface_assembly(unsatisfiable)
        self.assertIs(unsatisfiable_result.status, SolveStatus.UNSATISFIABLE)
        self.assertEqual(
            unsatisfiable_result.assembly_digest, digest(unsatisfiable.as_dict())
        )
        self.assertTrue(
            verify_interface_assembly_result(unsatisfiable, unsatisfiable_result)
        )

        inconclusive = InterfaceAssembly.from_dict(
            v2_cycle_document(two_cycle_alternatives=True)
        )
        inconclusive_result = solve_interface_assembly(inconclusive)
        self.assertIs(inconclusive_result.status, SolveStatus.INCONCLUSIVE)
        self.assertEqual(
            inconclusive_result.assembly_digest, digest(inconclusive.as_dict())
        )
        self.assertTrue(
            verify_interface_assembly_result(inconclusive, inconclusive_result)
        )

    def test_occurrence_must_match_bound_request_and_projection(self) -> None:
        document = v2_assembly_document()
        document["occurrences"][1]["occurrence_id"] = "other-motor"
        with self.assertRaisesRegex(InputError, "must match"):
            InterfaceAssembly.from_dict(document)

    def test_reference_subject_digest_mismatch_is_rejected(self) -> None:
        document = v2_assembly_document()
        participant = document["occurrences"][1]["participant"]
        reference = participant["reference_component"]
        reference["title"] = "Different protected subject"
        payload = {
            key: value for key, value in reference.items() if key != "content_digest"
        }
        reference["content_digest"] = digest(payload)
        with self.assertRaises(ContrainteError):
            InterfaceAssembly.from_dict(document)

    def test_semantically_rehashed_projection_tamper_is_rejected(self) -> None:
        document = v2_assembly_document()
        projection = document["occurrences"][1]["participant"][
            "design_around_projection"
        ]
        projection["evidence_blockers"].append("invented:blocker")
        projection["evidence_blockers"].sort()
        payload = {
            key: value for key, value in projection.items() if key != "content_digest"
        }
        projection["content_digest"] = digest(payload)
        with self.assertRaises(ContrainteError):
            InterfaceAssembly.from_dict(document)

    def test_unrequested_reference_interface_is_not_exposed(self) -> None:
        document = v2_assembly_document(add_unrequested=True)
        document["mates"][0]["first"]["interface_id"] = "unused"
        with self.assertRaisesRegex(InputError, "exactly one framed interface"):
            InterfaceAssembly.from_dict(document)

    def test_protected_interface_semantics_are_enforced_after_normalization(
        self,
    ) -> None:
        cases = (
            ("kind", "electrical", "kinds"),
            ("medium", "other-flange", "media"),
        )
        for field, value, message in cases:
            document = v2_assembly_document()
            interface = document["occurrences"][0]["participant"]["component"][
                "interfaces"
            ][0]
            interface[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(InputError, message):
                InterfaceAssembly.from_dict(document)

        document = v2_assembly_document()
        interface = document["occurrences"][0]["participant"]["component"][
            "interfaces"
        ][0]
        interface["properties"]["bolt-pattern"] = "different"
        with self.assertRaisesRegex(InputError, "selected property"):
            InterfaceAssembly.from_dict(document)

    def test_observational_authority_and_blockers_are_retained(self) -> None:
        assembly = InterfaceAssembly.from_dict(v2_assembly_document(observational=True))
        protected = assembly.occurrences[1].participant
        self.assertIsInstance(protected, ProtectedReferenceParticipant)
        self.assertEqual(
            protected.interface_authorities,
            (("mount", EvidenceAuthority.OBSERVATION),),
        )
        self.assertIn(
            "evidence-resolution:/reference_frames/mount",
            protected.evidence_blockers,
        )
        result = solve_interface_assembly(assembly)
        summary = next(
            item
            for item in result.participant_evidence
            if item.occurrence_id == "traction-motor"
        )
        self.assertGreater(summary.protected_constraint_count, 0)
        self.assertGreater(summary.resolution_required_count, 0)
        self.assertGreater(dict(summary.authority_counts)["observation"], 0)
        self.assertEqual(
            summary.exposed_interfaces[0].authority,
            EvidenceAuthority.OBSERVATION,
        )
        self.assertIn(
            "evidence-resolution:/reference_frames/mount",
            summary.evidence_blockers,
        )
        self.assertTrue(verify_interface_assembly_result(assembly, result))

        tampered = result.as_dict()
        protected_summary = next(
            item
            for item in tampered["participant_evidence"]
            if item["occurrence_id"] == "traction-motor"
        )
        protected_summary["evidence_blockers"].append("invented:blocker")
        protected_summary["evidence_blockers"].sort()
        self.assertFalse(
            verify_interface_assembly_result(
                assembly, InterfaceAssemblyResult.from_dict(tampered)
            )
        )

    def test_v2_cli_reports_non_release_evidence_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                status = cli_main(
                    [
                        "interface-assembly",
                        "solve",
                        str(MIXED_EXAMPLE),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(status, 0)
            report = json.loads(stdout.getvalue())
            self.assertIs(report["release_eligible"], False)
            self.assertEqual(len(report["participant_evidence"]), 2)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                status = cli_main(
                    [
                        "interface-assembly",
                        "verify",
                        str(MIXED_EXAMPLE),
                        str(output),
                    ]
                )
            self.assertEqual(status, 0)
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["status"], "verified")
            self.assertIs(report["release_eligible"], False)

    def test_tag_shape_and_schema_boundaries_are_strict(self) -> None:
        document = v2_assembly_document()
        document["occurrences"][0]["participant"]["kind"] = "unknown"
        with self.assertRaisesRegex(InputError, "kind is unsupported"):
            InterfaceAssembly.from_dict(document)

        document = v2_assembly_document()
        document["occurrences"][0]["participant"]["surprise"] = True
        with self.assertRaisesRegex(InputError, "unsupported fields"):
            InterfaceAssembly.from_dict(document)

        assembly = InterfaceAssembly.from_dict(v2_assembly_document())
        result_document = solve_interface_assembly(assembly).as_dict()
        result_document.pop("assembly_digest")
        with self.assertRaisesRegex(InputError, "missing required fields"):
            InterfaceAssemblyResult.from_dict(result_document)

        result_document = solve_interface_assembly(assembly).as_dict()
        result_document["release_eligible"] = True
        with self.assertRaisesRegex(InputError, "not a release"):
            InterfaceAssemblyResult.from_dict(result_document)

        v1 = InterfaceAssembly.from_dict(
            loads_strict(
                (ROOT / "examples" / "motor-design-around-interface.json").read_bytes()
            )
        )
        v1_result = solve_interface_assembly(v1).as_dict()
        v1_result["assembly_digest"] = DIGEST
        with self.assertRaisesRegex(InputError, "unsupported fields"):
            InterfaceAssemblyResult.from_dict(v1_result)

    def test_direct_mutation_and_oversized_projection_fail_before_materialization(
        self,
    ) -> None:
        assembly = InterfaceAssembly.from_dict(v2_assembly_document())
        protected = assembly.occurrences[1].participant
        object.__setattr__(
            protected.reference_component,
            "evidence",
            list(protected.reference_component.evidence),
        )
        with self.assertRaisesRegex(InputError, "direct collection limits"):
            solve_interface_assembly(assembly)

        assembly = InterfaceAssembly.from_dict(v2_assembly_document())
        protected = assembly.occurrences[1].participant
        frame = protected.reference_component.reference_frames[0]
        object.__setattr__(frame, "properties", list(frame.properties))
        with (
            patch.object(
                ProtectedReferenceParticipant,
                "as_dict",
                side_effect=AssertionError("must not serialize"),
            ),
            self.assertRaisesRegex(InputError, "nested collection limits"),
        ):
            solve_interface_assembly(assembly)

        assembly = InterfaceAssembly.from_dict(v2_assembly_document())
        protected = assembly.occurrences[1].participant
        constraint = protected.design_around_projection.protected_constraints[0]
        object.__setattr__(
            protected.design_around_projection,
            "protected_constraints",
            (constraint,) * 4_097,
        )
        with self.assertRaisesRegex(InputError, "direct collection limits"):
            solve_interface_assembly(assembly)

    def test_hostile_json_depth_and_float_are_rejected(self) -> None:
        nested: object = None
        for _ in range(MAX_JSON_DEPTH + 1):
            nested = [nested]
        with self.assertRaisesRegex(InputError, "depth limit"):
            InterfaceAssembly.from_dict(nested)

        document = v2_assembly_document()
        document["candidate_budget"] = 1.0
        with self.assertRaisesRegex(InputError, "not a supported JSON value"):
            InterfaceAssembly.from_dict(document)

    def test_hostile_unicode_integer_cardinality_and_exact_tags_fail_closed(
        self,
    ) -> None:
        document = v2_assembly_document()
        document["occurrences"][0]["participant"]["component"]["title"] = "\ud800"
        with self.assertRaisesRegex(InputError, "valid UTF-8 scalar"):
            InterfaceAssembly.from_dict(document)

        document = v2_assembly_document()
        document["\ud800"] = None
        with self.assertRaisesRegex(InputError, "valid UTF-8 scalar"):
            InterfaceAssembly.from_dict(document)

        document = v2_assembly_document()
        document["candidate_budget"] = 1 << 100
        with self.assertRaisesRegex(InputError, "64-bit integer"):
            InterfaceAssembly.from_dict(document)

        with self.assertRaisesRegex(InputError, "node input limit"):
            InterfaceAssembly.from_dict([None] * MAX_JSON_NODES)

        class StringSubclass(str):
            pass

        document = v2_assembly_document()
        document["occurrences"][0]["participant"]["kind"] = StringSubclass(
            "released_component"
        )
        with self.assertRaisesRegex(InputError, "not a supported JSON value"):
            InterfaceAssembly.from_dict(document)

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "hostile.json"
            output = Path(directory) / "result.json"
            source.write_text(
                '{"schema_version":"contrainte.interface-assembly/0.2",'
                '"candidate_budget":1267650600228229401496703205376}',
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                status = cli_main(
                    [
                        "interface-assembly",
                        "solve",
                        str(source),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(status, 2)
            self.assertIn("64-bit integer", stderr.getvalue())

    def test_verifier_oracle_rejects_common_mode_production_frame_tamper(
        self,
    ) -> None:
        module = importlib.import_module("contrainte.interface_assembly")
        assembly = InterfaceAssembly.from_dict(v2_assembly_document())
        original = module._normalize_occurrence
        shift = module.ExactRigidTransform.from_dict(
            {
                **identity_transform(),
                "translation": {"x": "1", "y": "0", "z": "0"},
            },
            field="test.shift",
        )

        def corrupted_normalization(occurrence):
            normalized = original(occurrence)
            if (
                normalized.participant_kind
                is module.ParticipantKind.PROTECTED_REFERENCE
            ):
                interface = normalized.interfaces[0]
                normalized = replace(
                    normalized,
                    interfaces=(replace(interface, frame=shift),),
                )
            return normalized

        with (
            patch.object(
                module, "_normalize_occurrence", side_effect=corrupted_normalization
            ),
            self.assertRaisesRegex(RuntimeError, "reconstruction failed"),
        ):
            solve_interface_assembly(assembly)


if __name__ == "__main__":
    unittest.main()
