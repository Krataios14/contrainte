"""Deterministic applicability evaluation, report digest binding and verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..canonical import canonical_bytes, digest, loads_strict
from ..errors import InputError, IntegrityError
from . import _parse as p
from .dimensional import exact_value
from .groups import GROUP_REGISTRY_VERSION, compute_group, registry_digest
from .intent import AssumptionStatus, Basis, Mode, PhysicsIntent, parse_intent
from .rules import CitationKind, RuleSet, parse_rule_set

REPORT_SCHEMA = "contrainte.physics-applicability-report/0.1"

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
}

INTENT_FILE = "physics-intent.json"
RULES_FILE = "applicability-rules.json"
REPORT_FILE = "applicability-report.json"


def check_pin(intent: PhysicsIntent, rules: RuleSet) -> None:
    if intent.rule_set_pin != rules.pin():
        raise p.StalePinError(
            f"intent {intent.intent_id} pins rule set {intent.rule_set_pin}; supplied rule set is {rules.pin()}"
        )


def _blocker(code: str, subject: str) -> dict[str, str]:
    return {"code": code, "subject": subject}


def _warning(code: str, subject: str, message: str) -> dict[str, str]:
    return {"code": code, "subject": subject, "message": message}


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

    warnings: list[dict[str, str]] = []
    review_tasks: list[dict[str, str]] = []
    qualified_blockers: list[dict[str, str]] = []
    controlled_blockers: list[dict[str, str]] = []
    rule_outcomes = []
    form_states: dict[str, list[str]] = {form.value: [] for form in candidates}
    form_rules: dict[str, list[str]] = {form.value: [] for form in candidates}
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
            warnings.append(
                _warning(
                    "RULE_INDETERMINATE",
                    rule.rule_id,
                    f"intent declares no {rule.form.form_id} group for this rule",
                )
            )
            qualified_blockers.append(_blocker("RULE_INDETERMINATE", rule.rule_id))
            controlled_blockers.append(_blocker("RULE_INDETERMINATE", rule.rule_id))
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
                warnings.append(
                    _warning(
                        "RULE_VIOLATED",
                        subject,
                        "group value lies outside every declared valid and marginal band",
                    )
                )
                qualified_blockers.append(_blocker("RULE_VIOLATED", subject))
                controlled_blockers.append(_blocker("RULE_VIOLATED", subject))
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
                warnings.append(
                    _warning(
                        "RULE_MARGINAL",
                        subject,
                        f"marginal band; review task {task_id} opened",
                    )
                )
                qualified_blockers.append(_blocker("MARGINAL_REVIEW_PENDING", task_id))

    model_form_outcomes = []
    for form in candidates:
        states = form_states[form.value]
        if not form_rules[form.value]:
            state = "no_rule"
            warnings.append(
                _warning(
                    "MODEL_FORM_WITHOUT_RULE",
                    form.value,
                    "no applicability rule in the pinned set covers this candidate model form",
                )
            )
            qualified_blockers.append(_blocker("MODEL_FORM_WITHOUT_RULE", form.value))
            controlled_blockers.append(_blocker("MODEL_FORM_WITHOUT_RULE", form.value))
        elif "violated" in states:
            state = "violated"
        elif "indeterminate" in states:
            state = "indeterminate"
        elif "marginal" in states:
            state = "marginal"
        else:
            state = "applicable"
        model_form_outcomes.append(
            {
                "model_form": form.value,
                "state": state,
                "rule_ids": form_rules[form.value],
            }
        )

    all_states = {item["state"] for item in model_form_outcomes}
    if "violated" in all_states:
        applicability_state = "rules_violated"
    elif all_states & {"indeterminate", "no_rule"}:
        applicability_state = "indeterminate"
    elif "marginal" in all_states:
        applicability_state = "marginal_review_required"
    else:
        applicability_state = "rules_satisfied"

    for rule_id in synthetic_rules:
        warnings.append(
            _warning(
                "SYNTHETIC_CITATION",
                rule_id,
                "rule is supported only by a synthetic illustration",
            )
        )
        qualified_blockers.append(_blocker("SYNTHETIC_CITATION", rule_id))
        controlled_blockers.append(_blocker("SYNTHETIC_CITATION", rule_id))
    for scale in intent.scales.values():
        if scale.basis is Basis.AI_PROPOSED:
            warnings.append(
                _warning(
                    "AI_PROPOSED_INPUT", scale.scale_id, "input basis is ai_proposed"
                )
            )
            qualified_blockers.append(_blocker("AI_PROPOSED_INPUT", scale.scale_id))
            controlled_blockers.append(_blocker("AI_PROPOSED_INPUT", scale.scale_id))
    for assumption in intent.assumptions:
        if assumption.critical and assumption.status is AssumptionStatus.OPEN:
            qualified_blockers.append(
                _blocker("OPEN_CRITICAL_ASSUMPTION", assumption.assumption_id)
            )
            controlled_blockers.append(
                _blocker("OPEN_CRITICAL_ASSUMPTION", assumption.assumption_id)
            )
    if intent.exploratory_acceptance:
        qualified_blockers.append(_blocker("EXPLORATORY_ACCEPTANCE", intent.intent_id))
        controlled_blockers.append(_blocker("EXPLORATORY_ACCEPTANCE", intent.intent_id))
    if intent.mode is not Mode.QUALIFIED:
        qualified_blockers.append(
            _blocker("REQUESTED_MODE_NOT_QUALIFIED", intent.mode.value)
        )
    qualified_blockers.append(_blocker("RULE_SET_NOT_APPROVED", rules.rule_set_id))
    qualified_blockers.append(_blocker("NO_IDENTITY_BACKED_APPROVAL", intent.intent_id))
    qualified_blockers.append(_blocker("NO_QUALIFIED_SOLVER_CAPSULE", intent.intent_id))

    body = {
        "schema_version": REPORT_SCHEMA,
        "kernel": {
            "package": "contrainte.physics",
            "group_registry": {
                "version": GROUP_REGISTRY_VERSION,
                "digest": registry_digest(),
            },
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
        "warnings": warnings,
        "review_tasks": review_tasks,
        "qualified_execution": {"permitted": False, "blockers": qualified_blockers},
        "controlled_review_readiness": {
            "state": "blocked"
            if controlled_blockers
            else "ready_for_independent_review",
            "blockers": controlled_blockers,
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
    if report.get("schema_version") != REPORT_SCHEMA:
        raise IntegrityError(
            f"unsupported report schema: {report.get('schema_version')!r}"
        )
    body = {key: value for key, value in report.items() if key != "report_digest"}
    if digest(body) != report["report_digest"]:
        raise IntegrityError("report digest does not match report content")
    rules = parse_rule_set(rules_raw)
    intent = parse_intent(intent_raw)
    bound = report.get("inputs")
    expected_inputs = {
        "intent": {
            "intent_id": intent.intent_id,
            "revision": intent.revision,
            "digest": intent.digest,
        },
        "rule_set": rules.pin(),
    }
    if bound != expected_inputs:
        raise IntegrityError("report is bound to different intent or rule-set digests")
    recomputed = evaluate(intent, rules)
    if canonical_bytes(recomputed) != canonical_bytes(report):
        raise IntegrityError(
            "report differs from independent recomputation of the bound inputs"
        )
    return recomputed


def load_json(path: str | Path) -> Any:
    try:
        content = Path(path).read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc.strerror}") from exc
    return loads_strict(content)


def write_bundle(
    output_dir: str | Path, intent_raw: Any, rules_raw: Any, report: dict[str, Any]
) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / INTENT_FILE).write_bytes(canonical_bytes(intent_raw))
    (directory / RULES_FILE).write_bytes(canonical_bytes(rules_raw))
    (directory / REPORT_FILE).write_bytes(canonical_bytes(report))
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
        document = loads_strict(content)
        if canonical_bytes(document) != content:
            raise IntegrityError(f"retained bundle file is not canonical: {name}")
        documents.append(document)
    report, intent_raw, rules_raw = documents
    return verify_report(report, intent_raw, rules_raw)


__all__ = [
    "CLAIM_BOUNDARY",
    "EXIT_BY_STATE",
    "REPORT_SCHEMA",
    "check_pin",
    "evaluate",
    "evaluate_documents",
    "load_json",
    "verify_bundle",
    "verify_report",
    "write_bundle",
]
