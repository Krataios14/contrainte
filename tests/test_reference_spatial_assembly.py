from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import ROUND_DOWN, Inexact, Rounded, localcontext
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

import contrainte
import contrainte.reference_spatial_assembly as spatial_module
from contrainte.artifacts import file_digest
from contrainte.cad import compile_part, load_part
from contrainte.canonical import digest, dumps_pretty, loads_strict
from contrainte.cli import main as cli_main
from contrainte.errors import ExecutionError, InputError, IntegrityError
from contrainte.exact_transform import ExactRigidTransform
from contrainte.interface_assembly import InterfaceAssembly, solve_interface_assembly
from contrainte.reference_component import (
    DesignAroundRequest,
    ReferenceComponentManifest,
    project_design_around,
    seal_design_around_request,
    seal_reference_component,
)
from contrainte.reference_spatial_assembly import (
    ProtectedReferenceBinding,
    ReferenceSpatialAssembly,
    compile_reference_spatial_assembly,
    compile_reference_spatial_assembly_file,
    load_reference_spatial_assembly,
    verify_reference_spatial_assembly_bundle,
)
from contrainte.release import (
    ComponentReleaseRequest,
    derive_component_manifest,
    write_component_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
PART_EXAMPLE = ROOT / "examples" / "mounting-plate.json"
REFERENCE_PAYLOAD = ROOT / "examples" / "reference-motor-payload.json"
REQUEST_PAYLOAD = ROOT / "examples" / "reference-motor-design-around-payload.json"
CAD_AVAILABLE = find_spec("build123d") is not None


def _identity_transform(x: str = "0") -> dict[str, object]:
    return {
        "schema_version": "contrainte.exact-rigid-transform/0.1",
        "unit": "mm",
        "translation": {"x": x, "y": "0", "z": "0"},
        "basis": {
            "x_axis": {"x": "1", "y": "0", "z": "0"},
            "y_axis": {"x": "0", "y": "1", "z": "0"},
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        },
    }


def _release_request() -> dict[str, object]:
    return {
        "schema_version": "contrainte.component-release-request/0.2",
        "component_id": "motor-surround.bracket",
        "revision": "A",
        "title": "Released mounting bracket beside an existing motor",
        "interfaces": [
            {
                "interface_id": "motor-mount",
                "kind": "mechanical",
                "direction": "bidirectional",
                "medium": "bolted-flange",
                "properties": {"bolt-pattern": "4xM8-PCD100"},
                "frame": {
                    "reference": "engineering_bundle",
                    "unit": "mm",
                    "origin": {"x": "60", "y": "0", "z": "5"},
                    "basis": _identity_transform()["basis"],
                },
            }
        ],
        "capabilities": ["synthetic_fixture"],
        "metadata": {"data_class": "synthetic"},
    }


@unittest.skipUnless(CAD_AVAILABLE, "optional CAD backend is not installed")
class ReferenceSpatialAssemblyTests(unittest.TestCase):
    def _write(self, path: Path, document: object) -> None:
        path.write_text(dumps_pretty(document), encoding="utf-8", newline="\n")

    def _fixture(
        self,
        root: Path,
        *,
        mount_x: str = "-50",
        extra_envelopes: int = 0,
    ) -> tuple[ReferenceSpatialAssembly, Path, Path]:
        root.mkdir(parents=True, exist_ok=True)
        component_root = root / "components"
        component_root.mkdir()
        compile_part(load_part(PART_EXAMPLE), component_root)
        source_bundle = component_root / "plate.demo.cad-bundle.json"
        released = derive_component_manifest(
            source_bundle, ComponentReleaseRequest.from_dict(_release_request())
        )
        manifest_path = component_root / "bracket.component.json"
        write_component_manifest(manifest_path, released, bundle_path=source_bundle)

        component_payload = loads_strict(REFERENCE_PAYLOAD.read_bytes())
        component_payload["reference_frames"][0]["transform"]["translation"]["x"] = (
            mount_x
        )
        component_payload["envelopes"][0]["bounds"] = {
            "unit": "mm",
            "minimum": {"x": "-40", "y": "60", "z": "-20"},
            "maximum": {"x": "40", "y": "100", "z": "20"},
        }
        for index in range(extra_envelopes):
            envelope = copy.deepcopy(component_payload["envelopes"][0])
            envelope["envelope_id"] = f"keepout-{index:02d}"
            envelope["purpose"] = "keepout"
            component_payload["envelopes"].append(envelope)
            component_payload["evidence"][0]["supports"].append(
                f"/envelopes/keepout-{index:02d}"
            )
        component_payload["envelopes"].sort(
            key=lambda item: (item["purpose"], item["envelope_id"])
        )
        component_payload["evidence"][0]["supports"].sort()
        component_document = seal_reference_component(component_payload)
        component = ReferenceComponentManifest.from_dict(component_document)
        request_payload = loads_strict(REQUEST_PAYLOAD.read_bytes())
        request_payload["reference_component_digest"] = component.content_digest
        request_document = seal_design_around_request(request_payload)
        request = DesignAroundRequest.from_dict(request_document)
        projection = project_design_around(component, request)

        protected_path = root / "existing-motor.reference.json"
        request_path = root / "existing-motor.request.json"
        projection_path = root / "existing-motor.projection.json"
        self._write(protected_path, component.as_dict())
        self._write(request_path, request.as_dict())
        self._write(projection_path, projection.as_dict())

        interface = InterfaceAssembly.from_dict(
            {
                "schema_version": "contrainte.interface-assembly/0.2",
                "occurrences": [
                    {
                        "occurrence_id": "motor-bracket",
                        "participant": {
                            "kind": "released_component",
                            "component": released.as_dict(),
                        },
                    },
                    {
                        "occurrence_id": "traction-motor",
                        "participant": {
                            "kind": "protected_reference",
                            "reference_component": component.as_dict(),
                            "design_around_request": request.as_dict(),
                            "design_around_projection": projection.as_dict(),
                        },
                        "anchor_transform": _identity_transform(),
                    },
                ],
                "mates": [
                    {
                        "mate_id": "existing-motor-mount",
                        "first": {
                            "occurrence_id": "traction-motor",
                            "interface_id": "mount",
                        },
                        "second": {
                            "occurrence_id": "motor-bracket",
                            "interface_id": "motor-mount",
                        },
                        "property_keys": ["bolt-pattern"],
                        "alternatives": [
                            {
                                "alternative_id": "declared-interface",
                                "preference_rank": 0,
                                "second_interface_in_first_interface": (
                                    _identity_transform()
                                ),
                            }
                        ],
                    }
                ],
                "candidate_budget": 1,
            }
        )
        result = solve_interface_assembly(interface)
        interface_path = root / "existing-motor.interface.json"
        result_path = root / "existing-motor.interface-result.json"
        self._write(interface_path, interface.as_dict())
        self._write(result_path, result.as_dict())

        assembly = ReferenceSpatialAssembly.from_dict(
            {
                "schema_version": "contrainte.reference-spatial-assembly/0.1",
                "assembly_id": "existing-motor-bracket",
                "revision": "A",
                "title": "Released bracket around one existing protected motor",
                "interface_assembly": {
                    "locator": interface_path.name,
                    "file_digest": file_digest(interface_path),
                },
                "interface_result": {
                    "locator": result_path.name,
                    "file_digest": file_digest(result_path),
                },
                "protected_reference": {
                    "occurrence_id": "traction-motor",
                    "reference_component": {
                        "locator": protected_path.name,
                        "file_digest": file_digest(protected_path),
                    },
                    "reference_component_digest": component.content_digest,
                    "design_around_request": {
                        "locator": request_path.name,
                        "file_digest": file_digest(request_path),
                    },
                    "design_around_request_digest": request.content_digest,
                    "design_around_projection": {
                        "locator": projection_path.name,
                        "file_digest": file_digest(projection_path),
                    },
                    "design_around_projection_digest": projection.content_digest,
                },
                "released_components": [
                    {
                        "occurrence_id": "motor-bracket",
                        "manifest_locator": "components/bracket.component.json",
                        "manifest_file_digest": file_digest(manifest_path),
                        "manifest_digest": released.manifest_digest,
                    }
                ],
                "minimum_occupied_clearance_mm": "0",
                "default_released_clearance_mm": "5",
                "released_pair_clearances": [],
            }
        )
        assembly_path = root / "existing-motor-spatial-assembly.json"
        self._write(assembly_path, assembly.as_dict())
        return assembly, assembly_path, manifest_path

    def test_public_api_and_canonical_roundtrip(self) -> None:
        self.assertIs(contrainte.ReferenceSpatialAssembly, ReferenceSpatialAssembly)
        self.assertIs(contrainte.ProtectedReferenceBinding, ProtectedReferenceBinding)
        self.assertIs(
            contrainte.compile_reference_spatial_assembly_file,
            compile_reference_spatial_assembly_file,
        )
        document = {
            "schema_version": "contrainte.reference-spatial-assembly/0.1",
            "assembly_id": "a",
            "revision": "A",
            "title": "Bounded reference spatial assembly",
            "interface_assembly": {
                "locator": "i.json",
                "file_digest": "sha256:" + "1" * 64,
            },
            "interface_result": {
                "locator": "r.json",
                "file_digest": "sha256:" + "2" * 64,
            },
            "protected_reference": {
                "occurrence_id": "protected",
                "reference_component": {
                    "locator": "p.json",
                    "file_digest": "sha256:" + "3" * 64,
                },
                "reference_component_digest": "sha256:" + "4" * 64,
                "design_around_request": {
                    "locator": "q.json",
                    "file_digest": "sha256:" + "5" * 64,
                },
                "design_around_request_digest": "sha256:" + "6" * 64,
                "design_around_projection": {
                    "locator": "x.json",
                    "file_digest": "sha256:" + "7" * 64,
                },
                "design_around_projection_digest": "sha256:" + "8" * 64,
            },
            "released_components": [
                {
                    "occurrence_id": "released",
                    "manifest_locator": "m.json",
                    "manifest_file_digest": "sha256:" + "9" * 64,
                    "manifest_digest": "sha256:" + "a" * 64,
                }
            ],
            "minimum_occupied_clearance_mm": "1/2",
            "default_released_clearance_mm": "5",
            "released_pair_clearances": [],
        }
        parsed = ReferenceSpatialAssembly.from_dict(document)
        self.assertEqual(parsed.as_dict(), document)
        self.assertEqual(parsed.assembly_digest, digest(document))

    def test_byte_parser_rejects_utf8_surrogates_duplicates_and_huge_integers(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "hostile.json"
            cases = (
                (b"\xff", "valid UTF-8"),
                (b'{"value":"\\ud800"}', "invalid Unicode"),
                (b'{"value":1,"value":2}', "duplicate JSON object field"),
                (b'{"value":999999999999999999999999999999}', "integer exceeds"),
            )
            for payload, message in cases:
                with self.subTest(message=message):
                    source.write_bytes(payload)
                    with self.assertRaisesRegex(InputError, message):
                        load_reference_spatial_assembly(source)

    def test_compiles_json_only_and_independently_replays(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _ = self._fixture(root)
            output = root / "compiled"
            first = compile_reference_spatial_assembly(assembly, root, output)
            second = compile_reference_spatial_assembly(assembly, root, output)
            bundle_path = (
                output / "existing-motor-bracket.reference-spatial-assembly-bundle.json"
            )
            with patch.object(
                spatial_module,
                "_compiler_spatial_analysis",
                side_effect=AssertionError("compiler oracle must not verify"),
            ):
                report = verify_reference_spatial_assembly_bundle(bundle_path, root)
            self.assertEqual(first, second)
            self.assertEqual(report["status"], "verified")
            self.assertIs(report["release_eligible"], False)
            content = first["content"]
            self.assertEqual(content["artifacts"], [])
            self.assertIs(content["release_eligible"], False)
            self.assertFalse(
                content["authority_summary"]["protected_reference_brep_claimed"]
            )
            self.assertEqual(content["analysis"]["status"], "passed")
            self.assertEqual(content["analysis"]["protected_region_count"], 2)
            self.assertTrue(
                all(
                    not item["protected_brep_claimed"]
                    for item in content["analysis"]["protected_regions"]
                )
            )
            self.assertEqual(
                sorted(path.name for path in output.iterdir()),
                ["existing-motor-bracket.reference-spatial-assembly-bundle.json"],
            )

    def test_cli_compile_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, assembly_path, _ = self._fixture(root)
            output = root / "cli-output"
            with redirect_stdout(__import__("io").StringIO()):
                self.assertEqual(
                    cli_main(
                        [
                            "reference-spatial-assembly",
                            "compile",
                            str(assembly_path),
                            "--source-root",
                            str(root),
                            "--output-dir",
                            str(output),
                        ]
                    ),
                    0,
                )
            bundle_path = (
                output / "existing-motor-bracket.reference-spatial-assembly-bundle.json"
            )
            captured = __import__("io").StringIO()
            with redirect_stdout(captured):
                self.assertEqual(
                    cli_main(
                        [
                            "reference-spatial-assembly",
                            "verify",
                            str(bundle_path),
                            "--source-root",
                            str(root),
                        ]
                    ),
                    0,
                )
            self.assertEqual(json.loads(captured.getvalue())["status"], "verified")

    def test_bound_file_compile_repeats_canonical_bundle_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, assembly_path, _ = self._fixture(root)
            output = root / "compiled"
            first = compile_reference_spatial_assembly_file(assembly_path, root, output)
            bundle_path = (
                output / "existing-motor-bracket.reference-spatial-assembly-bundle.json"
            )
            first_bytes = bundle_path.read_bytes()
            second = compile_reference_spatial_assembly_file(
                assembly_path, root, output
            )
            self.assertEqual(first, second)
            self.assertEqual(bundle_path.read_bytes(), first_bytes)
            self.assertEqual(
                sorted(path.name for path in output.iterdir()), [bundle_path.name]
            )

    def test_constraint_failure_and_rehashed_bundle_tamper_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            colliding, _, _ = self._fixture(root, mount_x="0")
            with self.assertRaisesRegex(ExecutionError, "constraints failed"):
                compile_reference_spatial_assembly(colliding, root, root / "bad")

            assembly, _, _ = self._fixture(root / "second")
            output = root / "second" / "compiled"
            compile_reference_spatial_assembly(assembly, root / "second", output)
            bundle_path = (
                output / "existing-motor-bracket.reference-spatial-assembly-bundle.json"
            )
            raw = loads_strict(bundle_path.read_bytes())
            raw["content"]["analysis"]["status"] = "failed"
            raw["digest"] = digest(raw["content"])
            self._write(bundle_path, raw)
            with self.assertRaisesRegex(IntegrityError, "independently reproduce"):
                verify_reference_spatial_assembly_bundle(bundle_path, root / "second")

    def test_pinned_sources_and_released_artifacts_are_rechecked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, manifest_path = self._fixture(root)
            manifest = loads_strict(manifest_path.read_bytes())
            step_locator = next(
                item["locator"]
                for item in manifest["artifacts"]
                if item["role"] == "exact_geometry"
            )
            step_path = manifest_path.parent / step_locator
            original = step_path.read_bytes()
            step_path.write_bytes(original + b"tamper")
            with self.assertRaises(IntegrityError):
                compile_reference_spatial_assembly(assembly, root, root / "bad")

    def test_decimal_context_independence_and_compiler_poisoning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _ = self._fixture(root)
            output = root / "compiled"
            baseline = compile_reference_spatial_assembly(assembly, root, output)
            with localcontext() as context:
                context.prec = 7
                context.rounding = ROUND_DOWN
                context.traps[Inexact] = True
                context.traps[Rounded] = True
                reproduced = compile_reference_spatial_assembly(assembly, root, output)
            self.assertEqual(baseline, reproduced)
            bundle_path = (
                output / "existing-motor-bracket.reference-spatial-assembly-bundle.json"
            )
            with patch.object(
                spatial_module,
                "_compiler_measure_pair",
                return_value=(spatial_module.Fraction(999), spatial_module.Fraction(0)),
            ):
                report = verify_reference_spatial_assembly_bundle(bundle_path, root)
            self.assertEqual(report["status"], "verified")

    def test_falsely_safe_compiler_measurement_is_rejected_by_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            colliding, _, _ = self._fixture(root, mount_x="0")
            output = root / "poisoned"
            with patch.object(
                spatial_module,
                "_compiler_measure_pair",
                return_value=(spatial_module.Fraction(100), spatial_module.Fraction(0)),
            ):
                compile_reference_spatial_assembly(colliding, root, output)
            bundle_path = (
                output / "existing-motor-bracket.reference-spatial-assembly-bundle.json"
            )
            with self.assertRaisesRegex(IntegrityError, "independently reproduce"):
                verify_reference_spatial_assembly_bundle(bundle_path, root)

    def test_falsely_shifted_compiler_placement_is_rejected_by_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            colliding, _, _ = self._fixture(root, mount_x="0")
            output = root / "shifted"
            false_transforms = {
                "motor-bracket": ExactRigidTransform.from_dict(
                    _identity_transform("-110"), field="false-placement"
                ),
                "traction-motor": ExactRigidTransform.from_dict(
                    _identity_transform(), field="protected-placement"
                ),
            }
            with patch.object(
                spatial_module,
                "_compiler_transforms",
                return_value=false_transforms,
            ):
                compile_reference_spatial_assembly(colliding, root, output)
            bundle_path = (
                output / "existing-motor-bracket.reference-spatial-assembly-bundle.json"
            )
            with self.assertRaisesRegex(IntegrityError, "independently reproduce"):
                verify_reference_spatial_assembly_bundle(bundle_path, root)

    def test_direct_constructor_and_resource_caps_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, assembly_path, _ = self._fixture(root)
            object.__setattr__(
                assembly, "released_components", list(assembly.released_components)
            )
            with self.assertRaisesRegex(InputError, "direct state"):
                compile_reference_spatial_assembly(assembly, root, root / "bad")

            raw = loads_strict(assembly_path.read_bytes())
            raw["released_components"] = raw["released_components"] * 64
            for index, item in enumerate(raw["released_components"]):
                item = copy.deepcopy(item)
                item["occurrence_id"] = f"released-{index:02d}"
                raw["released_components"][index] = item
            with self.assertRaisesRegex(InputError, "1 to 63"):
                ReferenceSpatialAssembly.from_dict(raw)

            huge = loads_strict(assembly_path.read_bytes())
            huge["unexpected"] = 1 << 1000
            with self.assertRaisesRegex(InputError, "integer exceeds"):
                ReferenceSpatialAssembly.from_dict(huge)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            oversized, _, _ = self._fixture(root, extra_envelopes=31)
            with self.assertRaisesRegex(InputError, "region count exceeds"):
                compile_reference_spatial_assembly(oversized, root, root / "bad")

    def test_nested_direct_state_and_hardlinked_input_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, assembly_path, _ = self._fixture(root)
            object.__setattr__(
                assembly.protected_reference.reference_component,
                "locator",
                ["not", "a", "locator"],
            )
            with self.assertRaises(InputError):
                compile_reference_spatial_assembly(assembly, root, root / "bad")

            hardlink = root / "hardlinked-spatial-assembly.json"
            os.link(assembly_path, hardlink)
            with self.assertRaisesRegex(InputError, "hard-linked"):
                load_reference_spatial_assembly(hardlink)

    def test_bundle_output_cannot_overwrite_a_consumed_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _ = self._fixture(root)
            original_interface = root / "existing-motor.interface.json"
            collision = root / "collision.reference-spatial-assembly-bundle.json"
            collision.write_bytes(original_interface.read_bytes())
            document = assembly.as_dict()
            document["assembly_id"] = "collision"
            document["interface_assembly"] = {
                "locator": collision.name,
                "file_digest": file_digest(collision),
            }
            rebound = ReferenceSpatialAssembly.from_dict(document)
            before = collision.read_bytes()
            with self.assertRaisesRegex(InputError, "cannot overwrite"):
                compile_reference_spatial_assembly(rebound, root, root)
            self.assertEqual(collision.read_bytes(), before)

    def test_cli_binds_exact_assembly_input_against_output_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _ = self._fixture(root)
            input_path = (
                root / "existing-motor-bracket.reference-spatial-assembly-bundle.json"
            )
            self._write(input_path, assembly.as_dict())
            before = input_path.read_bytes()
            errors = __import__("io").StringIO()
            with redirect_stderr(errors):
                status = cli_main(
                    [
                        "reference-spatial-assembly",
                        "compile",
                        str(input_path),
                        "--source-root",
                        str(root),
                        "--output-dir",
                        str(root),
                    ]
                )
            self.assertEqual(status, 2)
            self.assertIn("cannot overwrite its assembly input", errors.getvalue())
            self.assertEqual(input_path.read_bytes(), before)

    def test_assembly_input_aliases_and_hardlinks_fail_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, assembly_path, _ = self._fixture(root)
            hardlink = root / "assembly-hardlink.json"
            os.link(assembly_path, hardlink)
            before = assembly_path.read_bytes()
            with self.assertRaisesRegex(InputError, "hard-linked"):
                compile_reference_spatial_assembly_file(
                    root / "." / assembly_path.name,
                    root,
                    root / "compiled",
                )
            self.assertEqual(assembly_path.read_bytes(), before)
            self.assertEqual(hardlink.read_bytes(), before)
            self.assertFalse((root / "compiled").exists())

    def test_reparse_or_symlink_input_ancestor_is_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            _, assembly_path, _ = self._fixture(real)
            alias = root / "alias"
            try:
                os.symlink(real, alias, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory links are unavailable: {exc}")
            before = assembly_path.read_bytes()
            with self.assertRaises(InputError):
                compile_reference_spatial_assembly_file(
                    alias / assembly_path.name,
                    real,
                    root / "compiled",
                )
            self.assertEqual(assembly_path.read_bytes(), before)
            self.assertFalse((root / "compiled").exists())

    def test_prior_bundle_survives_every_publication_phase_failure(self) -> None:
        events = (
            "before_stage_create",
            "stage_created_before_write",
            "after_stage_write",
            "before_promotion",
            "after_prior_backup",
            "after_stage_promotion",
            "before_backup_cleanup",
        )
        for event in events:
            with self.subTest(event=event), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, assembly_path, _ = self._fixture(root)
                output = root / "compiled"
                compile_reference_spatial_assembly_file(assembly_path, root, output)
                bundle_path = (
                    output
                    / "existing-motor-bracket.reference-spatial-assembly-bundle.json"
                )
                before = bundle_path.read_bytes()

                def fail(selected: str, failure_event: str = event) -> None:
                    if selected == failure_event:
                        raise IntegrityError(
                            f"injected publication failure: {failure_event}"
                        )

                with (
                    patch.object(
                        spatial_module, "_spatial_publish_fault_hook", side_effect=fail
                    ),
                    self.assertRaisesRegex(
                        IntegrityError, "injected publication failure"
                    ),
                ):
                    compile_reference_spatial_assembly_file(assembly_path, root, output)
                self.assertEqual(bundle_path.read_bytes(), before)
                self.assertEqual(
                    sorted(path.name for path in output.iterdir()),
                    [bundle_path.name],
                )

    def test_staging_hardlink_before_write_leaves_zero_outside_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, assembly_path, _ = self._fixture(root)
            output = root / "compiled"
            output.mkdir()
            outside = root / "outside-hardlink.bin"

            def insert_hardlink(event: str) -> None:
                if event != "stage_created_before_write":
                    return
                stage = next(path for path in output.iterdir() if ".tmp-" in path.name)
                os.link(stage, outside)

            with (
                patch.object(
                    spatial_module,
                    "_spatial_publish_fault_hook",
                    side_effect=insert_hardlink,
                ),
                self.assertRaisesRegex(IntegrityError, "hard-linked before write"),
            ):
                compile_reference_spatial_assembly_file(assembly_path, root, output)
            self.assertTrue(outside.is_file())
            self.assertEqual(outside.read_bytes(), b"")
            self.assertEqual(list(output.iterdir()), [])

    def test_staged_byte_substitution_preserves_prior_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, assembly_path, _ = self._fixture(root)
            output = root / "compiled"
            compile_reference_spatial_assembly_file(assembly_path, root, output)
            bundle_path = (
                output / "existing-motor-bracket.reference-spatial-assembly-bundle.json"
            )
            before = bundle_path.read_bytes()
            create = spatial_module._create_staged_publish_file

            def substitute(parent, name, captured):
                staged = create(parent, name, captured)
                if parent.windows:
                    spatial_module._windows_write(staged.handle, b"substitution")
                else:
                    os.pwrite(staged.handle, b"substitution", 0)
                return staged

            with (
                patch.object(
                    spatial_module,
                    "_create_staged_publish_file",
                    side_effect=substitute,
                ),
                self.assertRaisesRegex(
                    IntegrityError, "metadata changed|bytes changed"
                ),
            ):
                compile_reference_spatial_assembly_file(assembly_path, root, output)
            self.assertEqual(bundle_path.read_bytes(), before)
            self.assertEqual(
                sorted(path.name for path in output.iterdir()), [bundle_path.name]
            )

    def test_output_ancestor_replacement_is_blocked_and_prior_survives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, assembly_path, _ = self._fixture(root)
            ancestor = root / "output-parent"
            output = ancestor / "compiled"
            compile_reference_spatial_assembly_file(assembly_path, root, output)
            bundle_path = (
                output / "existing-motor-bracket.reference-spatial-assembly-bundle.json"
            )
            before = bundle_path.read_bytes()
            moved = root / "output-parent-moved"
            outside = root / "outside-output"
            outside.mkdir()
            marker = outside / "marker.bin"
            marker.write_bytes(b"outside-must-not-change")
            swapped = False

            def replace_ancestor(event: str) -> None:
                nonlocal swapped
                if event != "before_stage_create":
                    return
                try:
                    os.replace(ancestor, moved)
                except OSError as exc:
                    raise IntegrityError(
                        "output ancestor replacement was handle-blocked"
                    ) from exc
                swapped = True
                try:
                    os.symlink(outside, ancestor, target_is_directory=True)
                except OSError as exc:
                    raise IntegrityError(
                        "output ancestor replacement link was unavailable"
                    ) from exc

            try:
                with (
                    patch.object(
                        spatial_module,
                        "_spatial_publish_fault_hook",
                        side_effect=replace_ancestor,
                    ),
                    self.assertRaisesRegex(
                        IntegrityError,
                        "replacement|location changed|no longer visible",
                    ),
                ):
                    compile_reference_spatial_assembly_file(assembly_path, root, output)
            finally:
                if swapped:
                    if ancestor.exists() or ancestor.is_symlink():
                        if ancestor.is_symlink():
                            ancestor.unlink()
                        else:
                            os.rmdir(ancestor)
                    os.replace(moved, ancestor)
            self.assertTrue(bundle_path.is_file())
            self.assertEqual(bundle_path.read_bytes(), before)
            self.assertEqual(marker.read_bytes(), b"outside-must-not-change")
            self.assertEqual({path.name for path in outside.iterdir()}, {"marker.bin"})

    def test_wrong_interface_version_is_rejected_without_changing_v01(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _ = self._fixture(root)
            interface_path = root / "existing-motor.interface.json"
            interface = loads_strict(interface_path.read_bytes())
            interface["schema_version"] = "contrainte.interface-assembly/0.1"
            self._write(interface_path, interface)
            document = assembly.as_dict()
            document["interface_assembly"]["file_digest"] = file_digest(interface_path)
            rebound = ReferenceSpatialAssembly.from_dict(document)
            with self.assertRaises(InputError):
                compile_reference_spatial_assembly(rebound, root, root / "bad")

            legacy = InterfaceAssembly.from_dict(
                loads_strict(
                    (ROOT / "examples" / "component-pair-interface.json").read_bytes()
                )
            )
            self.assertEqual(legacy.schema_version, "contrainte.interface-assembly/0.1")


if __name__ == "__main__":
    unittest.main()
