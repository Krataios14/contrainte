from __future__ import annotations

import copy
import tempfile
import unittest
from decimal import Decimal
from importlib.util import find_spec
from pathlib import Path

from contrainte.cad import PrismaticPart, compile_part, load_part, verify_cad_bundle
from contrainte.canonical import loads_strict
from contrainte.errors import InputError

EXAMPLE = Path(__file__).parents[1] / "examples" / "mounting-plate.json"


class ConstrainedCadTests(unittest.TestCase):
    def document(self) -> dict:
        return loads_strict(EXAMPLE.read_bytes())

    def test_part_round_trip_and_analytical_mass(self) -> None:
        part = load_part(EXAMPLE)
        reparsed = PrismaticPart.from_dict(part.as_dict())

        self.assertEqual(part, reparsed)
        properties = part.analytical_properties()
        self.assertGreater(Decimal(properties["net_volume_m3"]), Decimal(0))
        self.assertGreater(Decimal(properties["mass_kg"]), Decimal(0))
        self.assertEqual(part.part_digest, reparsed.part_digest)

    def test_worst_case_edge_distance_is_enforced(self) -> None:
        document = self.document()
        document["holes"][0]["x"]["value"] = "50"

        with self.assertRaisesRegex(InputError, "edge distance"):
            PrismaticPart.from_dict(document)

    def test_worst_case_hole_web_is_enforced(self) -> None:
        document = self.document()
        document["holes"][1]["x"]["value"] = "-30"
        document["holes"][1]["y"]["value"] = "20"

        with self.assertRaisesRegex(InputError, "web thickness"):
            PrismaticPart.from_dict(document)

    def test_material_property_evidence_is_not_optional(self) -> None:
        document = self.document()
        document["material"]["properties"]["density"]["evidence_ids"] = ["missing"]

        with self.assertRaisesRegex(InputError, "missing evidence"):
            PrismaticPart.from_dict(document)

    def test_unknown_feature_data_is_rejected(self) -> None:
        document = copy.deepcopy(self.document())
        document["holes"][0]["thread"] = "M10"

        with self.assertRaisesRegex(InputError, "unsupported fields"):
            PrismaticPart.from_dict(document)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_opencascade_compilation_and_bundle_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            part = load_part(EXAMPLE)
            bundle = compile_part(part, directory)
            bundle_path = Path(directory) / f"{part.part_id}.cad-bundle.json"

            self.assertTrue((Path(directory) / f"{part.part_id}.step").is_file())
            self.assertEqual(
                verify_cad_bundle(bundle_path)["bundle_digest"], bundle["digest"]
            )


if __name__ == "__main__":
    unittest.main()
