from __future__ import annotations

import copy
import unittest

from contrainte.component import (
    ComponentInterface,
    ComponentManifest,
    InterfaceDirection,
    InterfaceKind,
)
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


def exact_interface_frame() -> dict:
    return {
        "reference": "engineering_bundle",
        "unit": "mm",
        "origin": {"x": "50", "y": "30", "z": "25"},
        "basis": {
            "x_axis": {"x": "3/5", "y": "4/5", "z": "0"},
            "y_axis": {"x": "-4/5", "y": "3/5", "z": "0"},
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        },
    }


def framed_manifest() -> dict:
    raw = valid_manifest()
    raw["schema_version"] = "contrainte.component-manifest/0.3"
    raw["geometry_bounds"] = exact_geometry_bounds()
    raw["interfaces"][0]["frame"] = exact_interface_frame()
    return raw


class ComponentManifestTests(unittest.TestCase):
    def test_round_trip_is_stable(self) -> None:
        parsed = ComponentManifest.from_dict(valid_manifest())
        reparsed = ComponentManifest.from_dict(parsed.as_dict())

        self.assertEqual(parsed, reparsed)
        self.assertEqual(parsed.as_dict(), valid_manifest())
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

    def test_legacy_interface_constructor_remains_compatible(self) -> None:
        interface = ComponentInterface(
            "mount",
            InterfaceKind.MECHANICAL,
            InterfaceDirection.BIDIRECTIONAL,
            "bolted_joint",
            {"datum": "base"},
        )

        self.assertIsNone(interface.frame)
        self.assertNotIn("frame", interface.as_dict())

    def test_schema_v3_round_trips_exact_interface_frame(self) -> None:
        manifest = ComponentManifest.from_dict(framed_manifest())

        self.assertEqual(
            manifest.interfaces[0].frame.as_dict(),  # type: ignore[union-attr]
            exact_interface_frame(),
        )
        self.assertEqual(manifest, ComponentManifest.from_dict(manifest.as_dict()))

    def test_legacy_schemas_reject_interface_frames(self) -> None:
        for schema in (
            "contrainte.component-manifest/0.1",
            "contrainte.component-manifest/0.2",
        ):
            with self.subTest(schema=schema):
                raw = valid_manifest()
                raw["schema_version"] = schema
                if schema.endswith("/0.2"):
                    raw["geometry_bounds"] = exact_geometry_bounds()
                raw["interfaces"][0]["frame"] = exact_interface_frame()

                with self.assertRaisesRegex(InputError, "unsupported fields"):
                    ComponentManifest.from_dict(raw)

    def test_schema_v3_requires_every_interface_frame(self) -> None:
        raw = framed_manifest()
        del raw["interfaces"][0]["frame"]

        with self.assertRaisesRegex(InputError, "frame is required"):
            ComponentManifest.from_dict(raw)

    def test_schema_v3_requires_canonical_bound_decimals(self) -> None:
        raw = framed_manifest()
        raw["geometry_bounds"]["minimum"]["x"] = "-50.0"

        with self.assertRaisesRegex(InputError, "canonical decimal string"):
            ComponentManifest.from_dict(raw)

    def test_frame_origin_must_be_within_inclusive_bounds(self) -> None:
        on_boundary = framed_manifest()
        on_boundary["interfaces"][0]["frame"]["origin"] = {
            "x": "-50",
            "y": "-30",
            "z": "0",
        }
        ComponentManifest.from_dict(on_boundary)

        outside = framed_manifest()
        outside["interfaces"][0]["frame"]["origin"]["x"] = "50.000000001"
        with self.assertRaisesRegex(InputError, "within or on geometry_bounds"):
            ComponentManifest.from_dict(outside)

    def test_frame_origin_rejects_non_string_and_non_finite_values(self) -> None:
        for value in (1.25, "NaN", "Infinity"):
            with self.subTest(value=value):
                raw = framed_manifest()
                raw["interfaces"][0]["frame"]["origin"]["x"] = value

                with self.assertRaisesRegex(InputError, "decimal string|finite"):
                    ComponentManifest.from_dict(raw)

    def test_frame_origin_requires_canonical_decimal_strings(self) -> None:
        for value in ("1.0", "1e0", "-0", "1" * 129):
            with self.subTest(value=value):
                raw = framed_manifest()
                raw["interfaces"][0]["frame"]["origin"]["x"] = value

                with self.assertRaisesRegex(InputError, "canonical decimal string"):
                    ComponentManifest.from_dict(raw)

    def test_basis_requires_canonical_reduced_rationals(self) -> None:
        for value in ("6/10", "0.6", "1/01", "-0", "1" * 129):
            with self.subTest(value=value):
                raw = framed_manifest()
                raw["interfaces"][0]["frame"]["basis"]["x_axis"]["x"] = value

                with self.assertRaisesRegex(InputError, "canonical|reduced"):
                    ComponentManifest.from_dict(raw)

    def test_direct_frame_constructor_enforces_serialized_scalar_limit(self) -> None:
        from decimal import Decimal
        from fractions import Fraction

        from contrainte.component import ExactInterfaceFrame

        huge = Fraction(10**128 + 1, 10**128)
        with self.assertRaisesRegex(InputError, "scalar size limit"):
            ExactInterfaceFrame(
                reference="engineering_bundle",
                unit="mm",
                origin={"x": Decimal(0), "y": Decimal(0), "z": Decimal(0)},
                x_axis=(huge, Fraction(0), Fraction(0)),
                y_axis=(Fraction(0), Fraction(1), Fraction(0)),
                z_axis=(Fraction(0), Fraction(0), Fraction(1)),
            )

    def test_basis_rejects_non_unit_non_orthogonal_and_left_handed_axes(self) -> None:
        non_unit = framed_manifest()
        non_unit["interfaces"][0]["frame"]["basis"]["x_axis"] = {
            "x": "1",
            "y": "1",
            "z": "0",
        }
        with self.assertRaisesRegex(InputError, "exact unit vector"):
            ComponentManifest.from_dict(non_unit)

        non_orthogonal = framed_manifest()
        non_orthogonal["interfaces"][0]["frame"]["basis"]["y_axis"] = {
            "x": "3/5",
            "y": "4/5",
            "z": "0",
        }
        with self.assertRaisesRegex(InputError, "exactly orthogonal"):
            ComponentManifest.from_dict(non_orthogonal)

        left_handed = framed_manifest()
        left_handed["interfaces"][0]["frame"]["basis"]["z_axis"]["z"] = "-1"
        with self.assertRaisesRegex(InputError, "exactly right-handed"):
            ComponentManifest.from_dict(left_handed)

    def test_frame_cannot_claim_unproved_surface_attachment(self) -> None:
        raw = framed_manifest()
        raw["interfaces"][0]["frame"]["surface_attachment"] = "proved"

        with self.assertRaisesRegex(InputError, "unsupported fields"):
            ComponentManifest.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
