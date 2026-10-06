"""Deterministic applicability evaluation, report digest binding and verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..canonical import canonical_bytes, digest, loads_strict
from ..errors import ContrainteError, InputError, IntegrityError
from . import _parse as p
from .dimensional import exact_value
from .groups import compute_group
from .intent import (
    AssumptionStatus,
    Basis,
    IntentEvidenceKind,
    Mode,
    PhysicsIntent,
    parse_intent,
)
from .model_forms import MODEL_FORMS
from .registry import REGISTRY_VERSION, registry_digest
from .rules import CitationKind, RuleSet, parse_rule_set

REPORT_SCHEMA = "contrainte.physics-applicability-report/0.2"
SUPERSEDED_REPORT_SCHEMAS = ("contrainte.physics-applicability-report/0.1",)

CLAIM_BOUNDARY = (
    "Rule applicability only: declared dimensionless groups were computed exactly from declared inputs and "
    "classified against caller-declared, cited bands. This is not physical validation, solver qualification, "
    "intended-use acceptance or release approval."
)

EXIT_BY_STATE = {
    "rules_satisfied": 0,
    "marginal_review_required": 10,
    "indeterminate": 11,
    "rules_violated": 12,
    "considerations_review_required": 13,
}

INTENT_FILE = "physics-intent.json"
RULES_FILE = "applicability-rules.json"
REPORT_FILE = "applicability-report.json"


class OutputError(ContrainteError):
    """Raised when the report bundle or another requested output cannot be written."""


def check_pin(intent: PhysicsIntent, rules: RuleSet) -> None:
    if intent.rule_set_pin != rules.pin():
        raise p.StalePinError(
            f"intent {intent.intent_id} pins rule set {intent.rule_set_pin}; supplied rule set is {rules.pin()}"
        )


def _blocker(code: str, subject: str) -> dict[str, str]:
    return {"code": code, "subject": subject}


def _warning(code: str, subject: str, message: str) -> dict[str, str]:
    return {"code": code, "subject": subject, "message": message}


class _Gates:
    def __init__(self) -> None:
        self.warnings: list[dict[str, str]] = []
        self.qualified: list[dict[str, str]] = []
        self.controlled: list[dict[str, str]] = []

    def block(
        self,
        code: str,
        subject: str,
        message: str | None = None,
        *,
        controlled: bool = True,
    ) -> None:
        if message is not None:
            self.warnings.append(_warning(code, subject, message))
        self.qualified.append(_blocker(code, subject))
        if controlled:
            self.controlled.append(_blocker(code, subject))


def _input_support(intent: PhysicsIntent, gates: _Gates) -> None:
    """Gate every scale that feeds a computed group on its actual cited support."""

    statuses = {item.assumption_id: item.status for item in intent.assumptions}
    bound: list[str] = []
    for declaration in intent.declarations:
        bound.extend(
            item for item in declaration.bindings.values() if item not in bound
        )
    for scale_id in bound:
        scale = intent.scales[scale_id]
        synthetic = [
            item
            for item in scale.evidence_ids
            if intent.evidence_kinds[item] is IntentEvidenceKind.SYNTHETIC_ILLUSTRATION
        ]
        real = [item for item in scale.evidence_ids if item not in synthetic]
        accepted = [
            item
            for item in scale.assumption_ids
            if statuses[item] is AssumptionStatus.ACCEPTED
        ]
        open_ = [
            item
            for item in scale.assumption_ids
            if statuses[item] is AssumptionStatus.OPEN
        ]
        if synthetic:
            gates.warnings.append(
                _warning(
                    "SYNTHETIC_INPUT_EVIDENCE",
                    scale_id,
                    f"bound input cites synthetic illustration evidence: {', '.join(synthetic)}",
                )
            )
        if not real and not accepted:
            cited = [f"synthetic evidence {item}" for item in synthetic] + [
                f"open assumption {item}" for item in open_
            ]
            gates.block(
                "INPUT_SUPPORT_NOT_QUALIFYING",
                scale_id,
                "bound input has no non-synthetic evidence and no accepted assumption"
                + (f" (cites only {', '.join(cited)})" if cited else ""),
            )


def evaluate(intent: PhysicsIntent, rules: RuleSet) -> dict[str, Any]:
    """Evaluate a parsed intent against a parsed, pinned rule set and return the sealed report."""

    check_pin(intent, rules)
    candidates = intent.candidate_model_forms

    groups = []
    values = {}
    for declaration in intent.declarations:
        quantities = {
            role: intent.scales[scale_id].quantity
            for role, scale_id in declaration.bindings.items()
        }
        value = compute_group(
            declaration.form,
            quantities,
            f"intent.group_declarations.{declaration.declaration_id}",
        )
        values[declaration.declaration_id] = value
        groups.append(
            {
                "declaration_id": declaration.declaration_id,
                "group_id": declaration.form.group_id,
                "form_id": declaration.form.form_id,
                "symbol": declaration.form.symbol,
                "expression": declaration.form.expression,
                "inputs": [
                    {
                        "role": role.role,
                        "exponent": role.exponent,
                        "scale_id": declaration.bindings[role.role],
                        "basis": intent.scales[
                            declaration.bindings[role.role]
                        ].basis.value,
                        "quantity": quantities[role.role].as_dict(),
                        "si_value": exact_value(quantities[role.role].si_value),
                    }
                    for role in declaration.form.roles
                ],
                "value": exact_value(value),
            }
        )

    gates = _Gates()
    review_tasks: list[dict[str, str]] = []
    rule_outcomes = []
    form_states: dict[str, list[str]] = {form.value: [] for form in candidates}
    form_rules: dict[str, list[str]] = {form.value: [] for form in candidates}
    form_groups: dict[str, set[str]] = {form.value: set() for form in candidates}
    synthetic_rules = []

    for rule in rules.rules:
        base = {
            "rule_id": rule.rule_id,
            "rule_version": rule.rule_version,
            "model_form": rule.model_form.value,
            "group_id": rule.form.group_id,
            "form_id": rule.form.form_id,
            "citation_ids": list(rule.citation_ids),
            "escalation_model_forms": [form.value for form in rule.escalation],
        }
        if rule.model_form not in candidates:
            rule_outcomes.append(
                base
                | {
                    "declaration_id": None,
                    "outcome": "not_selected",
                    "reason": "model_form_not_candidate",
                    "value": None,
                    "matched_band": None,
                }
            )
            continue
        form_rules[rule.model_form.value].append(rule.rule_id)
        form_groups[rule.model_form.value].add(rule.form.group_id)
        if any(
            rules.citations[item].kind is CitationKind.SYNTHETIC_ILLUSTRATION
            for item in rule.citation_ids
        ):
            synthetic_rules.append(rule.rule_id)
        matching = [
            item
            for item in intent.declarations
            if item.form.form_id == rule.form.form_id
        ]
        if not matching:
            rule_outcomes.append(
                base
                | {
                    "declaration_id": None,
                    "outcome": "indeterminate",
                    "reason": "group_not_declared",
                    "value": None,
                    "matched_band": None,
                }
            )
            form_states[rule.model_form.value].append("indeterminate")
            gates.block(
                "RULE_INDETERMINATE",
                rule.rule_id,
                f"intent declares no {rule.form.form_id} group for this rule",
            )
            continue
        for declaration in matching:
            value = values[declaration.declaration_id]
            outcome, interval = rule.classify(value)
            subject = f"{rule.rule_id}/{declaration.declaration_id}"
            rule_outcomes.append(
                base
                | {
                    "declaration_id": declaration.declaration_id,
                    "outcome": outcome,
                    "reason": None,
                    "value": exact_value(value),
                    "matched_band": None
                    if interval is None
                    else {"band": outcome, "interval": interval.raw},
                }
            )
            form_states[rule.model_form.value].append(outcome)
            if outcome == "violated":
                gates.block(
                    "RULE_VIOLATED",
                    subject,
                    "group value lies outside every declared valid and marginal band",
                )
            elif outcome == "marginal":
                task_id = f"RVW-{len(review_tasks) + 1}"
                review_tasks.append(
                    {
                        "task_id": task_id,
                        "kind": "marginal_applicability_review",
                        "rule_id": rule.rule_id,
                        "declaration_id": declaration.declaration_id,
                        "review_role": rule.review_role,
                        "status": "open",
                    }
                )
                gates.warnings.append(
                    _warning(
                        "RULE_MARGINAL",
                        subject,
                        f"marginal band; review task {task_id} opened",
                    )
                )
                gates.block("MARGINAL_REVIEW_PENDING", task_id, controlled=False)

    model_form_outcomes = []
    for form in candidates:
        entry = MODEL_FORMS[form]
        states = form_states[form.value]
        missing = [
            group
            for group in entry.required_groups
            if group not in form_groups[form.value]
        ]
        considerations = [item.consideration_id for item in entry.unevaluated]
        if not form_rules[form.value]:
            gates.block(
                "MODEL_FORM_WITHOUT_RULE",
                form.value,
                "no applicability rule in the pinned set covers this candidate model form",
            )
        for group in missing:
            gates.block(
                "REQUIRED_GROUP_NOT_COVERED",
                f"{form.value}/{group}",
                f"{REGISTRY_VERSION} requires a {group} rule for {form.value}; the pinned set has none",
            )
        for item in entry.unevaluated:
            gates.block(
                "CONSIDERATION_NOT_EVALUATED",
                f"{form.value}/{item.consideration_id}",
                f"{item.source}: {item.description} This kernel cannot evaluate it; independent review must.",
            )
        if "violated" in states:
            state = "violated"
        elif not form_rules[form.value]:
            state = "no_rule"
        elif "indeterminate" in states or missing:
            state = "indeterminate"
        elif "marginal" in states:
            state = "marginal"
        elif considerations:
            state = "considerations_unevaluated"
        else:
            state = "applicable"
        model_form_outcomes.append(
            {
                "model_form": form.value,
                "state": state,
                "rule_ids": form_rules[form.value],
                "required_groups": list(entry.required_groups),
                "missing_required_groups": missing,
                "unevaluated_considerations": considerations,
            }
        )

    all_states = {item["state"] for item in model_form_outcomes}
    if "violated" in all_states:
        applicability_state = "rules_violated"
    elif all_states & {"indeterminate", "no_rule"}:
        applicability_state = "indeterminate"
    elif "marginal" in all_states:
        applicability_state = "marginal_review_required"
    elif any(item["unevaluated_considerations"] for item in model_form_outcomes):
        applicability_state = "considerations_review_required"
    else:
        applicability_state = "rules_satisfied"

    for rule_id in synthetic_rules:
        gates.block(
            "SYNTHETIC_CITATION",
            rule_id,
            "rule is supported only by a synthetic illustration",
        )
    _input_support(intent, gates)
    for scale in intent.scales.values():
        if scale.basis is Basis.AI_PROPOSED:
            gates.block(
                "AI_PROPOSED_INPUT", scale.scale_id, "input basis is ai_proposed"
            )
    for assumption in intent.assumptions:
        if assumption.critical and assumption.status is AssumptionStatus.OPEN:
            gates.block("OPEN_CRITICAL_ASSUMPTION", assumption.assumption_id)
    if intent.exploratory_acceptance:
        gates.block("EXPLORATORY_ACCEPTANCE", intent.intent_id)
    if intent.mode is not Mode.QUALIFIED:
        gates.block("REQUESTED_MODE_NOT_QUALIFIED", intent.mode.value, controlled=False)
    gates.block("RULE_SET_NOT_APPROVED", rules.rule_set_id, controlled=False)
    gates.block("NO_IDENTITY_BACKED_APPROVAL", intent.intent_id, controlled=False)
    gates.block("NO_QUALIFIED_SOLVER_CAPSULE", intent.intent_id, controlled=False)

    body = {
        "schema_version": REPORT_SCHEMA,
        "kernel": {
            "package": "contrainte.physics",
            "registry": {"version": REGISTRY_VERSION, "digest": registry_digest()},
        },
        "inputs": {
            "intent": {
                "intent_id": intent.intent_id,
                "revision": intent.revision,
                "digest": intent.digest,
            },
            "rule_set": rules.pin(),
        },
        "requested_mode": intent.mode.value,
        "output_label": "exploratory"
        if intent.mode is Mode.EXPLORATION
        else "non_release",
        "groups": groups,
        "rule_outcomes": rule_outcomes,
        "model_form_outcomes": model_form_outcomes,
        "applicability_state": applicability_state,
        "warnings": gates.warnings,
        "review_tasks": review_tasks,
        "qualified_execution": {"permitted": False, "blockers": gates.qualified},
        "controlled_review_readiness": {
            "state": "blocked" if gates.controlled else "ready_for_independent_review",
            "blockers": gates.controlled,
        },
        "authority_promotion_permitted": False,
        "authority": {
            "release_authority": False,
            "approval_authority": False,
            "write_authority": False,
            "control_authority": False,
            "human_review_required": True,
        },
        "qualification_level": "none",
        "output_basis": "computed_from_declared_inputs",
        "claim_boundary": CLAIM_BOUNDARY,
        "unsupported": {
            "declared_domains_without_execution": [
                domain.value for domain in intent.domains
            ],
            "execution_available_domains": [],
            "kernel_scope": "intent and applicability only; no solver plan, adapter, capsule or execution",
        },
    }
    return body | {"report_digest": digest(body)}


def evaluate_documents(intent_raw: Any, rules_raw: Any) -> dict[str, Any]:
    rules = parse_rule_set(rules_raw)
    intent = parse_intent(intent_raw)
    return evaluate(intent, rules)


def verify_report(report: Any, intent_raw: Any, rules_raw: Any) -> dict[str, Any]:
    """Verify a report by self-digest, input binding and full recomputation from the inputs."""

    if not isinstance(report, dict) or not isinstance(report.get("report_digest"), str):
        raise IntegrityError("report must be an object with a report_digest")
    version = report.get("schema_version")
    if version in SUPERSEDED_REPORT_SCHEMAS:
        raise IntegrityError(
            f"report schema {version!r} is a superseded unpublished draft; re-evaluate"
        )
    if version != REPORT_SCHEMA:
        raise IntegrityError(f"unsupported report schema: {version!r}")
    try:
        p.require_unicode_text(report, "report")
    except InputError as exc:
        raise IntegrityError(str(exc)) from exc
    body = {key: value for key, value in report.items() if key != "report_digest"}
    try:
        recorded = digest(body)
    except RecursionError as exc:
        raise IntegrityError("report is nested too deeply to verify") from exc
    if recorded != report["report_digest"]:
        raise IntegrityError("report digest does not match report content")
    rules = parse_rule_set(rules_raw)
    intent = parse_intent(intent_raw)
    expected_inputs = {
        "intent": {
            "intent_id": intent.intent_id,
            "revision": intent.revision,
            "digest": intent.digest,
        },
        "rule_set": rules.pin(),
    }
    if report.get("inputs") != expected_inputs:
        raise IntegrityError("report is bound to different intent or rule-set digests")
    recomputed = evaluate(intent, rules)
    if canonical_bytes(recomputed) != canonical_bytes(report):
        raise IntegrityError(
            "report differs from independent recomputation of the bound inputs"
        )
    return recomputed


def decode_json(
    content: bytes, label: str, error: type[ContrainteError] = InputError
) -> Any:
    """Decode strict UTF-8 JSON bytes, mapping every decoding failure to a controlled error.

    Bytes are decoded as UTF-8 first (a leading BOM is ignored) so that the JSON library cannot
    silently accept UTF-16 or UTF-32 input.
    """

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise error(f"{label} is not valid UTF-8 JSON") from exc
    try:
        return loads_strict(text)
    except InputError as exc:
        if error is InputError:
            raise
        raise error(f"{label}: {exc}") from exc
    except RecursionError as exc:
        raise error(f"{label} is nested too deeply") from exc
    except (
        ValueError
    ) as exc:  # e.g. integer literals beyond the interpreter digit limit
        raise error(f"{label} cannot be decoded: {exc}") from exc


def load_json(path: str | Path) -> Any:
    try:
        content = Path(path).read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc.strerror}") from exc
    return decode_json(content, str(path))


def write_bundle(
    output_dir: str | Path, intent_raw: Any, rules_raw: Any, report: dict[str, Any]
) -> Path:
    directory = Path(output_dir)
    contents = {
        INTENT_FILE: canonical_bytes(intent_raw),
        RULES_FILE: canonical_bytes(rules_raw),
        REPORT_FILE: canonical_bytes(report),
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for name, content in contents.items():
            (directory / name).write_bytes(content)
    except OSError as exc:
        raise OutputError(
            f"cannot write report bundle to {directory}: {exc.strerror or exc}"
        ) from exc
    return directory / REPORT_FILE


def verify_bundle(directory: str | Path) -> dict[str, Any]:
    """Verify a retained evaluation bundle; every retained file must hold canonical bytes."""

    directory = Path(directory)
    documents = []
    for name in (REPORT_FILE, INTENT_FILE, RULES_FILE):
        path = directory / name
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise IntegrityError(f"retained bundle file is unreadable: {path}") from exc
        document = decode_json(content, f"retained bundle file {name}", IntegrityError)
        try:
            canonical = canonical_bytes(document)
        except (UnicodeEncodeError, RecursionError) as exc:
            raise IntegrityError(
                f"retained bundle file is not canonical: {name}"
            ) from exc
        if canonical != content:
            raise IntegrityError(f"retained bundle file is not canonical: {name}")
        documents.append(document)
    report, intent_raw, rules_raw = documents
    try:
        return verify_report(report, intent_raw, rules_raw)
    except IntegrityError:
        raise
    except ContrainteError as exc:
        # A retained bundle was valid when written; any later rejection means it was altered.
        raise IntegrityError(
            f"retained bundle input no longer validates: {exc}"
        ) from exc


__all__ = [
    "CLAIM_BOUNDARY",
    "EXIT_BY_STATE",
    "REPORT_SCHEMA",
    "OutputError",
    "check_pin",
    "decode_json",
    "evaluate",
    "evaluate_documents",
    "load_json",
    "verify_bundle",
    "verify_report",
    "write_bundle",
]
