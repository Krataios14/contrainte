"""Versioned registry of exact dimensionless-group forms."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Any

from ..errors import DimensionalityError, InputError
from .dimensional import DIMENSIONLESS, KINDS, DimensionalQuantity


class RoleDomain(str, Enum):
    POSITIVE = "positive"
    NON_NEGATIVE = "non_negative"


@dataclass(frozen=True)
class GroupRole:
    role: str
    kind: str
    exponent: int
    domain: RoleDomain


@dataclass(frozen=True)
class GroupForm:
    group_id: str
    form_id: str
    symbol: str
    expression: str
    roles: tuple[GroupRole, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "form_id": self.form_id,
            "symbol": self.symbol,
            "expression": self.expression,
            "roles": [
                {
                    "role": item.role,
                    "kind": item.kind,
                    "exponent": item.exponent,
                    "domain": item.domain.value,
                }
                for item in self.roles
            ],
        }


_P = RoleDomain.POSITIVE
_N = RoleDomain.NON_NEGATIVE


def _form(
    group_id: str,
    form_id: str,
    symbol: str,
    expression: str,
    *roles: tuple[str, str, int, RoleDomain],
) -> GroupForm:
    return GroupForm(
        group_id,
        form_id,
        symbol,
        expression,
        tuple(
            GroupRole(role, kind, exponent, domain)
            for role, kind, exponent, domain in roles
        ),
    )


_FORMS = (
    _form(
        "mach",
        "mach.speed_ratio",
        "Ma",
        "flow_speed / speed_of_sound",
        ("flow_speed", "velocity", 1, _N),
        ("speed_of_sound", "velocity", -1, _P),
    ),
    _form(
        "reynolds",
        "reynolds.dynamic_viscosity",
        "Re",
        "density * flow_speed * characteristic_length / dynamic_viscosity",
        ("density", "density", 1, _P),
        ("flow_speed", "velocity", 1, _N),
        ("characteristic_length", "length", 1, _P),
        ("dynamic_viscosity", "dynamic_viscosity", -1, _P),
    ),
    _form(
        "reynolds",
        "reynolds.kinematic_viscosity",
        "Re",
        "flow_speed * characteristic_length / kinematic_viscosity",
        ("flow_speed", "velocity", 1, _N),
        ("characteristic_length", "length", 1, _P),
        ("kinematic_viscosity", "kinematic_viscosity", -1, _P),
    ),
    _form(
        "knudsen",
        "knudsen.mean_free_path",
        "Kn",
        "mean_free_path / characteristic_length",
        ("mean_free_path", "length", 1, _P),
        ("characteristic_length", "length", -1, _P),
    ),
    _form(
        "beam_slenderness",
        "beam_slenderness.span_to_depth",
        "L/h",
        "span_length / section_depth",
        ("span_length", "length", 1, _P),
        ("section_depth", "length", -1, _P),
    ),
    _form(
        "beam_slenderness",
        "beam_slenderness.effective_squared",
        "lambda^2",
        "(effective_length_factor * unbraced_length)^2 * section_area / second_moment_of_area",
        ("effective_length_factor", "dimensionless", 2, _P),
        ("unbraced_length", "length", 2, _P),
        ("section_area", "area", 1, _P),
        ("second_moment_of_area", "second_moment_of_area", -1, _P),
    ),
    _form(
        "biot",
        "biot.lumped",
        "Bi",
        "heat_transfer_coefficient * characteristic_length / thermal_conductivity",
        ("heat_transfer_coefficient", "heat_transfer_coefficient", 1, _N),
        ("characteristic_length", "length", 1, _P),
        ("thermal_conductivity", "thermal_conductivity", -1, _P),
    ),
    _form(
        "time_scale_ratio",
        "time_scale_ratio.response_to_process",
        "tau_r/tau_p",
        "response_time / process_time",
        ("response_time", "time", 1, _P),
        ("process_time", "time", -1, _P),
    ),
    _form(
        "shell_thickness_ratio",
        "shell_thickness_ratio.thickness_to_radius",
        "t/R",
        "shell_thickness / radius_of_curvature",
        ("shell_thickness", "length", 1, _P),
        ("radius_of_curvature", "length", -1, _P),
    ),
    _form(
        "density_variation",
        "density_variation.relative",
        "drho/rho",
        "density_change / reference_density",
        ("density_change", "density", 1, _N),
        ("reference_density", "density", -1, _P),
    ),
)

FORMS: dict[str, GroupForm] = {form.form_id: form for form in _FORMS}


def _dimension_of(roles: tuple[GroupRole, ...]) -> tuple[int, ...]:
    total = [0, 0, 0, 0]
    for role in roles:
        for index, exponent in enumerate(KINDS[role.kind]):
            total[index] += exponent * role.exponent
    return tuple(total)


for _definition in _FORMS:
    # Explicit checks (not ``assert``) so every form stays dimensionless under ``python -O``.
    if _dimension_of(_definition.roles) != DIMENSIONLESS:
        raise RuntimeError(f"group form {_definition.form_id} is not dimensionless")
    if not _definition.form_id.startswith(_definition.group_id + "."):
        raise RuntimeError(
            f"group form {_definition.form_id} is not namespaced by its group"
        )


def forms_description() -> list[dict[str, Any]]:
    return [form.as_dict() for form in _FORMS]


def require_form(group_id: Any, form_id: Any, field: str) -> GroupForm:
    if not isinstance(group_id, str) or not isinstance(form_id, str):
        raise InputError(f"{field}.group_id and {field}.form_id must be strings")
    form = FORMS.get(form_id)
    if form is None:
        raise InputError(f"{field}.form_id is not a registered group form: {form_id!r}")
    if form.group_id != group_id:
        raise InputError(
            f"{field}: form {form_id!r} does not belong to group {group_id!r}"
        )
    return form


def check_binding_kinds(
    form: GroupForm, quantities: Mapping[str, DimensionalQuantity], field: str
) -> None:
    expected = {role.role for role in form.roles}
    missing = sorted(expected - set(quantities))
    if missing:
        raise InputError(f"{field} is missing inputs for roles: {', '.join(missing)}")
    unknown = sorted(set(quantities) - expected)
    if unknown:
        raise InputError(f"{field} binds unknown roles: {', '.join(unknown)}")
    for role in form.roles:
        quantity = quantities[role.role]
        if quantity.kind != role.kind:
            raise DimensionalityError(
                f"{field}.{role.role} requires kind {role.kind!r}, got {quantity.kind!r}"
            )


def compute_group(
    form: GroupForm, quantities: Mapping[str, DimensionalQuantity], field: str
) -> Fraction:
    """Compute one exact group value after checking kinds, domains and dimensions."""

    check_binding_kinds(form, quantities, field)
    total = [0, 0, 0, 0]
    value = Fraction(1)
    for role in form.roles:
        quantity = quantities[role.role]
        si_value = quantity.si_value
        if role.domain is RoleDomain.POSITIVE and si_value <= 0:
            raise InputError(f"{field}.{role.role} must be greater than zero")
        if role.domain is RoleDomain.NON_NEGATIVE and si_value < 0:
            raise InputError(f"{field}.{role.role} must not be negative")
        for index, exponent in enumerate(quantity.dimension):
            total[index] += exponent * role.exponent
        value *= si_value**role.exponent
    if tuple(total) != DIMENSIONLESS:
        raise DimensionalityError(f"{field} does not reduce to a dimensionless group")
    return value
