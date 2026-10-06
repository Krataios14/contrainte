"""Kernel-owned model-form table: required groups, admissible groups, unevaluated considerations.

The table records which dimensionless groups a rule set must cover for each candidate model
form and which section 13.3 considerations this kernel cannot evaluate. It holds no numeric
thresholds: every band remains declared and cited by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .groups import FORMS


class ModelForm(str, Enum):
    EULER_BERNOULLI_BEAM = "euler_bernoulli_beam"
    TIMOSHENKO_BEAM = "timoshenko_beam"
    THIN_SHELL = "thin_shell"
    CONTINUUM_SOLID = "continuum_solid"
    LINEAR_ELASTIC = "linear_elastic"
    INCOMPRESSIBLE_FLOW = "incompressible_flow"
    COMPRESSIBLE_FLOW = "compressible_flow"
    LAMINAR_FLOW = "laminar_flow"
    TURBULENT_FLOW = "turbulent_flow"
    CONTINUUM_FLOW = "continuum_flow"
    RAREFIED_FLOW = "rarefied_flow"
    LUMPED_CAPACITANCE_THERMAL = "lumped_capacitance_thermal"
    DISTRIBUTED_CONDUCTION_THERMAL = "distributed_conduction_thermal"
    STEADY_STATE = "steady_state"
    TRANSIENT_RESPONSE = "transient_response"
    QUASI_STATIC = "quasi_static"


@dataclass(frozen=True)
class Consideration:
    consideration_id: str
    source: str
    description: str


@dataclass(frozen=True)
class ModelFormEntry:
    model_form: ModelForm
    required_groups: tuple[str, ...]
    admissible_groups: tuple[str, ...]
    unevaluated: tuple[Consideration, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_form": self.model_form.value,
            "required_groups": list(self.required_groups),
            "admissible_groups": list(self.admissible_groups),
            "unevaluated_considerations": [
                {
                    "consideration_id": item.consideration_id,
                    "source": item.source,
                    "description": item.description,
                }
                for item in self.unevaluated
            ],
        }


_BEAM = "TECHNICAL_SPEC 13.3 beam theory"
_SHELL = "TECHNICAL_SPEC 13.3 shell theory"
_ELASTIC = "TECHNICAL_SPEC 13.3 linear elasticity"
_TURBULENCE = "TECHNICAL_SPEC 13.3 turbulence-model selection"
_SCOPE = "kernel scope"

_LOCAL_STRESS = Consideration(
    "local_stress_needs",
    _BEAM,
    "Whether local stress near supports, holes or load points is a target output.",
)
_TURBULENCE_CONSIDERATIONS = (
    Consideration(
        "wall_treatment", _TURBULENCE, "Near-wall resolution or wall-function adequacy."
    ),
    Consideration("separation", _TURBULENCE, "Presence or onset of flow separation."),
    Consideration(
        "target_quantity_sensitivity",
        _TURBULENCE,
        "Sensitivity of the target outputs to the closure.",
    ),
)
_NO_CRITERIA = Consideration(
    "no_kernel_applicability_criteria",
    _SCOPE,
    "This kernel registers no dimensionless group that can gate this model form.",
)


def _entry(
    form: ModelForm,
    required: tuple[str, ...],
    unevaluated: tuple[Consideration, ...] = (),
    optional: tuple[str, ...] = (),
) -> ModelFormEntry:
    return ModelFormEntry(form, required, required + optional, unevaluated)


_ENTRIES = (
    _entry(ModelForm.EULER_BERNOULLI_BEAM, ("beam_slenderness",), (_LOCAL_STRESS,)),
    _entry(ModelForm.TIMOSHENKO_BEAM, ("beam_slenderness",), (_LOCAL_STRESS,)),
    _entry(
        ModelForm.THIN_SHELL,
        ("shell_thickness_ratio",),
        (
            Consideration(
                "through_thickness_effects",
                _SHELL,
                "Through-thickness stress and deformation effects.",
            ),
        ),
    ),
    _entry(ModelForm.CONTINUUM_SOLID, (), (_NO_CRITERIA,)),
    _entry(
        ModelForm.LINEAR_ELASTIC,
        (),
        (
            Consideration(
                "strain_magnitude",
                _ELASTIC,
                "Strain level relative to the linear range.",
            ),
            Consideration(
                "material_behavior",
                _ELASTIC,
                "Linearity of the constitutive behaviour.",
            ),
            Consideration(
                "contact", _ELASTIC, "Contact or changing boundary conditions."
            ),
            Consideration(
                "geometric_change",
                _ELASTIC,
                "Geometric change large enough to alter stiffness.",
            ),
        ),
    ),
    _entry(ModelForm.INCOMPRESSIBLE_FLOW, ("mach", "density_variation")),
    _entry(ModelForm.COMPRESSIBLE_FLOW, ("mach",), optional=("density_variation",)),
    _entry(ModelForm.LAMINAR_FLOW, ("reynolds",), _TURBULENCE_CONSIDERATIONS),
    _entry(ModelForm.TURBULENT_FLOW, ("reynolds",), _TURBULENCE_CONSIDERATIONS),
    _entry(ModelForm.CONTINUUM_FLOW, ("knudsen",)),
    _entry(ModelForm.RAREFIED_FLOW, ("knudsen",)),
    _entry(ModelForm.LUMPED_CAPACITANCE_THERMAL, ("biot",)),
    _entry(ModelForm.DISTRIBUTED_CONDUCTION_THERMAL, ("biot",)),
    _entry(ModelForm.STEADY_STATE, ("time_scale_ratio",)),
    _entry(ModelForm.TRANSIENT_RESPONSE, ("time_scale_ratio",)),
    _entry(ModelForm.QUASI_STATIC, ("time_scale_ratio",)),
)

MODEL_FORMS: dict[ModelForm, ModelFormEntry] = {
    entry.model_form: entry for entry in _ENTRIES
}


def _check_table() -> None:
    # Explicit checks (not ``assert``) so the table stays valid under ``python -O``.
    group_ids = {form.group_id for form in FORMS.values()}
    if set(MODEL_FORMS) != set(ModelForm) or len(_ENTRIES) != len(ModelForm):
        raise RuntimeError("model-form table must cover every model form exactly once")
    for entry in _ENTRIES:
        if not set(entry.required_groups) <= set(entry.admissible_groups) <= group_ids:
            raise RuntimeError(
                f"model-form table entry {entry.model_form.value} references unknown groups"
            )
        if not entry.required_groups and not entry.unevaluated:
            raise RuntimeError(
                f"model form {entry.model_form.value} has no group and no declared consideration"
            )


_check_table()


def model_form_table_description() -> list[dict[str, Any]]:
    return [entry.as_dict() for entry in _ENTRIES]
