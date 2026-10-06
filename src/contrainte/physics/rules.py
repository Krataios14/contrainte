"""Versioned, citation-bound applicability rules (``contrainte.applicability-rules/0.2``)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Any

from ..canonical import digest, digest_bytes
from ..errors import InputError, IntegrityError
from ..evidence import require_zoned_timestamp
from . import _parse as p
from .dimensional import parse_exact
from .groups import GroupForm, require_form
from .model_forms import MODEL_FORMS, ModelForm
from .registry import REGISTRY_VERSION, registry_digest

RULES_SCHEMA = "contrainte.applicability-rules/0.2"
SUPERSEDED_RULES_SCHEMAS = ("contrainte.applicability-rules/0.1",)

RULE_SET_ID = p.identifier_pattern("RULESET")
RULE_ID = p.identifier_pattern("RULE")
EVIDENCE_ID = p.identifier_pattern("EVD")


class AuthoringStatus(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"


class CitationKind(str, Enum):
    STANDARD = "standard"
    SOURCE_DOCUMENT = "source_document"
    DATABASE_RECORD = "database_record"
    TEST_RECORD = "test_record"
    ENGINEERING_RATIONALE = "engineering_rationale"
    SYNTHETIC_ILLUSTRATION = "synthetic_illustration"


@dataclass(frozen=True)
class Bound:
    value: Fraction
    inclusive: bool


@dataclass(frozen=True)
class Interval:
    lower: Bound | None
    upper: Bound | None
    raw: dict[str, Any]

    def contains(self, value: Fraction) -> bool:
        lower, upper = self.lower, self.upper
        if lower is not None and (
            value < lower.value or (value == lower.value and not lower.inclusive)
        ):
            return False
        return (
            upper is None
            or value < upper.value
            or (value == upper.value and upper.inclusive)
        )


@dataclass(frozen=True)
class Citation:
    evidence_id: str
    kind: CitationKind


@dataclass(frozen=True)
class Rule:
    rule_id: str
    rule_version: int
    model_form: ModelForm
    form: GroupForm
    valid: tuple[Interval, ...]
    marginal: tuple[Interval, ...]
    citation_ids: tuple[str, ...]
    review_role: str
    escalation: tuple[ModelForm, ...]

    def classify(self, value: Fraction) -> tuple[str, Interval | None]:
        for interval in self.valid:
            if interval.contains(value):
                return "valid", interval
        for interval in self.marginal:
            if interval.contains(value):
                return "marginal", interval
        return "violated", None


@dataclass(frozen=True)
class RuleSet:
    rule_set_id: str
    revision: str
    citations: dict[str, Citation]
    rules: tuple[Rule, ...]
    raw: dict[str, Any]

    @property
    def digest(self) -> str:
        return digest(self.raw)

    def pin(self) -> dict[str, str]:
        return {
            "rule_set_id": self.rule_set_id,
            "revision": self.revision,
            "digest": self.digest,
        }


def _bound(raw: Any, field: str) -> Bound | None:
    if raw is None:
        return None
    raw = p.obj(raw, field, ("value", "inclusive"))
    return Bound(
        parse_exact(raw["value"], f"{field}.value"), p.boolean(raw, "inclusive", field)
    )


def _interval(raw: Any, field: str) -> Interval:
    raw = p.obj(raw, field, ("lower", "upper"))
    lower = _bound(raw["lower"], f"{field}.lower")
    upper = _bound(raw["upper"], f"{field}.upper")
    if lower is not None and upper is not None and lower.value >= upper.value:
        raise InputError(
            f"{field} is reversed or empty: lower must be strictly below upper"
        )
    return Interval(lower, upper, raw)


def _tighter(a: Bound | None, b: Bound | None, *, lower: bool) -> Bound | None:
    # ``None`` is unbounded; at equal values only a shared inclusive endpoint stays inclusive.
    if a is None or b is None:
        return b if a is None else a
    if a.value == b.value:
        return Bound(a.value, a.inclusive and b.inclusive)
    if lower:
        return a if a.value > b.value else b
    return a if a.value < b.value else b


def _intersects(a: Interval, b: Interval) -> bool:
    low = _tighter(a.lower, b.lower, lower=True)
    high = _tighter(a.upper, b.upper, lower=False)
    if low is None or high is None:
        return True
    if low.value != high.value:
        return low.value < high.value
    return low.inclusive and high.inclusive


def _check_disjoint(intervals: list[tuple[str, Interval]], field: str) -> None:
    for index, (name_a, a) in enumerate(intervals):
        for name_b, b in intervals[index + 1 :]:
            if _intersects(a, b):
                raise InputError(f"{field}: intervals {name_a} and {name_b} overlap")


def _citation(raw: Any, field: str) -> Citation:
    raw = p.obj(
        raw,
        field,
        (
            "evidence_id",
            "kind",
            "title",
            "authority",
            "locator",
            "revision",
            "retrieved_at",
            "excerpt",
            "excerpt_digest",
        ),
    )
    evidence_id = p.ident(raw, "evidence_id", field, EVIDENCE_ID)
    kind = p.enum(raw, "kind", field, CitationKind)
    for name in ("title", "authority", "locator", "revision", "excerpt"):
        p.text(raw, name, field)
    require_zoned_timestamp(p.text(raw, "retrieved_at", field), f"{field}.retrieved_at")
    declared = p.digest_text(raw, "excerpt_digest", field)
    actual = digest_bytes(raw["excerpt"].encode("utf-8"))
    if declared != actual:
        raise IntegrityError(
            f"{field} excerpt digest mismatch: declared {declared}, actual {actual}"
        )
    return Citation(evidence_id, kind)


def _rule(raw: Any, field: str, citations: dict[str, Citation]) -> Rule:
    raw = p.obj(
        raw,
        field,
        (
            "rule_id",
            "rule_version",
            "title",
            "model_form",
            "group",
            "bands",
            "rationale",
            "citation_ids",
            "on_marginal",
        ),
        ("escalation_model_forms",),
    )
    rule_id = p.ident(raw, "rule_id", field, RULE_ID)
    version = p.positive_int(raw, "rule_version", field)
    p.text(raw, "title", field)
    p.text(raw, "rationale", field)
    model_form = p.enum(raw, "model_form", field, ModelForm)
    group = p.obj(raw["group"], f"{field}.group", ("group_id", "form_id"))
    form = require_form(group["group_id"], group["form_id"], f"{field}.group")
    admissible = MODEL_FORMS[model_form].admissible_groups
    if form.group_id not in admissible:
        raise InputError(
            f"{field}: group {form.group_id!r} is not admissible for model form {model_form.value!r} "
            f"under {REGISTRY_VERSION} (admissible: {', '.join(admissible) or 'none'})"
        )
    bands = p.obj(raw["bands"], f"{field}.bands", ("valid", "marginal"))
    valid = tuple(
        _interval(item, f"{field}.bands.valid[{index}]")
        for index, item in enumerate(
            p.array(bands, "valid", f"{field}.bands", minimum=1)
        )
    )
    marginal = tuple(
        _interval(item, f"{field}.bands.marginal[{index}]")
        for index, item in enumerate(p.array(bands, "marginal", f"{field}.bands"))
    )
    _check_disjoint(
        [(f"valid[{i}]", item) for i, item in enumerate(valid)]
        + [(f"marginal[{i}]", item) for i, item in enumerate(marginal)],
        f"{field}.bands",
    )
    citation_ids = p.id_list(raw, "citation_ids", field, EVIDENCE_ID, minimum=1)
    p.resolve(citation_ids, citations, f"{field}.citation_ids")
    on_marginal = p.obj(
        raw["on_marginal"], f"{field}.on_marginal", ("review_role", "instruction")
    )
    review_role = p.text(on_marginal, "review_role", f"{field}.on_marginal")
    p.text(on_marginal, "instruction", f"{field}.on_marginal")
    escalation: tuple[ModelForm, ...] = ()
    if "escalation_model_forms" in raw:
        escalation = p.enum_list(
            raw, "escalation_model_forms", field, ModelForm, minimum=1
        )
    return Rule(
        rule_id,
        version,
        model_form,
        form,
        valid,
        marginal,
        citation_ids,
        review_role,
        escalation,
    )


def parse_rule_set(raw: Any) -> RuleSet:
    field = "rule_set"
    p.require_unicode_text(raw, field)
    p.schema_version(raw, "applicability-rules", RULES_SCHEMA, SUPERSEDED_RULES_SCHEMAS)
    raw = p.obj(
        raw,
        field,
        (
            "schema_version",
            "rule_set_id",
            "revision",
            "title",
            "authoring",
            "registry",
            "citations",
            "rules",
        ),
    )
    rule_set_id = p.ident(raw, "rule_set_id", field, RULE_SET_ID)
    revision = p.text(raw, "revision", field)
    p.text(raw, "title", field)
    authoring = p.obj(raw["authoring"], f"{field}.authoring", ("owner", "status"))
    p.text(authoring, "owner", f"{field}.authoring")
    p.enum(authoring, "status", f"{field}.authoring", AuthoringStatus)
    registry = p.obj(raw["registry"], f"{field}.registry", ("version", "digest"))
    p.digest_text(registry, "digest", f"{field}.registry")
    if (
        registry["version"] != REGISTRY_VERSION
        or registry["digest"] != registry_digest()
    ):
        raise p.StalePinError(
            f"{field}.registry pins {registry['version']!r} {registry['digest']!r}; "
            f"this kernel provides {REGISTRY_VERSION!r} {registry_digest()!r}"
        )
    citation_list = [
        _citation(item, f"{field}.citations[{index}]")
        for index, item in enumerate(p.array(raw, "citations", field, minimum=1))
    ]
    p.unique((item.evidence_id for item in citation_list), f"{field}.citations")
    citations = {item.evidence_id: item for item in citation_list}
    rules = tuple(
        _rule(item, f"{field}.rules[{index}]", citations)
        for index, item in enumerate(p.array(raw, "rules", field, minimum=1))
    )
    p.unique((rule.rule_id for rule in rules), f"{field}.rules")
    return RuleSet(rule_set_id, revision, citations, rules, raw)
