from __future__ import annotations

import copy
import hashlib
import itertools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .cad import PrismaticPart, build_part_shape
from .canonical import decimal_text, digest, dumps_pretty, loads_strict
from .errors import ExecutionError, InputError, IntegrityError
from .geometry import (
    RigidTransform,
    kernel_measurement,
    normalize_step_occurrence_identifiers,
)
from .units import Quantity

ASSEMBLY_SCHEMA = "contrainte.assembly/0.1"
ASSEMBLY_BUNDLE_SCHEMA = "contrainte.assembly-bundle/0.1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_INTERFERENCE_TOLERANCE_MM3 = Decimal("0.000001")
_DISTANCE_TOLERANCE_MM = Decimal("0.000001")


def _string(raw: Mapping[str, Any], name: str, field: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise InputError(f"{field}.{name} must be a non-empty string")
    return value


def _length(raw: Any, field: str, *, non_negative: bool = False) -> Quantity:
    value = Quantity.from_dict(raw, field=field)
    if value.kind != "length":
        raise InputError(f"{field} must have kind 'length'")
    if non_negative and value.value < 0:
        raise InputError(f"{field} must be non-negative")
    return value


@dataclass(frozen=True)
class PartOccurrence:
    occurrence_id: str
    title: str
    part_id: str
    transform: RigidTransform

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> PartOccurrence:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        allowed = {"occurrence_id", "title", "part_id", "transform"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
        occurrence_id = _string(raw, "occurrence_id", field)
        if not _SAFE_ID.fullmatch(occurrence_id):
            raise InputError(f"{field}.occurrence_id contains unsupported characters")
        return cls(
            occurrence_id=occurrence_id,
            title=_string(raw, "title", field),
            part_id=_string(raw, "part_id", field),
            transform=RigidTransform.from_dict(
                raw.get("transform"), field=f"{field}.transform"
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "occurrence_id": self.occurrence_id,
            "title": self.title,
            "part_id": self.part_id,
            "transform": self.transform.as_dict(),
        }


@dataclass(frozen=True)
class PairClearanceRule:
    first_occurrence_id: str
    second_occurrence_id: str
    minimum_clearance: Quantity

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> PairClearanceRule:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        allowed = {
            "first_occurrence_id",
            "second_occurrence_id",
            "minimum_clearance",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
        first = _string(raw, "first_occurrence_id", field)
        second = _string(raw, "second_occurrence_id", field)
        if first >= second:
            raise InputError(
                f"{field} occurrence identifiers must be in ascending lexical order"
            )
        return cls(
            first_occurrence_id=first,
            second_occurrence_id=second,
            minimum_clearance=_length(
                raw.get("minimum_clearance"),
                f"{field}.minimum_clearance",
                non_negative=True,
            ),
        )

    @property
    def pair(self) -> tuple[str, str]:
        return self.first_occurrence_id, self.second_occurrence_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "first_occurrence_id": self.first_occurrence_id,
            "second_occurrence_id": self.second_occurrence_id,
            "minimum_clearance": self.minimum_clearance.as_dict(),
        }


@dataclass(frozen=True)
class Assembly:
    schema_version: str
    assembly_id: str
    revision: str
    title: str
    parts: tuple[PrismaticPart, ...]
    occurrences: tuple[PartOccurrence, ...]
    default_minimum_clearance: Quantity
    pair_rules: tuple[PairClearanceRule, ...]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str = "assembly") -> Assembly:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        allowed = {
            "schema_version",
            "assembly_id",
            "revision",
            "title",
            "parts",
            "occurrences",
            "default_minimum_clearance",
            "pair_rules",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
        schema = _string(raw, "schema_version", field)
        if schema != ASSEMBLY_SCHEMA:
            raise InputError(f"unsupported assembly schema: {schema!r}")
        assembly_id = _string(raw, "assembly_id", field)
        if not _SAFE_ID.fullmatch(assembly_id):
            raise InputError(f"{field}.assembly_id contains unsupported characters")
        parts_raw = raw.get("parts")
        if not isinstance(parts_raw, list) or not parts_raw:
            raise InputError(f"{field}.parts must be a non-empty list")
        parts = tuple(
            PrismaticPart.from_dict(item, field=f"{field}.parts[{index}]")
            for index, item in enumerate(parts_raw)
        )
        part_ids = [item.part_id for item in parts]
        if len(part_ids) != len(set(part_ids)):
            raise InputError(f"{field}.part identifiers must be unique")
        occurrences_raw = raw.get("occurrences")
        if not isinstance(occurrences_raw, list) or not occurrences_raw:
            raise InputError(f"{field}.occurrences must be a non-empty list")
        occurrences = tuple(
            PartOccurrence.from_dict(item, field=f"{field}.occurrences[{index}]")
            for index, item in enumerate(occurrences_raw)
        )
        occurrence_ids = [item.occurrence_id for item in occurrences]
        if len(occurrence_ids) != len(set(occurrence_ids)):
            raise InputError(f"{field}.occurrence identifiers must be unique")
        missing_parts = sorted({item.part_id for item in occurrences} - set(part_ids))
        if missing_parts:
            raise InputError(
                f"{field}.occurrences reference unknown parts: {', '.join(missing_parts)}"
            )
        rules_raw = raw.get("pair_rules", [])
        if not isinstance(rules_raw, list):
            raise InputError(f"{field}.pair_rules must be a list")
        rules = tuple(
            PairClearanceRule.from_dict(item, field=f"{field}.pair_rules[{index}]")
            for index, item in enumerate(rules_raw)
        )
        pairs = [item.pair for item in rules]
        if len(pairs) != len(set(pairs)):
            raise InputError(f"{field}.pair rules must be unique")
        known_occurrences = set(occurrence_ids)
        unknown_occurrences = sorted(
            {
                occurrence_id
                for rule in rules
                for occurrence_id in rule.pair
                if occurrence_id not in known_occurrences
            }
        )
        if unknown_occurrences:
            raise InputError(
                f"{field}.pair rules reference unknown occurrences: "
                + ", ".join(unknown_occurrences)
            )
        return cls(
            schema_version=schema,
            assembly_id=assembly_id,
            revision=_string(raw, "revision", field),
            title=_string(raw, "title", field),
            parts=parts,
            occurrences=occurrences,
            default_minimum_clearance=_length(
                raw.get("default_minimum_clearance"),
                f"{field}.default_minimum_clearance",
                non_negative=True,
            ),
            pair_rules=rules,
        )

    @property
    def assembly_digest(self) -> str:
        return digest(self.as_dict())

    @property
    def part_index(self) -> Mapping[str, PrismaticPart]:
        return {item.part_id: item for item in self.parts}

    def clearance_for(self, first: str, second: str) -> Quantity:
        pair = tuple(sorted((first, second)))
        rule = next((item for item in self.pair_rules if item.pair == pair), None)
        return rule.minimum_clearance if rule else self.default_minimum_clearance

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "assembly_id": self.assembly_id,
            "revision": self.revision,
            "title": self.title,
            "parts": [item.as_dict() for item in self.parts],
            "occurrences": [item.as_dict() for item in self.occurrences],
            "default_minimum_clearance": self.default_minimum_clearance.as_dict(),
            "pair_rules": [item.as_dict() for item in self.pair_rules],
        }


def load_assembly(path: str | Path) -> Assembly:
    source = Path(path)
    try:
        return Assembly.from_dict(loads_strict(source.read_bytes()))
    except OSError as exc:
        raise InputError(f"cannot read assembly {source}: {exc}") from exc


def analyze_assembly(assembly: Assembly) -> tuple[dict[str, Any], Any]:
    try:
        from build123d import Compound, Location
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc

    base_shapes = {part.part_id: build_part_shape(part) for part in assembly.parts}
    placed: dict[str, Any] = {}
    for occurrence in assembly.occurrences:
        transform = occurrence.transform
        shape = copy.copy(base_shapes[occurrence.part_id])
        shape.label = occurrence.occurrence_id
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
        placed[occurrence.occurrence_id] = shape

    pair_results: list[dict[str, str]] = []
    failures: list[str] = []
    ordered = sorted(assembly.occurrences, key=lambda item: item.occurrence_id)
    for first, second in itertools.combinations(ordered, 2):
        first_shape = placed[first.occurrence_id]
        second_shape = placed[second.occurrence_id]
        raw_distance = Decimal(str(first_shape.distance_to(second_shape)))
        distance = kernel_measurement(raw_distance)
        intersection = first_shape & second_shape
        raw_interference_volume = sum(
            (Decimal(str(solid.volume)) for solid in intersection.solids()), Decimal(0)
        )
        interference_volume = kernel_measurement(raw_interference_volume)
        required = assembly.clearance_for(
            first.occurrence_id, second.occurrence_id
        ).to("mm").value
        if raw_interference_volume > _INTERFERENCE_TOLERANCE_MM3:
            status = "interference"
            failures.append(
                f"{first.occurrence_id}/{second.occurrence_id} interfere by "
                f"{decimal_text(interference_volume)} mm3"
            )
        elif raw_distance + _DISTANCE_TOLERANCE_MM < required:
            status = "clearance_violation"
            failures.append(
                f"{first.occurrence_id}/{second.occurrence_id} clearance "
                f"{decimal_text(distance)} mm is below {decimal_text(required)} mm"
            )
        else:
            status = "passed"
        pair_results.append(
            {
                "first_occurrence_id": first.occurrence_id,
                "second_occurrence_id": second.occurrence_id,
                "distance_mm": decimal_text(distance),
                "minimum_clearance_mm": decimal_text(required),
                "interference_volume_mm3": decimal_text(interference_volume),
                "status": status,
            }
        )
    compound = Compound(
        label=assembly.assembly_id,
        children=[placed[item.occurrence_id] for item in assembly.occurrences],
    )
    valid = compound.is_valid
    if callable(valid):
        valid = valid()
    if not valid:
        failures.append("assembly compound is not a valid boundary representation")
    total_mass = sum(
        (
            Decimal(assembly.part_index[item.part_id].analytical_properties()["mass_kg"])
            for item in assembly.occurrences
        ),
        Decimal(0),
    )
    bounds = compound.bounding_box().size
    analysis = {
        "status": "passed" if not failures else "failed",
        "occurrence_count": len(assembly.occurrences),
        "pair_count": len(pair_results),
        "total_mass_kg": decimal_text(total_mass),
        "bounding_box_mm": {
            "x": decimal_text(kernel_measurement(bounds.X)),
            "y": decimal_text(kernel_measurement(bounds.Y)),
            "z": decimal_text(kernel_measurement(bounds.Z)),
        },
        "pair_results": pair_results,
        "failures": failures,
    }
    return analysis, compound


def compile_assembly(
    assembly: Assembly, output_directory: str | Path
) -> dict[str, Any]:
    try:
        from build123d import export_step, export_stl
    except ImportError as exc:
        raise ExecutionError(
            "the CAD backend is not installed; install Contrainte with the 'cad' extra"
        ) from exc
    analysis, compound = analyze_assembly(assembly)
    if analysis["status"] != "passed":
        raise ExecutionError(
            "assembly verification failed: " + "; ".join(analysis["failures"])
        )
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    step_path = destination / f"{assembly.assembly_id}.step"
    stl_path = destination / f"{assembly.assembly_id}.stl"
    if not export_step(compound, step_path, timestamp="2000-01-01T00:00:00"):
        raise ExecutionError("Open CASCADE failed to export the assembly STEP file")
    normalize_step_occurrence_identifiers(step_path)
    if not export_stl(compound, stl_path, tolerance=0.01, angular_tolerance=0.1):
        raise ExecutionError("Open CASCADE failed to export the assembly STL file")
    artifacts = [
        _artifact(step_path, "model/step", "exact_assembly"),
        _artifact(stl_path, "model/stl", "assembly_mesh"),
    ]
    content = {
        "schema_version": ASSEMBLY_BUNDLE_SCHEMA,
        "qualification": "unqualified_demonstration",
        "assembly_digest": assembly.assembly_digest,
        "assembly": assembly.as_dict(),
        "analysis": analysis,
        "checks": [
            {"id": "ASSEMBLY-SCHEMA", "status": "passed"},
            {"id": "ASSEMBLY-BREP-VALIDITY", "status": "passed"},
            {"id": "ASSEMBLY-PAIR-INTERFERENCE", "status": "passed"},
            {"id": "ASSEMBLY-PAIR-CLEARANCE", "status": "passed"},
        ],
        "artifacts": artifacts,
    }
    bundle = {"digest": digest(content), "content": content}
    bundle_path = destination / f"{assembly.assembly_id}.assembly-bundle.json"
    bundle_path.write_text(dumps_pretty(bundle), encoding="utf-8", newline="\n")
    return bundle


def verify_assembly_bundle(bundle_path: str | Path) -> dict[str, str]:
    path = Path(bundle_path)
    try:
        bundle = loads_strict(path.read_bytes())
    except OSError as exc:
        raise InputError(f"cannot read assembly bundle {path}: {exc}") from exc
    if not isinstance(bundle, dict) or set(bundle) != {"digest", "content"}:
        raise IntegrityError("assembly bundle must contain exactly digest and content")
    content = bundle.get("content")
    if not isinstance(content, dict) or digest(content) != bundle.get("digest"):
        raise IntegrityError("assembly bundle digest mismatch")
    if content.get("schema_version") != ASSEMBLY_BUNDLE_SCHEMA:
        raise IntegrityError("unsupported assembly bundle schema")
    assembly = Assembly.from_dict(content.get("assembly"))
    if assembly.assembly_digest != content.get("assembly_digest"):
        raise IntegrityError("embedded assembly does not match its declared digest")
    analysis, _ = analyze_assembly(assembly)
    if analysis != content.get("analysis"):
        raise IntegrityError("assembly analysis does not reproduce")
    if analysis["status"] != "passed":
        raise IntegrityError("embedded assembly no longer passes interference checks")
    for artifact in content.get("artifacts", []):
        if not isinstance(artifact, dict):
            raise IntegrityError("assembly artifact descriptor must be an object")
        artifact_path = path.parent / artifact.get("path", "")
        if not artifact_path.is_file():
            raise IntegrityError(f"assembly artifact is missing: {artifact_path.name}")
        if _file_digest(artifact_path) != artifact.get("digest"):
            raise IntegrityError(
                f"assembly artifact digest mismatch: {artifact_path.name}"
            )
    return {
        "status": "verified",
        "bundle_digest": bundle["digest"],
        "assembly_digest": assembly.assembly_digest,
    }


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
