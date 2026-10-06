"""Versioned applicability registry: units, group forms and the model-form table, bound by one digest."""

from __future__ import annotations

from typing import Any

from ..canonical import digest
from .dimensional import unit_registry_description
from .groups import forms_description
from .model_forms import model_form_table_description

REGISTRY_VERSION = "contrainte.applicability-registry/0.2"


def registry_description() -> dict[str, Any]:
    return {
        "version": REGISTRY_VERSION,
        "quantities": unit_registry_description(),
        "forms": forms_description(),
        "model_forms": model_form_table_description(),
    }


def registry_digest() -> str:
    return digest(registry_description())
