from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import localcontext
from typing import Any

from .errors import InputError
from .evidence import (
    Claim,
    DerivedClaim,
    EvidenceRef,
    require_zoned_timestamp,
    validate_claim_evidence,
)
from .units import Quantity

REQUIRED_CLAIMS = {
    "length": "length",
    "width": "length",
    "thickness": "length",
    "elastic_modulus": "pressure",
    "yield_strength": "pressure",
    "tensile_load": "force",
}


@dataclass(frozen=True)
class AxialCase:
    schema_version: str
    design_id: str
    title: str
    effective_at: str
    evidence: Mapping[str, EvidenceRef]
    claims: Mapping[str, Claim]

    @classmethod
    def from_dict(cls, raw: Any) -> AxialCase:
        if not isinstance(raw, dict):
            raise InputError("design input must be an object")
        if raw.get("schema_version") != "contrainte.axial-case/0.1":
            raise InputError("schema_version must be 'contrainte.axial-case/0.1'")
        for field in ("design_id", "title", "effective_at"):
            if not isinstance(raw.get(field), str) or not raw[field]:
                raise InputError(f"{field} must be a non-empty string")
        require_zoned_timestamp(raw["effective_at"], "effective_at")

        raw_evidence = raw.get("evidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise InputError("evidence must be a non-empty list")
        evidence: dict[str, EvidenceRef] = {}
        for index, item in enumerate(raw_evidence):
            parsed = EvidenceRef.from_dict(item, field=f"evidence[{index}]")
            if parsed.evidence_id in evidence:
                raise InputError(f"duplicate evidence identifier: {parsed.evidence_id}")
            evidence[parsed.evidence_id] = parsed

        raw_claims = raw.get("claims")
        if not isinstance(raw_claims, dict):
            raise InputError("claims must be an object keyed by property name")
        if set(raw_claims) != set(REQUIRED_CLAIMS):
            missing = sorted(set(REQUIRED_CLAIMS) - set(raw_claims))
            extra = sorted(set(raw_claims) - set(REQUIRED_CLAIMS))
            details = []
            if missing:
                details.append(f"missing {missing}")
            if extra:
                details.append(f"unexpected {extra}")
            raise InputError(
                f"claims do not match the axial schema: {'; '.join(details)}"
            )
        claims = {
            name: Claim.from_dict(item, field=f"claims.{name}")
            for name, item in raw_claims.items()
        }
        validate_claim_evidence(claims, evidence)
        for name, expected_kind in REQUIRED_CLAIMS.items():
            claim = claims[name]
            if claim.quantity.kind != expected_kind:
                raise InputError(
                    f"claim {name!r} must have quantity kind {expected_kind!r}, "
                    f"not {claim.quantity.kind!r}"
                )
            claim.quantity.require_positive(name)

        return cls(
            schema_version=raw["schema_version"],
            design_id=raw["design_id"],
            title=raw["title"],
            effective_at=raw["effective_at"],
            evidence=evidence,
            claims=claims,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "design_id": self.design_id,
            "title": self.title,
            "effective_at": self.effective_at,
            "evidence": [self.evidence[key].as_dict() for key in sorted(self.evidence)],
            "claims": {key: self.claims[key].as_dict() for key in sorted(self.claims)},
        }


@dataclass(frozen=True)
class AxialResult:
    solver_id: str
    solver_version: str
    assumptions: tuple[str, ...]
    derived_claims: tuple[DerivedClaim, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "solver": {"id": self.solver_id, "version": self.solver_version},
            "assumptions": list(self.assumptions),
            "derived_claims": [claim.as_dict() for claim in self.derived_claims],
        }


def solve_axial_case(case: AxialCase) -> AxialResult:
    claims = case.claims
    with localcontext() as context:
        context.prec = 40
        length = claims["length"].quantity.si_value
        width = claims["width"].quantity.si_value
        thickness = claims["thickness"].quantity.si_value
        elastic_modulus = claims["elastic_modulus"].quantity.si_value
        yield_strength = claims["yield_strength"].quantity.si_value
        load = claims["tensile_load"].quantity.si_value

        area = width * thickness
        stress = load / area
        strain = stress / elastic_modulus
        displacement = strain * length
        safety_factor = yield_strength / stress

    member = case.design_id
    derived = (
        DerivedClaim(
            "CLM-AREA",
            member,
            "cross_sectional_area",
            Quantity.si(area, "area"),
            (claims["width"].claim_id, claims["thickness"].claim_id),
            "A = width × thickness",
        ),
        DerivedClaim(
            "CLM-STRESS",
            member,
            "axial_stress",
            Quantity.si(stress, "pressure"),
            (claims["tensile_load"].claim_id, "CLM-AREA"),
            "σ = F / A",
        ),
        DerivedClaim(
            "CLM-STRAIN",
            member,
            "axial_strain",
            Quantity.si(strain, "dimensionless"),
            ("CLM-STRESS", claims["elastic_modulus"].claim_id),
            "ε = σ / E",
        ),
        DerivedClaim(
            "CLM-DISPLACEMENT",
            member,
            "axial_displacement",
            Quantity.si(displacement, "length"),
            ("CLM-STRAIN", claims["length"].claim_id),
            "δ = ε × L",
        ),
        DerivedClaim(
            "CLM-YIELD-SAFETY-FACTOR",
            member,
            "yield_safety_factor",
            Quantity.si(safety_factor, "dimensionless"),
            (claims["yield_strength"].claim_id, "CLM-STRESS"),
            "n_y = S_y / σ",
        ),
    )
    assumptions = (
        "The member is straight and prismatic.",
        "The tensile load is centered and purely axial.",
        "Stress is uniform over the cross-section.",
        "Material response is isotropic, linear elastic, and small strain.",
        "Stress concentrations, joints, defects, residual stress, fatigue, and thermal effects are excluded.",
        "The calculation is a screening demonstration, not a general or qualified structural analysis.",
    )
    return AxialResult(
        solver_id="contrainte.analytical.axial-tension",
        solver_version="0.1.0",
        assumptions=assumptions,
        derived_claims=derived,
    )
