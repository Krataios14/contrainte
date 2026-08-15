from __future__ import annotations

import copy
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

from contrainte.canonical import digest, dumps_pretty, loads_strict
from contrainte.errors import ExecutionError, InputError, IntegrityError
from contrainte.solid import (
    SolidProgram,
    analyze_solid_program,
    compile_solid_program,
    verify_solid_bundle,
)

PART_EXAMPLE = Path(__file__).parents[1] / "examples" / "mounting-plate.json"


def length(value: str) -> dict[str, str]:
    return {"kind": "length", "unit": "mm", "value": value}


def transform(x: str = "0", y: str = "0", z: str = "0") -> dict:
    return {
        "translation": {"x": length(x), "y": length(y), "z": length(z)},
        "rotation_xyz_deg": ["0", "0", "0"],
    }


class SolidProgramTests(unittest.TestCase):
    def document(self) -> dict:
        part = loads_strict(PART_EXAMPLE.read_bytes())
        return {
            "schema_version": "contrainte.solid-program/0.1",
            "part_id": "bracket.demo",
            "revision": "A",
            "title": "Demonstration pedestal bracket",
            "material": part["material"],
            "manufacturing": {
                "process": "3-axis milling",
                "minimum_feature_size": length("2"),
            },
            "limits": {
                "maximum_mass": {"kind": "mass", "unit": "kg", "value": "10"},
                "maximum_bounding_box": {
                    "x": length("120"),
                    "y": length("80"),
                    "z": length("60"),
                },
            },
            "nodes": [
                {
                    "node_id": "base",
                    "operation": "box",
                    "inputs": [],
                    "parameters": {
                        "x": length("100"),
                        "y": length("60"),
                        "z": length("10"),
                    },
                    "transform": transform(),
                },
                {
                    "node_id": "tower",
                    "operation": "box",
                    "inputs": [],
                    "parameters": {
                        "x": length("20"),
                        "y": length("20"),
                        "z": length("40"),
                    },
                    "transform": transform(z="10"),
                },
                {
                    "node_id": "body",
                    "operation": "union",
                    "inputs": ["base", "tower"],
                    "parameters": {},
                    "transform": transform(),
                },
                {
                    "node_id": "hole",
                    "operation": "cylinder",
                    "inputs": [],
                    "parameters": {
                        "radius": length("5"),
                        "height": length("50"),
                    },
                    "transform": transform(),
                },
                {
                    "node_id": "root",
                    "operation": "cut",
                    "inputs": ["body", "hole"],
                    "parameters": {},
                    "transform": transform(),
                },
            ],
            "output_node_id": "root",
        }

    def test_round_trip_and_topological_order(self) -> None:
        program = SolidProgram.from_dict(self.document())
        reparsed = SolidProgram.from_dict(program.as_dict())

        self.assertEqual(program, reparsed)
        self.assertEqual(program.program_digest, reparsed.program_digest)
        self.assertEqual(program.topological_order()[-1], "root")

    def test_unknown_input_is_rejected(self) -> None:
        document = self.document()
        document["nodes"][-1]["inputs"] = ["body", "missing"]

        with self.assertRaisesRegex(InputError, "unknown inputs"):
            SolidProgram.from_dict(document)

    def test_unused_node_is_rejected(self) -> None:
        document = self.document()
        document["nodes"].append(
            {
                "node_id": "unused",
                "operation": "sphere",
                "inputs": [],
                "parameters": {"radius": length("5")},
                "transform": transform(),
            }
        )

        with self.assertRaisesRegex(InputError, "not used by the output"):
            SolidProgram.from_dict(document)

    def test_commutative_inputs_require_canonical_order(self) -> None:
        document = self.document()
        document["nodes"][2]["inputs"] = ["tower", "base"]

        with self.assertRaisesRegex(InputError, "ascending lexical order"):
            SolidProgram.from_dict(document)

    def test_minimum_feature_size_is_enforced(self) -> None:
        document = self.document()
        document["nodes"][3]["parameters"]["radius"] = length("0.5")

        with self.assertRaisesRegex(InputError, "minimum feature size"):
            SolidProgram.from_dict(document)

    def test_cycle_is_rejected(self) -> None:
        document = self.document()
        document["nodes"][0] = {
            "node_id": "base",
            "operation": "union",
            "inputs": ["root", "tower"],
            "parameters": {},
            "transform": transform(),
        }

        with self.assertRaisesRegex(InputError, "contains a cycle"):
            SolidProgram.from_dict(document)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_exact_boolean_analysis_closes_limits(self) -> None:
        analysis, _ = analyze_solid_program(SolidProgram.from_dict(self.document()))

        self.assertEqual(analysis["status"], "passed")
        self.assertEqual(analysis["node_count"], 5)
        self.assertEqual(analysis["solid_count"], 1)
        self.assertEqual(
            analysis["bounding_box_mm"], {"x": "100", "y": "60", "z": "50"}
        )

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_sphere_intersection_operation_is_executable(self) -> None:
        document = self.document()
        document["nodes"] = [
            {
                "node_id": "box",
                "operation": "box",
                "inputs": [],
                "parameters": {
                    "x": length("10"),
                    "y": length("10"),
                    "z": length("10"),
                },
                "transform": transform(),
            },
            {
                "node_id": "sphere",
                "operation": "sphere",
                "inputs": [],
                "parameters": {"radius": length("10")},
                "transform": transform(),
            },
            {
                "node_id": "root",
                "operation": "intersection",
                "inputs": ["box", "sphere"],
                "parameters": {},
                "transform": transform(),
            },
        ]
        program = SolidProgram.from_dict(document)

        analysis, _ = analyze_solid_program(program)
        self.assertEqual(analysis["status"], "passed")
        self.assertEqual(analysis["node_results"][-1]["operation"], "intersection")

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_disconnected_output_is_rejected(self) -> None:
        document = self.document()
        document["nodes"] = [
            {
                "node_id": "left",
                "operation": "box",
                "inputs": [],
                "parameters": {
                    "x": length("10"),
                    "y": length("10"),
                    "z": length("10"),
                },
                "transform": transform(x="-20"),
            },
            {
                "node_id": "right",
                "operation": "box",
                "inputs": [],
                "parameters": {
                    "x": length("10"),
                    "y": length("10"),
                    "z": length("10"),
                },
                "transform": transform(x="20"),
            },
            {
                "node_id": "root",
                "operation": "union",
                "inputs": ["left", "right"],
                "parameters": {},
                "transform": transform(),
            },
        ]
        program = SolidProgram.from_dict(document)

        analysis, _ = analyze_solid_program(program)
        self.assertEqual(analysis["status"], "failed")
        self.assertIn("exactly one", analysis["failures"][0])

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_mass_limit_prevents_export(self) -> None:
        document = copy.deepcopy(self.document())
        document["limits"]["maximum_mass"]["value"] = "0.1"
        program = SolidProgram.from_dict(document)

        analysis, _ = analyze_solid_program(program)
        self.assertEqual(analysis["status"], "failed")
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ExecutionError, "mass"),
        ):
            compile_solid_program(program, directory)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_compilation_is_reproducible_and_verifiable(self) -> None:
        program = SolidProgram.from_dict(self.document())
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
        ):
            first = compile_solid_program(program, first_directory)
            second = compile_solid_program(program, second_directory)
            bundle_path = Path(first_directory) / f"{program.part_id}.solid-bundle.json"

            self.assertEqual(first, second)
            self.assertEqual(
                verify_solid_bundle(bundle_path)["bundle_digest"], first["digest"]
            )

            false_role = copy.deepcopy(first)
            false_role["content"]["artifacts"][0]["role"] = "visualization_mesh"
            false_role["digest"] = digest(false_role["content"])
            bundle_path.write_text(
                dumps_pretty(false_role), encoding="utf-8", newline="\n"
            )
            with self.assertRaisesRegex(IntegrityError, "role mismatch"):
                verify_solid_bundle(bundle_path)


if __name__ == "__main__":
    unittest.main()
