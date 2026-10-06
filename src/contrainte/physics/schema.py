"""JSON Schema (Draft 2020-12) exports for the physics intent, rule set and report.

The schemas describe structure only. Unit/kind compatibility, reference resolution, band
overlap, digests and pins are enforced by the Python parsers and cannot be expressed here.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from .dimensional import KINDS, UNITS
from .evaluate import REPORT_SCHEMA
from .groups import FORMS, GROUP_REGISTRY_VERSION
from .intent import (
    INTENT_SCHEMA,
    AssumptionStatus,
    Basis,
    BoundaryKind,
    Comparator,
    Coupling,
    Criticality,
    Disposition,
    Domain,
    FidelityLevel,
    GeometryRole,
    InitialRelevance,
    IntentEvidenceKind,
    LoadKind,
    MaterialModel,
    Mode,
    Nonlinearity,
    TimeCharacter,
    UncertaintyCategory,
    ValidationStatus,
)
from .rules import RULES_SCHEMA, AuthoringStatus, CitationKind, ModelForm

DIALECT = "https://json-schema.org/draft/2020-12/schema"
_COMMENT = (
    "Structural schema only. JSON Schema treats 1.0 as an integer and cannot see JSON lexical form; the "
    "strict loader rejects every float literal and the parser enforces units, references, bands, digests and pins."
)
_EXACT = r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]{1,2})?$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"
_TEXT = {
    "type": "string",
    "minLength": 1,
    "maxLength": 4000,
    "pattern": r"^\S([\s\S]*\S)?$",
}


def _id(*prefixes: str) -> dict[str, Any]:
    return {
        "type": "string",
        "pattern": rf"^({'|'.join(prefixes)})-[A-Z0-9]+(-[A-Z0-9]+)*$",
    }


def _enum(kind: type[Enum]) -> dict[str, Any]:
    return {"enum": [item.value for item in kind]}


def _closed(
    properties: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties) if required is None else required,
        "properties": properties,
    }


def _list(
    items: dict[str, Any], minimum: int = 0, unique: bool = False
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array", "items": items, "minItems": minimum}
    if unique:
        schema["uniqueItems"] = True
    return schema


_DIGEST_SCHEMA = {"type": "string", "pattern": _DIGEST}
_NULLABLE_DIGEST = {"oneOf": [{"type": "null"}, _DIGEST_SCHEMA]}
_QUANTITY = _closed(
    {
        "value": {"type": "string", "pattern": _EXACT},
        "unit": {"enum": sorted(UNITS)},
        "kind": {"enum": sorted(KINDS)},
    }
)
_GEOMETRY_REF = _id("FEA", "OCC", "SUR")
_EVIDENCE_REF = _id("EVD")
_GROUP_IDS = sorted({form.group_id for form in FORMS.values()})
_FORM_IDS = sorted(FORMS)


def intent_schema() -> dict[str, Any]:
    return {
        "$schema": DIALECT,
        "$id": "https://contrainte.dev/schemas/physics-intent-0.1.schema.json",
        "title": INTENT_SCHEMA,
        "$comment": _COMMENT,
        **_closed(
            {
                "schema_version": {"const": INTENT_SCHEMA},
                "intent_id": _id("PHY"),
                "revision": _TEXT,
                "title": _TEXT,
                "requested_mode": _enum(Mode),
                "criticality": _enum(Criticality),
                "decision": _closed(
                    {
                        "statement": _TEXT,
                        "owner": _TEXT,
                        "requirement_ids": _list(_id("REQ"), unique=True),
                    }
                ),
                "target_outputs": _list(
                    _closed(
                        {
                            "output_id": _id("QOI"),
                            "description": _TEXT,
                            "kind": {"enum": sorted(KINDS)},
                            "unit": {"enum": sorted(UNITS)},
                            "location_ref": _GEOMETRY_REF,
                        }
                    ),
                    1,
                ),
                "acceptance": {
                    "oneOf": [
                        _closed({"kind": {"const": "exploratory"}, "rationale": _TEXT}),
                        _closed(
                            {
                                "kind": {"const": "criteria"},
                                "criteria": _list(
                                    _closed(
                                        {
                                            "criterion_id": _id("ACC"),
                                            "output_id": _id("QOI"),
                                            "comparator": _enum(Comparator),
                                            "limit": _QUANTITY,
                                            "rationale": _TEXT,
                                        }
                                    ),
                                    1,
                                ),
                            }
                        ),
                    ]
                },
                "geometry": _closed(
                    {
                        "modeled": _list(
                            _closed(
                                {
                                    "ref_id": _GEOMETRY_REF,
                                    "role": _enum(GeometryRole),
                                    "description": _TEXT,
                                    "source_digest": _NULLABLE_DIGEST,
                                }
                            ),
                            1,
                        ),
                        "excluded": _list(
                            _closed({"ref_id": _GEOMETRY_REF, "reason": _TEXT})
                        ),
                        "simplifications": _list(
                            _closed(
                                {
                                    "simplification_id": _id("SIM"),
                                    "description": _TEXT,
                                    "rationale": _TEXT,
                                }
                            )
                        ),
                    }
                ),
                "domains": _list(_enum(Domain), 1, unique=True),
                "time": _closed(
                    {
                        "character": _enum(TimeCharacter),
                        "duration": {"oneOf": [{"type": "null"}, _QUANTITY]},
                        "fidelity": _closed(
                            {"level": _enum(FidelityLevel), "rationale": _TEXT}
                        ),
                    }
                ),
                "nonlinearities": _list(
                    _closed({"kind": _enum(Nonlinearity), "description": _TEXT}), 1
                ),
                "scales": _list(
                    _closed(
                        {
                            "scale_id": _id("SCL"),
                            "description": _TEXT,
                            "quantity": _QUANTITY,
                            "basis": _enum(Basis),
                            "evidence_ids": _list(_EVIDENCE_REF, unique=True),
                            "assumption_ids": _list(_id("ASM"), unique=True),
                        }
                    ),
                    1,
                ),
                "group_declarations": _list(
                    _closed(
                        {
                            "declaration_id": _id("GRP"),
                            "group_id": {"enum": _GROUP_IDS},
                            "form_id": {"enum": _FORM_IDS},
                            "bindings": {
                                "type": "object",
                                "minProperties": 1,
                                "additionalProperties": _id("SCL"),
                            },
                        }
                    )
                ),
                "candidate_model_forms": _list(_enum(ModelForm), 1, unique=True),
                "materials": _list(
                    _closed(
                        {
                            "material_ref": _id("MAT"),
                            "model_requirement": _enum(MaterialModel),
                            "record_digest": _NULLABLE_DIGEST,
                            "applies_to": _list(_GEOMETRY_REF, 1, unique=True),
                        }
                    )
                ),
                "loads": _list(
                    _closed(
                        {
                            "load_id": _id("LOAD"),
                            "kind": _enum(LoadKind),
                            "applies_to": _GEOMETRY_REF,
                            "magnitude": _QUANTITY,
                            "description": _TEXT,
                        }
                    )
                ),
                "environment": _closed(
                    {
                        "state_id": _id("ENV"),
                        "description": _TEXT,
                        "conditions": _list(_id("SCL"), unique=True),
                    }
                ),
                "boundary_conditions": _list(
                    _closed(
                        {
                            "bc_id": _id("BC"),
                            "kind": _enum(BoundaryKind),
                            "applies_to": _GEOMETRY_REF,
                            "description": _TEXT,
                        }
                    ),
                    1,
                ),
                "initial_conditions": _closed(
                    {
                        "relevance": _enum(InitialRelevance),
                        "rationale": _TEXT,
                        "conditions": _list(
                            _closed(
                                {
                                    "ic_id": _id("IC"),
                                    "description": _TEXT,
                                    "applies_to": _GEOMETRY_REF,
                                }
                            )
                        ),
                    }
                ),
                "interfaces": _list(
                    _closed(
                        {
                            "interface_id": _id("IFC"),
                            "between": {
                                "type": "array",
                                "items": _GEOMETRY_REF,
                                "minItems": 2,
                                "maxItems": 2,
                                "uniqueItems": True,
                            },
                            "coupling": _enum(Coupling),
                            "description": _TEXT,
                        }
                    )
                ),
                "failure_modes": _list(
                    _closed({"failure_mode_id": _id("FM"), "description": _TEXT}), 1
                ),
                "uncertainty_sources": _list(
                    _closed(
                        {
                            "source_id": _id("UNC"),
                            "category": _enum(UncertaintyCategory),
                            "description": _TEXT,
                        }
                    ),
                    1,
                ),
                "evidence": _list(
                    _closed(
                        {
                            "evidence_id": _EVIDENCE_REF,
                            "kind": _enum(IntentEvidenceKind),
                            "title": _TEXT,
                            "locator": _TEXT,
                            "content_digest": _DIGEST_SCHEMA,
                        }
                    )
                ),
                "validation_evidence": _list(
                    _closed(
                        {
                            "validation_id": _id("VAL"),
                            "status": _enum(ValidationStatus),
                            "description": _TEXT,
                            "evidence_ids": _list(_EVIDENCE_REF, unique=True),
                        }
                    ),
                    1,
                ),
                "model_form_alternatives": _list(
                    _closed(
                        {
                            "model_form": _enum(ModelForm),
                            "disposition": _enum(Disposition),
                            "rationale": _TEXT,
                        }
                    )
                ),
                "assumptions": _list(
                    _closed(
                        {
                            "assumption_id": _id("ASM"),
                            "statement": _TEXT,
                            "owner": _TEXT,
                            "rationale": _TEXT,
                            "impact": _TEXT,
                            "verification_plan": _TEXT,
                            "status": _enum(AssumptionStatus),
                            "critical": {"type": "boolean"},
                        }
                    )
                ),
                "rule_set_pin": _closed(
                    {
                        "rule_set_id": _id("RULESET"),
                        "revision": _TEXT,
                        "digest": _DIGEST_SCHEMA,
                    }
                ),
            }
        ),
    }


_BOUND = {
    "oneOf": [
        {"type": "null"},
        _closed(
            {
                "value": {"type": "string", "pattern": _EXACT},
                "inclusive": {"type": "boolean"},
            }
        ),
    ]
}
_INTERVAL = _closed({"lower": _BOUND, "upper": _BOUND})


def rules_schema() -> dict[str, Any]:
    return {
        "$schema": DIALECT,
        "$id": "https://contrainte.dev/schemas/applicability-rules-0.1.schema.json",
        "title": RULES_SCHEMA,
        "$comment": _COMMENT,
        **_closed(
            {
                "schema_version": {"const": RULES_SCHEMA},
                "rule_set_id": _id("RULESET"),
                "revision": _TEXT,
                "title": _TEXT,
                "authoring": _closed(
                    {"owner": _TEXT, "status": _enum(AuthoringStatus)}
                ),
                "group_registry": _closed(
                    {
                        "version": {"const": GROUP_REGISTRY_VERSION},
                        "digest": _DIGEST_SCHEMA,
                    }
                ),
                "citations": _list(
                    _closed(
                        {
                            "evidence_id": _EVIDENCE_REF,
                            "kind": _enum(CitationKind),
                            "title": _TEXT,
                            "authority": _TEXT,
                            "locator": _TEXT,
                            "revision": _TEXT,
                            "retrieved_at": _TEXT,
                            "excerpt": _TEXT,
                            "excerpt_digest": _DIGEST_SCHEMA,
                        }
                    ),
                    1,
                ),
                "rules": _list(
                    _closed(
                        {
                            "rule_id": _id("RULE"),
                            "rule_version": {"type": "integer", "minimum": 1},
                            "title": _TEXT,
                            "model_form": _enum(ModelForm),
                            "group": _closed(
                                {
                                    "group_id": {"enum": _GROUP_IDS},
                                    "form_id": {"enum": _FORM_IDS},
                                }
                            ),
                            "bands": _closed(
                                {
                                    "valid": _list(_INTERVAL, 1),
                                    "marginal": _list(_INTERVAL),
                                }
                            ),
                            "rationale": _TEXT,
                            "citation_ids": _list(_EVIDENCE_REF, 1, unique=True),
                            "on_marginal": _closed(
                                {"review_role": _TEXT, "instruction": _TEXT}
                            ),
                            "escalation_model_forms": _list(
                                _enum(ModelForm), 1, unique=True
                            ),
                        },
                        required=[
                            "rule_id",
                            "rule_version",
                            "title",
                            "model_form",
                            "group",
                            "bands",
                            "rationale",
                            "citation_ids",
                            "on_marginal",
                        ],
                    ),
                    1,
                ),
            }
        ),
    }


_EXACT_VALUE = _closed(
    {
        "rational": {"type": "string", "pattern": r"^-?[0-9]+(/[1-9][0-9]*)?$"},
        "decimal": {
            "oneOf": [
                {"type": "null"},
                {"type": "string", "pattern": r"^-?[0-9]+(\.[0-9]+)?$"},
            ]
        },
    }
)
_ISSUE = _closed({"code": {"type": "string"}, "subject": {"type": "string"}})
_FALSE = {"const": False}


def report_schema() -> dict[str, Any]:
    nullable_value = {"oneOf": [{"type": "null"}, _EXACT_VALUE]}
    return {
        "$schema": DIALECT,
        "$id": "https://contrainte.dev/schemas/physics-applicability-report-0.1.schema.json",
        "title": REPORT_SCHEMA,
        "$comment": _COMMENT,
        **_closed(
            {
                "schema_version": {"const": REPORT_SCHEMA},
                "kernel": _closed(
                    {
                        "package": {"const": "contrainte.physics"},
                        "group_registry": _closed(
                            {
                                "version": {"const": GROUP_REGISTRY_VERSION},
                                "digest": _DIGEST_SCHEMA,
                            }
                        ),
                    }
                ),
                "inputs": _closed(
                    {
                        "intent": _closed(
                            {
                                "intent_id": _id("PHY"),
                                "revision": _TEXT,
                                "digest": _DIGEST_SCHEMA,
                            }
                        ),
                        "rule_set": _closed(
                            {
                                "rule_set_id": _id("RULESET"),
                                "revision": _TEXT,
                                "digest": _DIGEST_SCHEMA,
                            }
                        ),
                    }
                ),
                "requested_mode": _enum(Mode),
                "output_label": {"enum": ["exploratory", "non_release"]},
                "groups": _list(
                    _closed(
                        {
                            "declaration_id": _id("GRP"),
                            "group_id": {"enum": _GROUP_IDS},
                            "form_id": {"enum": _FORM_IDS},
                            "symbol": {"type": "string"},
                            "expression": {"type": "string"},
                            "inputs": _list(
                                _closed(
                                    {
                                        "role": {"type": "string"},
                                        "exponent": {"type": "integer"},
                                        "scale_id": _id("SCL"),
                                        "basis": _enum(Basis),
                                        "quantity": _QUANTITY,
                                        "si_value": _EXACT_VALUE,
                                    }
                                ),
                                1,
                            ),
                            "value": _EXACT_VALUE,
                        }
                    )
                ),
                "rule_outcomes": _list(
                    _closed(
                        {
                            "rule_id": _id("RULE"),
                            "rule_version": {"type": "integer", "minimum": 1},
                            "model_form": _enum(ModelForm),
                            "group_id": {"enum": _GROUP_IDS},
                            "form_id": {"enum": _FORM_IDS},
                            "citation_ids": _list(_EVIDENCE_REF, 1),
                            "escalation_model_forms": _list(_enum(ModelForm)),
                            "declaration_id": {"oneOf": [{"type": "null"}, _id("GRP")]},
                            "outcome": {
                                "enum": [
                                    "valid",
                                    "marginal",
                                    "violated",
                                    "indeterminate",
                                    "not_selected",
                                ]
                            },
                            "reason": {
                                "enum": [
                                    None,
                                    "group_not_declared",
                                    "model_form_not_candidate",
                                ]
                            },
                            "value": nullable_value,
                            "matched_band": {
                                "oneOf": [
                                    {"type": "null"},
                                    _closed(
                                        {
                                            "band": {"enum": ["valid", "marginal"]},
                                            "interval": _INTERVAL,
                                        }
                                    ),
                                ]
                            },
                        }
                    )
                ),
                "model_form_outcomes": _list(
                    _closed(
                        {
                            "model_form": _enum(ModelForm),
                            "state": {
                                "enum": [
                                    "applicable",
                                    "marginal",
                                    "violated",
                                    "indeterminate",
                                    "no_rule",
                                ]
                            },
                            "rule_ids": _list(_id("RULE")),
                        }
                    ),
                    1,
                ),
                "applicability_state": {
                    "enum": [
                        "rules_satisfied",
                        "marginal_review_required",
                        "indeterminate",
                        "rules_violated",
                    ]
                },
                "warnings": _list(
                    _closed(
                        {
                            "code": {"type": "string"},
                            "subject": {"type": "string"},
                            "message": {"type": "string"},
                        }
                    )
                ),
                "review_tasks": _list(
                    _closed(
                        {
                            "task_id": {
                                "type": "string",
                                "pattern": r"^RVW-[1-9][0-9]*$",
                            },
                            "kind": {"const": "marginal_applicability_review"},
                            "rule_id": _id("RULE"),
                            "declaration_id": _id("GRP"),
                            "review_role": {"type": "string"},
                            "status": {"const": "open"},
                        }
                    )
                ),
                "qualified_execution": _closed(
                    {"permitted": _FALSE, "blockers": _list(_ISSUE, 1)}
                ),
                "controlled_review_readiness": _closed(
                    {
                        "state": {"enum": ["blocked", "ready_for_independent_review"]},
                        "blockers": _list(_ISSUE),
                    }
                ),
                "authority_promotion_permitted": _FALSE,
                "authority": _closed(
                    {
                        "release_authority": _FALSE,
                        "approval_authority": _FALSE,
                        "write_authority": _FALSE,
                        "control_authority": _FALSE,
                        "human_review_required": {"const": True},
                    }
                ),
                "qualification_level": {"const": "none"},
                "output_basis": {"const": "computed_from_declared_inputs"},
                "claim_boundary": {"type": "string"},
                "unsupported": _closed(
                    {
                        "declared_domains_without_execution": _list(_enum(Domain), 1),
                        "execution_available_domains": {"type": "array", "maxItems": 0},
                        "kernel_scope": {"type": "string"},
                    }
                ),
                "report_digest": _DIGEST_SCHEMA,
            }
        ),
    }


SCHEMAS = {
    "intent": ("physics-intent-0.1.schema.json", intent_schema),
    "rules": ("applicability-rules-0.1.schema.json", rules_schema),
    "report": ("physics-applicability-report-0.1.schema.json", report_schema),
}


def schema_text(name: str) -> str:
    return (
        json.dumps(SCHEMAS[name][1](), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )
