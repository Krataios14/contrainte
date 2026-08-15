from __future__ import annotations

import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

from contrainte.artifacts import file_digest
from contrainte.canonical import digest, dumps_pretty, loads_strict
from contrainte.errors import InputError, IntegrityError
from contrainte.sketch import (
    SketchExtrusion,
    analyze_sketch_extrusion,
    compile_sketch_extrusion,
    solve_constraints,
    verify_sketch_bundle,
)

PART_EXAMPLE = Path(__file__).parents[1] / "examples" / "mounting-plate.json"


def length(value: str) -> dict[str, str]:
    return {"kind": "length", "unit": "mm", "value": value}


def fixed(identifier: str, point: str, x: str, y: str) -> dict:
    return {
        "constraint_id": identifier,
        "kind": "fixed",
        "point_id": point,
        "x": length(x),
        "y": length(y),
    }


def pair(
    identifier: str,
    kind: str,
    first: str,
    second: str,
    distance: str | None = None,
) -> dict:
    document = {
        "constraint_id": identifier,
        "kind": kind,
        "first_point_id": first,
        "second_point_id": second,
    }
    if distance is not None:
        document["distance"] = length(distance)
    return document


def constrained_rectangle(
    prefix: str, start: int, origin_x: str, origin_y: str, width: str, height: str
) -> list[dict]:
    p0, p1, p2, p3 = (f"{prefix}{index}" for index in range(4))
    return [
        fixed(f"c{start:02d}", p0, origin_x, origin_y),
        pair(f"c{start + 1:02d}", "horizontal", p0, p1),
        pair(f"c{start + 2:02d}", "offset_x", p0, p1, width),
        pair(f"c{start + 3:02d}", "vertical", p1, p2),
        pair(f"c{start + 4:02d}", "offset_y", p1, p2, height),
        pair(f"c{start + 5:02d}", "horizontal", p2, p3),
        pair(f"c{start + 6:02d}", "vertical", p3, p0),
    ]


def sketch_document() -> dict:
    part = loads_strict(PART_EXAMPLE.read_bytes())
    constraints = constrained_rectangle("h", 1, "20", "20", "60", "20")
    constraints.extend(constrained_rectangle("p", 8, "0", "0", "100", "60"))
    return {
        "schema_version": "contrainte.sketch-extrusion/0.1",
        "part_id": "plate.sketch.demo",
        "revision": "A",
        "title": "Fully constrained demonstration plate",
        "material": part["material"],
        "manufacturing": {
            "process": "3-axis milling",
            "minimum_feature_size": length("2"),
        },
        "limits": {
            "maximum_mass": {"kind": "mass", "unit": "kg", "value": "1"},
            "maximum_bounding_box": {
                "x": length("110"),
                "y": length("70"),
                "z": length("20"),
            },
        },
        "points": [{"point_id": f"{prefix}{index}"} for prefix in ("h", "p") for index in range(4)],
        "constraints": constraints,
        "profile": {
            "outer_loop": ["p0", "p1", "p2", "p3"],
            "inner_loops": [["h0", "h3", "h2", "h1"]],
        },
        "extrusion_distance": length("10"),
    }


class SketchExtrusionTests(unittest.TestCase):
    def test_exact_solver_fully_constrains_profile(self) -> None:
        sketch = SketchExtrusion.from_dict(sketch_document())

        analysis, _ = analyze_sketch_extrusion(sketch)

        self.assertEqual(analysis["status"], "passed")
        self.assertEqual(analysis["constraint_solution"]["rank"], 16)
        self.assertEqual(analysis["constraint_solution"]["equation_count"], 16)
        self.assertEqual(analysis["profile"]["net_area_mm2"], "4800")
        self.assertEqual(analysis["exact_volume_mm3"], "48000")

    def test_underconstrained_sketch_is_rejected(self) -> None:
        document = sketch_document()
        document["constraints"].pop()

        with self.assertRaisesRegex(InputError, "underconstrained"):
            SketchExtrusion.from_dict(document)

    def test_inconsistent_sketch_is_rejected(self) -> None:
        document = sketch_document()
        document["constraints"].append(fixed("c99", "p1", "101", "0"))

        with self.assertRaisesRegex(InputError, "inconsistent"):
            SketchExtrusion.from_dict(document)

    def test_redundant_sketch_equations_are_rejected(self) -> None:
        document = sketch_document()
        document["constraints"].append(fixed("c99", "p1", "100", "0"))

        with self.assertRaisesRegex(InputError, "redundant or overconstraining"):
            SketchExtrusion.from_dict(document)

    def test_profile_winding_is_semantic(self) -> None:
        document = sketch_document()
        document["profile"]["inner_loops"][0] = ["h0", "h1", "h2", "h3"]

        with self.assertRaisesRegex(InputError, "clockwise winding"):
            SketchExtrusion.from_dict(document)

    def test_long_decimal_coordinates_remain_exact(self) -> None:
        document = sketch_document()
        outer_origin = "123456789012345678901234567890.123456789"
        hole_origin = "123456789012345678901234567910.123456789"
        document["constraints"][0]["x"] = length(hole_origin)
        document["constraints"][7]["x"] = length(outer_origin)

        sketch = SketchExtrusion.from_dict(document)
        _, report = solve_constraints(sketch)

        solved = {
            item["point_id"]: item for item in report["solved_points_mm"]
        }
        self.assertEqual(solved["p0"]["x"], outer_origin)
        self.assertEqual(solved["h0"]["x"], hole_origin)

    def test_hole_wall_below_minimum_feature_is_rejected(self) -> None:
        document = sketch_document()
        document["constraints"][0]["x"] = length("1")

        with self.assertRaisesRegex(InputError, "closer to outer_loop"):
            SketchExtrusion.from_dict(document)

    def test_thin_triangle_altitude_is_rejected_as_minimum_feature(self) -> None:
        document = sketch_document()
        document["points"] = [
            {"point_id": "p0"},
            {"point_id": "p1"},
            {"point_id": "p2"},
        ]
        document["constraints"] = [
            fixed("c01", "p0", "0", "0"),
            fixed("c02", "p1", "100", "0"),
            fixed("c03", "p2", "50", "1"),
        ]
        document["profile"] = {
            "outer_loop": ["p0", "p1", "p2"],
            "inner_loops": [],
        }

        with self.assertRaisesRegex(InputError, "vertex and nonincident edge"):
            SketchExtrusion.from_dict(document)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_bundle_compiles_reproduces_and_verifies_artifacts(self) -> None:
        sketch = SketchExtrusion.from_dict(sketch_document())
        with tempfile.TemporaryDirectory() as directory:
            first = compile_sketch_extrusion(sketch, directory)
            second = compile_sketch_extrusion(sketch, directory)
            bundle_path = Path(directory) / "plate.sketch.demo.sketch-bundle.json"

            report = verify_sketch_bundle(bundle_path)

            self.assertEqual(first, second)
            self.assertEqual(report["status"], "verified")
            self.assertTrue((Path(directory) / "plate.sketch.demo.step").is_file())
            self.assertTrue((Path(directory) / "plate.sketch.demo.svg").is_file())

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_rehashed_false_constraint_report_is_rejected(self) -> None:
        sketch = SketchExtrusion.from_dict(sketch_document())
        with tempfile.TemporaryDirectory() as directory:
            bundle = compile_sketch_extrusion(sketch, directory)
            bundle["content"]["analysis"]["constraint_solution"]["rank"] = 15
            bundle["digest"] = digest(bundle["content"])
            bundle_path = Path(directory) / "plate.sketch.demo.sketch-bundle.json"
            bundle_path.write_text(dumps_pretty(bundle), encoding="utf-8", newline="\n")

            with self.assertRaisesRegex(IntegrityError, "does not reproduce"):
                verify_sketch_bundle(bundle_path)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_rehashed_substitute_artifact_is_rejected(self) -> None:
        sketch = SketchExtrusion.from_dict(sketch_document())
        with tempfile.TemporaryDirectory() as directory:
            bundle = compile_sketch_extrusion(sketch, directory)
            svg_path = Path(directory) / "plate.sketch.demo.svg"
            svg_path.write_text("<svg/>\n", encoding="utf-8", newline="\n")
            descriptor = next(
                item
                for item in bundle["content"]["artifacts"]
                if item["path"] == svg_path.name
            )
            descriptor["digest"] = file_digest(svg_path)
            descriptor["size_bytes"] = svg_path.stat().st_size
            bundle["digest"] = digest(bundle["content"])
            bundle_path = Path(directory) / "plate.sketch.demo.sketch-bundle.json"
            bundle_path.write_text(dumps_pretty(bundle), encoding="utf-8", newline="\n")

            with self.assertRaisesRegex(IntegrityError, "artifacts do not reproduce"):
                verify_sketch_bundle(bundle_path)

    def test_round_trip_preserves_digest(self) -> None:
        sketch = SketchExtrusion.from_dict(sketch_document())

        reparsed = SketchExtrusion.from_dict(sketch.as_dict())

        self.assertEqual(sketch, reparsed)
        self.assertEqual(sketch.sketch_digest, reparsed.sketch_digest)


if __name__ == "__main__":
    unittest.main()
