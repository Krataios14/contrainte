"""Physics intent and versioned applicability rules (PHYS-01 bounded kernel).

This package records the engineering question and checks caller-declared applicability
rules over exact dimensionless groups. It never runs a solver and never grants authority.
"""

from ._parse import StalePinError
from .dimensional import QUANTITY_SCHEMA, DimensionalQuantity
from .evaluate import (
    CLAIM_BOUNDARY,
    EXIT_BY_STATE,
    REPORT_SCHEMA,
    evaluate,
    evaluate_documents,
    verify_bundle,
    verify_report,
    write_bundle,
)
from .groups import FORMS, GROUP_REGISTRY_VERSION, registry_description, registry_digest
from .intent import INTENT_SCHEMA, PhysicsIntent, parse_intent
from .rules import RULES_SCHEMA, ModelForm, RuleSet, parse_rule_set

__all__ = [
    "CLAIM_BOUNDARY",
    "EXIT_BY_STATE",
    "FORMS",
    "GROUP_REGISTRY_VERSION",
    "INTENT_SCHEMA",
    "QUANTITY_SCHEMA",
    "REPORT_SCHEMA",
    "RULES_SCHEMA",
    "DimensionalQuantity",
    "ModelForm",
    "PhysicsIntent",
    "RuleSet",
    "StalePinError",
    "evaluate",
    "evaluate_documents",
    "parse_intent",
    "parse_rule_set",
    "registry_description",
    "registry_digest",
    "verify_bundle",
    "verify_report",
    "write_bundle",
]
