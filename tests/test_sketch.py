from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from fractions import Fraction
from importlib.util import find_spec
from pathlib import Path

from contrainte.artifacts import file_digest
from contrainte.canonical import digest, dumps_pretty, loads_strict
from contrainte.cli import main as cli_main
from contrainte.errors import InputError, IntegrityError
from contrainte.sketch import (
    SketchConstraint,
    SketchExtrusion,
    SketchProfile,
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


def circular_sketch_document() -> dict:
    document = sketch_document()
    document["schema_version"] = "contrainte.sketch-extrusion/0.2"
    document["part_id"] = "plate.circular-sketch.demo"
    document["title"] = "Fully constrained plate with circular through-holes"
    document["points"].extend([{"point_id": "q0"}, {"point_id": "q1"}])
    document["constraints"].extend(
        [fixed("c15", "q0", "10", "10"), fixed("c16", "q1", "90", "50")]
    )
    document["profile"]["circular_holes"] = [
        {
            "circle_id": "round.01",
            "center_point_id": "q0",
            "diameter": length("6"),
        },
        {
            "circle_id": "round.02",
            "center_point_id": "q1",
            "diameter": length("6"),
        },
    ]
    return document


def midpoint(identifier: str, first: str, second: str, center: str) -> dict:
    return {
        "constraint_id": identifier,
        "kind": "midpoint",
        "first_point_id": first,
        "second_point_id": second,
        "midpoint_point_id": center,
    }


def midpoint_sketch_document() -> dict:
    """The 0.2 circular plate with both centres located by midpoint relations.

    q0 = (p0 + h0) / 2 = (10, 10) and q1 = (h2 + p2) / 2 = (90, 50), the same
    centres the 0.2 fixture fixes explicitly.
    """
    document = circular_sketch_document()
    document["schema_version"] = "contrainte.sketch-extrusion/0.3"
    document["part_id"] = "plate.midpoint-sketch.demo"
    document["title"] = "Plate with circular holes located by midpoint relations"
    document["constraints"][14] = midpoint("c15", "p0", "h0", "q0")
    document["constraints"][15] = midpoint("c16", "h2", "p2", "q1")
    return document


def coupled_midpoint_plate_document(width: str) -> dict:
    """A plate whose two hole centres locate each other through midpoints.

    q0 = (p0 + q1) / 2 and q1 = (q0 + p2) / 2 give q0.x = width / 3 and
    q1.x = 2 * width / 3; q0.y = 20 and q1.y = 40 for the 60 mm height.
    """
    document = midpoint_sketch_document()
    document["points"] = [
        point for point in document["points"] if not point["point_id"].startswith("h")
    ]
    document["constraints"] = document["constraints"][7:14] + [
        midpoint("c15", "p0", "q1", "q0"),
        midpoint("c16", "q0", "p2", "q1"),
    ]
    document["constraints"][2]["distance"] = length(width)
    document["profile"]["inner_loops"] = []
    return document


def solved_mm(document: dict) -> dict[str, tuple[Fraction, Fraction]]:
    solved, _ = solve_constraints(SketchExtrusion.from_dict(document))
    return solved


class SketchExtrusionTests(unittest.TestCase):
    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
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
            self.assertEqual(
                first["content"]["schema_version"], "contrainte.sketch-bundle/0.1"
            )
            self.assertEqual(
                [item["id"] for item in first["content"]["checks"]],
                [
                    "SKETCH-SCHEMA",
                    "SKETCH-EXACT-LINEAR-CONSTRAINTS",
                    "SKETCH-FULLY-CONSTRAINED",
                    "SKETCH-SIMPLE-PROFILE-TOPOLOGY",
                    "SKETCH-MINIMUM-FEATURE",
                    "SKETCH-BREP-VALIDITY",
                    "SKETCH-EXACT-VOLUME-CROSSCHECK",
                    "SKETCH-MASS-LIMIT",
                    "SKETCH-ENVELOPE-LIMIT",
                ],
            )
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
        document = sketch_document()
        sketch = SketchExtrusion.from_dict(document)

        reparsed = SketchExtrusion.from_dict(sketch.as_dict())

        self.assertEqual(sketch, reparsed)
        self.assertEqual(sketch.as_dict(), document)
        self.assertEqual(sketch.sketch_digest, reparsed.sketch_digest)

    def test_v1_profile_python_api_remains_backward_compatible(self) -> None:
        raw = sketch_document()["profile"]

        profile = SketchProfile.from_dict(raw, field="profile")

        self.assertEqual(profile.as_dict(), raw)

    def test_v1_rejects_circular_profile_fields(self) -> None:
        document = sketch_document()
        document["profile"]["circular_holes"] = []

        with self.assertRaisesRegex(InputError, "must contain exactly"):
            SketchExtrusion.from_dict(document)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_v2_has_symbolic_circular_area_and_volume_authority(self) -> None:
        sketch = SketchExtrusion.from_dict(circular_sketch_document())

        analysis, _ = analyze_sketch_extrusion(sketch)

        self.assertEqual(
            analysis["profile"]["net_area_symbolic_mm2"],
            {
                "form": "rational_constant + pi * pi_coefficient",
                "rational_constant": "4800",
                "pi_coefficient": "-18",
            },
        )
        self.assertEqual(
            analysis["symbolic_volume_mm3"],
            {
                "form": "rational_constant + pi * pi_coefficient",
                "rational_constant": "48000",
                "pi_coefficient": "-180",
            },
        )
        self.assertEqual(analysis["profile"]["circular_hole_count"], 2)
        self.assertEqual(
            analysis["profile"]["circular_holes"][0]["radius_mm"], "3"
        )
        self.assertEqual(
            analysis["pi_comparison_basis"]["scope"],
            "Open CASCADE comparison only; symbolic coefficients are authority",
        )
        self.assertEqual(analysis["pi_comparison_basis"]["decimal_places"], 100)
        self.assertNotIn("exact_volume_mm3", analysis)

    def test_v2_requires_canonical_diameter(self) -> None:
        document = circular_sketch_document()
        circle = document["profile"]["circular_holes"][0]
        circle["radius"] = circle.pop("diameter")

        with self.assertRaisesRegex(InputError, "exactly circle_id.*diameter"):
            SketchExtrusion.from_dict(document)

    def test_circular_holes_have_canonical_unique_identities(self) -> None:
        document = circular_sketch_document()
        document["profile"]["circular_holes"].reverse()
        with self.assertRaisesRegex(InputError, "ordered by circle_id"):
            SketchExtrusion.from_dict(document)

        document = circular_sketch_document()
        document["profile"]["circular_holes"][1]["circle_id"] = "round.01"
        with self.assertRaisesRegex(InputError, "identifiers must be unique"):
            SketchExtrusion.from_dict(document)

        document = circular_sketch_document()
        document["profile"]["circular_holes"][1]["center_point_id"] = "q0"
        with self.assertRaisesRegex(InputError, "distinct center points"):
            SketchExtrusion.from_dict(document)

    def test_circular_diameter_below_minimum_feature_is_rejected(self) -> None:
        document = circular_sketch_document()
        document["profile"]["circular_holes"][0]["diameter"] = length("1.999")

        with self.assertRaisesRegex(InputError, "diameter is below"):
            SketchExtrusion.from_dict(document)

    def test_circle_outer_clearance_is_exactly_enforced(self) -> None:
        document = circular_sketch_document()
        document["constraints"][14] = fixed("c15", "q0", "4.999", "10")

        with self.assertRaisesRegex(InputError, "closer to outer_loop"):
            SketchExtrusion.from_dict(document)

    def test_circle_polygon_hole_clearance_is_exactly_enforced(self) -> None:
        document = circular_sketch_document()
        document["constraints"][14] = fixed("c15", "q0", "15.001", "30")

        with self.assertRaisesRegex(InputError, r"closer to inner_loops\[0\]"):
            SketchExtrusion.from_dict(document)

    def test_circle_inside_polygon_hole_is_rejected(self) -> None:
        document = circular_sketch_document()
        document["constraints"][14] = fixed("c15", "q0", "30", "30")

        with self.assertRaisesRegex(InputError, "center lies in or on inner_loops"):
            SketchExtrusion.from_dict(document)

    def test_circle_to_circle_clearance_is_exactly_enforced(self) -> None:
        document = circular_sketch_document()
        document["constraints"][15] = fixed("c16", "q1", "17.999", "10")

        with self.assertRaisesRegex(InputError, r"closer to circular_holes\[1\]"):
            SketchExtrusion.from_dict(document)

    def test_exact_minimum_circular_clearance_is_accepted(self) -> None:
        document = circular_sketch_document()
        document["constraints"][14] = fixed("c15", "q0", "5", "10")
        document["constraints"][15] = fixed("c16", "q1", "13", "10")

        sketch = SketchExtrusion.from_dict(document)

        self.assertEqual(sketch.profile.circular_holes[0].radius_mm, 3)

    def test_circle_center_must_be_a_distinct_fully_constrained_point(self) -> None:
        document = circular_sketch_document()
        document["constraints"].pop(14)

        with self.assertRaisesRegex(InputError, "underconstrained.*q0"):
            SketchExtrusion.from_dict(document)

        document = circular_sketch_document()
        document["profile"]["circular_holes"][0]["center_point_id"] = "p0"
        with self.assertRaisesRegex(InputError, "must not also be polygon vertices"):
            SketchExtrusion.from_dict(document)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_v2_bundle_uses_real_circles_and_reproduces(self) -> None:
        sketch = SketchExtrusion.from_dict(circular_sketch_document())
        with tempfile.TemporaryDirectory() as directory:
            bundle = compile_sketch_extrusion(sketch, directory)
            bundle_path = Path(directory) / "plate.circular-sketch.demo.sketch-bundle.json"

            report = verify_sketch_bundle(bundle_path)
            svg = (Path(directory) / "plate.circular-sketch.demo.svg").read_text(
                encoding="utf-8"
            )

            self.assertEqual(bundle["content"]["schema_version"], "contrainte.sketch-bundle/0.2")
            self.assertEqual(report["status"], "verified")
            self.assertNotIn("<circle ", svg)
            self.assertEqual(svg.count("A 3 3 0 1 0"), 4)
            self.assertIn('fill-rule="evenodd"', svg)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_rehashed_pi_comparison_basis_tampering_is_rejected(self) -> None:
        sketch = SketchExtrusion.from_dict(circular_sketch_document())
        with tempfile.TemporaryDirectory() as directory:
            bundle = compile_sketch_extrusion(sketch, directory)
            bundle["content"]["analysis"]["pi_comparison_basis"]["decimal_value"] = "3.14"
            bundle["digest"] = digest(bundle["content"])
            bundle_path = Path(directory) / "plate.circular-sketch.demo.sketch-bundle.json"
            bundle_path.write_text(dumps_pretty(bundle), encoding="utf-8", newline="\n")

            with self.assertRaisesRegex(IntegrityError, "analysis does not reproduce"):
                verify_sketch_bundle(bundle_path)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_rehashed_symbolic_coefficient_tampering_is_rejected(self) -> None:
        sketch = SketchExtrusion.from_dict(circular_sketch_document())
        with tempfile.TemporaryDirectory() as directory:
            bundle = compile_sketch_extrusion(sketch, directory)
            bundle["content"]["analysis"]["symbolic_volume_mm3"][
                "pi_coefficient"
            ] = "-179"
            bundle["digest"] = digest(bundle["content"])
            bundle_path = Path(directory) / "plate.circular-sketch.demo.sketch-bundle.json"
            bundle_path.write_text(dumps_pretty(bundle), encoding="utf-8", newline="\n")

            with self.assertRaisesRegex(IntegrityError, "analysis does not reproduce"):
                verify_sketch_bundle(bundle_path)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_sketch_and_bundle_schema_mismatch_is_rejected(self) -> None:
        sketch = SketchExtrusion.from_dict(circular_sketch_document())
        with tempfile.TemporaryDirectory() as directory:
            bundle = compile_sketch_extrusion(sketch, directory)
            bundle["content"]["schema_version"] = "contrainte.sketch-bundle/0.1"
            bundle["digest"] = digest(bundle["content"])
            bundle_path = Path(directory) / "plate.circular-sketch.demo.sketch-bundle.json"
            bundle_path.write_text(dumps_pretty(bundle), encoding="utf-8", newline="\n")

            with self.assertRaisesRegex(IntegrityError, "versions do not correspond"):
                verify_sketch_bundle(bundle_path)

    def test_v2_round_trip_is_unchanged_by_v3(self) -> None:
        document = circular_sketch_document()

        sketch = SketchExtrusion.from_dict(document)

        self.assertEqual(sketch.as_dict(), document)
        self.assertNotIn("midpoint_point_id", str(sketch.as_dict()))

    def test_v3_midpoint_solves_exact_centres(self) -> None:
        sketch = SketchExtrusion.from_dict(midpoint_sketch_document())

        solved, report = solve_constraints(sketch)

        self.assertEqual(solved["q0"], (Fraction(10), Fraction(10)))
        self.assertEqual(solved["q1"], (Fraction(90), Fraction(50)))
        self.assertEqual(solved, solved_mm(circular_sketch_document()))
        self.assertEqual(report["status"], "fully_constrained")
        self.assertEqual(report["variable_count"], 20)
        self.assertEqual(report["equation_count"], 20)
        self.assertEqual(report["rank"], 20)

    def test_v3_round_trip_preserves_digest(self) -> None:
        document = midpoint_sketch_document()
        sketch = SketchExtrusion.from_dict(document)

        reparsed = SketchExtrusion.from_dict(sketch.as_dict())

        self.assertEqual(sketch.as_dict(), document)
        self.assertEqual(sketch, reparsed)
        self.assertEqual(sketch.sketch_digest, reparsed.sketch_digest)

    def test_midpoint_follows_changed_endpoints(self) -> None:
        document = midpoint_sketch_document()
        document["constraints"][9]["distance"] = length("101")
        self.assertEqual(solved_mm(document)["q1"], (Fraction(181, 2), Fraction(50)))

        document = midpoint_sketch_document()
        document["constraints"][0]["x"] = length("24")
        document["constraints"][0]["y"] = length("22")
        solved = solved_mm(document)
        self.assertEqual(solved["q0"], (Fraction(12), Fraction(11)))
        self.assertEqual(solved["q1"], (Fraction(92), Fraction(51)))

        fixed_centres = circular_sketch_document()
        fixed_centres["constraints"][9]["distance"] = length("101")
        self.assertEqual(solved_mm(fixed_centres)["q1"], (Fraction(90), Fraction(50)))

    def test_midpoint_halving_remains_finite_decimal_evidence(self) -> None:
        document = midpoint_sketch_document()
        document["constraints"][9]["distance"] = length("100.001")

        _, report = solve_constraints(SketchExtrusion.from_dict(document))

        q1 = next(item for item in report["solved_points_mm"] if item["point_id"] == "q1")
        self.assertEqual(q1, {"point_id": "q1", "x": "90.0005", "y": "50"})

    def test_cyclic_midpoints_with_thirds_are_rejected_as_input(self) -> None:
        # Independent review F1: a=(0,0), c=(1,0), midpoint(a,b)->m and
        # midpoint(m,c)->b is full rank with exact b=2/3 mm, m=1/3 mm.
        document = midpoint_sketch_document()
        document["manufacturing"]["minimum_feature_size"] = length("0.1")
        document["points"] = [{"point_id": point} for point in ("a", "b", "c", "d", "m")]
        document["constraints"] = [
            fixed("c01", "a", "0", "0"),
            fixed("c02", "c", "1", "0"),
            fixed("c03", "d", "0", "1"),
            midpoint("c04", "a", "b", "m"),
            midpoint("c05", "m", "c", "b"),
        ]
        document["profile"] = {
            "outer_loop": ["a", "m", "b", "c", "d"],
            "inner_loops": [],
            "circular_holes": [],
        }

        with self.assertRaises(InputError) as raised:
            SketchExtrusion.from_dict(document)

        self.assertEqual(
            str(raised.exception),
            "sketch constraint solution is not a finite decimal and is unsupported; "
            "non-terminating coordinates: b.x = 2/3 mm, m.x = 1/3 mm; "
            "coupled midpoint constraints: c04, c05",
        )

    def test_cyclic_midpoint_plate_rejection_and_representable_cycle(self) -> None:
        document = coupled_midpoint_plate_document("100")
        with self.assertRaisesRegex(
            InputError,
            r"non-terminating coordinates: q0\.x = 100/3 mm, q1\.x = 200/3 mm; "
            r"coupled midpoint constraints: c15, c16$",
        ):
            SketchExtrusion.from_dict(document)

        solved, report = solve_constraints(
            SketchExtrusion.from_dict(coupled_midpoint_plate_document("90"))
        )
        self.assertEqual(solved["q0"], (Fraction(30), Fraction(20)))
        self.assertEqual(solved["q1"], (Fraction(60), Fraction(40)))
        self.assertEqual(report["rank"], report["variable_count"])

    def test_chained_midpoints_keep_exact_finite_decimals(self) -> None:
        document = coupled_midpoint_plate_document("100")
        document["constraints"][7] = midpoint("c15", "p0", "p2", "q0")
        document["constraints"][8] = midpoint("c16", "q0", "p2", "q1")
        document["constraints"][2]["distance"] = length("100.002")

        _, report = solve_constraints(SketchExtrusion.from_dict(document))

        centres = {
            item["point_id"]: (item["x"], item["y"])
            for item in report["solved_points_mm"]
            if item["point_id"] in {"q0", "q1"}
        }
        self.assertEqual(centres, {"q0": ("50.001", "30"), "q1": ("75.0015", "45")})

    def test_cli_reports_nonterminating_midpoint_solution_as_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "cyclic.json"
            input_path.write_text(
                dumps_pretty(coupled_midpoint_plate_document("100")),
                encoding="utf-8",
                newline="\n",
            )
            output_dir = Path(directory) / "out"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                status = cli_main(
                    ["sketch", "compile", str(input_path), "--output-dir", str(output_dir)]
                )

            self.assertEqual(status, 2)
            self.assertIn("q0.x = 100/3 mm", stderr.getvalue())
            self.assertIn("coupled midpoint constraints: c15, c16", stderr.getvalue())
            self.assertFalse(output_dir.exists())

    def test_midpoint_centre_clearance_tracks_endpoint_perturbation(self) -> None:
        document = midpoint_sketch_document()
        document["constraints"][4]["distance"] = length("30")
        sketch = SketchExtrusion.from_dict(document)
        self.assertEqual(solved_mm(sketch.as_dict())["q1"], (Fraction(90), Fraction(55)))

        document["constraints"][4]["distance"] = length("30.002")
        with self.assertRaisesRegex(InputError, "closer to outer_loop"):
            SketchExtrusion.from_dict(document)

    def test_midpoint_centre_topology_is_validated(self) -> None:
        document = midpoint_sketch_document()
        document["constraints"][14] = midpoint("c15", "p0", "p1", "q0")
        with self.assertRaisesRegex(InputError, "center is not strictly inside"):
            SketchExtrusion.from_dict(document)

        document = midpoint_sketch_document()
        document["constraints"][14] = midpoint("c15", "h0", "h2", "q0")
        with self.assertRaisesRegex(InputError, "center lies in or on inner_loops"):
            SketchExtrusion.from_dict(document)

    def test_midpoint_omission_is_underconstrained(self) -> None:
        document = midpoint_sketch_document()
        document["constraints"].pop(14)

        with self.assertRaisesRegex(InputError, "underconstrained.*q0.x, q0.y"):
            SketchExtrusion.from_dict(document)

    def test_midpoint_redundancy_is_rejected(self) -> None:
        for extra in (
            fixed("c99", "q0", "10", "10"),
            midpoint("c17", "p0", "h0", "q0"),
            midpoint("c17", "h0", "p0", "q0"),
        ):
            with self.subTest(extra=extra):
                document = midpoint_sketch_document()
                document["constraints"].append(extra)
                with self.assertRaisesRegex(InputError, "redundant or overconstraining"):
                    SketchExtrusion.from_dict(document)

    def test_midpoint_inconsistency_is_rejected(self) -> None:
        for extra in (
            fixed("c99", "q0", "11", "10"),
            midpoint("c17", "p1", "h1", "q0"),
        ):
            with self.subTest(extra=extra):
                document = midpoint_sketch_document()
                document["constraints"].append(extra)
                with self.assertRaisesRegex(InputError, "inconsistent"):
                    SketchExtrusion.from_dict(document)

    def test_midpoint_requires_three_distinct_known_points(self) -> None:
        for first, second, center in (
            ("p0", "p0", "q0"),
            ("p0", "h0", "p0"),
            ("p0", "h0", "h0"),
        ):
            with self.subTest(points=(first, second, center)):
                document = midpoint_sketch_document()
                document["constraints"][14] = midpoint("c15", first, second, center)
                with self.assertRaisesRegex(InputError, "three different points"):
                    SketchExtrusion.from_dict(document)

        document = midpoint_sketch_document()
        document["constraints"][14] = midpoint("c15", "p0", "h0", "zz")
        with self.assertRaisesRegex(InputError, "references unknown points: zz"):
            SketchExtrusion.from_dict(document)

    def test_midpoint_shape_is_closed(self) -> None:
        document = midpoint_sketch_document()
        del document["constraints"][14]["midpoint_point_id"]
        with self.assertRaisesRegex(InputError, "midpoint constraint must contain exactly"):
            SketchExtrusion.from_dict(document)

        document = midpoint_sketch_document()
        document["constraints"][14]["distance"] = length("0")
        with self.assertRaisesRegex(InputError, "midpoint constraint must contain exactly"):
            SketchExtrusion.from_dict(document)

        document = midpoint_sketch_document()
        document["constraints"][9]["midpoint_point_id"] = "q0"
        with self.assertRaisesRegex(InputError, "offset_x constraint must contain exactly"):
            SketchExtrusion.from_dict(document)

    def test_legacy_versions_reject_midpoint(self) -> None:
        document = midpoint_sketch_document()
        document["schema_version"] = "contrainte.sketch-extrusion/0.2"
        with self.assertRaisesRegex(InputError, "kind is unsupported: 'midpoint'"):
            SketchExtrusion.from_dict(document)

        document = sketch_document()
        document["constraints"].append(midpoint("c99", "p0", "p2", "h0"))
        with self.assertRaisesRegex(InputError, "kind is unsupported: 'midpoint'"):
            SketchExtrusion.from_dict(document)

        with self.assertRaisesRegex(InputError, "kind is unsupported: 'midpoint'"):
            SketchConstraint.from_dict(
                midpoint("c01", "p0", "p1", "q0"), field="constraint"
            )

    def test_v3_requires_circular_holes_field(self) -> None:
        document = midpoint_sketch_document()
        del document["profile"]["circular_holes"]

        with self.assertRaisesRegex(InputError, "must contain exactly"):
            SketchExtrusion.from_dict(document)

    @unittest.skipUnless(find_spec("build123d"), "optional CAD backend is not installed")
    def test_v3_bundle_reproduces_v2_geometry_and_rejects_version_substitution(
        self,
    ) -> None:
        sketch = SketchExtrusion.from_dict(midpoint_sketch_document())
        explicit, _ = analyze_sketch_extrusion(
            SketchExtrusion.from_dict(circular_sketch_document())
        )
        with tempfile.TemporaryDirectory() as directory:
            bundle = compile_sketch_extrusion(sketch, directory)
            bundle_path = Path(directory) / "plate.midpoint-sketch.demo.sketch-bundle.json"

            report = verify_sketch_bundle(bundle_path)

            self.assertEqual(report["status"], "verified")
            content = bundle["content"]
            self.assertEqual(content["schema_version"], "contrainte.sketch-bundle/0.3")
            self.assertEqual(content["analysis"], explicit)
            self.assertEqual(
                [item["id"] for item in content["checks"]],
                [
                    "SKETCH-SCHEMA",
                    "SKETCH-EXACT-LINEAR-CONSTRAINTS",
                    "SKETCH-FULLY-CONSTRAINED",
                    "SKETCH-SIMPLE-PROFILE-TOPOLOGY",
                    "SKETCH-MINIMUM-FEATURE",
                    "SKETCH-BREP-VALIDITY",
                    "SKETCH-EXACT-CIRCULAR-DIMENSIONS",
                    "SKETCH-CIRCULAR-CLEARANCE",
                    "SKETCH-SYMBOLIC-AREA-PINNED-PI-VOLUME-CROSSCHECK",
                    "SKETCH-MASS-LIMIT",
                    "SKETCH-ENVELOPE-LIMIT",
                ],
            )

            content["schema_version"] = "contrainte.sketch-bundle/0.2"
            bundle["digest"] = digest(content)
            bundle_path.write_text(dumps_pretty(bundle), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(IntegrityError, "versions do not correspond"):
                verify_sketch_bundle(bundle_path)


if __name__ == "__main__":
    unittest.main()
