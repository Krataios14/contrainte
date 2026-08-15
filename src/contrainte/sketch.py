from __future__ import annotations

import html
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

from .artifacts import artifact_descriptor, package_version, verify_artifacts
from .canonical import decimal_text, digest, dumps_pretty, loads_strict
from .errors import ExecutionError, InputError, IntegrityError
from .geometry import kernel_measurement, normalize_step_occurrence_identifiers
from .materials import MaterialRecord
from .solid import SolidLimits, SolidManufacturing
from .units import Quantity

SKETCH_EXTRUSION_SCHEMA = "contrainte.sketch-extrusion/0.1"
SKETCH_BUNDLE_SCHEMA = "contrainte.sketch-bundle/0.1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CONSTRAINT_KINDS = {"fixed", "horizontal", "vertical", "offset_x", "offset_y"}
_AXES = ("x", "y")


def _string(raw: Mapping[str, Any], name: str, field: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise InputError(f"{field}.{name} must be a non-empty string")
    return value


def _safe_id(raw: Mapping[str, Any], name: str, field: str) -> str:
    value = _string(raw, name, field)
    if not _SAFE_ID.fullmatch(value):
        raise InputError(f"{field}.{name} contains unsupported characters")
    return value


def _length(raw: Any, field: str, *, positive: bool = False) -> Quantity:
    value = Quantity.from_dict(raw, field=field)
    if value.kind != "length":
        raise InputError(f"{field} must have kind 'length'")
    if positive:
        value.require_positive(field)
    return value


def _mm_fraction(value: Quantity) -> Fraction:
    scale_to_mm = {"mm": 1, "cm": 10, "m": 1000}
    try:
        scale = scale_to_mm[value.unit]
    except KeyError as exc:
        raise InputError(f"unsupported length unit in sketch solver: {value.unit!r}") from exc
    return Fraction(value.value) * scale


def _kg_fraction(value: Quantity) -> Fraction:
    scale_to_kg = {"kg": Fraction(1), "g": Fraction(1, 1000)}
    try:
        scale = scale_to_kg[value.unit]
    except KeyError as exc:
        raise InputError(f"unsupported mass unit in sketch limits: {value.unit!r}") from exc
    return Fraction(value.value) * scale


def _fraction_text(value: Fraction) -> str:
    denominator = value.denominator
    powers_of_two = 0
    while denominator % 2 == 0:
        denominator //= 2
        powers_of_two += 1
    powers_of_five = 0
    while denominator % 5 == 0:
        denominator //= 5
        powers_of_five += 1
    if denominator != 1:
        raise ExecutionError("constraint solution cannot be represented as a finite decimal")
    places = max(powers_of_two, powers_of_five)
    scaled = abs(value.numerator) * (10**places // value.denominator)
    if places == 0:
        rendered = str(scaled)
    else:
        digits = str(scaled).zfill(places + 1)
        rendered = f"{digits[:-places]}.{digits[-places:]}".rstrip("0").rstrip(".")
    if value < 0:
        rendered = "-" + rendered
    return rendered


@dataclass(frozen=True)
class SketchPoint:
    point_id: str

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> SketchPoint:
        if not isinstance(raw, dict) or set(raw) != {"point_id"}:
            raise InputError(f"{field} must contain exactly point_id")
        return cls(_safe_id(raw, "point_id", field))

    def as_dict(self) -> dict[str, str]:
        return {"point_id": self.point_id}


@dataclass(frozen=True)
class SketchConstraint:
    constraint_id: str
    kind: str
    point_id: str | None
    first_point_id: str | None
    second_point_id: str | None
    x: Quantity | None
    y: Quantity | None
    distance: Quantity | None

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> SketchConstraint:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        constraint_id = _safe_id(raw, "constraint_id", field)
        kind = _string(raw, "kind", field)
        if kind not in _CONSTRAINT_KINDS:
            raise InputError(f"{field}.kind is unsupported: {kind!r}")
        if kind == "fixed":
            expected = {"constraint_id", "kind", "point_id", "x", "y"}
            if set(raw) != expected:
                raise InputError(
                    f"{field} fixed constraint must contain exactly "
                    "constraint_id, kind, point_id, x, and y"
                )
            return cls(
                constraint_id,
                kind,
                _safe_id(raw, "point_id", field),
                None,
                None,
                _length(raw["x"], f"{field}.x"),
                _length(raw["y"], f"{field}.y"),
                None,
            )
        expected = {
            "constraint_id",
            "kind",
            "first_point_id",
            "second_point_id",
        }
        if kind in {"offset_x", "offset_y"}:
            expected.add("distance")
        if set(raw) != expected:
            rendered = ", ".join(sorted(expected))
            raise InputError(f"{field} {kind} constraint must contain exactly {rendered}")
        first = _safe_id(raw, "first_point_id", field)
        second = _safe_id(raw, "second_point_id", field)
        if first == second:
            raise InputError(f"{field} must reference two different points")
        return cls(
            constraint_id,
            kind,
            None,
            first,
            second,
            None,
            None,
            (
                _length(raw["distance"], f"{field}.distance")
                if "distance" in raw
                else None
            ),
        )

    @property
    def referenced_points(self) -> tuple[str, ...]:
        if self.point_id is not None:
            return (self.point_id,)
        assert self.first_point_id is not None
        assert self.second_point_id is not None
        return (self.first_point_id, self.second_point_id)

    def as_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "constraint_id": self.constraint_id,
            "kind": self.kind,
        }
        if self.kind == "fixed":
            assert self.point_id is not None and self.x is not None and self.y is not None
            document.update(
                {"point_id": self.point_id, "x": self.x.as_dict(), "y": self.y.as_dict()}
            )
        else:
            document.update(
                {
                    "first_point_id": self.first_point_id,
                    "second_point_id": self.second_point_id,
                }
            )
            if self.distance is not None:
                document["distance"] = self.distance.as_dict()
        return document


@dataclass(frozen=True)
class SketchProfile:
    outer_loop: tuple[str, ...]
    inner_loops: tuple[tuple[str, ...], ...]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> SketchProfile:
        if not isinstance(raw, dict) or set(raw) != {"outer_loop", "inner_loops"}:
            raise InputError(f"{field} must contain exactly outer_loop and inner_loops")
        outer = _loop(raw.get("outer_loop"), f"{field}.outer_loop")
        inner_raw = raw.get("inner_loops")
        if not isinstance(inner_raw, list):
            raise InputError(f"{field}.inner_loops must be a list")
        inner = tuple(
            _loop(item, f"{field}.inner_loops[{index}]")
            for index, item in enumerate(inner_raw)
        )
        first_ids = [loop[0] for loop in inner]
        if first_ids != sorted(first_ids):
            raise InputError(f"{field}.inner_loops must be ordered by their first point")
        return cls(outer, inner)

    @property
    def loops(self) -> tuple[tuple[str, ...], ...]:
        return (self.outer_loop, *self.inner_loops)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outer_loop": list(self.outer_loop),
            "inner_loops": [list(loop) for loop in self.inner_loops],
        }


def _loop(raw: Any, field: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or len(raw) < 3:
        raise InputError(f"{field} must contain at least three point identifiers")
    if not all(isinstance(item, str) and _SAFE_ID.fullmatch(item) for item in raw):
        raise InputError(f"{field} contains an invalid point identifier")
    loop = tuple(raw)
    if len(loop) != len(set(loop)):
        raise InputError(f"{field} must not repeat a point or repeat the closing point")
    if loop[0] != min(loop):
        raise InputError(f"{field} must start with its lowest lexical point identifier")
    return loop


@dataclass(frozen=True)
class SketchExtrusion:
    schema_version: str
    part_id: str
    revision: str
    title: str
    material: MaterialRecord
    manufacturing: SolidManufacturing
    limits: SolidLimits
    points: tuple[SketchPoint, ...]
    constraints: tuple[SketchConstraint, ...]
    profile: SketchProfile
    extrusion_distance: Quantity

    @classmethod
    def from_dict(cls, raw: Any, *, field: str = "sketch_extrusion") -> SketchExtrusion:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        allowed = {
            "schema_version",
            "part_id",
            "revision",
            "title",
            "material",
            "manufacturing",
            "limits",
            "points",
            "constraints",
            "profile",
            "extrusion_distance",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
        schema = _string(raw, "schema_version", field)
        if schema != SKETCH_EXTRUSION_SCHEMA:
            raise InputError(f"unsupported sketch-extrusion schema: {schema!r}")
        points_raw = raw.get("points")
        if not isinstance(points_raw, list) or len(points_raw) < 3:
            raise InputError(f"{field}.points must contain at least three points")
        points = tuple(
            SketchPoint.from_dict(item, field=f"{field}.points[{index}]")
            for index, item in enumerate(points_raw)
        )
        point_ids = [item.point_id for item in points]
        if len(point_ids) != len(set(point_ids)):
            raise InputError(f"{field}.point identifiers must be unique")
        if point_ids != sorted(point_ids):
            raise InputError(f"{field}.points must be ordered by point_id")
        constraints_raw = raw.get("constraints")
        if not isinstance(constraints_raw, list) or not constraints_raw:
            raise InputError(f"{field}.constraints must be a non-empty list")
        constraints = tuple(
            SketchConstraint.from_dict(item, field=f"{field}.constraints[{index}]")
            for index, item in enumerate(constraints_raw)
        )
        constraint_ids = [item.constraint_id for item in constraints]
        if len(constraint_ids) != len(set(constraint_ids)):
            raise InputError(f"{field}.constraint identifiers must be unique")
        if constraint_ids != sorted(constraint_ids):
            raise InputError(f"{field}.constraints must be ordered by constraint_id")
        known = set(point_ids)
        for constraint in constraints:
            missing = sorted(set(constraint.referenced_points) - known)
            if missing:
                raise InputError(
                    f"constraint {constraint.constraint_id!r} references unknown points: "
                    + ", ".join(missing)
                )
        profile = SketchProfile.from_dict(raw.get("profile"), field=f"{field}.profile")
        profile_points = [point for loop in profile.loops for point in loop]
        if len(profile_points) != len(set(profile_points)):
            raise InputError(f"{field}.profile loops must not share points")
        if set(profile_points) != known:
            missing = sorted(known - set(profile_points))
            unknown_profile = sorted(set(profile_points) - known)
            details = []
            if missing:
                details.append("unused points: " + ", ".join(missing))
            if unknown_profile:
                details.append("unknown points: " + ", ".join(unknown_profile))
            raise InputError(f"{field}.profile does not use points exactly: {'; '.join(details)}")
        sketch = cls(
            schema,
            _safe_id(raw, "part_id", field),
            _string(raw, "revision", field),
            _string(raw, "title", field),
            MaterialRecord.from_dict(raw.get("material"), field=f"{field}.material"),
            SolidManufacturing.from_dict(
                raw.get("manufacturing"), field=f"{field}.manufacturing"
            ),
            SolidLimits.from_dict(raw.get("limits"), field=f"{field}.limits"),
            points,
            constraints,
            profile,
            _length(
                raw.get("extrusion_distance"),
                f"{field}.extrusion_distance",
                positive=True,
            ),
        )
        solved, _ = solve_constraints(sketch)
        validate_profile(sketch, solved)
        minimum = _mm_fraction(sketch.manufacturing.minimum_feature_size)
        if _mm_fraction(sketch.extrusion_distance) < minimum:
            raise InputError("extrusion distance violates the minimum feature size")
        return sketch

    @property
    def sketch_digest(self) -> str:
        return digest(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "part_id": self.part_id,
            "revision": self.revision,
            "title": self.title,
            "material": self.material.as_dict(),
            "manufacturing": self.manufacturing.as_dict(),
            "limits": self.limits.as_dict(),
            "points": [item.as_dict() for item in self.points],
            "constraints": [item.as_dict() for item in self.constraints],
            "profile": self.profile.as_dict(),
            "extrusion_distance": self.extrusion_distance.as_dict(),
        }


PointMap = Mapping[str, tuple[Fraction, Fraction]]


def solve_constraints(
    sketch: SketchExtrusion,
) -> tuple[dict[str, tuple[Fraction, Fraction]], dict[str, Any]]:
    variables = [
        (point.point_id, axis) for point in sketch.points for axis in _AXES
    ]
    index = {variable: offset for offset, variable in enumerate(variables)}
    equations: list[list[Fraction]] = []

    def equation(terms: Mapping[tuple[str, str], int], result: Fraction) -> None:
        row = [Fraction(0) for _ in range(len(variables) + 1)]
        for variable, coefficient in terms.items():
            row[index[variable]] = Fraction(coefficient)
        row[-1] = result
        equations.append(row)

    for constraint in sketch.constraints:
        if constraint.kind == "fixed":
            assert constraint.point_id and constraint.x and constraint.y
            equation({(constraint.point_id, "x"): 1}, _mm_fraction(constraint.x))
            equation({(constraint.point_id, "y"): 1}, _mm_fraction(constraint.y))
            continue
        assert constraint.first_point_id and constraint.second_point_id
        axis = "y" if constraint.kind == "horizontal" else "x"
        result = Fraction(0)
        if constraint.kind in {"offset_x", "offset_y"}:
            axis = constraint.kind[-1]
            assert constraint.distance is not None
            result = _mm_fraction(constraint.distance)
        equation(
            {
                (constraint.first_point_id, axis): -1,
                (constraint.second_point_id, axis): 1,
            },
            result,
        )

    pivot_columns: list[int] = []
    pivot_row = 0
    for column in range(len(variables)):
        candidate = next(
            (
                row
                for row in range(pivot_row, len(equations))
                if equations[row][column] != 0
            ),
            None,
        )
        if candidate is None:
            continue
        equations[pivot_row], equations[candidate] = (
            equations[candidate],
            equations[pivot_row],
        )
        pivot = equations[pivot_row][column]
        equations[pivot_row] = [value / pivot for value in equations[pivot_row]]
        for row in range(len(equations)):
            if row == pivot_row:
                continue
            factor = equations[row][column]
            if factor != 0:
                equations[row] = [
                    current - factor * source
                    for current, source in zip(equations[row], equations[pivot_row])
                ]
        pivot_columns.append(column)
        pivot_row += 1
        if pivot_row == len(equations):
            break

    for row in equations:
        if all(value == 0 for value in row[:-1]) and row[-1] != 0:
            raise InputError("sketch constraints are inconsistent")
    rank = len(pivot_columns)
    if rank < len(variables):
        free = [
            f"{point}.{axis}"
            for column, (point, axis) in enumerate(variables)
            if column not in pivot_columns
        ]
        raise InputError(
            "sketch is underconstrained; unconstrained coordinates: " + ", ".join(free)
        )
    if len(equations) > rank:
        raise InputError("sketch contains redundant or overconstraining equations")
    solution_by_column = {
        column: equations[row][-1] for row, column in enumerate(pivot_columns)
    }
    solved = {
        point.point_id: (
            solution_by_column[index[(point.point_id, "x")]],
            solution_by_column[index[(point.point_id, "y")]],
        )
        for point in sketch.points
    }
    report = {
        "status": "fully_constrained",
        "variable_count": len(variables),
        "equation_count": len(equations),
        "rank": rank,
        "exact_arithmetic": "rational",
        "solved_points_mm": [
            {
                "point_id": point.point_id,
                "x": _fraction_text(solved[point.point_id][0]),
                "y": _fraction_text(solved[point.point_id][1]),
            }
            for point in sketch.points
        ],
    }
    return solved, report


def validate_profile(sketch: SketchExtrusion, points: PointMap) -> None:
    outer_area = _signed_double_area(sketch.profile.outer_loop, points)
    if outer_area <= 0:
        raise InputError("profile outer_loop must have counter-clockwise winding")
    for index, loop in enumerate(sketch.profile.inner_loops):
        if _signed_double_area(loop, points) >= 0:
            raise InputError(f"profile inner_loops[{index}] must have clockwise winding")
    minimum = _mm_fraction(sketch.manufacturing.minimum_feature_size)
    for index, loop in enumerate(sketch.profile.loops):
        _validate_simple_loop(loop, points, f"profile.loops[{index}]", minimum)
    outer_segments = _segments(sketch.profile.outer_loop, points)
    for hole_index, hole in enumerate(sketch.profile.inner_loops):
        if _point_in_polygon(points[hole[0]], sketch.profile.outer_loop, points) != 1:
            raise InputError(f"profile inner_loops[{hole_index}] is not strictly inside outer_loop")
        hole_segments = _segments(hole, points)
        if _loops_intersect(outer_segments, hole_segments):
            raise InputError(f"profile inner_loops[{hole_index}] intersects outer_loop")
        if _segments_below_separation(outer_segments, hole_segments, minimum):
            raise InputError(
                f"profile inner_loops[{hole_index}] is closer to outer_loop than "
                "the minimum feature size"
            )
    for first_index, first in enumerate(sketch.profile.inner_loops):
        first_segments = _segments(first, points)
        for second_index, second in enumerate(
            sketch.profile.inner_loops[first_index + 1 :], start=first_index + 1
        ):
            if _loops_intersect(first_segments, _segments(second, points)):
                raise InputError(
                    f"profile inner_loops[{first_index}] intersects inner_loops[{second_index}]"
                )
            if (
                _point_in_polygon(points[first[0]], second, points) == 1
                or _point_in_polygon(points[second[0]], first, points) == 1
            ):
                raise InputError("profile holes must not contain one another")
            if _segments_below_separation(
                first_segments, _segments(second, points), minimum
            ):
                raise InputError(
                    f"profile inner_loops[{first_index}] is closer to "
                    f"inner_loops[{second_index}] than the minimum feature size"
                )


def _signed_double_area(loop: Sequence[str], points: PointMap) -> Fraction:
    return sum(
        (
            points[first][0] * points[second][1]
            - points[second][0] * points[first][1]
            for first, second in zip(loop, (*loop[1:], loop[0]))
        ),
        Fraction(0),
    )


Segment = tuple[tuple[Fraction, Fraction], tuple[Fraction, Fraction]]


def _segments(loop: Sequence[str], points: PointMap) -> tuple[Segment, ...]:
    return tuple(
        (points[first], points[second])
        for first, second in zip(loop, (*loop[1:], loop[0]))
    )


def _validate_simple_loop(
    loop: Sequence[str], points: PointMap, field: str, minimum: Fraction
) -> None:
    segments = _segments(loop, points)
    minimum_squared = minimum * minimum
    for first, second in segments:
        squared = (second[0] - first[0]) ** 2 + (second[1] - first[1]) ** 2
        if squared < minimum_squared:
            raise InputError(f"{field} contains an edge below the minimum feature size")
    count = len(segments)
    for first_index, first in enumerate(segments):
        for second_index in range(first_index + 1, count):
            if second_index in {
                first_index,
                (first_index + 1) % count,
                (first_index - 1) % count,
            }:
                continue
            if _segment_intersects(first, segments[second_index]):
                raise InputError(f"{field} is self-intersecting")
    for vertex_index, point_id in enumerate(loop):
        for segment_index, segment in enumerate(segments):
            if segment_index in {vertex_index, (vertex_index - 1) % count}:
                continue
            if _point_segment_distance_squared(points[point_id], segment) < minimum_squared:
                raise InputError(
                    f"{field} contains a vertex and nonincident edge closer than the minimum "
                    "feature size"
                )


def _cross(
    first: tuple[Fraction, Fraction],
    second: tuple[Fraction, Fraction],
    third: tuple[Fraction, Fraction],
) -> Fraction:
    return (second[0] - first[0]) * (third[1] - first[1]) - (
        second[1] - first[1]
    ) * (third[0] - first[0])


def _on_segment(
    point: tuple[Fraction, Fraction], segment: Segment
) -> bool:
    first, second = segment
    return (
        _cross(first, second, point) == 0
        and min(first[0], second[0]) <= point[0] <= max(first[0], second[0])
        and min(first[1], second[1]) <= point[1] <= max(first[1], second[1])
    )


def _segment_intersects(first: Segment, second: Segment) -> bool:
    a, b = first
    c, d = second
    orientations = (_cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b))
    if any(value == 0 for value in orientations):
        return any(
            _on_segment(point, segment)
            for point, segment in ((c, first), (d, first), (a, second), (b, second))
        )
    return (orientations[0] > 0) != (orientations[1] > 0) and (
        orientations[2] > 0
    ) != (orientations[3] > 0)


def _loops_intersect(first: Sequence[Segment], second: Sequence[Segment]) -> bool:
    return any(_segment_intersects(a, b) for a in first for b in second)


def _point_segment_distance_squared(
    point: tuple[Fraction, Fraction], segment: Segment
) -> Fraction:
    first, second = segment
    delta_x = second[0] - first[0]
    delta_y = second[1] - first[1]
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0:
        return (point[0] - first[0]) ** 2 + (point[1] - first[1]) ** 2
    projection = (
        (point[0] - first[0]) * delta_x + (point[1] - first[1]) * delta_y
    ) / length_squared
    if projection <= 0:
        closest = first
    elif projection >= 1:
        closest = second
    else:
        closest = (
            first[0] + projection * delta_x,
            first[1] + projection * delta_y,
        )
    return (point[0] - closest[0]) ** 2 + (point[1] - closest[1]) ** 2


def _segment_distance_squared(first: Segment, second: Segment) -> Fraction:
    if _segment_intersects(first, second):
        return Fraction(0)
    return min(
        _point_segment_distance_squared(first[0], second),
        _point_segment_distance_squared(first[1], second),
        _point_segment_distance_squared(second[0], first),
        _point_segment_distance_squared(second[1], first),
    )


def _segments_below_separation(
    first: Sequence[Segment], second: Sequence[Segment], minimum: Fraction
) -> bool:
    minimum_squared = minimum * minimum
    return any(
        _segment_distance_squared(first_segment, second_segment) < minimum_squared
        for first_segment in first
        for second_segment in second
    )


def _point_in_polygon(
    point: tuple[Fraction, Fraction], loop: Sequence[str], points: PointMap
) -> int:
    segments = _segments(loop, points)
    if any(_on_segment(point, segment) for segment in segments):
        return 0
    inside = False
    px, py = point
    for (x1, y1), (x2, y2) in segments:
        if (y1 > py) != (y2 > py):
            intersection_x = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if intersection_x > px:
                inside = not inside
    return 1 if inside else -1


def load_sketch_extrusion(path: str | Path) -> SketchExtrusion:
    source = Path(path)
    try:
        return SketchExtrusion.from_dict(loads_strict(source.read_bytes()))
    except OSError as exc:
        raise InputError(f"cannot read sketch extrusion {source}: {exc}") from exc


def build_sketch_shape(sketch: SketchExtrusion) -> Any:
    try:
        from build123d import Polygon, extrude
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc
    solved, _ = solve_constraints(sketch)
    outer = Polygon(*[(float(x), float(y)) for x, y in _loop_points(sketch.profile.outer_loop, solved)])
    profile = outer
    for loop in sketch.profile.inner_loops:
        hole = Polygon(*[(float(x), float(y)) for x, y in _loop_points(loop, solved)])
        profile = profile - hole
    shape = extrude(profile, amount=float(sketch.extrusion_distance.to("mm").value))
    valid = shape.is_valid
    if callable(valid):
        valid = valid()
    if not valid or len(shape.solids()) != 1:
        raise ExecutionError("Open CASCADE did not produce one valid extruded solid")
    return shape


def _loop_points(
    loop: Sequence[str], points: PointMap
) -> tuple[tuple[Fraction, Fraction], ...]:
    return tuple(points[point_id] for point_id in loop)


def analyze_sketch_extrusion(sketch: SketchExtrusion) -> tuple[dict[str, Any], Any]:
    solved, constraint_report = solve_constraints(sketch)
    validate_profile(sketch, solved)
    shape = build_sketch_shape(sketch)
    outer_area = _signed_double_area(sketch.profile.outer_loop, solved) / 2
    holes_area = sum(
        (-_signed_double_area(loop, solved) / 2 for loop in sketch.profile.inner_loops),
        Fraction(0),
    )
    net_area = outer_area - holes_area
    distance = _mm_fraction(sketch.extrusion_distance)
    expected_volume = net_area * distance
    raw_volume = Decimal(str(shape.volume))
    expected_text = _fraction_text(expected_volume)
    density_quantity = sketch.material.properties["density"].quantity
    if density_quantity.unit != "kg/m3":
        raise ExecutionError("sketch material density must be expressed in kg/m3")
    density = density_quantity.value
    calculation_digits = max(
        50,
        len(expected_text.replace("-", "").replace(".", "")) + 20,
        len(decimal_text(density).replace("-", "").replace(".", "")) + 30,
    )
    with localcontext() as context:
        context.prec = calculation_digits
        expected_decimal = Decimal(expected_text)
        relative_error = abs(raw_volume - expected_decimal) / expected_decimal
        mass_kg = raw_volume * Decimal("0.000000001") * density
    failures: list[str] = []
    if relative_error > Decimal("0.00000001"):
        failures.append("kernel volume does not match exact profile area times extrusion")
    maximum_mass = _kg_fraction(sketch.limits.maximum_mass)
    if mass_kg > maximum_mass:
        failures.append(
            f"mass {decimal_text(kernel_measurement(mass_kg))} kg exceeds "
            f"{_fraction_text(maximum_mass)} kg"
        )
    bounds = shape.bounding_box().size
    bounding_box = {
        axis: kernel_measurement(getattr(bounds, axis.upper())) for axis in ("x", "y", "z")
    }
    for axis in ("x", "y", "z"):
        maximum = _mm_fraction(sketch.limits.maximum_bounding_box[axis])
        if bounding_box[axis] > maximum:
            failures.append(
                f"bounding box {axis}={decimal_text(bounding_box[axis])} mm exceeds "
                f"{_fraction_text(maximum)} mm"
            )
    analysis = {
        "status": "passed" if not failures else "failed",
        "constraint_solution": constraint_report,
        "profile": {
            "outer_area_mm2": _fraction_text(outer_area),
            "inner_area_mm2": _fraction_text(holes_area),
            "net_area_mm2": _fraction_text(net_area),
            "outer_vertex_count": len(sketch.profile.outer_loop),
            "inner_loop_count": len(sketch.profile.inner_loops),
        },
        "extrusion_distance_mm": _fraction_text(distance),
        "exact_volume_mm3": _fraction_text(expected_volume),
        "kernel_volume_mm3": decimal_text(kernel_measurement(raw_volume)),
        "relative_volume_error": decimal_text(kernel_measurement(relative_error)),
        "mass_kg": decimal_text(kernel_measurement(mass_kg)),
        "maximum_mass_kg": _fraction_text(maximum_mass),
        "bounding_box_mm": {
            axis: decimal_text(bounding_box[axis]) for axis in ("x", "y", "z")
        },
        "failures": failures,
    }
    return analysis, shape


def compile_sketch_extrusion(
    sketch: SketchExtrusion, output_directory: str | Path
) -> dict[str, Any]:
    try:
        from build123d import export_step, export_stl
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc
    analysis, shape = analyze_sketch_extrusion(sketch)
    if analysis["status"] != "passed":
        raise ExecutionError(
            "sketch-extrusion verification failed: " + "; ".join(analysis["failures"])
        )
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    step_path = destination / f"{sketch.part_id}.step"
    stl_path = destination / f"{sketch.part_id}.stl"
    svg_path = destination / f"{sketch.part_id}.svg"
    if not export_step(shape, step_path, timestamp="2000-01-01T00:00:00"):
        raise ExecutionError("Open CASCADE failed to export sketch-extrusion STEP geometry")
    normalize_step_occurrence_identifiers(step_path)
    if not export_stl(shape, stl_path, tolerance=0.01, angular_tolerance=0.1):
        raise ExecutionError("Open CASCADE failed to export sketch-extrusion STL geometry")
    svg_path.write_text(_profile_svg(sketch), encoding="utf-8", newline="\n")
    artifacts = [
        artifact_descriptor(step_path, "model/step", "exact_geometry"),
        artifact_descriptor(stl_path, "model/stl", "visualization_mesh"),
        artifact_descriptor(svg_path, "image/svg+xml", "drawing"),
    ]
    content = {
        "schema_version": SKETCH_BUNDLE_SCHEMA,
        "qualification": "unqualified_demonstration",
        "sketch_digest": sketch.sketch_digest,
        "material_digest": sketch.material.material_digest,
        "sketch": sketch.as_dict(),
        "analysis": analysis,
        "kernel": {
            "backend": "build123d-opencascade",
            "build123d_version": package_version("build123d"),
            "opencascade_distribution_version": package_version("cadquery-ocp"),
        },
        "checks": _sketch_checks(),
        "artifacts": artifacts,
    }
    bundle = {"digest": digest(content), "content": content}
    bundle_path = destination / f"{sketch.part_id}.sketch-bundle.json"
    bundle_path.write_text(dumps_pretty(bundle), encoding="utf-8", newline="\n")
    return bundle


def verify_sketch_bundle(bundle_path: str | Path) -> dict[str, str]:
    path = Path(bundle_path)
    try:
        bundle = loads_strict(path.read_bytes())
    except OSError as exc:
        raise InputError(f"cannot read sketch bundle {path}: {exc}") from exc
    if not isinstance(bundle, dict) or set(bundle) != {"digest", "content"}:
        raise IntegrityError("sketch bundle must contain exactly digest and content")
    content = bundle.get("content")
    if not isinstance(content, dict) or digest(content) != bundle.get("digest"):
        raise IntegrityError("sketch bundle digest mismatch")
    required = {
        "schema_version",
        "qualification",
        "sketch_digest",
        "material_digest",
        "sketch",
        "analysis",
        "kernel",
        "checks",
        "artifacts",
    }
    if set(content) != required:
        raise IntegrityError("sketch bundle content has unsupported or missing fields")
    if content.get("schema_version") != SKETCH_BUNDLE_SCHEMA:
        raise IntegrityError("unsupported sketch bundle schema")
    if content.get("qualification") != "unqualified_demonstration":
        raise IntegrityError("sketch bundle qualification is unsupported")
    try:
        sketch = SketchExtrusion.from_dict(content.get("sketch"))
    except InputError as exc:
        raise IntegrityError("embedded sketch is invalid") from exc
    if sketch.sketch_digest != content.get("sketch_digest"):
        raise IntegrityError("embedded sketch does not match its declared digest")
    if sketch.material.material_digest != content.get("material_digest"):
        raise IntegrityError("embedded sketch material does not match its declared digest")
    analysis, _ = analyze_sketch_extrusion(sketch)
    if analysis != content.get("analysis") or analysis["status"] != "passed":
        raise IntegrityError("sketch analysis does not reproduce as passed")
    expected_kernel = {
        "backend": "build123d-opencascade",
        "build123d_version": package_version("build123d"),
        "opencascade_distribution_version": package_version("cadquery-ocp"),
    }
    if content.get("kernel") != expected_kernel:
        raise IntegrityError("sketch kernel identity does not match the reproducing runtime")
    if content.get("checks") != _sketch_checks():
        raise IntegrityError("sketch checks are false, incomplete, or unsupported")
    verify_artifacts(
        path.parent,
        content.get("artifacts"),
        {
            f"{sketch.part_id}.step": ("model/step", "exact_geometry"),
            f"{sketch.part_id}.stl": ("model/stl", "visualization_mesh"),
            f"{sketch.part_id}.svg": ("image/svg+xml", "drawing"),
        },
    )
    with tempfile.TemporaryDirectory(prefix="contrainte-sketch-verify-") as directory:
        reproduced = compile_sketch_extrusion(sketch, directory)
    if reproduced["content"]["artifacts"] != content.get("artifacts"):
        raise IntegrityError("sketch artifacts do not reproduce from the embedded sketch")
    return {
        "status": "verified",
        "bundle_digest": bundle["digest"],
        "sketch_digest": sketch.sketch_digest,
    }


def _profile_svg(sketch: SketchExtrusion) -> str:
    solved, _ = solve_constraints(sketch)
    xs = [point[0] for point in solved.values()]
    ys = [point[1] for point in solved.values()]
    padding = Fraction(5)
    minimum_x = min(xs) - padding
    maximum_y = max(ys) + padding
    width = max(xs) - min(xs) + padding * 2
    height = max(ys) - min(ys) + padding * 2
    paths = []
    for loop in sketch.profile.loops:
        coordinates = _loop_points(loop, solved)
        commands = [
            f"M {_fraction_text(coordinates[0][0])} {_fraction_text(-coordinates[0][1])}"
        ]
        commands.extend(
            f"L {_fraction_text(x)} {_fraction_text(-y)}" for x, y in coordinates[1:]
        )
        commands.append("Z")
        paths.append(" ".join(commands))
    title = html.escape(sketch.title)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{_fraction_text(minimum_x)} '
        f'{_fraction_text(-maximum_y)} {_fraction_text(width)} {_fraction_text(height)}">\n'
        f"  <title>{title}</title>\n"
        f'  <path d="{" ".join(paths)}" fill="#d9e3ea" fill-rule="evenodd" '
        'stroke="#17242d" stroke-width="0.5"/>\n'
        "</svg>\n"
    )


def _sketch_checks() -> list[dict[str, str]]:
    return [
        {"id": "SKETCH-SCHEMA", "status": "passed"},
        {"id": "SKETCH-EXACT-LINEAR-CONSTRAINTS", "status": "passed"},
        {"id": "SKETCH-FULLY-CONSTRAINED", "status": "passed"},
        {"id": "SKETCH-SIMPLE-PROFILE-TOPOLOGY", "status": "passed"},
        {"id": "SKETCH-MINIMUM-FEATURE", "status": "passed"},
        {"id": "SKETCH-BREP-VALIDITY", "status": "passed"},
        {"id": "SKETCH-EXACT-VOLUME-CROSSCHECK", "status": "passed"},
        {"id": "SKETCH-MASS-LIMIT", "status": "passed"},
        {"id": "SKETCH-ENVELOPE-LIMIT", "status": "passed"},
    ]
