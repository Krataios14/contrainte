from __future__ import annotations

import copy
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

from contrainte.canonical import dumps_pretty, loads_strict
from contrainte.component import ArtifactRole, Qualification
from contrainte.errors import InputError, IntegrityError
from contrainte.release import (
    ComponentReleaseRequest,
    derive_component_manifest,
    verify_local_component_manifest,
    write_component_manifest,
)
from contrainte.solid import compile_solid_program, load_solid_program

SOLID_EXAMPLE = Path(__file__).parents[1] / "examples" / "pedestal-bracket.json"


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

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_verified_solid_bundle_derives_local_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = load_solid_program(SOLID_EXAMPLE)
            bundle = compile_solid_program(program, root)
            bundle_path = root / f"{program.part_id}.solid-bundle.json"
            request = ComponentReleaseRequest.from_dict(self.request_document())
            manifest = derive_component_manifest(bundle_path, request)
            manifest_path = root / "component.fixture.demo.json"
            write_component_manifest(
                manifest_path, manifest, bundle_path=bundle_path
            )

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

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
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

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
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
        request = ComponentReleaseRequest.from_dict(self.request_document())
        self.assertEqual(
            ComponentReleaseRequest.from_dict(
                loads_strict(dumps_pretty(request.as_dict()))
            ),
            request,
        )


if __name__ == "__main__":
    unittest.main()
