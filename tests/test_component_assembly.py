from __future__ import annotations

import tempfile
import unittest
from decimal import ROUND_DOWN, Inexact, Rounded, localcontext
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import contrainte
from contrainte.artifacts import file_digest
from contrainte.cad import compile_part, load_part
from contrainte.canonical import digest, dumps_pretty, loads_strict
from contrainte.component_assembly import (
    ComponentAssembly,
    _compiler_pair_analysis,
    _compiler_place_shapes,
    _load_context,
    _LoadedContext,
    _read_bounded_chunks,
    _verifier_pair_analysis,
    _verifier_place_shapes,
    compile_component_assembly,
    load_component_assembly,
    verify_component_assembly_bundle,
)
from contrainte.errors import ExecutionError, InputError, IntegrityError
from contrainte.interface_assembly import (
    InterfaceAssembly,
    InterfaceAssemblyResult,
    solve_interface_assembly,
)
from contrainte.release import (
    ComponentReleaseRequest,
    derive_component_manifest,
    write_component_manifest,
)

PART_EXAMPLE = Path(__file__).parents[1] / "examples" / "mounting-plate.json"
CAD_AVAILABLE = find_spec("build123d") is not None


def _basis_345() -> dict[str, dict[str, str]]:
    return {
        "x_axis": {"x": "3/5", "y": "4/5", "z": "0"},
        "y_axis": {"x": "-4/5", "y": "3/5", "z": "0"},
        "z_axis": {"x": "0", "y": "0", "z": "1"},
    }


def _basis_513() -> dict[str, dict[str, str]]:
    return {
        "x_axis": {"x": "5/13", "y": "12/13", "z": "0"},
        "y_axis": {"x": "-12/13", "y": "5/13", "z": "0"},
        "z_axis": {"x": "0", "y": "0", "z": "1"},
    }


def _transform(
    x: str, y: str, z: str, *, basis: dict[str, dict[str, str]] | None = None
) -> dict[str, object]:
    return {
        "schema_version": "contrainte.exact-rigid-transform/0.1",
        "unit": "mm",
        "translation": {"x": x, "y": y, "z": z},
        "basis": basis
        or {
            "x_axis": {"x": "1", "y": "0", "z": "0"},
            "y_axis": {"x": "0", "y": "1", "z": "0"},
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        },
    }


def _release_request(component_id: str, interface_id: str, x: str) -> dict:
    return {
        "schema_version": "contrainte.component-release-request/0.2",
        "component_id": component_id,
        "revision": "A",
        "title": component_id,
        "interfaces": [
            {
                "interface_id": interface_id,
                "kind": "mechanical",
                "direction": "bidirectional",
                "medium": "dry_fixture_gap",
                "properties": {"standard": "synthetic-edge"},
                "frame": {
                    "reference": "engineering_bundle",
                    "unit": "mm",
                    "origin": {"x": x, "y": "0", "z": "5"},
                    "basis": {
                        "x_axis": {"x": "1", "y": "0", "z": "0"},
                        "y_axis": {"x": "0", "y": "1", "z": "0"},
                        "z_axis": {"x": "0", "y": "0", "z": "1"},
                    },
                },
            }
        ],
        "capabilities": ["synthetic_fixture"],
        "metadata": {"data_class": "synthetic"},
    }


@unittest.skipUnless(CAD_AVAILABLE, "optional CAD backend is not installed")
class ComponentAssemblyTests(unittest.TestCase):
    def test_public_api_exports_component_assembly_certificate(self) -> None:
        self.assertIs(contrainte.ComponentAssembly, ComponentAssembly)
        self.assertIs(contrainte.compile_component_assembly, compile_component_assembly)
        self.assertIs(
            contrainte.verify_component_assembly_bundle,
            verify_component_assembly_bundle,
        )

    def _fixture(
        self,
        root: Path,
        *,
        gap: str = "5",
        minimum_clearance: str = "5",
        anchor_basis: dict[str, dict[str, str]] | None = None,
    ) -> tuple[ComponentAssembly, Path, Path, Path]:
        component_root = root / "components"
        component_root.mkdir()
        part = load_part(PART_EXAMPLE)
        compile_part(part, component_root)
        bundle_path = component_root / "plate.demo.cad-bundle.json"
        manifests = []
        for occurrence_id, component_id, interface_id, x in (
            ("left", "component.plate-left", "edge-right", "60"),
            ("right", "component.plate-right", "edge-left", "-60"),
        ):
            request = ComponentReleaseRequest.from_dict(
                _release_request(component_id, interface_id, x)
            )
            manifest = derive_component_manifest(bundle_path, request)
            manifest_path = component_root / f"{occurrence_id}.component.json"
            write_component_manifest(manifest_path, manifest, bundle_path=bundle_path)
            manifests.append((occurrence_id, interface_id, manifest, manifest_path))

        interface_document = {
            "schema_version": "contrainte.interface-assembly/0.1",
            "occurrences": [
                {
                    "occurrence_id": "left",
                    "component": manifests[0][2].as_dict(),
                    "anchor_transform": _transform(
                        "0", "0", "0", basis=anchor_basis or _basis_345()
                    ),
                },
                {
                    "occurrence_id": "right",
                    "component": manifests[1][2].as_dict(),
                },
            ],
            "mates": [
                {
                    "mate_id": "edge-gap",
                    "first": {
                        "occurrence_id": "left",
                        "interface_id": "edge-right",
                    },
                    "second": {
                        "occurrence_id": "right",
                        "interface_id": "edge-left",
                    },
                    "property_keys": ["standard"],
                    "alternatives": [
                        {
                            "alternative_id": "declared-gap",
                            "preference_rank": 0,
                            "second_interface_in_first_interface": _transform(
                                gap, "0", "0"
                            ),
                        }
                    ],
                }
            ],
            "candidate_budget": 1,
        }
        interface = InterfaceAssembly.from_dict(interface_document)
        result = solve_interface_assembly(interface)
        interface_path = root / "interface.json"
        result_path = root / "interface-result.json"
        interface_path.write_text(
            dumps_pretty(interface.as_dict()), encoding="utf-8", newline="\n"
        )
        result_path.write_text(
            dumps_pretty(result.as_dict()), encoding="utf-8", newline="\n"
        )
        assembly = ComponentAssembly.from_dict(
            {
                "schema_version": "contrainte.component-assembly/0.1",
                "assembly_id": "component-pair",
                "revision": "A",
                "title": "Geometry-backed component pair",
                "interface_assembly": {
                    "locator": "interface.json",
                    "file_digest": file_digest(interface_path),
                },
                "interface_result": {
                    "locator": "interface-result.json",
                    "file_digest": file_digest(result_path),
                },
                "component_bindings": [
                    {
                        "occurrence_id": occurrence_id,
                        "manifest_locator": f"components/{occurrence_id}.component.json",
                        "manifest_file_digest": file_digest(manifest_path),
                        "manifest_digest": manifest.manifest_digest,
                    }
                    for occurrence_id, _, manifest, manifest_path in manifests
                ],
                "default_minimum_clearance_mm": minimum_clearance,
                "pair_clearances": [],
            }
        )
        return assembly, interface_path, result_path, component_root

    def test_compiles_repeats_and_independently_verifies_real_components(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            output = root / "output"

            first = compile_component_assembly(assembly, root, output)
            second = compile_component_assembly(assembly, root, output)
            bundle_path = output / "component-pair.component-assembly-bundle.json"
            with patch(
                "contrainte.component_assembly._compiler_place_shapes",
                side_effect=AssertionError("compiler placement must not verify"),
            ):
                report = verify_component_assembly_bundle(bundle_path, root)

            self.assertEqual(first, second)
            self.assertEqual(report["status"], "verified")
            analysis = first["content"]["analysis"]
            self.assertEqual(analysis["pair_results"][0]["distance_mm"], "5")
            self.assertEqual(analysis["pair_results"][0]["status"], "passed")
            self.assertEqual(
                analysis["transform_projections"][0]["exact_transform"]["basis"],
                _basis_345(),
            )
            self.assertEqual(
                analysis["transform_projections"][0]["method"],
                "direct-exact-basis-to-gp-trsf/0.1",
            )
            self.assertTrue((output / "component-pair.step").is_file())
            self.assertTrue((output / "component-pair.stl").is_file())

    def test_hostile_decimal_context_cannot_change_projection_or_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root, anchor_basis=_basis_513())
            ordinary = compile_component_assembly(assembly, root, root / "ordinary")

            with localcontext() as context:
                context.prec = 1
                context.rounding = ROUND_DOWN
                context.traps[Inexact] = True
                context.traps[Rounded] = True
                hostile = compile_component_assembly(assembly, root, root / "hostile")
                report = verify_component_assembly_bundle(
                    root / "hostile" / "component-pair.component-assembly-bundle.json",
                    root,
                )

            self.assertEqual(hostile, ordinary)
            self.assertEqual(report["status"], "verified")
            self.assertNotEqual(
                hostile["content"]["analysis"]["transform_projections"][0][
                    "maximum_matrix_projection_error"
                ],
                "0",
            )

    def test_large_transform_error_is_exact_under_hostile_decimal_context(self) -> None:
        class EchoTransform:
            def SetValues(self, *values):
                self.values = values

            def Value(self, row, column):
                return self.values[(row - 1) * 4 + column - 1]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            loaded = _load_context(assembly, root)
            result = loaded.interface_result.as_dict()
            result["occurrence_transforms"][0]["transform"]["translation"]["x"] = (
                "10000000000000001"
            )
            hostile = _LoadedContext(
                interface_assembly=loaded.interface_assembly,
                interface_result=InterfaceAssemblyResult.from_dict(result),
                shapes=loaded.shapes,
                source_records=loaded.source_records,
            )
            with localcontext() as context, patch("OCP.gp.gp_Trsf", EchoTransform):
                context.prec = 1
                context.rounding = ROUND_DOWN
                context.traps[Inexact] = True
                context.traps[Rounded] = True
                with self.assertRaisesRegex(ExecutionError, "beyond tolerance"):
                    _compiler_place_shapes(hostile)
                with self.assertRaisesRegex(IntegrityError, "no longer reproduces"):
                    _verifier_place_shapes(hostile)

    def test_pair_threshold_is_exact_under_hostile_decimal_context(self) -> None:
        class SyntheticShape:
            def distance_to(self, other):
                return 0.0

            def __and__(self, other):
                return SimpleNamespace(
                    solids=lambda: [SimpleNamespace(volume=0.0000011)]
                )

        class SyntheticCompound:
            is_valid = True

            def __init__(self, **kwargs):
                pass

            def bounding_box(self):
                return SimpleNamespace(size=SimpleNamespace(X=1.0, Y=1.0, Z=1.0))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            placed = {"left": SyntheticShape(), "right": SyntheticShape()}
            with (
                localcontext() as context,
                patch("build123d.Compound", SyntheticCompound),
            ):
                context.prec = 1
                context.rounding = ROUND_DOWN
                context.traps[Inexact] = True
                context.traps[Rounded] = True
                compiler, _ = _compiler_pair_analysis(assembly, placed, [])
                verifier, _ = _verifier_pair_analysis(assembly, placed, [])

            self.assertEqual(compiler, verifier)
            self.assertEqual(compiler["pair_results"][0]["status"], "interference")
            self.assertEqual(
                compiler["pair_results"][0]["interference_volume_mm3"],
                "0.0000011",
            )

    def test_semantically_valid_mate_cannot_hide_interference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root, gap="-10", minimum_clearance="0")

            with self.assertRaisesRegex(ExecutionError, "interfere"):
                compile_component_assembly(assembly, root, root / "output")

    def test_clearance_is_enforced_after_exact_pose_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root, gap="3", minimum_clearance="5")

            with self.assertRaisesRegex(ExecutionError, "clearance"):
                compile_component_assembly(assembly, root, root / "output")

    def test_tampered_interface_result_is_rejected_after_digest_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, result_path, _ = self._fixture(root)
            result = loads_strict(result_path.read_bytes())
            result["occurrence_transforms"][1]["transform"]["translation"]["x"] = "76"
            result_path.write_text(dumps_pretty(result), encoding="utf-8", newline="\n")
            document = assembly.as_dict()
            document["interface_result"]["file_digest"] = file_digest(result_path)
            rebound = ComponentAssembly.from_dict(document)

            with self.assertRaisesRegex(IntegrityError, "independently reproduce"):
                compile_component_assembly(rebound, root, root / "output")

    def test_local_and_embedded_manifests_must_be_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, interface_path, _, _ = self._fixture(root)
            interface = loads_strict(interface_path.read_bytes())
            interface["occurrences"][0]["component"]["title"] = "substituted title"
            interface_path.write_text(
                dumps_pretty(interface), encoding="utf-8", newline="\n"
            )
            document = assembly.as_dict()
            document["interface_assembly"]["file_digest"] = file_digest(interface_path)
            rebound = ComponentAssembly.from_dict(document)

            with self.assertRaisesRegex(IntegrityError, "does not match embedded"):
                compile_component_assembly(rebound, root, root / "output")

    def test_manifest_file_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, component_root = self._fixture(root)
            manifest_path = component_root / "left.component.json"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8") + " ",
                encoding="utf-8",
                newline="\n",
            )

            with self.assertRaisesRegex(IntegrityError, "source file digest mismatch"):
                compile_component_assembly(assembly, root, root / "output")

    def test_component_artifact_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, component_root = self._fixture(root)
            step_path = component_root / "plate.demo.step"
            step_path.write_bytes(step_path.read_bytes() + b"tamper")

            with self.assertRaisesRegex(IntegrityError, "artifact.*mismatch"):
                compile_component_assembly(assembly, root, root / "output")

    def test_hard_linked_bound_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, result_path, _ = self._fixture(root)
            linked = root / "linked-result.json"
            try:
                linked.hardlink_to(result_path)
            except OSError as exc:
                self.skipTest(f"hard links are unavailable: {exc}")
            document = assembly.as_dict()
            document["interface_result"]["locator"] = linked.name
            rebound = ComponentAssembly.from_dict(document)

            with self.assertRaisesRegex(InputError, "hard-linked"):
                compile_component_assembly(rebound, root, root / "output")

    def test_rehashed_bundle_analysis_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            output = root / "output"
            compile_component_assembly(assembly, root, output)
            bundle_path = output / "component-pair.component-assembly-bundle.json"
            bundle = loads_strict(bundle_path.read_bytes())
            bundle["content"]["analysis"]["pair_results"][0]["distance_mm"] = "500"
            bundle["digest"] = digest(bundle["content"])
            bundle_path.write_text(dumps_pretty(bundle), encoding="utf-8", newline="\n")

            with self.assertRaisesRegex(IntegrityError, "independently reproduce"):
                verify_component_assembly_bundle(bundle_path, root)

    def test_output_artifact_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            output = root / "output"
            compile_component_assembly(assembly, root, output)
            stl_path = output / "component-pair.stl"
            stl_path.write_bytes(stl_path.read_bytes() + b"tamper")

            with self.assertRaisesRegex(IntegrityError, "artifact size mismatch"):
                verify_component_assembly_bundle(
                    output / "component-pair.component-assembly-bundle.json", root
                )

    def test_rehashed_arbitrary_outputs_do_not_replace_geometry_replay(self) -> None:
        for suffix in ("step", "stl"):
            with (
                self.subTest(suffix=suffix),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                assembly, _, _, _ = self._fixture(root)
                output = root / "output"
                compile_component_assembly(assembly, root, output)
                artifact_path = output / f"component-pair.{suffix}"
                replacement = (f"arbitrary-{suffix}-payload\n").encode()
                artifact_path.write_bytes(replacement)
                bundle_path = output / "component-pair.component-assembly-bundle.json"
                bundle = loads_strict(bundle_path.read_bytes())
                descriptor = next(
                    item
                    for item in bundle["content"]["artifacts"]
                    if item["path"] == artifact_path.name
                )
                descriptor["digest"] = file_digest(artifact_path)
                descriptor["size_bytes"] = len(replacement)
                bundle["digest"] = digest(bundle["content"])
                bundle_path.write_text(
                    dumps_pretty(bundle), encoding="utf-8", newline="\n"
                )

                with self.assertRaisesRegex(
                    IntegrityError, "do not reproduce from rebuilt geometry"
                ):
                    verify_component_assembly_bundle(bundle_path, root)

    def test_hard_linked_output_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            output = root / "output"
            compile_component_assembly(assembly, root, output)
            step_path = output / "component-pair.step"
            shadow = output / "step-shadow.bin"
            step_path.replace(shadow)
            try:
                step_path.hardlink_to(shadow)
            except OSError as exc:
                self.skipTest(f"hard links are unavailable: {exc}")

            with self.assertRaisesRegex(IntegrityError, "hard-linked"):
                verify_component_assembly_bundle(
                    output / "component-pair.component-assembly-bundle.json", root
                )

    def test_linked_output_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            output = root / "output"
            compile_component_assembly(assembly, root, output)
            step_path = output / "component-pair.step"
            shadow = output / "step-shadow.bin"
            step_path.replace(shadow)
            try:
                step_path.symlink_to(shadow.name)
            except OSError as exc:
                self.skipTest(f"symbolic links are unavailable: {exc}")

            with self.assertRaisesRegex(IntegrityError, "link or reparse"):
                verify_component_assembly_bundle(
                    output / "component-pair.component-assembly-bundle.json", root
                )

    def test_hard_linked_release_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, component_root = self._fixture(root)
            step_path = component_root / "plate.demo.step"
            shadow = component_root / "plate-shadow.step"
            step_path.replace(shadow)
            try:
                step_path.hardlink_to(shadow)
            except OSError as exc:
                self.skipTest(f"hard links are unavailable: {exc}")

            with self.assertRaisesRegex(InputError, "hard-linked"):
                compile_component_assembly(assembly, root, root / "output")

    def test_linked_release_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, component_root = self._fixture(root)
            step_path = component_root / "plate.demo.step"
            shadow = component_root / "plate-shadow.step"
            step_path.replace(shadow)
            try:
                step_path.symlink_to(shadow.name)
            except OSError as exc:
                self.skipTest(f"symbolic links are unavailable: {exc}")

            with self.assertRaisesRegex(InputError, "links or reparse"):
                compile_component_assembly(assembly, root, root / "output")

    def test_interface_snapshot_detects_mid_read_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, interface_path, _, _ = self._fixture(root)

            def replace_after_read(handle, maximum_bytes):
                captured = _read_bounded_chunks(handle, maximum_bytes)
                if Path(handle.name) == interface_path:
                    interface_path.write_bytes(captured + b" ")
                return captured

            with (
                patch(
                    "contrainte.component_assembly._read_bounded_chunks",
                    side_effect=replace_after_read,
                ),
                self.assertRaisesRegex(InputError, "changed while"),
            ):
                compile_component_assembly(assembly, root, root / "output")

    def test_result_snapshot_detects_mid_read_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, result_path, _ = self._fixture(root)

            def replace_after_read(handle, maximum_bytes):
                captured = _read_bounded_chunks(handle, maximum_bytes)
                if Path(handle.name) == result_path:
                    result_path.write_bytes(captured + b" ")
                return captured

            with (
                patch(
                    "contrainte.component_assembly._read_bounded_chunks",
                    side_effect=replace_after_read,
                ),
                self.assertRaisesRegex(InputError, "changed while"),
            ):
                compile_component_assembly(assembly, root, root / "output")

    def test_manifest_snapshot_detects_mid_read_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, component_root = self._fixture(root)
            manifest_path = component_root / "left.component.json"

            def replace_after_read(handle, maximum_bytes):
                captured = _read_bounded_chunks(handle, maximum_bytes)
                if Path(handle.name) == manifest_path:
                    manifest_path.write_bytes(captured + b" ")
                return captured

            with (
                patch(
                    "contrainte.component_assembly._read_bounded_chunks",
                    side_effect=replace_after_read,
                ),
                self.assertRaisesRegex(InputError, "changed while"),
            ):
                compile_component_assembly(assembly, root, root / "output")

    def test_release_snapshot_detects_mid_read_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, component_root = self._fixture(root)
            step_path = component_root / "plate.demo.step"

            def replace_after_read(handle, maximum_bytes):
                captured = _read_bounded_chunks(handle, maximum_bytes)
                if Path(handle.name) == step_path:
                    step_path.write_bytes(captured + b" ")
                return captured

            with (
                patch(
                    "contrainte.component_assembly._read_bounded_chunks",
                    side_effect=replace_after_read,
                ),
                self.assertRaisesRegex(InputError, "changed while"),
            ):
                compile_component_assembly(assembly, root, root / "output")

    def test_oversized_documents_are_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            oversized = root / "oversized.json"
            with oversized.open("wb") as handle:
                handle.truncate(4 * 1024 * 1024 + 1)
            with (
                patch.object(
                    Path,
                    "open",
                    side_effect=AssertionError("must not open oversized file"),
                ),
                self.assertRaisesRegex(InputError, "byte limit"),
            ):
                load_component_assembly(oversized)
            with (
                patch.object(
                    Path,
                    "open",
                    side_effect=AssertionError("must not open oversized file"),
                ),
                self.assertRaisesRegex(IntegrityError, "byte limit"),
            ):
                verify_component_assembly_bundle(oversized, root)

    def test_oversized_bound_sources_are_rejected_before_target_read(self) -> None:
        for target_kind in ("interface", "result", "manifest"):
            with (
                self.subTest(target=target_kind),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                assembly, interface_path, result_path, component_root = self._fixture(
                    root
                )
                targets = {
                    "interface": interface_path,
                    "result": result_path,
                    "manifest": component_root / "left.component.json",
                }
                target = targets[target_kind]
                with target.open("r+b") as handle:
                    handle.truncate(4 * 1024 * 1024 + 1)

                def reject_target_read(handle, maximum_bytes, target_path=target):
                    if Path(handle.name) == target_path:
                        raise AssertionError("oversized source must not be read")
                    return _read_bounded_chunks(handle, maximum_bytes)

                with (
                    patch(
                        "contrainte.component_assembly._read_bounded_chunks",
                        side_effect=reject_target_read,
                    ),
                    self.assertRaisesRegex(InputError, "source file size limit"),
                ):
                    compile_component_assembly(assembly, root, root / "output")

    def test_release_artifact_byte_limit_is_checked_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, component_root = self._fixture(root)
            step_path = component_root / "plate.demo.step"
            with step_path.open("r+b") as handle:
                handle.truncate(64 * 1024 * 1024 + 1)

            def reject_target_read(handle, maximum_bytes):
                if Path(handle.name) == step_path:
                    raise AssertionError("oversized artifact must not be read")
                return _read_bounded_chunks(handle, maximum_bytes)

            with (
                patch(
                    "contrainte.component_assembly._read_bounded_chunks",
                    side_effect=reject_target_read,
                ),
                self.assertRaisesRegex(InputError, "artifact exceeds its byte limit"),
            ):
                compile_component_assembly(assembly, root, root / "output")

    def test_release_chain_limit_is_checked_before_artifact_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, component_root = self._fixture(root)
            manifest_path = component_root / "left.component.json"
            manifest = loads_strict(manifest_path.read_bytes())
            for index in (1, 2):
                name = f"large-{index}.bin"
                with (component_root / name).open("wb") as handle:
                    handle.truncate(64 * 1024 * 1024)
                manifest["artifacts"].append(
                    {
                        "artifact_id": f"large-{index}",
                        "role": "test_record",
                        "media_type": "application/octet-stream",
                        "digest": "sha256:" + str(index) * 64,
                        "locator": name,
                    }
                )
            manifest_path.write_text(
                dumps_pretty(manifest), encoding="utf-8", newline="\n"
            )
            document = assembly.as_dict()
            document["component_bindings"][0]["manifest_file_digest"] = file_digest(
                manifest_path
            )
            rebound = ComponentAssembly.from_dict(document)

            def reject_large_read(handle, maximum_bytes):
                if Path(handle.name).name.startswith("large-"):
                    raise AssertionError("oversized chain artifacts must not be read")
                return _read_bounded_chunks(handle, maximum_bytes)

            with (
                patch(
                    "contrainte.component_assembly._read_bounded_chunks",
                    side_effect=reject_large_read,
                ),
                self.assertRaisesRegex(InputError, "release chain exceeds"),
            ):
                compile_component_assembly(rebound, root, root / "output")

    def test_direct_construction_limits_precede_as_dict_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            malformed = ComponentAssembly(
                assembly_id=assembly.assembly_id,
                revision=assembly.revision,
                title=assembly.title,
                interface_assembly=assembly.interface_assembly,
                interface_result=assembly.interface_result,
                component_bindings=list(assembly.component_bindings),
                default_minimum_clearance_mm=assembly.default_minimum_clearance_mm,
                pair_clearances=assembly.pair_clearances,
            )
            oversized = ComponentAssembly(
                assembly_id=assembly.assembly_id,
                revision=assembly.revision,
                title=assembly.title,
                interface_assembly=assembly.interface_assembly,
                interface_result=assembly.interface_result,
                component_bindings=(assembly.component_bindings[0],) * 65,
                default_minimum_clearance_mm=assembly.default_minimum_clearance_mm,
                pair_clearances=assembly.pair_clearances,
            )
            for value in (malformed, oversized):
                with (
                    self.subTest(kind=type(value.component_bindings).__name__),
                    patch.object(
                        ComponentAssembly,
                        "as_dict",
                        side_effect=AssertionError("as_dict must not be called"),
                    ),
                    self.assertRaisesRegex(InputError, "component_bindings"),
                ):
                    compile_component_assembly(value, root, root / "output")

    def test_source_locators_are_confined_and_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            traversal = assembly.as_dict()
            traversal["component_bindings"][0]["manifest_locator"] = "../left.json"
            with self.assertRaisesRegex(InputError, "POSIX file locator"):
                ComponentAssembly.from_dict(traversal)

            missing = assembly.as_dict()
            missing["interface_result"]["locator"] = "absent.json"
            with self.assertRaisesRegex(InputError, "within the source root"):
                compile_component_assembly(
                    ComponentAssembly.from_dict(missing), root, root / "output"
                )

    def test_unknown_fields_and_noncanonical_clearance_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            unknown = assembly.as_dict()
            unknown["claim"] = "released"
            with self.assertRaisesRegex(InputError, "must contain exactly"):
                ComponentAssembly.from_dict(unknown)

            noncanonical = assembly.as_dict()
            noncanonical["default_minimum_clearance_mm"] = "10/2"
            with self.assertRaisesRegex(InputError, "reduced and canonical"):
                ComponentAssembly.from_dict(noncanonical)
