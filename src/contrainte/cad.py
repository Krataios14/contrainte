from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .artifacts import artifact_descriptor, package_version, verify_artifacts
from .canonical import decimal_text, digest, dumps_pretty, loads_strict
from .errors import ExecutionError, InputError, IntegrityError
from .materials import MaterialRecord
from .units import Quantity

PART_SCHEMA = "contrainte.prismatic-part/0.1"
CAD_BUNDLE_SCHEMA = "contrainte.cad-bundle/0.1"
_PI = Decimal("3.1415926535897932384626433832795028841971693993751")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _quantity(raw: Any, field: str, *, positive: bool = False) -> Quantity:
    value = Quantity.from_dict(raw, field=field)
    if value.kind != "length":
        raise InputError(f"{field} must have kind 'length'")
    if positive:
        value.require_positive(field)
    return value


def _string(raw: dict[str, Any], name: str, field: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise InputError(f"{field}.{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ThroughHole:
    hole_id: str
    x: Quantity
    y: Quantity
    diameter: Quantity
    diameter_tolerance: Quantity
    position_tolerance: Quantity

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ThroughHole:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        allowed = {
            "hole_id",
            "x",
            "y",
            "diameter",
            "diameter_tolerance",
            "position_tolerance",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
        hole_id = _string(raw, "hole_id", field)
        if not _SAFE_ID.fullmatch(hole_id):
            raise InputError(f"{field}.hole_id contains unsupported characters")
        diameter_tolerance = _quantity(
            raw.get("diameter_tolerance"), f"{field}.diameter_tolerance"
        )
        position_tolerance = _quantity(
            raw.get("position_tolerance"), f"{field}.position_tolerance"
        )
        if diameter_tolerance.value < 0 or position_tolerance.value < 0:
            raise InputError(f"{field} tolerances must be non-negative")
        return cls(
            hole_id=hole_id,
            x=_quantity(raw.get("x"), f"{field}.x"),
            y=_quantity(raw.get("y"), f"{field}.y"),
            diameter=_quantity(raw.get("diameter"), f"{field}.diameter", positive=True),
            diameter_tolerance=diameter_tolerance,
            position_tolerance=position_tolerance,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "hole_id": self.hole_id,
            "x": self.x.as_dict(),
            "y": self.y.as_dict(),
            "diameter": self.diameter.as_dict(),
            "diameter_tolerance": self.diameter_tolerance.as_dict(),
            "position_tolerance": self.position_tolerance.as_dict(),
        }


@dataclass(frozen=True)
class ManufacturingRules:
    process: str
    minimum_edge_distance: Quantity
    minimum_web_thickness: Quantity

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> ManufacturingRules:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        unknown = sorted(
            set(raw) - {"process", "minimum_edge_distance", "minimum_web_thickness"}
        )
        if unknown:
            raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
        return cls(
            process=_string(raw, "process", field),
            minimum_edge_distance=_quantity(
                raw.get("minimum_edge_distance"),
                f"{field}.minimum_edge_distance",
                positive=True,
            ),
            minimum_web_thickness=_quantity(
                raw.get("minimum_web_thickness"),
                f"{field}.minimum_web_thickness",
                positive=True,
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "process": self.process,
            "minimum_edge_distance": self.minimum_edge_distance.as_dict(),
            "minimum_web_thickness": self.minimum_web_thickness.as_dict(),
        }


@dataclass(frozen=True)
class PrismaticPart:
    schema_version: str
    part_id: str
    revision: str
    title: str
    length: Quantity
    width: Quantity
    thickness: Quantity
    holes: tuple[ThroughHole, ...]
    material: MaterialRecord
    manufacturing: ManufacturingRules

    @classmethod
    def from_dict(cls, raw: Any, *, field: str = "part") -> PrismaticPart:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        allowed = {
            "schema_version",
            "part_id",
            "revision",
            "title",
            "stock",
            "holes",
            "material",
            "manufacturing",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
        schema = _string(raw, "schema_version", field)
        if schema != PART_SCHEMA:
            raise InputError(f"unsupported prismatic-part schema: {schema!r}")
        part_id = _string(raw, "part_id", field)
        if not _SAFE_ID.fullmatch(part_id):
            raise InputError(f"{field}.part_id contains unsupported characters")
        stock = raw.get("stock")
        if not isinstance(stock, dict) or set(stock) != {"length", "width", "thickness"}:
            raise InputError(
                f"{field}.stock must contain exactly length, width, and thickness"
            )
        holes_raw = raw.get("holes", [])
        if not isinstance(holes_raw, list):
            raise InputError(f"{field}.holes must be a list")
        holes = tuple(
            ThroughHole.from_dict(value, field=f"{field}.holes[{index}]")
            for index, value in enumerate(holes_raw)
        )
        if len({item.hole_id for item in holes}) != len(holes):
            raise InputError(f"{field}.hole identifiers must be unique")
        part = cls(
            schema_version=schema,
            part_id=part_id,
            revision=_string(raw, "revision", field),
            title=_string(raw, "title", field),
            length=_quantity(stock["length"], f"{field}.stock.length", positive=True),
            width=_quantity(stock["width"], f"{field}.stock.width", positive=True),
            thickness=_quantity(
                stock["thickness"], f"{field}.stock.thickness", positive=True
            ),
            holes=holes,
            material=MaterialRecord.from_dict(raw.get("material"), field=f"{field}.material"),
            manufacturing=ManufacturingRules.from_dict(
                raw.get("manufacturing"), field=f"{field}.manufacturing"
            ),
        )
        part.validate_constraints()
        return part

    @property
    def part_digest(self) -> str:
        return digest(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "part_id": self.part_id,
            "revision": self.revision,
            "title": self.title,
            "stock": {
                "length": self.length.as_dict(),
                "width": self.width.as_dict(),
                "thickness": self.thickness.as_dict(),
            },
            "holes": [item.as_dict() for item in self.holes],
            "material": self.material.as_dict(),
            "manufacturing": self.manufacturing.as_dict(),
        }

    def validate_constraints(self) -> None:
        half_length = self.length.si_value / 2
        half_width = self.width.si_value / 2
        edge = self.manufacturing.minimum_edge_distance.si_value
        web = self.manufacturing.minimum_web_thickness.si_value
        for hole in self.holes:
            radius_with_tolerance = (
                hole.diameter.si_value + hole.diameter_tolerance.si_value
            ) / 2 + hole.position_tolerance.si_value
            if abs(hole.x.si_value) + radius_with_tolerance + edge > half_length:
                raise InputError(
                    f"hole {hole.hole_id!r} violates minimum edge distance on the x axis"
                )
            if abs(hole.y.si_value) + radius_with_tolerance + edge > half_width:
                raise InputError(
                    f"hole {hole.hole_id!r} violates minimum edge distance on the y axis"
                )
        for index, first in enumerate(self.holes):
            for second in self.holes[index + 1 :]:
                dx = first.x.si_value - second.x.si_value
                dy = first.y.si_value - second.y.si_value
                center_distance_squared = dx * dx + dy * dy
                clearance = (
                    first.diameter.si_value
                    + first.diameter_tolerance.si_value
                    + second.diameter.si_value
                    + second.diameter_tolerance.si_value
                ) / 2 + first.position_tolerance.si_value + second.position_tolerance.si_value + web
                if center_distance_squared < clearance * clearance:
                    raise InputError(
                        f"holes {first.hole_id!r} and {second.hole_id!r} violate "
                        "minimum web thickness"
                    )

    def analytical_properties(self) -> dict[str, str]:
        gross_volume = self.length.si_value * self.width.si_value * self.thickness.si_value
        removed_volume = sum(
            (
                _PI
                * (hole.diameter.si_value / 2)
                * (hole.diameter.si_value / 2)
                * self.thickness.si_value
            )
            for hole in self.holes
        )
        net_volume = gross_volume - removed_volume
        density = self.material.properties["density"].quantity.si_value
        return {
            "gross_volume_m3": decimal_text(gross_volume),
            "removed_volume_m3": decimal_text(removed_volume),
            "net_volume_m3": decimal_text(net_volume),
            "mass_kg": decimal_text(net_volume * density),
        }


def load_part(path: str | Path) -> PrismaticPart:
    source = Path(path)
    try:
        return PrismaticPart.from_dict(loads_strict(source.read_bytes()))
    except OSError as exc:
        raise InputError(f"cannot read prismatic part {source}: {exc}") from exc


def compile_part(part: PrismaticPart, output_directory: str | Path) -> dict[str, Any]:
    """Compile one validated feature model through build123d/Open CASCADE."""

    try:
        from build123d import export_step, export_stl
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc

    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    shape = build_part_shape(part)

    step_path = destination / f"{part.part_id}.step"
    stl_path = destination / f"{part.part_id}.stl"
    svg_path = destination / f"{part.part_id}.svg"
    if not export_step(shape, step_path, timestamp="2000-01-01T00:00:00"):
        raise ExecutionError("Open CASCADE failed to export STEP geometry")
    if not export_stl(shape, stl_path, tolerance=0.01, angular_tolerance=0.1):
        raise ExecutionError("Open CASCADE failed to export STL geometry")
    svg_path.write_text(_top_view_svg(part), encoding="utf-8", newline="\n")
    artifacts = [
        artifact_descriptor(step_path, "model/step", "exact_geometry"),
        artifact_descriptor(stl_path, "model/stl", "mesh"),
        artifact_descriptor(svg_path, "image/svg+xml", "drawing"),
    ]
    kernel = _kernel_report(part, shape)
    content = {
        "schema_version": CAD_BUNDLE_SCHEMA,
        "qualification": "unqualified_demonstration",
        "part_digest": part.part_digest,
        "material_digest": part.material.material_digest,
        "part": part.as_dict(),
        "analytical_properties": part.analytical_properties(),
        "kernel": kernel,
        "checks": _cad_checks(),
        "artifacts": artifacts,
    }
    bundle = {"digest": digest(content), "content": content}
    bundle_path = destination / f"{part.part_id}.cad-bundle.json"
    bundle_path.write_text(dumps_pretty(bundle), encoding="utf-8", newline="\n")
    return bundle


def build_part_shape(part: PrismaticPart) -> Any:
    """Build an in-memory exact shape for integration backends."""

    try:
        from build123d import Align, Box, Cylinder, Pos
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc

    length_mm = float(part.length.to("mm").value)
    width_mm = float(part.width.to("mm").value)
    thickness_mm = float(part.thickness.to("mm").value)
    shape = Box(
        length_mm,
        width_mm,
        thickness_mm,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    for hole in part.holes:
        cutter = Pos(
            float(hole.x.to("mm").value), float(hole.y.to("mm").value), 0
        ) * Cylinder(
            float(hole.diameter.to("mm").value / 2),
            thickness_mm,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        shape -= cutter
    shape_valid = shape.is_valid
    if callable(shape_valid):
        shape_valid = shape_valid()
    if not shape_valid:
        raise ExecutionError("Open CASCADE produced an invalid boundary representation")
    return shape


def verify_cad_bundle(bundle_path: str | Path) -> dict[str, str]:
    path = Path(bundle_path)
    try:
        bundle = loads_strict(path.read_bytes())
    except OSError as exc:
        raise InputError(f"cannot read CAD bundle {path}: {exc}") from exc
    if not isinstance(bundle, dict) or set(bundle) != {"digest", "content"}:
        raise IntegrityError("CAD bundle must contain exactly digest and content")
    content = bundle.get("content")
    if not isinstance(content, dict) or digest(content) != bundle.get("digest"):
        raise IntegrityError("CAD bundle digest mismatch")
    if content.get("schema_version") != CAD_BUNDLE_SCHEMA:
        raise IntegrityError("unsupported CAD bundle schema")
    required_content = {
        "schema_version",
        "qualification",
        "part_digest",
        "material_digest",
        "part",
        "analytical_properties",
        "kernel",
        "checks",
        "artifacts",
    }
    if set(content) != required_content:
        raise IntegrityError("CAD bundle content has unsupported or missing fields")
    if content.get("qualification") != "unqualified_demonstration":
        raise IntegrityError("CAD bundle qualification is unsupported")
    part = PrismaticPart.from_dict(content.get("part"))
    if part.part_digest != content.get("part_digest"):
        raise IntegrityError("embedded part does not match its declared digest")
    if part.material.material_digest != content.get("material_digest"):
        raise IntegrityError("embedded material does not match its declared digest")
    if part.analytical_properties() != content.get("analytical_properties"):
        raise IntegrityError("CAD analytical properties do not reproduce")
    expected_kernel = _kernel_report(part, build_part_shape(part))
    if content.get("kernel") != expected_kernel:
        raise IntegrityError("CAD kernel analysis does not reproduce")
    if content.get("checks") != _cad_checks():
        raise IntegrityError("CAD checks are false, incomplete, or unsupported")
    verify_artifacts(
        path.parent,
        content.get("artifacts"),
        {
            f"{part.part_id}.step": ("model/step", "exact_geometry"),
            f"{part.part_id}.stl": ("model/stl", "mesh"),
            f"{part.part_id}.svg": ("image/svg+xml", "drawing"),
        },
    )
    return {
        "status": "verified",
        "bundle_digest": bundle["digest"],
        "part_digest": part.part_digest,
    }


def _kernel_report(part: PrismaticPart, shape: Any) -> dict[str, Any]:
    expected_mm3 = Decimal(part.analytical_properties()["net_volume_m3"]) * Decimal(
        1000000000
    )
    kernel_mm3 = Decimal(str(shape.volume))
    relative_error = (
        abs(kernel_mm3 - expected_mm3) / expected_mm3 if expected_mm3 else Decimal(0)
    )
    if relative_error > Decimal("0.00000001"):
        raise ExecutionError(
            "kernel volume does not agree with the independently calculated volume"
        )
    return {
        "backend": "build123d-opencascade",
        "build123d_version": package_version("build123d"),
        "opencascade_distribution_version": package_version("cadquery-ocp"),
        "shape_valid": True,
        "volume_mm3": decimal_text(kernel_mm3),
        "relative_volume_error": decimal_text(relative_error),
    }


def _cad_checks() -> list[dict[str, str]]:
    return [
        {"id": "CAD-SCHEMA", "status": "passed"},
        {"id": "CAD-EDGE-DISTANCE", "status": "passed"},
        {"id": "CAD-WEB-THICKNESS", "status": "passed"},
        {"id": "CAD-BREP-VALIDITY", "status": "passed"},
        {"id": "CAD-INDEPENDENT-VOLUME", "status": "passed"},
    ]


def _top_view_svg(part: PrismaticPart) -> str:
    length = part.length.to("mm").value
    width = part.width.to("mm").value
    margin = Decimal(12)
    view_width = length + margin * 2
    view_height = width + margin * 2
    circles = []
    for hole in part.holes:
        x = margin + length / 2 + hole.x.to("mm").value
        y = margin + width / 2 - hole.y.to("mm").value
        circles.append(
            f'  <circle cx="{decimal_text(x)}" cy="{decimal_text(y)}" '
            f'r="{decimal_text(hole.diameter.to("mm").value / 2)}" />'
        )
    circle_text = "\n".join(circles)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{decimal_text(view_width)}mm" '
        f'height="{decimal_text(view_height)}mm" viewBox="0 0 {decimal_text(view_width)} '
        f'{decimal_text(view_height)}">\n'
        '  <g fill="none" stroke="#151515" stroke-width="0.5">\n'
        f'  <rect x="{decimal_text(margin)}" y="{decimal_text(margin)}" '
        f'width="{decimal_text(length)}" height="{decimal_text(width)}" />\n'
        f'{circle_text}\n'
        '  </g>\n'
        f'  <text x="{decimal_text(margin)}" y="8" font-family="monospace" '
        f'font-size="4">{part.part_id} · TOP · mm</text>\n'
        '</svg>\n'
    )
