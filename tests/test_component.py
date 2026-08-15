from __future__ import annotations

import copy
import unittest

from contrainte.component import ComponentManifest
from contrainte.errors import InputError

_BUNDLE_DIGEST = "sha256:" + "1" * 64


def valid_manifest() -> dict:
    return {
        "schema_version": "contrainte.component-manifest/0.1",
        "component_id": "component.filler.demo",
        "revision": "A",
        "title": "Demonstration filler",
        "lifecycle_state": "concept",
        "qualification": "unqualified_demonstration",
        "source_bundle_digest": _BUNDLE_DIGEST,
        "artifacts": [
            {
                "artifact_id": "engineering-bundle",
                "role": "engineering_bundle",
                "media_type": "application/json",
                "digest": _BUNDLE_DIGEST,
                "locator": "fixtures/filler.bundle.json",
            }
        ],
        "interfaces": [
            {
                "interface_id": "product-in",
                "kind": "material",
                "direction": "input",
                "medium": "vial",
                "properties": {"nominal_format": "10R"},
            }
        ],
        "capabilities": ["dose_liquid"],
        "metadata": {"data_class": "synthetic"},
    }


def exact_geometry_bounds() -> dict:
    return {
        "frame": "engineering_bundle",
        "unit": "mm",
        "minimum": {"x": "-50", "y": "-30", "z": "0"},
        "maximum": {"x": "50", "y": "30", "z": "50"},
    }


class ComponentManifestTests(unittest.TestCase):
    def test_round_trip_is_stable(self) -> None:
        parsed = ComponentManifest.from_dict(valid_manifest())
        reparsed = ComponentManifest.from_dict(parsed.as_dict())

        self.assertEqual(parsed, reparsed)
        self.assertEqual(parsed.manifest_digest, reparsed.manifest_digest)

    def test_source_bundle_must_resolve_to_artifact(self) -> None:
        raw = valid_manifest()
        raw["source_bundle_digest"] = "sha256:" + "2" * 64

        with self.assertRaisesRegex(InputError, "exactly one engineering_bundle"):
            ComponentManifest.from_dict(raw)

    def test_interface_identifiers_are_unique(self) -> None:
        raw = valid_manifest()
        raw["interfaces"].append(copy.deepcopy(raw["interfaces"][0]))

        with self.assertRaisesRegex(InputError, "interface identifiers must be unique"):
            ComponentManifest.from_dict(raw)

    def test_digest_changes_with_meaningful_content(self) -> None:
        first = ComponentManifest.from_dict(valid_manifest())
        changed = valid_manifest()
        changed["revision"] = "B"
        second = ComponentManifest.from_dict(changed)

        self.assertNotEqual(first.manifest_digest, second.manifest_digest)

    def test_unknown_fields_are_not_silently_discarded(self) -> None:
        raw = valid_manifest()
        raw["future_meaning"] = "must not disappear"

        with self.assertRaisesRegex(InputError, "unsupported fields"):
            ComponentManifest.from_dict(raw)

    def test_schema_v2_carries_exact_geometry_bounds(self) -> None:
        raw = valid_manifest()
        raw["schema_version"] = "contrainte.component-manifest/0.2"
        raw["geometry_bounds"] = exact_geometry_bounds()

        manifest = ComponentManifest.from_dict(raw)

        self.assertEqual(
            manifest.geometry_bounds.size_mm,  # type: ignore[union-attr]
            {"x": 100, "y": 60, "z": 50},
        )
        self.assertEqual(manifest, ComponentManifest.from_dict(manifest.as_dict()))

    def test_schema_v2_requires_geometry_bounds(self) -> None:
        raw = valid_manifest()
        raw["schema_version"] = "contrainte.component-manifest/0.2"

        with self.assertRaisesRegex(InputError, "geometry_bounds is required"):
            ComponentManifest.from_dict(raw)

    def test_schema_v1_cannot_claim_v2_geometry_semantics(self) -> None:
        raw = valid_manifest()
        raw["geometry_bounds"] = exact_geometry_bounds()

        with self.assertRaisesRegex(InputError, "requires component schema"):
            ComponentManifest.from_dict(raw)

    def test_geometry_bounds_must_have_positive_extent(self) -> None:
        raw = valid_manifest()
        raw["schema_version"] = "contrainte.component-manifest/0.2"
        raw["geometry_bounds"] = exact_geometry_bounds()
        raw["geometry_bounds"]["maximum"]["x"] = "-50"

        with self.assertRaisesRegex(InputError, "greater than minimum"):
            ComponentManifest.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
