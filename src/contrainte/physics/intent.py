"""Physics intent (``contrainte.physics-intent/0.1``), the engineering question before software."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..canonical import digest
from ..errors import DimensionalityError, InputError
from . import _parse as p
from .dimensional import KINDS, UNITS, DimensionalQuantity
from .groups import GroupForm, check_binding_kinds, require_form
from .model_forms import ModelForm
from .rules import EVIDENCE_ID, RULE_SET_ID

INTENT_SCHEMA = "contrainte.physics-intent/0.2"
SUPERSEDED_INTENT_SCHEMAS = ("contrainte.physics-intent/0.1",)

PHY_ID = p.identifier_pattern("PHY")
REQ_ID = p.identifier_pattern("REQ")
ASM_ID = p.identifier_pattern("ASM")
MAT_ID = p.identifier_pattern("MAT")
GEOMETRY_ID = p.identifier_pattern("FEA", "OCC", "SUR")
IFC_ID = p.identifier_pattern("IFC")
SCL_ID = p.identifier_pattern("SCL")
QOI_ID = p.identifier_pattern("QOI")
ACC_ID = p.identifier_pattern("ACC")
LOAD_ID = p.identifier_pattern("LOAD")
BC_ID = p.identifier_pattern("BC")
IC_ID = p.identifier_pattern("IC")
ENV_ID = p.identifier_pattern("ENV")
FM_ID = p.identifier_pattern("FM")
UNC_ID = p.identifier_pattern("UNC")
SIM_ID = p.identifier_pattern("SIM")
VAL_ID = p.identifier_pattern("VAL")
GRP_ID = p.identifier_pattern("GRP")


class Mode(str, Enum):
    EXPLORATION = "exploration"
    CONTROLLED = "controlled"
    QUALIFIED = "qualified"


class Criticality(str, Enum):
    CRITICAL = "critical"
    NON_CRITICAL = "non_critical"


class Domain(str, Enum):
    ANALYTICAL_SOLID_MECHANICS_SCREEN = "analytical_solid_mechanics_screen"
    LINEAR_STATIC_SOLID_MECHANICS = "linear_static_solid_mechanics"
    MODAL = "modal"
    TRANSIENT_STRUCTURAL_DYNAMICS = "transient_structural_dynamics"
    CONTACT_MECHANICS = "contact_mechanics"
    GEOMETRIC_NONLINEARITY = "geometric_nonlinearity"
    MATERIAL_NONLINEARITY = "material_nonlinearity"
    FRACTURE_MECHANICS = "fracture_mechanics"
    FATIGUE_DURABILITY = "fatigue_durability"
    STEADY_HEAT_CONDUCTION = "steady_heat_conduction"
    TRANSIENT_HEAT_TRANSFER = "transient_heat_transfer"
    CONVECTION_RADIATION_BOUNDARY = "convection_radiation_boundary"
    INCOMPRESSIBLE_FLOW = "incompressible_flow"
    COMPRESSIBLE_FLOW = "compressible_flow"
    LAMINAR_TURBULENCE = "laminar_turbulence"
    SPECIES_TRANSPORT = "species_transport"
    PARTICLE_TRANSPORT = "particle_transport"
    CONJUGATE_HEAT_TRANSFER = "conjugate_heat_transfer"
    FLUID_STRUCTURE_INTERACTION = "fluid_structure_interaction"
    THERMO_MECHANICAL_COUPLING = "thermo_mechanical_coupling"
    ELECTROMAGNETICS = "electromagnetics"
    ACOUSTICS = "acoustics"
    CHEMICAL_REACTION_NETWORKS = "chemical_reaction_networks"
    POPULATION_BALANCE = "population_balance"


class TimeCharacter(str, Enum):
    STEADY = "steady"
    TRANSIENT = "transient"
    CYCLIC = "cyclic"
    STOCHASTIC = "stochastic"


class FidelityLevel(str, Enum):
    SCREENING = "screening"
    ENGINEERING = "engineering"
    HIGH_FIDELITY = "high_fidelity"


class Nonlinearity(str, Enum):
    NONE_EXPECTED = "none_expected"
    GEOMETRIC = "geometric"
    MATERIAL = "material"
    CONTACT = "contact"
    BOUNDARY = "boundary"


class Basis(str, Enum):
    OBSERVED = "observed"
    MEASURED = "measured"
    SUPPLIER_DECLARED = "supplier_declared"
    STANDARD_SPECIFIED = "standard_specified"
    COMPUTED = "computed"
    CRITICALLY_EVALUATED = "critically_evaluated"
    PREDICTED = "predicted"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    AI_PROPOSED = "ai_proposed"


class GeometryRole(str, Enum):
    BODY = "body"
    REGION = "region"
    SURFACE = "surface"


class Comparator(str, Enum):
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"


class MaterialModel(str, Enum):
    LINEAR_ELASTIC_ISOTROPIC = "linear_elastic_isotropic"
    LINEAR_ELASTIC_ANISOTROPIC = "linear_elastic_anisotropic"
    ELASTOPLASTIC = "elastoplastic"
    HYPERELASTIC = "hyperelastic"
    VISCOELASTIC = "viscoelastic"
    NEWTONIAN_FLUID = "newtonian_fluid"
    NON_NEWTONIAN_FLUID = "non_newtonian_fluid"
    CONSTANT_THERMAL_PROPERTIES = "constant_thermal_properties"
    TEMPERATURE_DEPENDENT_THERMAL_PROPERTIES = (
        "temperature_dependent_thermal_properties"
    )


class LoadKind(str, Enum):
    FORCE = "force"
    PRESSURE = "pressure"
    THERMAL = "thermal"
    INERTIAL = "inertial"
    FLOW = "flow"
    HEAT_FLUX = "heat_flux"


class BoundaryKind(str, Enum):
    FIXED = "fixed"
    SYMMETRY = "symmetry"
    PRESCRIBED_DISPLACEMENT = "prescribed_displacement"
    PRESCRIBED_TEMPERATURE = "prescribed_temperature"
    CONVECTION = "convection"
    HEAT_FLUX = "heat_flux"
    INLET = "inlet"
    OUTLET = "outlet"
    WALL = "wall"
    FREE_SURFACE = "free_surface"


class InitialRelevance(str, Enum):
    NOT_RELEVANT = "not_relevant"
    SPECIFIED = "specified"


class Coupling(str, Enum):
    NONE = "none"
    ONE_WAY = "one_way"
    TWO_WAY = "two_way"


class UncertaintyCategory(str, Enum):
    ALEATORY = "aleatory"
    EPISTEMIC = "epistemic"
    MODEL_FORM = "model_form"
    NUMERICAL = "numerical"


class IntentEvidenceKind(str, Enum):
    MEASUREMENT_RECORD = "measurement_record"
    SOURCE_DOCUMENT = "source_document"
    STANDARD = "standard"
    DATABASE_RECORD = "database_record"
    TEST_RECORD = "test_record"
    SOLVER_RESULT = "solver_result"
    HUMAN_RATIONALE = "human_rationale"
    SYNTHETIC_ILLUSTRATION = "synthetic_illustration"


class ValidationStatus(str, Enum):
    AVAILABLE = "available"
    PLANNED = "planned"


class Disposition(str, Enum):
    SELECTED = "selected"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class AssumptionStatus(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    RETIRED = "retired"


@dataclass(frozen=True)
class Scale:
    scale_id: str
    quantity: DimensionalQuantity
    basis: Basis
    evidence_ids: tuple[str, ...]
    assumption_ids: tuple[str, ...]


@dataclass(frozen=True)
class GroupDeclaration:
    declaration_id: str
    form: GroupForm
    bindings: dict[str, str]


@dataclass(frozen=True)
class Assumption:
    assumption_id: str
    status: AssumptionStatus
    critical: bool


@dataclass(frozen=True)
class PhysicsIntent:
    intent_id: str
    revision: str
    mode: Mode
    criticality: Criticality
    exploratory_acceptance: bool
    domains: tuple[Domain, ...]
    scales: dict[str, Scale]
    declarations: tuple[GroupDeclaration, ...]
    candidate_model_forms: tuple[ModelForm, ...]
    assumptions: tuple[Assumption, ...]
    evidence_kinds: dict[str, IntentEvidenceKind]
    rule_set_pin: dict[str, str]
    raw: dict[str, Any]

    @property
    def digest(self) -> str:
        return digest(self.raw)


def _quantity(raw: Any, field: str, *, kind: str | None = None) -> DimensionalQuantity:
    quantity = DimensionalQuantity.from_dict(raw, field=field)
    if kind is not None and quantity.kind != kind:
        raise DimensionalityError(
            f"{field} must have kind {kind!r}, got {quantity.kind!r}"
        )
    return quantity


def _records(
    raw: dict[str, Any], name: str, field: str, *, minimum: int = 0
) -> list[tuple[str, Any]]:
    return [
        (f"{field}.{name}[{index}]", item)
        for index, item in enumerate(p.array(raw, name, field, minimum=minimum))
    ]


def parse_intent(raw: Any) -> PhysicsIntent:
    f = "intent"
    p.require_unicode_text(raw, f)
    p.schema_version(raw, "physics-intent", INTENT_SCHEMA, SUPERSEDED_INTENT_SCHEMAS)
    raw = p.obj(
        raw,
        f,
        (
            "schema_version",
            "intent_id",
            "revision",
            "title",
            "requested_mode",
            "criticality",
            "decision",
            "target_outputs",
            "acceptance",
            "geometry",
            "domains",
            "time",
            "nonlinearities",
            "scales",
            "group_declarations",
            "candidate_model_forms",
            "materials",
            "loads",
            "environment",
            "boundary_conditions",
            "initial_conditions",
            "interfaces",
            "failure_modes",
            "uncertainty_sources",
            "evidence",
            "validation_evidence",
            "model_form_alternatives",
            "assumptions",
            "rule_set_pin",
        ),
    )
    intent_id = p.ident(raw, "intent_id", f, PHY_ID)
    revision = p.text(raw, "revision", f)
    p.text(raw, "title", f)
    mode = p.enum(raw, "requested_mode", f, Mode)
    criticality = p.enum(raw, "criticality", f, Criticality)

    decision = p.obj(
        raw["decision"], f"{f}.decision", ("statement", "owner", "requirement_ids")
    )
    p.text(decision, "statement", f"{f}.decision")
    p.text(decision, "owner", f"{f}.decision")
    p.id_list(decision, "requirement_ids", f"{f}.decision", REQ_ID)

    # Evidence and assumptions are parsed first so every later reference can resolve.
    evidence_ids = []
    evidence_kinds: dict[str, IntentEvidenceKind] = {}
    for field, item in _records(raw, "evidence", f):
        item = p.obj(
            item, field, ("evidence_id", "kind", "title", "locator", "content_digest")
        )
        evidence_ids.append(p.ident(item, "evidence_id", field, EVIDENCE_ID))
        evidence_kinds[evidence_ids[-1]] = p.enum(
            item, "kind", field, IntentEvidenceKind
        )
        p.text(item, "title", field)
        p.text(item, "locator", field)
        p.digest_text(item, "content_digest", field)
    p.unique(evidence_ids, f"{f}.evidence")

    assumptions = []
    for field, item in _records(raw, "assumptions", f):
        item = p.obj(
            item,
            field,
            (
                "assumption_id",
                "statement",
                "owner",
                "rationale",
                "impact",
                "verification_plan",
                "status",
                "critical",
            ),
        )
        for name in ("statement", "owner", "rationale", "impact", "verification_plan"):
            p.text(item, name, field)
        assumptions.append(
            Assumption(
                p.ident(item, "assumption_id", field, ASM_ID),
                p.enum(item, "status", field, AssumptionStatus),
                p.boolean(item, "critical", field),
            )
        )
    p.unique((item.assumption_id for item in assumptions), f"{f}.assumptions")
    assumption_ids = {item.assumption_id for item in assumptions}
    retired_assumptions = {
        item.assumption_id
        for item in assumptions
        if item.status is AssumptionStatus.RETIRED
    }

    geometry = p.obj(
        raw["geometry"], f"{f}.geometry", ("modeled", "excluded", "simplifications")
    )
    modeled = []
    for field, item in _records(geometry, "modeled", f"{f}.geometry", minimum=1):
        item = p.obj(item, field, ("ref_id", "role", "description", "source_digest"))
        modeled.append(p.ident(item, "ref_id", field, GEOMETRY_ID))
        p.enum(item, "role", field, GeometryRole)
        p.text(item, "description", field)
        p.digest_text(item, "source_digest", field, nullable=True)
    excluded = []
    for field, item in _records(geometry, "excluded", f"{f}.geometry"):
        item = p.obj(item, field, ("ref_id", "reason"))
        excluded.append(p.ident(item, "ref_id", field, GEOMETRY_ID))
        p.text(item, "reason", field)
    p.unique(modeled + excluded, f"{f}.geometry")
    simplifications = []
    for field, item in _records(geometry, "simplifications", f"{f}.geometry"):
        item = p.obj(item, field, ("simplification_id", "description", "rationale"))
        simplifications.append(p.ident(item, "simplification_id", field, SIM_ID))
        p.text(item, "description", field)
        p.text(item, "rationale", field)
    p.unique(simplifications, f"{f}.geometry.simplifications")
    modeled_set = set(modeled)

    def applies_to(item: dict[str, Any], field: str) -> None:
        p.resolve(
            [p.ident(item, "applies_to", field, GEOMETRY_ID)],
            modeled_set,
            f"{field}.applies_to",
        )

    outputs: dict[str, str] = {}
    for field, item in _records(raw, "target_outputs", f, minimum=1):
        item = p.obj(
            item, field, ("output_id", "description", "kind", "unit", "location_ref")
        )
        output_id = p.ident(item, "output_id", field, QOI_ID)
        p.text(item, "description", field)
        kind, unit = item["kind"], item["unit"]
        if not isinstance(kind, str) or kind not in KINDS:
            raise InputError(f"{field}.kind is unsupported: {kind!r}")
        if not isinstance(unit, str) or unit not in UNITS:
            raise InputError(f"{field}.unit is unsupported: {unit!r}")
        if UNITS[unit].dimension != KINDS[kind]:
            raise DimensionalityError(
                f"{field}: unit {unit!r} is incompatible with kind {kind!r}"
            )
        p.resolve(
            [p.ident(item, "location_ref", field, GEOMETRY_ID)],
            modeled_set,
            f"{field}.location_ref",
        )
        if output_id in outputs:
            raise InputError(
                f"{f}.target_outputs contains duplicate identifier {output_id!r}"
            )
        outputs[output_id] = kind

    acceptance = raw["acceptance"]
    if not isinstance(acceptance, dict) or acceptance.get("kind") not in {
        "criteria",
        "exploratory",
    }:
        raise InputError(f"{f}.acceptance.kind must be 'criteria' or 'exploratory'")
    exploratory_acceptance = acceptance["kind"] == "exploratory"
    if exploratory_acceptance:
        acceptance = p.obj(acceptance, f"{f}.acceptance", ("kind", "rationale"))
        p.text(acceptance, "rationale", f"{f}.acceptance")
    else:
        acceptance = p.obj(acceptance, f"{f}.acceptance", ("kind", "criteria"))
        criteria = []
        for field, item in _records(
            acceptance, "criteria", f"{f}.acceptance", minimum=1
        ):
            item = p.obj(
                item,
                field,
                ("criterion_id", "output_id", "comparator", "limit", "rationale"),
            )
            criteria.append(p.ident(item, "criterion_id", field, ACC_ID))
            output_id = p.ident(item, "output_id", field, QOI_ID)
            p.resolve([output_id], outputs, f"{field}.output_id")
            p.enum(item, "comparator", field, Comparator)
            _quantity(item["limit"], f"{field}.limit", kind=outputs[output_id])
            p.text(item, "rationale", field)
        p.unique(criteria, f"{f}.acceptance.criteria")

    domains = p.enum_list(raw, "domains", f, Domain, minimum=1)

    time = p.obj(raw["time"], f"{f}.time", ("character", "duration", "fidelity"))
    p.enum(time, "character", f"{f}.time", TimeCharacter)
    duration = time["duration"]
    if (
        duration is not None
        and _quantity(duration, f"{f}.time.duration", kind="time").value <= 0
    ):
        raise InputError(f"{f}.time.duration must be greater than zero")
    fidelity = p.obj(time["fidelity"], f"{f}.time.fidelity", ("level", "rationale"))
    p.enum(fidelity, "level", f"{f}.time.fidelity", FidelityLevel)
    p.text(fidelity, "rationale", f"{f}.time.fidelity")

    nonlinear_kinds = []
    for field, item in _records(raw, "nonlinearities", f, minimum=1):
        item = p.obj(item, field, ("kind", "description"))
        nonlinear_kinds.append(p.enum(item, "kind", field, Nonlinearity))
        p.text(item, "description", field)
    p.unique(nonlinear_kinds, f"{f}.nonlinearities")
    if Nonlinearity.NONE_EXPECTED in nonlinear_kinds and len(nonlinear_kinds) > 1:
        raise InputError(
            f"{f}.nonlinearities: none_expected cannot be combined with other kinds"
        )

    scales: dict[str, Scale] = {}
    for field, item in _records(raw, "scales", f, minimum=1):
        item = p.obj(
            item,
            field,
            (
                "scale_id",
                "description",
                "quantity",
                "basis",
                "evidence_ids",
                "assumption_ids",
            ),
        )
        scale_id = p.ident(item, "scale_id", field, SCL_ID)
        p.text(item, "description", field)
        basis = p.enum(item, "basis", field, Basis)
        cited_evidence = p.id_list(item, "evidence_ids", field, EVIDENCE_ID)
        cited_assumptions = p.id_list(item, "assumption_ids", field, ASM_ID)
        p.resolve(cited_evidence, evidence_ids, f"{field}.evidence_ids")
        p.resolve(cited_assumptions, assumption_ids, f"{field}.assumption_ids")
        if not cited_evidence and not cited_assumptions:
            raise InputError(
                f"{field} must cite at least one evidence or assumption identifier"
            )
        if basis is Basis.ASSUMED and not cited_assumptions:
            raise InputError(f"{field} has basis 'assumed' and must cite an assumption")
        retired = [item for item in cited_assumptions if item in retired_assumptions]
        if retired:
            raise InputError(
                f"{field} cites retired assumptions, which cannot support a live input: {', '.join(retired)}"
            )
        if scale_id in scales:
            raise InputError(f"{f}.scales contains duplicate identifier {scale_id!r}")
        scales[scale_id] = Scale(
            scale_id,
            _quantity(item["quantity"], f"{field}.quantity"),
            basis,
            cited_evidence,
            cited_assumptions,
        )

    declarations = []
    for field, item in _records(raw, "group_declarations", f):
        item = p.obj(item, field, ("declaration_id", "group_id", "form_id", "bindings"))
        declaration_id = p.ident(item, "declaration_id", field, GRP_ID)
        form = require_form(item["group_id"], item["form_id"], field)
        bindings = item["bindings"]
        if not isinstance(bindings, dict):
            raise InputError(f"{field}.bindings must be an object")
        for role, scale_id in bindings.items():
            if not isinstance(scale_id, str) or not SCL_ID.fullmatch(scale_id):
                raise InputError(
                    f"{field}.bindings.{role} is not a valid scale identifier: {scale_id!r}"
                )
            p.resolve([scale_id], scales, f"{field}.bindings.{role}")
        bound = list(bindings.values())
        if len(bound) != len(set(bound)):
            raise InputError(
                f"{field}.bindings must bind each scale to at most one role"
            )
        check_binding_kinds(
            form,
            {role: scales[scale_id].quantity for role, scale_id in bindings.items()},
            f"{field}.bindings",
        )
        declarations.append(GroupDeclaration(declaration_id, form, dict(bindings)))
    p.unique((item.declaration_id for item in declarations), f"{f}.group_declarations")

    candidate_model_forms = p.enum_list(
        raw, "candidate_model_forms", f, ModelForm, minimum=1
    )

    materials = []
    for field, item in _records(raw, "materials", f):
        item = p.obj(
            item,
            field,
            ("material_ref", "model_requirement", "record_digest", "applies_to"),
        )
        materials.append(p.ident(item, "material_ref", field, MAT_ID))
        p.enum(item, "model_requirement", field, MaterialModel)
        p.digest_text(item, "record_digest", field, nullable=True)
        targets = p.id_list(item, "applies_to", field, GEOMETRY_ID, minimum=1)
        p.resolve(targets, modeled_set, f"{field}.applies_to")
    p.unique(materials, f"{f}.materials")

    loads = []
    for field, item in _records(raw, "loads", f):
        item = p.obj(
            item, field, ("load_id", "kind", "applies_to", "magnitude", "description")
        )
        loads.append(p.ident(item, "load_id", field, LOAD_ID))
        p.enum(item, "kind", field, LoadKind)
        applies_to(item, field)
        _quantity(item["magnitude"], f"{field}.magnitude")
        p.text(item, "description", field)
    p.unique(loads, f"{f}.loads")

    environment = p.obj(
        raw["environment"],
        f"{f}.environment",
        ("state_id", "description", "conditions"),
    )
    p.ident(environment, "state_id", f"{f}.environment", ENV_ID)
    p.text(environment, "description", f"{f}.environment")
    conditions = p.id_list(environment, "conditions", f"{f}.environment", SCL_ID)
    p.resolve(conditions, scales, f"{f}.environment.conditions")

    boundary = []
    for field, item in _records(raw, "boundary_conditions", f, minimum=1):
        item = p.obj(item, field, ("bc_id", "kind", "applies_to", "description"))
        boundary.append(p.ident(item, "bc_id", field, BC_ID))
        p.enum(item, "kind", field, BoundaryKind)
        applies_to(item, field)
        p.text(item, "description", field)
    p.unique(boundary, f"{f}.boundary_conditions")

    initial = p.obj(
        raw["initial_conditions"],
        f"{f}.initial_conditions",
        ("relevance", "rationale", "conditions"),
    )
    relevance = p.enum(
        initial, "relevance", f"{f}.initial_conditions", InitialRelevance
    )
    p.text(initial, "rationale", f"{f}.initial_conditions")
    initial_ids = []
    for field, item in _records(initial, "conditions", f"{f}.initial_conditions"):
        item = p.obj(item, field, ("ic_id", "description", "applies_to"))
        initial_ids.append(p.ident(item, "ic_id", field, IC_ID))
        p.text(item, "description", field)
        applies_to(item, field)
    p.unique(initial_ids, f"{f}.initial_conditions.conditions")
    if relevance is InitialRelevance.SPECIFIED and not initial_ids:
        raise InputError(
            f"{f}.initial_conditions: 'specified' requires at least one condition"
        )
    if relevance is InitialRelevance.NOT_RELEVANT and initial_ids:
        raise InputError(
            f"{f}.initial_conditions: 'not_relevant' must not list conditions"
        )

    interfaces = []
    for field, item in _records(raw, "interfaces", f):
        item = p.obj(
            item, field, ("interface_id", "between", "coupling", "description")
        )
        interfaces.append(p.ident(item, "interface_id", field, IFC_ID))
        between = p.id_list(item, "between", field, GEOMETRY_ID, minimum=2)
        if len(between) != 2:
            raise InputError(
                f"{field}.between must name exactly two geometry references"
            )
        p.resolve(between, modeled_set, f"{field}.between")
        p.enum(item, "coupling", field, Coupling)
        p.text(item, "description", field)
    p.unique(interfaces, f"{f}.interfaces")

    failure_modes = []
    for field, item in _records(raw, "failure_modes", f, minimum=1):
        item = p.obj(item, field, ("failure_mode_id", "description"))
        failure_modes.append(p.ident(item, "failure_mode_id", field, FM_ID))
        p.text(item, "description", field)
    p.unique(failure_modes, f"{f}.failure_modes")

    uncertainty = []
    for field, item in _records(raw, "uncertainty_sources", f, minimum=1):
        item = p.obj(item, field, ("source_id", "category", "description"))
        uncertainty.append(p.ident(item, "source_id", field, UNC_ID))
        p.enum(item, "category", field, UncertaintyCategory)
        p.text(item, "description", field)
    p.unique(uncertainty, f"{f}.uncertainty_sources")

    validation = []
    for field, item in _records(raw, "validation_evidence", f, minimum=1):
        item = p.obj(
            item, field, ("validation_id", "status", "description", "evidence_ids")
        )
        validation.append(p.ident(item, "validation_id", field, VAL_ID))
        status = p.enum(item, "status", field, ValidationStatus)
        p.text(item, "description", field)
        cited = p.id_list(item, "evidence_ids", field, EVIDENCE_ID)
        p.resolve(cited, evidence_ids, f"{field}.evidence_ids")
        if status is ValidationStatus.AVAILABLE and not cited:
            raise InputError(
                f"{field}: available validation evidence must cite evidence identifiers"
            )
    p.unique(validation, f"{f}.validation_evidence")

    alternatives = []
    for field, item in _records(raw, "model_form_alternatives", f):
        item = p.obj(item, field, ("model_form", "disposition", "rationale"))
        alternatives.append(p.enum(item, "model_form", field, ModelForm))
        p.enum(item, "disposition", field, Disposition)
        p.text(item, "rationale", field)
    p.unique(alternatives, f"{f}.model_form_alternatives")
    rejected = [
        item["model_form"]
        for item in raw["model_form_alternatives"]
        if item["disposition"] == Disposition.REJECTED.value
        and item["model_form"] in candidate_model_forms
    ]
    if rejected:
        raise InputError(
            f"{f}.candidate_model_forms includes forms rejected in model_form_alternatives: {', '.join(rejected)}"
        )
    if criticality is Criticality.CRITICAL and not alternatives:
        raise InputError(
            f"{f}.model_form_alternatives must not be empty for a critical analysis"
        )

    pin = p.obj(
        raw["rule_set_pin"], f"{f}.rule_set_pin", ("rule_set_id", "revision", "digest")
    )
    p.ident(pin, "rule_set_id", f"{f}.rule_set_pin", RULE_SET_ID)
    p.text(pin, "revision", f"{f}.rule_set_pin")
    p.digest_text(pin, "digest", f"{f}.rule_set_pin")

    return PhysicsIntent(
        intent_id=intent_id,
        revision=revision,
        mode=mode,
        criticality=criticality,
        exploratory_acceptance=exploratory_acceptance,
        domains=domains,
        scales=scales,
        declarations=tuple(declarations),
        candidate_model_forms=candidate_model_forms,
        assumptions=tuple(assumptions),
        evidence_kinds=evidence_kinds,
        rule_set_pin=dict(pin),
        raw=raw,
    )
