from __future__ import annotations

import copy
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

from contrainte.assembly import (
    Assembly,
    analyze_assembly,
    compile_assembly,
    verify_assembly_bundle,
)
from contrainte.canonical import loads_strict
from contrainte.errors import ExecutionError, InputError

PART_EXAMPLE = Path(__file__).parents[1] / "examples" / "mounting-plate.json"


def length(value: str) -> dict[str, str]:
    return {"kind": "length", "unit": "mm", "value": value}


class AssemblyTests(unittest.TestCase):
    def document(self) -> dict:
        part = loads_strict(PART_EXAMPLE.read_bytes())
        return {
            "schema_version": "contrainte.assembly/0.1",
            "assembly_id": "assembly.demo",
            "revision": "A",
            "title": "Separated mounting plates",
            "parts": [part],
            "occurrences": [
                {
                    "occurrence_id": "plate.left",
                    "title": "Left plate",
                    "part_id": part["part_id"],
                    "transform": {
                        "translation": {
                            "x": length("-70"),
                            "y": length("0"),
                            "z": length("0"),
                        },
                        "rotation_xyz_deg": ["0", "0", "0"],
                    },
                },
                {
                    "occurrence_id": "plate.right",
                    "title": "Right plate",
                    "part_id": part["part_id"],
                    "transform": {
                        "translation": {
                            "x": length("70"),
                            "y": length("0"),
                            "z": length("0"),
                        },
                        "rotation_xyz_deg": ["0", "0", "90"],
                    },
                },
            ],
            "default_minimum_clearance": length("5"),
            "pair_rules": [],
        }

    def test_round_trip_preserves_digest(self) -> None:
        assembly = Assembly.from_dict(self.document())
        reparsed = Assembly.from_dict(assembly.as_dict())

        self.assertEqual(assembly, reparsed)
        self.assertEqual(assembly.assembly_digest, reparsed.assembly_digest)

    def test_unknown_part_reference_is_rejected(self) -> None:
        document = self.document()
        document["occurrences"][0]["part_id"] = "part.missing"

        with self.assertRaisesRegex(InputError, "unknown parts"):
            Assembly.from_dict(document)

    def test_pair_rule_order_is_canonical(self) -> None:
        document = self.document()
        document["pair_rules"] = [
            {
                "first_occurrence_id": "plate.right",
                "second_occurrence_id": "plate.left",
                "minimum_clearance": length("10"),
            }
        ]

        with self.assertRaisesRegex(InputError, "ascending lexical order"):
            Assembly.from_dict(document)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_exact_pair_analysis_reports_clearance(self) -> None:
        analysis, _ = analyze_assembly(Assembly.from_dict(self.document()))

        self.assertEqual(analysis["status"], "passed")
        self.assertEqual(analysis["occurrence_count"], 2)
        self.assertEqual(analysis["pair_count"], 1)
        self.assertEqual(analysis["pair_results"][0]["distance_mm"], "40")
        self.assertEqual(analysis["pair_results"][0]["status"], "passed")

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_interference_prevents_export(self) -> None:
        document = self.document()
        document["occurrences"][1]["transform"]["translation"]["x"] = length("0")
        assembly = Assembly.from_dict(document)

        analysis, _ = analyze_assembly(assembly)
        self.assertEqual(analysis["pair_results"][0]["status"], "interference")
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ExecutionError, "interfere"),
        ):
            compile_assembly(assembly, directory)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_pair_specific_clearance_prevents_export(self) -> None:
        document = self.document()
        document["pair_rules"] = [
            {
                "first_occurrence_id": "plate.left",
                "second_occurrence_id": "plate.right",
                "minimum_clearance": length("50"),
            }
        ]
        assembly = Assembly.from_dict(document)

        analysis, _ = analyze_assembly(assembly)
        self.assertEqual(analysis["pair_results"][0]["status"], "clearance_violation")
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ExecutionError, "below 50 mm"),
        ):
            compile_assembly(assembly, directory)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_compilation_is_reproducible_and_verifiable(self) -> None:
        assembly = Assembly.from_dict(self.document())
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
        ):
            first = compile_assembly(assembly, first_directory)
            second = compile_assembly(assembly, second_directory)
            bundle_path = (
                Path(first_directory) / f"{assembly.assembly_id}.assembly-bundle.json"
            )

            self.assertEqual(first, second)
            self.assertEqual(
                verify_assembly_bundle(bundle_path)["bundle_digest"],
                first["digest"],
            )
            self.assertTrue(
                (Path(first_directory) / f"{assembly.assembly_id}.step").is_file()
            )

    def test_unknown_assembly_field_is_rejected(self) -> None:
        document = copy.deepcopy(self.document())
        document["notes"] = "unchecked"

        with self.assertRaisesRegex(InputError, "unsupported fields"):
            Assembly.from_dict(document)


if __name__ == "__main__":
    unittest.main()
