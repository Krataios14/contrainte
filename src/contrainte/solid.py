from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .canonical import decimal_text, digest, dumps_pretty, loads_strict
from .errors import ExecutionError, InputError, IntegrityError
from .geometry import (
    RigidTransform,
    kernel_measurement,
    normalize_step_occurrence_identifiers,
)
from .materials import MaterialRecord
from .units import Quantity

SOLID_PROGRAM_SCHEMA = "contrainte.solid-program/0.1"
SOLID_BUNDLE_SCHEMA = "contrainte.solid-bundle/0.1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_OPERATIONS = {"box", "cylinder", "sphere", "union", "cut", "intersection"}
_PARAMETERS = {
    "box": ("x", "y", "z"),
    "cylinder": ("radius", "height"),
    "sphere": ("radius",),
    "union": (),
    "cut": (),
    "intersection": (),
}


def _string(raw: Mapping[str, Any], name: str, field: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise InputError(f"{field}.{name} must be a non-empty string")
    return value


def _length(raw: Any, field: str, *, positive: bool = False) -> Quantity:
    value = Quantity.from_dict(raw, field=field)
    if value.kind != "length":
        raise InputError(f"{field} must have kind 'length'")
    if positive:
        value.require_positive(field)
    return value


def _mass(raw: Any, field: str) -> Quantity:
    value = Quantity.from_dict(raw, field=field)
    if value.kind != "mass":
        raise InputError(f"{field} must have kind 'mass'")
    value.require_positive(field)
    return value


@dataclass(frozen=True)
class SolidNode:
    node_id: str
    operation: str
    inputs: tuple[str, ...]
    parameters: Mapping[str, Quantity]
    transform: RigidTransform

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> SolidNode:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        allowed = {"node_id", "operation", "inputs", "parameters", "transform"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
        node_id = _string(raw, "node_id", field)
        if not _SAFE_ID.fullmatch(node_id):
            raise InputError(f"{field}.node_id contains unsupported characters")
        operation = _string(raw, "operation", field)
        if operation not in _OPERATIONS:
            raise InputError(f"{field}.operation is unsupported: {operation!r}")
        inputs_raw = raw.get("inputs")
        if not isinstance(inputs_raw, list) or not all(
            isinstance(item, str) and item for item in inputs_raw
        ):
            raise InputError(f"{field}.inputs must be a list of identifiers")
        inputs = tuple(inputs_raw)
        if len(inputs) != len(set(inputs)):
            raise InputError(f"{field}.inputs must be unique")
        if operation in {"box", "cylinder", "sphere"} and inputs:
            raise InputError(f"{field}.{operation} must not have inputs")
        if operation in {"union", "intersection"}:
            if len(inputs) < 2:
                raise InputError(f"{field}.{operation} requires at least two inputs")
            if inputs != tuple(sorted(inputs)):
                raise InputError(
                    f"{field}.{operation} inputs must be in ascending lexical order"
                )
        if operation == "cut":
            if len(inputs) < 2:
                raise InputError(f"{field}.cut requires a base followed by one or more tools")
            if inputs[1:] != tuple(sorted(inputs[1:])):
                raise InputError(f"{field}.cut tools must be in ascending lexical order")
        parameters_raw = raw.get("parameters")
        expected = set(_PARAMETERS[operation])
        if not isinstance(parameters_raw, dict) or set(parameters_raw) != expected:
            rendered = ", ".join(sorted(expected)) or "no fields"
            raise InputError(
                f"{field}.parameters for {operation!r} must contain exactly {rendered}"
            )
        parameters = {
            name: _length(
                parameters_raw[name], f"{field}.parameters.{name}", positive=True
            )
            for name in _PARAMETERS[operation]
        }
        transform_raw = raw.get("transform")
        transform = (
            RigidTransform.identity()
            if transform_raw is None
            else RigidTransform.from_dict(transform_raw, field=f"{field}.transform")
        )
        return cls(node_id, operation, inputs, parameters, transform)

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "operation": self.operation,
            "inputs": list(self.inputs),
            "parameters": {
                name: self.parameters[name].as_dict()
                for name in _PARAMETERS[self.operation]
            },
            "transform": self.transform.as_dict(),
        }


@dataclass(frozen=True)
class SolidManufacturing:
    process: str
    minimum_feature_size: Quantity

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> SolidManufacturing:
        if not isinstance(raw, dict) or set(raw) != {
            "process",
            "minimum_feature_size",
        }:
            raise InputError(
                f"{field} must contain exactly process and minimum_feature_size"
            )
        return cls(
            process=_string(raw, "process", field),
            minimum_feature_size=_length(
                raw.get("minimum_feature_size"),
                f"{field}.minimum_feature_size",
                positive=True,
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "process": self.process,
            "minimum_feature_size": self.minimum_feature_size.as_dict(),
        }


@dataclass(frozen=True)
class SolidLimits:
    maximum_mass: Quantity
    maximum_bounding_box: Mapping[str, Quantity]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> SolidLimits:
        if not isinstance(raw, dict) or set(raw) != {
            "maximum_mass",
            "maximum_bounding_box",
        }:
            raise InputError(
                f"{field} must contain exactly maximum_mass and maximum_bounding_box"
            )
        bounds = raw.get("maximum_bounding_box")
        if not isinstance(bounds, dict) or set(bounds) != {"x", "y", "z"}:
            raise InputError(f"{field}.maximum_bounding_box must contain x, y, and z")
        return cls(
            maximum_mass=_mass(raw.get("maximum_mass"), f"{field}.maximum_mass"),
            maximum_bounding_box={
                axis: _length(
                    bounds[axis],
                    f"{field}.maximum_bounding_box.{axis}",
                    positive=True,
                )
                for axis in ("x", "y", "z")
            },
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "maximum_mass": self.maximum_mass.as_dict(),
            "maximum_bounding_box": {
                axis: self.maximum_bounding_box[axis].as_dict()
                for axis in ("x", "y", "z")
            },
        }


@dataclass(frozen=True)
class SolidProgram:
    schema_version: str
    part_id: str
    revision: str
    title: str
    material: MaterialRecord
    manufacturing: SolidManufacturing
    limits: SolidLimits
    nodes: tuple[SolidNode, ...]
    output_node_id: str

    @classmethod
    def from_dict(cls, raw: Any, *, field: str = "solid_program") -> SolidProgram:
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
            "nodes",
            "output_node_id",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
        schema = _string(raw, "schema_version", field)
        if schema != SOLID_PROGRAM_SCHEMA:
            raise InputError(f"unsupported solid-program schema: {schema!r}")
        part_id = _string(raw, "part_id", field)
        if not _SAFE_ID.fullmatch(part_id):
            raise InputError(f"{field}.part_id contains unsupported characters")
        nodes_raw = raw.get("nodes")
        if not isinstance(nodes_raw, list) or not nodes_raw:
            raise InputError(f"{field}.nodes must be a non-empty list")
        nodes = tuple(
            SolidNode.from_dict(item, field=f"{field}.nodes[{index}]")
            for index, item in enumerate(nodes_raw)
        )
        node_ids = [node.node_id for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            raise InputError(f"{field}.node identifiers must be unique")
        output_node_id = _string(raw, "output_node_id", field)
        if output_node_id not in set(node_ids):
            raise InputError(f"{field}.output_node_id references an unknown node")
        known = set(node_ids)
        for node in nodes:
            missing = sorted(set(node.inputs) - known)
            if missing:
                raise InputError(
                    f"node {node.node_id!r} references unknown inputs: {', '.join(missing)}"
                )
            if node.node_id in node.inputs:
                raise InputError(f"node {node.node_id!r} cannot consume itself")
        program = cls(
            schema,
            part_id,
            _string(raw, "revision", field),
            _string(raw, "title", field),
            MaterialRecord.from_dict(raw.get("material"), field=f"{field}.material"),
            SolidManufacturing.from_dict(
                raw.get("manufacturing"), field=f"{field}.manufacturing"
            ),
            SolidLimits.from_dict(raw.get("limits"), field=f"{field}.limits"),
            nodes,
            output_node_id,
        )
        order = program.topological_order()
        unused = sorted(set(node_ids) - set(order))
        if unused:
            raise InputError(
                f"{field} contains nodes not used by the output: {', '.join(unused)}"
            )
        program.validate_feature_sizes()
        return program

    @property
    def program_digest(self) -> str:
        return digest(self.as_dict())

    @property
    def node_index(self) -> Mapping[str, SolidNode]:
        return {node.node_id: node for node in self.nodes}

    def topological_order(self) -> tuple[str, ...]:
        index = self.node_index
        temporary: set[str] = set()
        permanent: set[str] = set()
        order: list[str] = []

        def visit(node_id: str) -> None:
            if node_id in permanent:
                return
            if node_id in temporary:
                raise InputError(f"solid feature graph contains a cycle at {node_id!r}")
            temporary.add(node_id)
            for input_id in index[node_id].inputs:
                visit(input_id)
            temporary.remove(node_id)
            permanent.add(node_id)
            order.append(node_id)

        visit(self.output_node_id)
        return tuple(order)

    def validate_feature_sizes(self) -> None:
        minimum = self.manufacturing.minimum_feature_size.si_value
        for node in self.nodes:
            if node.operation == "box":
                dimensions = node.parameters.values()
            elif node.operation == "cylinder":
                dimensions = (
                    Quantity.si(node.parameters["radius"].si_value * 2, "length"),
                    node.parameters["height"],
                )
            elif node.operation == "sphere":
                dimensions = (
                    Quantity.si(node.parameters["radius"].si_value * 2, "length"),
                )
            else:
                continue
            if any(item.si_value < minimum for item in dimensions):
                raise InputError(
                    f"node {node.node_id!r} violates the minimum feature size"
                )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "part_id": self.part_id,
            "revision": self.revision,
            "title": self.title,
            "material": self.material.as_dict(),
            "manufacturing": self.manufacturing.as_dict(),
            "limits": self.limits.as_dict(),
            "nodes": [node.as_dict() for node in self.nodes],
            "output_node_id": self.output_node_id,
        }


def load_solid_program(path: str | Path) -> SolidProgram:
    source = Path(path)
    try:
        return SolidProgram.from_dict(loads_strict(source.read_bytes()))
    except OSError as exc:
        raise InputError(f"cannot read solid program {source}: {exc}") from exc


def analyze_solid_program(program: SolidProgram) -> tuple[dict[str, Any], Any]:
    shapes = _build_nodes(program)
    shape = shapes[program.output_node_id]
    solids = shape.solids()
    failures: list[str] = []
    if len(solids) != 1:
        failures.append(f"output contains {len(solids)} solids; exactly one is required")
    valid = shape.is_valid
    if callable(valid):
        valid = valid()
    if not valid:
        failures.append("output is not a valid boundary representation")
    raw_volume_mm3 = Decimal(str(shape.volume))
    volume_mm3 = kernel_measurement(raw_volume_mm3)
    density = program.material.properties["density"].quantity.si_value
    mass_kg = raw_volume_mm3 * Decimal("0.000000001") * density
    maximum_mass_kg = program.limits.maximum_mass.to("kg").value
    if mass_kg > maximum_mass_kg:
        failures.append(
            f"mass {decimal_text(kernel_measurement(mass_kg))} kg exceeds "
            f"{decimal_text(maximum_mass_kg)} kg"
        )
    bounds = shape.bounding_box().size
    bounding_box = {
        "x": kernel_measurement(bounds.X),
        "y": kernel_measurement(bounds.Y),
        "z": kernel_measurement(bounds.Z),
    }
    for axis in ("x", "y", "z"):
        limit = program.limits.maximum_bounding_box[axis].to("mm").value
        if bounding_box[axis] > limit:
            failures.append(
                f"bounding box {axis}={decimal_text(bounding_box[axis])} mm exceeds "
                f"{decimal_text(limit)} mm"
            )
    node_results = []
    for node_id in program.topological_order():
        node_shape = shapes[node_id]
        node_results.append(
            {
                "node_id": node_id,
                "operation": program.node_index[node_id].operation,
                "solid_count": len(node_shape.solids()),
                "volume_mm3": decimal_text(kernel_measurement(node_shape.volume)),
            }
        )
    return (
        {
            "status": "passed" if not failures else "failed",
            "root_node_id": program.output_node_id,
            "node_count": len(program.nodes),
            "solid_count": len(solids),
            "volume_mm3": decimal_text(volume_mm3),
            "mass_kg": decimal_text(kernel_measurement(mass_kg)),
            "maximum_mass_kg": decimal_text(maximum_mass_kg),
            "bounding_box_mm": {
                axis: decimal_text(bounding_box[axis]) for axis in ("x", "y", "z")
            },
            "maximum_bounding_box_mm": {
                axis: decimal_text(
                    program.limits.maximum_bounding_box[axis].to("mm").value
                )
                for axis in ("x", "y", "z")
            },
            "node_results": node_results,
            "failures": failures,
        },
        shape,
    )


def compile_solid_program(
    program: SolidProgram, output_directory: str | Path
) -> dict[str, Any]:
    try:
        from build123d import export_step, export_stl
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc
    analysis, shape = analyze_solid_program(program)
    if analysis["status"] != "passed":
        raise ExecutionError(
            "solid-program verification failed: " + "; ".join(analysis["failures"])
        )
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    step_path = destination / f"{program.part_id}.step"
    stl_path = destination / f"{program.part_id}.stl"
    if not export_step(shape, step_path, timestamp="2000-01-01T00:00:00"):
        raise ExecutionError("Open CASCADE failed to export solid-program STEP geometry")
    normalize_step_occurrence_identifiers(step_path)
    if not export_stl(shape, stl_path, tolerance=0.01, angular_tolerance=0.1):
        raise ExecutionError("Open CASCADE failed to export solid-program STL geometry")
    artifacts = [
        _artifact(step_path, "model/step", "exact_geometry"),
        _artifact(stl_path, "model/stl", "visualization_mesh"),
    ]
    content = {
        "schema_version": SOLID_BUNDLE_SCHEMA,
        "qualification": "unqualified_demonstration",
        "program_digest": program.program_digest,
        "material_digest": program.material.material_digest,
        "program": program.as_dict(),
        "analysis": analysis,
        "kernel": {
            "backend": "build123d-opencascade",
            "build123d_version": _package_version("build123d"),
            "opencascade_distribution_version": _package_version("cadquery-ocp"),
        },
        "checks": [
            {"id": "SOLID-SCHEMA", "status": "passed"},
            {"id": "SOLID-FEATURE-DAG", "status": "passed"},
            {"id": "SOLID-MINIMUM-FEATURE", "status": "passed"},
            {"id": "SOLID-BREP-VALIDITY", "status": "passed"},
            {"id": "SOLID-SINGLE-BODY", "status": "passed"},
            {"id": "SOLID-MASS-LIMIT", "status": "passed"},
            {"id": "SOLID-ENVELOPE-LIMIT", "status": "passed"},
        ],
        "artifacts": artifacts,
    }
    bundle = {"digest": digest(content), "content": content}
    bundle_path = destination / f"{program.part_id}.solid-bundle.json"
    bundle_path.write_text(dumps_pretty(bundle), encoding="utf-8", newline="\n")
    return bundle


def verify_solid_bundle(bundle_path: str | Path) -> dict[str, str]:
    path = Path(bundle_path)
    try:
        bundle = loads_strict(path.read_bytes())
    except OSError as exc:
        raise InputError(f"cannot read solid bundle {path}: {exc}") from exc
    if not isinstance(bundle, dict) or set(bundle) != {"digest", "content"}:
        raise IntegrityError("solid bundle must contain exactly digest and content")
    content = bundle.get("content")
    if not isinstance(content, dict) or digest(content) != bundle.get("digest"):
        raise IntegrityError("solid bundle digest mismatch")
    if content.get("schema_version") != SOLID_BUNDLE_SCHEMA:
        raise IntegrityError("unsupported solid bundle schema")
    program = SolidProgram.from_dict(content.get("program"))
    if program.program_digest != content.get("program_digest"):
        raise IntegrityError("embedded solid program does not match its declared digest")
    analysis, _ = analyze_solid_program(program)
    if analysis != content.get("analysis"):
        raise IntegrityError("solid-program analysis does not reproduce")
    if analysis["status"] != "passed":
        raise IntegrityError("embedded solid program no longer passes its constraints")
    for artifact in content.get("artifacts", []):
        if not isinstance(artifact, dict):
            raise IntegrityError("solid artifact descriptor must be an object")
        artifact_path = path.parent / artifact.get("path", "")
        if not artifact_path.is_file():
            raise IntegrityError(f"solid artifact is missing: {artifact_path.name}")
        if _file_digest(artifact_path) != artifact.get("digest"):
            raise IntegrityError(f"solid artifact digest mismatch: {artifact_path.name}")
    return {
        "status": "verified",
        "bundle_digest": bundle["digest"],
        "program_digest": program.program_digest,
    }


def _build_nodes(program: SolidProgram) -> Mapping[str, Any]:
    try:
        from build123d import Align, Box, Cylinder, Location, Sphere
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc
    shapes: dict[str, Any] = {}
    for node_id in program.topological_order():
        node = program.node_index[node_id]
        if node.operation == "box":
            shape = Box(
                float(node.parameters["x"].to("mm").value),
                float(node.parameters["y"].to("mm").value),
                float(node.parameters["z"].to("mm").value),
                align=(Align.CENTER, Align.CENTER, Align.MIN),
            )
        elif node.operation == "cylinder":
            shape = Cylinder(
                float(node.parameters["radius"].to("mm").value),
                float(node.parameters["height"].to("mm").value),
                align=(Align.CENTER, Align.CENTER, Align.MIN),
            )
        elif node.operation == "sphere":
            shape = Sphere(float(node.parameters["radius"].to("mm").value))
        elif node.operation == "union":
            shape = copy.copy(shapes[node.inputs[0]])
            for input_id in node.inputs[1:]:
                shape = shape + copy.copy(shapes[input_id])
        elif node.operation == "cut":
            shape = copy.copy(shapes[node.inputs[0]])
            for input_id in node.inputs[1:]:
                shape = shape - copy.copy(shapes[input_id])
        elif node.operation == "intersection":
            shape = copy.copy(shapes[node.inputs[0]])
            for input_id in node.inputs[1:]:
                shape = shape & copy.copy(shapes[input_id])
        else:
            raise AssertionError(f"unhandled solid operation: {node.operation}")
        transform = node.transform
        shape.locate(
            Location(
                (
                    float(transform.x.to("mm").value),
                    float(transform.y.to("mm").value),
                    float(transform.z.to("mm").value),
                ),
                tuple(float(item) for item in transform.rotation_xyz_deg),
            )
        )
        valid = shape.is_valid
        if callable(valid):
            valid = valid()
        if not valid:
            raise ExecutionError(
                f"Open CASCADE produced an invalid shape at node {node_id!r}"
            )
        if Decimal(str(shape.volume)) <= Decimal("0.000000001"):
            raise ExecutionError(f"solid operation {node_id!r} produced an empty shape")
        shapes[node_id] = shape
    return shapes


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return f"sha256:{hasher.hexdigest()}"


def _artifact(path: Path, media_type: str, role: str) -> dict[str, Any]:
    return {
        "path": path.name,
        "media_type": media_type,
        "role": role,
        "digest": _file_digest(path),
        "size_bytes": path.stat().st_size,
    }


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"
