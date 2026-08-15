from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import ROUND_DOWN, Inexact, Rounded, localcontext
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import contrainte
import contrainte.component_assembly as component_assembly_module
from contrainte.artifacts import file_digest
from contrainte.cad import compile_part, load_part
from contrainte.canonical import digest, dumps_pretty, loads_strict
from contrainte.cli import main as cli_main
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
    prepare_component_assembly,
    verify_component_assembly_bundle,
)
from contrainte.errors import ExecutionError, InputError, IntegrityError
from contrainte.interface_assembly import (
    InterfaceAssembly,
    InterfaceAssemblyResult,
    solve_interface_assembly,
    verify_interface_assembly_result,
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
        self.assertIs(contrainte.prepare_component_assembly, prepare_component_assembly)
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

    def _write_prepare_template(self, root: Path, assembly: ComponentAssembly) -> None:
        (root / "assembly-template.json").write_text(
            dumps_pretty(assembly.as_dict()), encoding="utf-8", newline="\n"
        )

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

    def test_prepare_rebinds_current_releases_and_closes_strict_compile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, interface_path, _, component_root = self._fixture(root)
            interface_template = loads_strict(interface_path.read_bytes())
            interface_template["occurrences"][0]["component"]["title"] = (
                "Stale platform-specific template component"
            )
            interface_path.write_text(
                dumps_pretty(interface_template), encoding="utf-8", newline="\n"
            )

            placeholder_digest = f"sha256:{'0' * 64}"
            assembly_template = assembly.as_dict()
            assembly_template["interface_assembly"]["file_digest"] = placeholder_digest
            assembly_template["interface_result"]["file_digest"] = placeholder_digest
            for binding in assembly_template["component_bindings"]:
                binding["manifest_file_digest"] = placeholder_digest
                binding["manifest_digest"] = placeholder_digest
            assembly_template_path = root / "assembly-template.json"
            assembly_template_path.write_text(
                dumps_pretty(assembly_template), encoding="utf-8", newline="\n"
            )

            first = prepare_component_assembly(
                "interface.json", "assembly-template.json", root, "prepared"
            )
            second = prepare_component_assembly(
                "interface.json", "assembly-template.json", root, "prepared"
            )
            self.assertEqual(first, second)
            self.assertEqual(first["status"], "prepared")

            prepared_interface_path = root / first["interface_locator"]
            prepared_result_path = root / first["result_locator"]
            prepared_assembly_path = root / first["assembly_locator"]
            prepared_interface = InterfaceAssembly.from_dict(
                loads_strict(prepared_interface_path.read_bytes())
            )
            prepared_result = InterfaceAssemblyResult.from_dict(
                loads_strict(prepared_result_path.read_bytes())
            )
            prepared_assembly = load_component_assembly(prepared_assembly_path)
            self.assertEqual(
                first["interface_file_digest"], file_digest(prepared_interface_path)
            )
            self.assertEqual(
                first["result_file_digest"], file_digest(prepared_result_path)
            )
            self.assertEqual(
                first["assembly_file_digest"], file_digest(prepared_assembly_path)
            )
            self.assertEqual(
                prepared_interface_path.read_bytes(),
                dumps_pretty(prepared_interface.as_dict()).encode("utf-8"),
            )
            self.assertEqual(
                prepared_result_path.read_bytes(),
                dumps_pretty(prepared_result.as_dict()).encode("utf-8"),
            )
            self.assertEqual(
                prepared_assembly_path.read_bytes(),
                dumps_pretty(prepared_assembly.as_dict()).encode("utf-8"),
            )
            self.assertTrue(
                verify_interface_assembly_result(prepared_interface, prepared_result)
            )
            self.assertEqual(
                prepared_assembly.interface_assembly.file_digest,
                file_digest(prepared_interface_path),
            )
            self.assertEqual(
                prepared_assembly.interface_result.file_digest,
                file_digest(prepared_result_path),
            )
            manifests = {
                occurrence_id: loads_strict(
                    (component_root / f"{occurrence_id}.component.json").read_bytes()
                )
                for occurrence_id in ("left", "right")
            }
            for occurrence in prepared_interface.occurrences:
                self.assertEqual(
                    occurrence.component.as_dict(), manifests[occurrence.occurrence_id]
                )
            for binding in prepared_assembly.component_bindings:
                manifest_path = root / binding.manifest_locator
                manifest = prepared_interface.occurrences[
                    0 if binding.occurrence_id == "left" else 1
                ].component
                self.assertEqual(
                    binding.manifest_file_digest, file_digest(manifest_path)
                )
                self.assertEqual(binding.manifest_digest, manifest.manifest_digest)

            bundle = compile_component_assembly(
                prepared_assembly, root, root / "compiled"
            )
            report = verify_component_assembly_bundle(
                root / "compiled" / "component-pair.component-assembly-bundle.json",
                root,
            )
            self.assertEqual(bundle["digest"], report["bundle_digest"])

    def test_prepare_rejects_confused_template_and_escaping_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            template = assembly.as_dict()
            template["interface_assembly"]["locator"] = "different.json"
            template_path = root / "assembly-template.json"
            template_path.write_text(
                dumps_pretty(template), encoding="utf-8", newline="\n"
            )
            with self.assertRaisesRegex(InputError, "supplied interface template"):
                prepare_component_assembly(
                    "interface.json", "assembly-template.json", root, "prepared"
                )

            template["interface_assembly"]["locator"] = "interface.json"
            template_path.write_text(
                dumps_pretty(template), encoding="utf-8", newline="\n"
            )
            with self.assertRaisesRegex(InputError, "within the source root"):
                prepare_component_assembly(
                    "interface.json", "assembly-template.json", root, "../outside"
                )

    def test_prepare_cli_dispatches_authoring_boundary(self) -> None:
        report = {
            "status": "prepared",
            "assembly_locator": "prepared/demo.component-assembly.json",
        }
        with (
            patch(
                "contrainte.cli.prepare_component_assembly", return_value=report
            ) as prepare,
            redirect_stdout(io.StringIO()) as output,
        ):
            code = cli_main(
                [
                    "component-assembly",
                    "prepare",
                    "templates/interface.json",
                    "templates/assembly.json",
                    "--source-root",
                    ".",
                    "--output-dir",
                    "prepared",
                ]
            )
        self.assertEqual(code, 0)
        prepare.assert_called_once_with(
            "templates/interface.json", "templates/assembly.json", ".", "prepared"
        )
        self.assertEqual(loads_strict(output.getvalue()), report)

    def test_prepare_staging_failures_leave_no_partial_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            self._write_prepare_template(root, assembly)
            original = component_assembly_module._BoundDirectory.write_new_file

            for failure_after in (1, 2, 3):
                calls = 0

                def fail_after_stage(
                    bound: object,
                    name: str,
                    captured: bytes,
                    *,
                    field: str,
                    failure_target: int = failure_after,
                ) -> None:
                    nonlocal calls
                    calls += 1
                    original(bound, name, captured, field=field)
                    if calls == failure_target:
                        raise ExecutionError("injected staging failure")

                with (
                    self.subTest(failure_after=failure_after),
                    patch(
                        "contrainte.component_assembly._BoundDirectory.write_new_file",
                        new=fail_after_stage,
                    ),
                    self.assertRaisesRegex(ExecutionError, "injected staging"),
                ):
                    prepare_component_assembly(
                        "interface.json",
                        "assembly-template.json",
                        root,
                        "publication/prepared",
                    )
                self.assertFalse((root / "publication" / "prepared").exists())
                self.assertEqual(tuple((root / "publication").iterdir()), ())

    def test_prepare_promotion_failures_restore_prior_exact_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            self._write_prepare_template(root, assembly)
            prepare_component_assembly(
                "interface.json",
                "assembly-template.json",
                root,
                "publication/prepared",
            )
            destination = root / "publication" / "prepared"
            prior = {path.name: path.read_bytes() for path in destination.iterdir()}
            real_rename = component_assembly_module._BoundDirectory.rename_child_handle

            for failure_after in (1, 2):
                calls = 0

                def fail_after_promotion(
                    bound: object,
                    child: object,
                    target: str,
                    failure_target: int = failure_after,
                ) -> None:
                    nonlocal calls
                    calls += 1
                    real_rename(bound, child, target)
                    if calls == failure_target:
                        raise OSError("injected promotion failure")

                with (
                    self.subTest(failure_after=failure_after),
                    patch(
                        "contrainte.component_assembly._BoundDirectory.rename_child_handle",
                        new=fail_after_promotion,
                    ),
                    self.assertRaisesRegex(OSError, "injected promotion"),
                ):
                    prepare_component_assembly(
                        "interface.json",
                        "assembly-template.json",
                        root,
                        "publication/prepared",
                    )
                self.assertEqual(
                    {path.name: path.read_bytes() for path in destination.iterdir()},
                    prior,
                )
                self.assertEqual(
                    {path.name for path in (root / "publication").iterdir()},
                    {"prepared"},
                )

            with (
                patch(
                    "contrainte.component_assembly._load_bound_context",
                    side_effect=IntegrityError("injected post-promotion failure"),
                ),
                self.assertRaisesRegex(IntegrityError, "post-promotion"),
            ):
                prepare_component_assembly(
                    "interface.json",
                    "assembly-template.json",
                    root,
                    "publication/prepared",
                )
            self.assertEqual(
                {path.name: path.read_bytes() for path in destination.iterdir()}, prior
            )

    def test_prepare_restores_prior_set_after_deleted_backup_cleanup_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, component_root = self._fixture(root)
            self._write_prepare_template(root, assembly)
            prepare_component_assembly(
                "interface.json",
                "assembly-template.json",
                root,
                "publication/prepared",
            )
            destination = root / "publication" / "prepared"
            prior = {path.name: path.read_bytes() for path in destination.iterdir()}

            changed_request = _release_request(
                "component.plate-left", "edge-right", "60"
            )
            changed_request["title"] = "changed local platform release"
            bundle_path = component_root / "plate.demo.cad-bundle.json"
            changed_manifest = derive_component_manifest(
                bundle_path,
                ComponentReleaseRequest.from_dict(changed_request),
            )
            write_component_manifest(
                component_root / "left.component.json",
                changed_manifest,
                bundle_path=bundle_path,
            )

            original = component_assembly_module._discard_bound_prepared_directory
            injected = False

            def fail_after_deleted_backup(*args: object, **kwargs: object) -> None:
                nonlocal injected
                bound_directory = args[1]
                is_backup = ".prepared.previous-" in bound_directory.path.name
                original(*args, **kwargs)
                if is_backup and not injected:
                    injected = True
                    raise OSError("injected post-delete backup cleanup failure")

            with (
                patch(
                    "contrainte.component_assembly._discard_bound_prepared_directory",
                    side_effect=fail_after_deleted_backup,
                ),
                self.assertRaisesRegex(
                    IntegrityError, "previous exact set was restored"
                ),
            ):
                prepare_component_assembly(
                    "interface.json",
                    "assembly-template.json",
                    root,
                    "publication/prepared",
                )

            self.assertTrue(injected)
            self.assertEqual(
                {path.name: path.read_bytes() for path in destination.iterdir()}, prior
            )
            self.assertEqual(
                {path.name for path in destination.parent.iterdir()}, {"prepared"}
            )

            prepare_component_assembly(
                "interface.json",
                "assembly-template.json",
                root,
                "publication/prepared",
            )
            changed = {path.name: path.read_bytes() for path in destination.iterdir()}
            self.assertNotEqual(changed, prior)

    @unittest.skipIf(os.name == "nt", "portable POSIX descriptor regression")
    def test_prepare_does_not_depend_on_procfs_descriptor_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            self._write_prepare_template(root, assembly)
            with patch(
                "contrainte.component_assembly.os.readlink",
                side_effect=OSError("procfs is unavailable"),
            ):
                report = prepare_component_assembly(
                    "interface.json",
                    "assembly-template.json",
                    root,
                    "publication/prepared",
                )
            self.assertEqual(report["status"], "prepared")
            self.assertTrue((root / report["assembly_locator"]).is_file())

    @unittest.skipIf(os.name == "nt", "POSIX transaction permissions")
    def test_prepare_private_stage_directory_has_owner_only_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            self._write_prepare_template(root, assembly)
            original = component_assembly_module._BoundDirectory.write_new_file
            observed_modes: list[int] = []

            def record_stage_mode(
                bound: object,
                name: str,
                captured: bytes,
                *,
                field: str,
            ) -> None:
                if field.startswith("staged prepared output"):
                    observed_modes.append(stat.S_IMODE(os.fstat(bound.handle).st_mode))
                original(bound, name, captured, field=field)

            with patch(
                "contrainte.component_assembly._BoundDirectory.write_new_file",
                new=record_stage_mode,
            ):
                prepare_component_assembly(
                    "interface.json",
                    "assembly-template.json",
                    root,
                    "publication/prepared",
                )
            self.assertEqual(observed_modes, [0o700, 0o700, 0o700])

    def test_prepare_rejects_semantic_equivalent_stage_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            self._write_prepare_template(root, assembly)
            original = component_assembly_module._BoundDirectory.write_new_file
            names = (
                "component-pair.interface.json",
                "component-pair.interface-result.json",
                "component-pair.component-assembly.json",
            )
            for target_name in names:

                def replace_with_compact(
                    bound: object,
                    name: str,
                    captured: bytes,
                    *,
                    field: str,
                    replacement_target: str = target_name,
                ) -> None:
                    original(bound, name, captured, field=field)
                    if name == replacement_target:
                        path = bound.path / name
                        path.write_text(
                            json.dumps(
                                loads_strict(captured),
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            encoding="utf-8",
                            newline="\n",
                        )

                with (
                    self.subTest(target=target_name),
                    patch(
                        "contrainte.component_assembly._BoundDirectory.write_new_file",
                        new=replace_with_compact,
                    ),
                    self.assertRaisesRegex(IntegrityError, "digest mismatch"),
                ):
                    prepare_component_assembly(
                        "interface.json",
                        "assembly-template.json",
                        root,
                        "publication/prepared",
                    )
                self.assertFalse((root / "publication" / "prepared").exists())

    def test_prepare_final_capture_rejects_semantic_equivalent_replacement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            self._write_prepare_template(root, assembly)
            original_load = component_assembly_module._load_bound_context
            names = (
                "component-pair.interface.json",
                "component-pair.interface-result.json",
                "component-pair.component-assembly.json",
            )
            for target_name in names:

                def replace_before_context(
                    *args: object,
                    replacement_target: str = target_name,
                    **kwargs: object,
                ) -> object:
                    path = root / "publication" / "prepared" / replacement_target
                    path.write_text(
                        json.dumps(
                            loads_strict(path.read_bytes()),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        encoding="utf-8",
                        newline="\n",
                    )
                    return original_load(*args, **kwargs)

                with (
                    self.subTest(target=target_name),
                    patch(
                        "contrainte.component_assembly._load_bound_context",
                        side_effect=replace_before_context,
                    ),
                    self.assertRaises(IntegrityError),
                ):
                    prepare_component_assembly(
                        "interface.json",
                        "assembly-template.json",
                        root,
                        "publication/prepared",
                    )
                self.assertFalse((root / "publication" / "prepared").exists())

    def test_prepare_retains_every_final_file_through_set_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            self._write_prepare_template(root, assembly)
            original_open = component_assembly_module._open_retained_bound_file
            names = (
                "component-pair.interface.json",
                "component-pair.interface-result.json",
                "component-pair.component-assembly.json",
            )
            for target_name in names:
                matching_captures = 0

                def replace_during_final_capture(
                    *args: object,
                    replacement_target: str = target_name,
                    **kwargs: object,
                ) -> object:
                    nonlocal matching_captures
                    retained = original_open(*args, **kwargs)
                    if kwargs["field"] != f"prepared output {replacement_target}":
                        return retained
                    matching_captures += 1
                    if matching_captures != 4:
                        return retained
                    path = retained.parent.path / retained.name
                    compact = json.dumps(
                        loads_strict(retained.captured),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    try:
                        path.write_text(compact, encoding="utf-8", newline="\n")
                    except OSError as exc:
                        retained.close()
                        raise IntegrityError(
                            "final prepared file replacement was handle-blocked"
                        ) from exc
                    return retained

                with (
                    self.subTest(target=target_name),
                    patch(
                        "contrainte.component_assembly._open_retained_bound_file",
                        side_effect=replace_during_final_capture,
                    ),
                    self.assertRaisesRegex(
                        IntegrityError, "handle-blocked|changed after capture"
                    ),
                ):
                    prepare_component_assembly(
                        "interface.json",
                        "assembly-template.json",
                        root,
                        "publication/prepared",
                    )
                self.assertEqual(matching_captures, 4)
                self.assertFalse((root / "publication" / "prepared").exists())

    def test_prepare_rejects_foreign_and_hard_linked_output_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            self._write_prepare_template(root, assembly)
            destination = root / "publication" / "prepared"
            destination.mkdir(parents=True)
            foreign = destination / "foreign.txt"
            foreign.write_text("foreign", encoding="utf-8")
            with self.assertRaisesRegex(InputError, "foreign"):
                prepare_component_assembly(
                    "interface.json",
                    "assembly-template.json",
                    root,
                    "publication/prepared",
                )
            self.assertEqual(foreign.read_text(encoding="utf-8"), "foreign")

            foreign.unlink()
            prepare_component_assembly(
                "interface.json",
                "assembly-template.json",
                root,
                "publication/prepared",
            )
            target = destination / "component-pair.interface.json"
            hardlink_source = root / "hardlink-source.json"
            hardlink_source.write_bytes(target.read_bytes())
            target.unlink()
            os.link(hardlink_source, target)
            with self.assertRaisesRegex(InputError, "hard-linked"):
                prepare_component_assembly(
                    "interface.json",
                    "assembly-template.json",
                    root,
                    "publication/prepared",
                )

    def test_prepare_rejects_linked_output_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            self._write_prepare_template(root, assembly)
            prepare_component_assembly(
                "interface.json",
                "assembly-template.json",
                root,
                "publication/prepared",
            )
            destination = root / "publication" / "prepared"
            target = destination / "component-pair.interface.json"
            shadow = root / "interface-shadow.json"
            target.replace(shadow)
            try:
                target.symlink_to(shadow)
            except OSError as exc:
                shadow.replace(target)
                self.skipTest(f"symbolic links are unavailable: {exc}")
            try:
                with self.assertRaisesRegex(InputError, "links or reparse"):
                    prepare_component_assembly(
                        "interface.json",
                        "assembly-template.json",
                        root,
                        "publication/prepared",
                    )
            finally:
                target.unlink()
                shadow.replace(target)

    def test_prepare_detects_source_ancestor_identity_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, component_root = self._fixture(root)
            self._write_prepare_template(root, assembly)
            displaced = root / "components-displaced"
            outside = root / "outside-components"
            outside.mkdir()
            marker = outside / "marker.bin"
            marker.write_bytes(b"outside-must-not-be-read-or-changed")
            swapped = False
            attempted = False

            def install_directory_link(link: Path, target: Path) -> None:
                if os.name == "nt":
                    completed = subprocess.run(
                        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if completed.returncode != 0:
                        raise unittest.SkipTest(
                            f"directory junctions are unavailable: {completed.stderr}"
                        )
                else:
                    link.symlink_to(target, target_is_directory=True)

            def attempt_swap(point: str) -> None:
                nonlocal attempted, swapped
                if point != "before_file_open:component manifest" or attempted:
                    return
                attempted = True
                try:
                    os.replace(component_root, displaced)
                except OSError as exc:
                    raise IntegrityError(
                        "source ancestor swap blocked before file read"
                    ) from exc
                swapped = True
                install_directory_link(component_root, outside)

            try:
                with (
                    patch(
                        "contrainte.component_assembly._prepare_fault_hook",
                        side_effect=attempt_swap,
                    ),
                    self.assertRaisesRegex(
                        IntegrityError,
                        "swap blocked|location changed|no longer visible",
                    ),
                ):
                    prepare_component_assembly(
                        "interface.json",
                        "assembly-template.json",
                        root,
                        "publication/prepared",
                    )
            finally:
                if swapped:
                    if os.name == "nt":
                        os.rmdir(component_root)
                    else:
                        component_root.unlink()
                    os.replace(displaced, component_root)
            self.assertTrue(attempted)
            self.assertEqual(
                marker.read_bytes(), b"outside-must-not-be-read-or-changed"
            )
            self.assertEqual({item.name for item in outside.iterdir()}, {"marker.bin"})

    def test_prepare_detects_output_ancestor_link_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assembly, _, _, _ = self._fixture(root)
            self._write_prepare_template(root, assembly)
            publication = root / "publication"
            displaced = root / "publication-displaced"
            outside = root / "outside-publication"
            outside.mkdir()
            marker = outside / "marker.bin"
            marker.write_bytes(b"outside-must-not-be-written-or-removed")
            swapped = False
            attempted = False

            def install_directory_link(link: Path, target: Path) -> None:
                if os.name == "nt":
                    completed = subprocess.run(
                        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if completed.returncode != 0:
                        raise unittest.SkipTest(
                            f"directory junctions are unavailable: {completed.stderr}"
                        )
                else:
                    link.symlink_to(target, target_is_directory=True)

            def attempt_swap(point: str) -> None:
                nonlocal attempted, swapped
                if not point.startswith("before_file_create:staged prepared output"):
                    return
                if not attempted:
                    attempted = True
                    try:
                        os.replace(publication, displaced)
                    except OSError as exc:
                        raise IntegrityError(
                            "output ancestor swap blocked before file write"
                        ) from exc
                    swapped = True
                    install_directory_link(publication, outside)

            try:
                with (
                    patch(
                        "contrainte.component_assembly._prepare_fault_hook",
                        side_effect=attempt_swap,
                    ),
                    self.assertRaisesRegex(
                        IntegrityError,
                        "swap blocked|location changed|no longer visible",
                    ),
                ):
                    prepare_component_assembly(
                        "interface.json",
                        "assembly-template.json",
                        root,
                        "publication/prepared",
                    )
            finally:
                if swapped:
                    if publication.exists() or publication.is_symlink():
                        if os.name == "nt":
                            os.rmdir(publication)
                        else:
                            publication.unlink()
                    os.replace(displaced, publication)
            self.assertTrue(attempted)
            self.assertFalse((publication / "prepared").exists())
            self.assertEqual(tuple(publication.iterdir()), ())
            self.assertEqual(
                marker.read_bytes(), b"outside-must-not-be-written-or-removed"
            )
            self.assertEqual({item.name for item in outside.iterdir()}, {"marker.bin"})

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
