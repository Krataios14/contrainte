from __future__ import annotations

import copy
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

from contrainte.artifacts import file_digest
from contrainte.cad import compile_part, load_part
from contrainte.canonical import dumps_pretty, loads_strict
from contrainte.component import ArtifactRole, Qualification
from contrainte.errors import InputError, IntegrityError
from contrainte.release import (
    ComponentReleaseRequest,
    derive_component_manifest,
    load_release_request,
    reproduce_local_component_shape,
    verify_local_component_manifest,
    write_component_manifest,
)
from contrainte.sketch import compile_sketch_extrusion, load_sketch_extrusion
from contrainte.solid import compile_solid_program, load_solid_program

SOLID_EXAMPLE = Path(__file__).parents[1] / "examples" / "pedestal-bracket.json"
SKETCH_EXAMPLE = (
    Path(__file__).parents[1] / "examples" / "constrained-pocket-plate.json"
)
CIRCULAR_SKETCH_EXAMPLE = (
    Path(__file__).parents[1] / "examples" / "circular-through-hole-plate.json"
)
CAD_EXAMPLE = Path(__file__).parents[1] / "examples" / "mounting-plate.json"
TOPOLOGY_REQUEST_EXAMPLE = (
    Path(__file__).parents[1] / "examples" / "mounting-plate-topology-component.json"
)


class ComponentReleaseTests(unittest.TestCase):
    def request_document(self) -> dict:
        return {
            "schema_version": "contrainte.component-release-request/0.1",
            "component_id": "component.fixture.demo",
            "revision": "A",
            "title": "Geometry-backed demonstration fixture",
            "interfaces": [
                {
                    "interface_id": "mount",
                    "kind": "mechanical",
                    "direction": "bidirectional",
                    "medium": "bolted_joint",
                    "properties": {"datum": "base"},
                }
            ],
            "capabilities": ["fixture_support"],
            "metadata": {"data_class": "synthetic"},
        }

    def framed_request_document(self) -> dict:
        document = self.request_document()
        document["schema_version"] = "contrainte.component-release-request/0.2"
        document["interfaces"][0]["frame"] = {
            "reference": "engineering_bundle",
            "unit": "mm",
            "origin": {"x": "0", "y": "0", "z": "0"},
            "basis": {
                "x_axis": {"x": "1", "y": "0", "z": "0"},
                "y_axis": {"x": "0", "y": "1", "z": "0"},
                "z_axis": {"x": "0", "y": "0", "z": "1"},
            },
        }
        return document

    def topology_request_document(self) -> dict:
        return loads_strict(TOPOLOGY_REQUEST_EXAMPLE.read_bytes())

    def topology_fixture(self, root: Path):
        part = load_part(CAD_EXAMPLE)
        compile_part(part, root)
        bundle_path = root / f"{part.part_id}.cad-bundle.json"
        request = ComponentReleaseRequest.from_dict(self.topology_request_document())
        manifest = derive_component_manifest(bundle_path, request)
        manifest_path = root / "component.mounting-plate.topology-demo.json"
        write_component_manifest(manifest_path, manifest, bundle_path=bundle_path)
        return manifest, manifest_path, bundle_path

    def test_release_request_rejects_promotion_fields(self) -> None:
        document = self.request_document()
        document["qualification"] = "engineering_reviewed"

        with self.assertRaisesRegex(InputError, "unsupported fields"):
            ComponentReleaseRequest.from_dict(document)

    def test_release_request_requires_canonical_capability_order(self) -> None:
        document = self.request_document()
        document["capabilities"] = ["zeta", "alpha"]

        with self.assertRaisesRegex(InputError, "ascending lexical order"):
            ComponentReleaseRequest.from_dict(document)

    def test_release_request_size_and_interface_count_are_bounded(self) -> None:
        legacy = self.request_document()
        legacy_template = legacy["interfaces"][0]
        legacy["interfaces"] = []
        for index in range(65):
            interface = copy.deepcopy(legacy_template)
            interface["interface_id"] = f"legacy-{index:02d}"
            legacy["interfaces"].append(interface)
        self.assertEqual(len(ComponentReleaseRequest.from_dict(legacy).interfaces), 65)

        document = self.topology_request_document()
        template = document["interfaces"][0]
        document["interfaces"] = []
        for index in range(64):
            interface = copy.deepcopy(template)
            interface["interface_id"] = f"mount-{index:02d}"
            document["interfaces"].append(interface)
        self.assertEqual(
            len(ComponentReleaseRequest.from_dict(document).interfaces), 64
        )

        document["interfaces"].append(
            {
                **copy.deepcopy(template),
                "interface_id": "mount-64",
            }
        )
        with self.assertRaisesRegex(InputError, "count limit"):
            ComponentReleaseRequest.from_dict(document)

        parsed = ComponentReleaseRequest.from_dict(self.topology_request_document())
        with self.assertRaisesRegex(InputError, "count limit"):
            ComponentReleaseRequest(
                schema_version=parsed.schema_version,
                component_id=parsed.component_id,
                revision=parsed.revision,
                title=parsed.title,
                interfaces=parsed.interfaces * 65,
                capabilities=parsed.capabilities,
                metadata=parsed.metadata,
            )

        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "oversized-request.json"
            request_path.write_bytes(b" " * (1024 * 1024 + 1))
            with self.assertRaisesRegex(InputError, "byte limit"):
                load_release_request(request_path)

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_verified_solid_bundle_derives_local_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = load_solid_program(SOLID_EXAMPLE)
            bundle = compile_solid_program(program, root)
            bundle_path = root / f"{program.part_id}.solid-bundle.json"
            request = ComponentReleaseRequest.from_dict(self.request_document())
            manifest = derive_component_manifest(bundle_path, request)
            manifest_path = root / "component.fixture.demo.json"
            write_component_manifest(manifest_path, manifest, bundle_path=bundle_path)

            report = verify_local_component_manifest(manifest_path)
            roles = {artifact.role for artifact in manifest.artifacts}
            self.assertEqual(report["status"], "verified")
            self.assertEqual(
                manifest.qualification, Qualification.UNQUALIFIED_DEMONSTRATION
            )
            self.assertEqual(
                manifest.schema_version, "contrainte.component-manifest/0.2"
            )
            self.assertIsNotNone(manifest.geometry_bounds)
            self.assertEqual(
                manifest.geometry_bounds.as_dict(),  # type: ignore[union-attr]
                {
                    "frame": "engineering_bundle",
                    "unit": "mm",
                    "minimum": {"x": "-50", "y": "-30", "z": "0"},
                    "maximum": {"x": "50", "y": "30", "z": "50"},
                },
            )
            self.assertEqual(
                roles,
                {
                    ArtifactRole.ENGINEERING_BUNDLE,
                    ArtifactRole.EXACT_GEOMETRY,
                    ArtifactRole.MESH,
                },
            )
            self.assertNotEqual(manifest.source_bundle_digest, bundle["digest"])
            self.assertEqual(
                manifest.metadata["engineering_bundle_content_digest"],
                bundle["digest"],
            )

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_geometry_handoff_returns_the_verified_manifest_snapshot(self) -> None:
        import contrainte.release as release_module

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = load_solid_program(SOLID_EXAMPLE)
            compile_solid_program(program, root)
            bundle_path = root / f"{program.part_id}.solid-bundle.json"
            manifest = derive_component_manifest(
                bundle_path,
                ComponentReleaseRequest.from_dict(self.request_document()),
            )
            manifest_path = root / "component.fixture.demo.json"
            write_component_manifest(manifest_path, manifest, bundle_path=bundle_path)
            promoted = manifest.as_dict()
            promoted["qualification"] = "engineering_reviewed"
            verified_value = release_module._verify_local_component_value
            replaced = False

            def replace_original_after_capture(path, captured_manifest):
                nonlocal replaced
                if not replaced:
                    manifest_path.write_text(
                        dumps_pretty(promoted), encoding="utf-8", newline="\n"
                    )
                    replaced = True
                return verified_value(path, captured_manifest)

            with patch(
                "contrainte.release._verify_local_component_value",
                side_effect=replace_original_after_capture,
            ):
                reproduced, shape = reproduce_local_component_shape(manifest_path)

            self.assertTrue(replaced)
            self.assertEqual(
                reproduced.qualification, Qualification.UNQUALIFIED_DEMONSTRATION
            )
            self.assertEqual(reproduced.as_dict(), manifest.as_dict())
            self.assertEqual(
                reproduced.geometry_bounds.as_dict(),  # type: ignore[union-attr]
                release_module._bounds_from_shape(shape).as_dict(),
            )
            self.assertEqual(
                loads_strict(manifest_path.read_bytes())["qualification"],
                "engineering_reviewed",
            )

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_rehashed_manifest_cannot_drop_or_promote_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = load_solid_program(SOLID_EXAMPLE)
            compile_solid_program(program, root)
            bundle_path = root / f"{program.part_id}.solid-bundle.json"
            manifest = derive_component_manifest(
                bundle_path,
                ComponentReleaseRequest.from_dict(self.request_document()),
            )
            manifest_path = root / "component.fixture.demo.json"
            original = manifest.as_dict()

            promoted = copy.deepcopy(original)
            promoted["qualification"] = "engineering_reviewed"
            manifest_path.write_text(
                dumps_pretty(promoted), encoding="utf-8", newline="\n"
            )
            with self.assertRaisesRegex(IntegrityError, "promoted"):
                verify_local_component_manifest(manifest_path)

            incomplete = copy.deepcopy(original)
            incomplete["artifacts"] = [
                item
                for item in incomplete["artifacts"]
                if item["role"] != "exact_geometry"
            ]
            manifest_path.write_text(
                dumps_pretty(incomplete), encoding="utf-8", newline="\n"
            )
            with self.assertRaisesRegex(IntegrityError, "exactly match"):
                verify_local_component_manifest(manifest_path)

            false_bounds = copy.deepcopy(original)
            false_bounds["geometry_bounds"]["maximum"]["x"] = "51"
            manifest_path.write_text(
                dumps_pretty(false_bounds), encoding="utf-8", newline="\n"
            )
            with self.assertRaisesRegex(IntegrityError, "bounds do not reproduce"):
                verify_local_component_manifest(manifest_path)

            traversal = copy.deepcopy(original)
            traversal["artifacts"][0]["locator"] = "../bundle.json"
            manifest_path.write_text(
                dumps_pretty(traversal), encoding="utf-8", newline="\n"
            )
            with self.assertRaisesRegex(IntegrityError, "safe local file"):
                verify_local_component_manifest(manifest_path)

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_manifest_must_be_written_beside_bundle(self) -> None:
        with (
            tempfile.TemporaryDirectory() as bundle_directory,
            tempfile.TemporaryDirectory() as other_directory,
        ):
            root = Path(bundle_directory)
            program = load_solid_program(SOLID_EXAMPLE)
            compile_solid_program(program, root)
            bundle_path = root / f"{program.part_id}.solid-bundle.json"
            manifest = derive_component_manifest(
                bundle_path,
                ComponentReleaseRequest.from_dict(self.request_document()),
            )

            with self.assertRaisesRegex(InputError, "written beside"):
                write_component_manifest(
                    Path(other_directory) / "component.json",
                    manifest,
                    bundle_path=bundle_path,
                )

    def test_manifest_json_remains_strictly_parseable(self) -> None:
        document = self.request_document()
        request = ComponentReleaseRequest.from_dict(document)
        self.assertEqual(request.as_dict(), document)
        self.assertEqual(
            ComponentReleaseRequest.from_dict(
                loads_strict(dumps_pretty(request.as_dict()))
            ),
            request,
        )

    def test_release_request_versions_keep_interface_semantics_separate(self) -> None:
        legacy = self.request_document()
        legacy["interfaces"][0]["frame"] = self.framed_request_document()["interfaces"][
            0
        ]["frame"]
        with self.assertRaisesRegex(InputError, "unsupported fields"):
            ComponentReleaseRequest.from_dict(legacy)

        framed = self.framed_request_document()
        del framed["interfaces"][0]["frame"]
        with self.assertRaisesRegex(InputError, "frame is required"):
            ComponentReleaseRequest.from_dict(framed)

    def test_topology_request_requires_frame_attachment_and_no_evidence(self) -> None:
        document = self.topology_request_document()
        request = ComponentReleaseRequest.from_dict(document)
        self.assertEqual(request.as_dict(), document)

        missing_frame = copy.deepcopy(document)
        del missing_frame["interfaces"][0]["frame"]
        with self.assertRaisesRegex(InputError, "frame is required"):
            ComponentReleaseRequest.from_dict(missing_frame)

        missing_attachment = copy.deepcopy(document)
        del missing_attachment["interfaces"][0]["attachment"]
        with self.assertRaisesRegex(InputError, "attachment is required"):
            ComponentReleaseRequest.from_dict(missing_attachment)

        supplied_evidence = copy.deepcopy(document)
        supplied_evidence["interfaces"][0]["attachment"]["evidence"] = {}
        with self.assertRaisesRegex(InputError, "unsupported fields"):
            ComponentReleaseRequest.from_dict(supplied_evidence)

    def test_pre_v3_requests_reject_topology_attachments(self) -> None:
        selector = copy.deepcopy(
            self.topology_request_document()["interfaces"][0]["attachment"]
        )
        for schema in (
            "contrainte.component-release-request/0.1",
            "contrainte.component-release-request/0.2",
        ):
            with self.subTest(schema=schema):
                document = (
                    self.request_document()
                    if schema.endswith("/0.1")
                    else self.framed_request_document()
                )
                document["interfaces"][0]["attachment"] = copy.deepcopy(selector)
                with self.assertRaisesRegex(InputError, "unsupported fields"):
                    ComponentReleaseRequest.from_dict(document)

    def test_direct_framed_request_requires_frames(self) -> None:
        legacy = ComponentReleaseRequest.from_dict(self.request_document())

        with self.assertRaisesRegex(InputError, "requires every interface frame"):
            ComponentReleaseRequest(
                "contrainte.component-release-request/0.2",
                legacy.component_id,
                legacy.revision,
                legacy.title,
                legacy.interfaces,
                legacy.capabilities,
                legacy.metadata,
            )

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_framed_request_derives_reproducible_component_v3(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = load_solid_program(SOLID_EXAMPLE)
            compile_solid_program(program, root)
            bundle_path = root / f"{program.part_id}.solid-bundle.json"
            manifest = derive_component_manifest(
                bundle_path,
                ComponentReleaseRequest.from_dict(self.framed_request_document()),
            )
            manifest_path = root / "component.fixture.demo.json"
            write_component_manifest(manifest_path, manifest, bundle_path=bundle_path)

            report = verify_local_component_manifest(manifest_path)

            self.assertEqual(report["status"], "verified")
            self.assertEqual(
                manifest.schema_version, "contrainte.component-manifest/0.3"
            )
            self.assertEqual(
                manifest.metadata["derivation"], "verified_exact_bundle/0.2"
            )
            self.assertRegex(
                manifest.metadata["component_release_request_content_digest"],
                r"^sha256:[0-9a-f]{64}$",
            )

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_framed_release_rejects_origin_outside_reproduced_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = load_solid_program(SOLID_EXAMPLE)
            compile_solid_program(program, root)
            bundle_path = root / f"{program.part_id}.solid-bundle.json"
            document = self.framed_request_document()
            document["interfaces"][0]["frame"]["origin"]["x"] = "50.000000001"

            with self.assertRaisesRegex(InputError, "within or on geometry_bounds"):
                derive_component_manifest(
                    bundle_path, ComponentReleaseRequest.from_dict(document)
                )

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_local_verifier_rejects_framed_interface_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = load_solid_program(SOLID_EXAMPLE)
            compile_solid_program(program, root)
            bundle_path = root / f"{program.part_id}.solid-bundle.json"
            manifest = derive_component_manifest(
                bundle_path,
                ComponentReleaseRequest.from_dict(self.framed_request_document()),
            )
            manifest_path = root / "component.fixture.demo.json"
            tampered = manifest.as_dict()
            tampered["interfaces"][0]["frame"]["origin"]["x"] = "1"
            manifest_path.write_text(
                dumps_pretty(tampered), encoding="utf-8", newline="\n"
            )

            with self.assertRaisesRegex(
                IntegrityError, "component_release_request_content_digest"
            ):
                verify_local_component_manifest(manifest_path)

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_local_verifier_reapplies_framed_request_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = load_solid_program(SOLID_EXAMPLE)
            compile_solid_program(program, root)
            bundle_path = root / f"{program.part_id}.solid-bundle.json"
            document = self.framed_request_document()
            document["capabilities"] = ["alpha", "zeta"]
            manifest = derive_component_manifest(
                bundle_path, ComponentReleaseRequest.from_dict(document)
            )
            manifest_path = root / "component.fixture.demo.json"
            tampered = manifest.as_dict()
            tampered["capabilities"] = ["zeta", "alpha"]
            manifest_path.write_text(
                dumps_pretty(tampered), encoding="utf-8", newline="\n"
            )

            with self.assertRaisesRegex(IntegrityError, "release request schema"):
                verify_local_component_manifest(manifest_path)

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_framed_derivation_cannot_be_relabelled_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = load_solid_program(SOLID_EXAMPLE)
            compile_solid_program(program, root)
            bundle_path = root / f"{program.part_id}.solid-bundle.json"
            request_document = self.framed_request_document()
            request_document["interfaces"] = []
            manifest = derive_component_manifest(
                bundle_path, ComponentReleaseRequest.from_dict(request_document)
            )
            manifest_path = root / "component.fixture.demo.json"
            relabelled = manifest.as_dict()
            relabelled["schema_version"] = "contrainte.component-manifest/0.2"
            manifest_path.write_text(
                dumps_pretty(relabelled), encoding="utf-8", newline="\n"
            )

            with self.assertRaisesRegex(IntegrityError, "derivation"):
                verify_local_component_manifest(manifest_path)

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_topology_request_derives_and_verifies_component_v4(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, manifest_path, bundle_path = self.topology_fixture(root)
            reproduced = derive_component_manifest(
                bundle_path,
                ComponentReleaseRequest.from_dict(self.topology_request_document()),
            )

            report = verify_local_component_manifest(manifest_path)

            self.assertEqual(report["status"], "verified")
            self.assertEqual(manifest, reproduced)
            self.assertEqual(
                manifest.schema_version, "contrainte.component-manifest/0.4"
            )
            self.assertEqual(
                manifest.metadata["derivation"], "verified_exact_bundle/0.3"
            )
            attachments = {
                interface.interface_id: interface.attachment.as_dict()  # type: ignore[union-attr]
                for interface in manifest.interfaces
            }
            self.assertEqual(
                attachments["mount-nw-wall"]["evidence"]["surface_type"],
                "cylinder",
            )
            self.assertEqual(attachments["mount-nw-wall"]["evidence"]["radius_mm"], "5")
            self.assertEqual(
                attachments["top-mounting-plane"]["evidence"]["surface_type"],
                "plane",
            )

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_topology_derivation_rejects_unproved_attachment_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            part = load_part(CAD_EXAMPLE)
            compile_part(part, root)
            bundle_path = root / f"{part.part_id}.cad-bundle.json"

            off_surface = self.topology_request_document()
            off_surface["interfaces"][1]["frame"]["origin"]["z"] = "9"

            wrong_orientation = self.topology_request_document()
            wrong_orientation["interfaces"][0]["frame"]["basis"] = {
                "x_axis": {"x": "-1", "y": "0", "z": "0"},
                "y_axis": {"x": "0", "y": "1", "z": "0"},
                "z_axis": {"x": "0", "y": "0", "z": "-1"},
            }

            unknown_feature = self.topology_request_document()
            unknown_feature["interfaces"][0]["attachment"]["selector"]["feature_id"] = (
                "missing-hole"
            )

            for document, message in (
                (off_surface, "not on the selected stock-face plane"),
                (wrong_orientation, "through-hole axis"),
                (unknown_feature, "unknown prismatic through-hole"),
            ):
                with self.subTest(message=message):
                    request = ComponentReleaseRequest.from_dict(document)
                    with self.assertRaisesRegex(InputError, message):
                        derive_component_manifest(bundle_path, request)

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_every_prismatic_stock_face_role_resolves_uniquely(self) -> None:
        cases = {
            "negative_x": (
                {"x": "-60", "y": "0", "z": "5"},
                (
                    {"x": "0", "y": "1", "z": "0"},
                    {"x": "0", "y": "0", "z": "-1"},
                    {"x": "-1", "y": "0", "z": "0"},
                ),
            ),
            "positive_x": (
                {"x": "60", "y": "0", "z": "5"},
                (
                    {"x": "0", "y": "1", "z": "0"},
                    {"x": "0", "y": "0", "z": "1"},
                    {"x": "1", "y": "0", "z": "0"},
                ),
            ),
            "negative_y": (
                {"x": "0", "y": "-40", "z": "5"},
                (
                    {"x": "1", "y": "0", "z": "0"},
                    {"x": "0", "y": "0", "z": "1"},
                    {"x": "0", "y": "-1", "z": "0"},
                ),
            ),
            "positive_y": (
                {"x": "0", "y": "40", "z": "5"},
                (
                    {"x": "1", "y": "0", "z": "0"},
                    {"x": "0", "y": "0", "z": "-1"},
                    {"x": "0", "y": "1", "z": "0"},
                ),
            ),
            "negative_z": (
                {"x": "0", "y": "0", "z": "0"},
                (
                    {"x": "1", "y": "0", "z": "0"},
                    {"x": "0", "y": "-1", "z": "0"},
                    {"x": "0", "y": "0", "z": "-1"},
                ),
            ),
            "positive_z": (
                {"x": "0", "y": "0", "z": "10"},
                (
                    {"x": "1", "y": "0", "z": "0"},
                    {"x": "0", "y": "1", "z": "0"},
                    {"x": "0", "y": "0", "z": "1"},
                ),
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            part = load_part(CAD_EXAMPLE)
            compile_part(part, root)
            bundle_path = root / f"{part.part_id}.cad-bundle.json"
            document = self.topology_request_document()
            template = document["interfaces"][1]
            document["interfaces"] = []
            for role, (origin, axes) in cases.items():
                interface = copy.deepcopy(template)
                interface["interface_id"] = f"stock-{role}"
                interface["frame"]["origin"] = origin
                interface["frame"]["basis"] = {
                    "x_axis": axes[0],
                    "y_axis": axes[1],
                    "z_axis": axes[2],
                }
                interface["attachment"]["selector"]["role"] = role
                document["interfaces"].append(interface)

            manifest = derive_component_manifest(
                bundle_path, ComponentReleaseRequest.from_dict(document)
            )

            self.assertEqual(len(manifest.interfaces), 6)
            self.assertTrue(
                all(
                    interface.attachment.evidence.surface_type.value == "plane"  # type: ignore[union-attr]
                    for interface in manifest.interfaces
                )
            )

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_attachment_points_must_avoid_topology_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            part = load_part(CAD_EXAMPLE)
            compile_part(part, root)
            bundle_path = root / f"{part.part_id}.cad-bundle.json"

            stock_edge = self.topology_request_document()
            stock_edge["interfaces"][1]["frame"]["origin"] = {
                "x": "60",
                "y": "0",
                "z": "10",
            }
            stock_hole = self.topology_request_document()
            stock_hole["interfaces"][1]["frame"]["origin"] = {
                "x": "-40",
                "y": "20",
                "z": "10",
            }
            cylinder_endpoint = self.topology_request_document()
            cylinder_endpoint["interfaces"][0]["frame"]["origin"]["z"] = "0"

            for document, message in (
                (stock_edge, "strictly inside the selected stock face"),
                (stock_hole, "strictly inside the selected stock face"),
                (cylinder_endpoint, "strictly on the selected cylindrical hole wall"),
            ):
                with (
                    self.subTest(message=message),
                    self.assertRaisesRegex(InputError, message),
                ):
                    derive_component_manifest(
                        bundle_path,
                        ComponentReleaseRequest.from_dict(document),
                    )

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_topology_release_rejects_non_prismatic_and_ambiguous_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = load_solid_program(SOLID_EXAMPLE)
            compile_solid_program(program, root)
            solid_bundle = root / f"{program.part_id}.solid-bundle.json"
            request = ComponentReleaseRequest.from_dict(
                self.topology_request_document()
            )
            with self.assertRaisesRegex(InputError, "verified prismatic CAD bundle"):
                derive_component_manifest(solid_bundle, request)

            part = load_part(CAD_EXAMPLE)
            compile_part(part, root)
            cad_bundle = root / f"{part.part_id}.cad-bundle.json"
            with (
                patch(
                    "contrainte.release._compiler_stock_face_matches",
                    return_value=[object(), object()],
                ),
                self.assertRaisesRegex(InputError, "resolved to 2 kernel faces"),
            ):
                derive_component_manifest(cad_bundle, request)

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_topology_verifier_rejects_plausible_evidence_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest_path, _ = self.topology_fixture(root)
            tampered = loads_strict(manifest_path.read_bytes())
            tampered["interfaces"][0]["attachment"]["evidence"][
                "source_feature_digest"
            ] = "sha256:" + "f" * 64
            manifest_path.write_text(
                dumps_pretty(tampered), encoding="utf-8", newline="\n"
            )

            with self.assertRaisesRegex(
                IntegrityError, "attachment evidence does not reproduce"
            ):
                verify_local_component_manifest(manifest_path)

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_derivation_binds_one_stable_source_bundle_snapshot(self) -> None:
        import contrainte.release as release_module

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            part = load_part(CAD_EXAMPLE)
            compile_part(part, root)
            bundle_path = root / f"{part.part_id}.cad-bundle.json"
            original_bytes = bundle_path.read_bytes()
            original_digest = file_digest(bundle_path)
            real_verify = release_module.verify_cad_bundle

            def replace_original_after_verify(snapshot_path):
                report = real_verify(snapshot_path)
                bundle_path.write_bytes(original_bytes + b"\n ")
                return report

            with patch(
                "contrainte.release.verify_cad_bundle",
                side_effect=replace_original_after_verify,
            ):
                manifest = derive_component_manifest(
                    bundle_path,
                    ComponentReleaseRequest.from_dict(self.topology_request_document()),
                )

            self.assertNotEqual(file_digest(bundle_path), original_digest)
            self.assertEqual(manifest.source_bundle_digest, original_digest)

    def test_legacy_request_keeps_preexisting_user_metadata_namespace(self) -> None:
        document = self.request_document()
        document["metadata"]["component_release_request_content_digest"] = "user-label"

        request = ComponentReleaseRequest.from_dict(document)

        self.assertEqual(request.as_dict(), document)

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_verified_sketch_bundle_derives_geometry_backed_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sketch = load_sketch_extrusion(SKETCH_EXAMPLE)
            compile_sketch_extrusion(sketch, root)
            bundle_path = root / f"{sketch.part_id}.sketch-bundle.json"
            manifest = derive_component_manifest(
                bundle_path,
                ComponentReleaseRequest.from_dict(self.request_document()),
            )
            manifest_path = root / "component.fixture.demo.json"
            write_component_manifest(manifest_path, manifest, bundle_path=bundle_path)

            report = verify_local_component_manifest(manifest_path)

            self.assertEqual(report["status"], "verified")
            self.assertEqual(
                manifest.geometry_bounds.as_dict(),  # type: ignore[union-attr]
                {
                    "frame": "engineering_bundle",
                    "unit": "mm",
                    "minimum": {"x": "0", "y": "0", "z": "0"},
                    "maximum": {"x": "100", "y": "60", "z": "10"},
                },
            )
            self.assertEqual(
                {item.role for item in manifest.artifacts},
                {
                    ArtifactRole.ENGINEERING_BUNDLE,
                    ArtifactRole.EXACT_GEOMETRY,
                    ArtifactRole.MESH,
                    ArtifactRole.DRAWING,
                },
            )

    @unittest.skipUnless(
        find_spec("build123d"), "optional CAD backend is not installed"
    )
    def test_circular_sketch_bundle_derives_geometry_backed_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sketch = load_sketch_extrusion(CIRCULAR_SKETCH_EXAMPLE)
            compile_sketch_extrusion(sketch, root)
            bundle_path = root / f"{sketch.part_id}.sketch-bundle.json"
            manifest = derive_component_manifest(
                bundle_path,
                ComponentReleaseRequest.from_dict(self.request_document()),
            )
            manifest_path = root / "component.fixture.demo.json"
            write_component_manifest(manifest_path, manifest, bundle_path=bundle_path)

            report = verify_local_component_manifest(manifest_path)

            self.assertEqual(report["status"], "verified")
            self.assertEqual(
                manifest.metadata["engineering_bundle_schema"],
                "contrainte.sketch-bundle/0.2",
            )
            self.assertEqual(
                manifest.geometry_bounds.as_dict(),  # type: ignore[union-attr]
                {
                    "frame": "engineering_bundle",
                    "unit": "mm",
                    "minimum": {"x": "0", "y": "0", "z": "0"},
                    "maximum": {"x": "100", "y": "60", "z": "10"},
                },
            )


if __name__ == "__main__":
    unittest.main()
