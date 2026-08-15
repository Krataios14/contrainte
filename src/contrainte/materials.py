from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .canonical import digest
from .errors import InputError
from .evidence import Claim, EvidenceRef, validate_claim_evidence

MATERIAL_SCHEMA = "contrainte.material-record/0.1"
_REQUIRED_PROPERTIES = {
    "density": "density",
    "elastic_modulus": "pressure",
    "yield_strength": "pressure",
    "poisson_ratio": "dimensionless",
}


def _string(raw: Mapping[str, Any], name: str, field: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise InputError(f"{field}.{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class MaterialRecord:
    schema_version: str
    material_id: str
    revision: str
    designation: str
    standard: str
    evidence: tuple[EvidenceRef, ...]
    properties: Mapping[str, Claim]
    applicability: Mapping[str, str]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str = "material") -> MaterialRecord:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        allowed = {
            "schema_version",
            "material_id",
            "revision",
            "designation",
            "standard",
            "evidence",
            "properties",
            "applicability",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")
        schema = _string(raw, "schema_version", field)
        if schema != MATERIAL_SCHEMA:
            raise InputError(f"unsupported material-record schema: {schema!r}")
        evidence_raw = raw.get("evidence")
        if not isinstance(evidence_raw, list) or not evidence_raw:
            raise InputError(f"{field}.evidence must be a non-empty list")
        evidence = tuple(
            EvidenceRef.from_dict(item, field=f"{field}.evidence[{index}]")
            for index, item in enumerate(evidence_raw)
        )
        evidence_by_id = {item.evidence_id: item for item in evidence}
        if len(evidence_by_id) != len(evidence):
            raise InputError(f"{field}.evidence identifiers must be unique")
        properties_raw = raw.get("properties")
        if not isinstance(properties_raw, dict):
            raise InputError(f"{field}.properties must be an object")
        properties = {
            name: Claim.from_dict(value, field=f"{field}.properties.{name}")
            for name, value in properties_raw.items()
        }
        missing = sorted(set(_REQUIRED_PROPERTIES) - set(properties))
        if missing:
            raise InputError(
                f"{field}.properties is missing required properties: {', '.join(missing)}"
            )
        validate_claim_evidence(properties, evidence_by_id)
        for name, expected_kind in _REQUIRED_PROPERTIES.items():
            if properties[name].quantity.kind != expected_kind:
                raise InputError(
                    f"{field}.properties.{name} must have kind {expected_kind!r}"
                )
        poisson = properties["poisson_ratio"].quantity.si_value
        if not 0 < poisson < 1:
            raise InputError(f"{field}.properties.poisson_ratio must be between zero and one")
        for name in ("density", "elastic_modulus", "yield_strength"):
            properties[name].quantity.require_positive(f"{field}.properties.{name}.quantity")
        applicability = raw.get("applicability", {})
        if not isinstance(applicability, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in applicability.items()
        ):
            raise InputError(f"{field}.applicability must map strings to strings")
        return cls(
            schema_version=schema,
            material_id=_string(raw, "material_id", field),
            revision=_string(raw, "revision", field),
            designation=_string(raw, "designation", field),
            standard=_string(raw, "standard", field),
            evidence=evidence,
            properties=properties,
            applicability=dict(applicability),
        )

    @property
    def material_digest(self) -> str:
        return digest(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "material_id": self.material_id,
            "revision": self.revision,
            "designation": self.designation,
            "standard": self.standard,
            "evidence": [item.as_dict() for item in self.evidence],
            "properties": {
                name: value.as_dict() for name, value in sorted(self.properties.items())
            },
            "applicability": dict(self.applicability),
        }
