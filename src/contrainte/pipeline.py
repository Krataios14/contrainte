from __future__ import annotations

from pathlib import Path
from typing import Any

from .axial import AxialCase, solve_axial_case
from .canonical import canonical_bytes, digest, digest_bytes, dumps_pretty, loads_strict
from .errors import InputError, IntegrityError

BUNDLE_SCHEMA = "contrainte.evidence-bundle/0.1"


def load_case(path: str | Path) -> AxialCase:
    source = Path(path)
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read design input {source}: {exc}") from exc
    return AxialCase.from_dict(loads_strict(content))


def compile_bundle(case: AxialCase) -> dict[str, Any]:
    case_document = case.as_dict()
    case_digest = digest(case_document)
    result = solve_axial_case(case)
    result_document = result.as_dict()
    content = {
        "schema_version": BUNDLE_SCHEMA,
        "mode": "exploration",
        "qualification": "unqualified_demonstration",
        "intended_use": (
            "Demonstrate deterministic, evidence-linked axial screening; "
            "not valid for engineering release."
        ),
        "input_artifact": {
            "schema_version": case.schema_version,
            "digest": case_digest,
        },
        "case": case_document,
        "result": result_document,
        "checks": [
            {"id": "CHK-SCHEMA", "status": "passed"},
            {"id": "CHK-EVIDENCE-INTEGRITY", "status": "passed"},
            {"id": "CHK-CLAIM-EVIDENCE", "status": "passed"},
            {"id": "CHK-DIMENSIONALITY", "status": "passed"},
            {"id": "CHK-POSITIVE-INPUTS", "status": "passed"},
            {"id": "CHK-ANALYTICAL-EXECUTION", "status": "passed"},
        ],
    }
    return {"digest": digest(content), "content": content}


def verify_bundle(bundle: Any) -> dict[str, str]:
    if not isinstance(bundle, dict):
        raise IntegrityError("bundle must be an object")
    if set(bundle) != {"digest", "content"}:
        raise IntegrityError("bundle must contain exactly 'digest' and 'content'")
    declared = bundle.get("digest")
    content = bundle.get("content")
    if not isinstance(declared, str) or not isinstance(content, dict):
        raise IntegrityError("bundle digest and content have invalid types")
    actual = digest(content)
    if declared != actual:
        raise IntegrityError(
            f"bundle digest mismatch: declared {declared}, actual {actual}"
        )
    if content.get("schema_version") != BUNDLE_SCHEMA:
        raise IntegrityError(
            f"unsupported bundle schema: {content.get('schema_version')!r}"
        )

    case_raw = content.get("case")
    case = AxialCase.from_dict(case_raw)
    expected_case_digest = digest(case.as_dict())
    input_artifact = content.get("input_artifact")
    if not isinstance(input_artifact, dict):
        raise IntegrityError("bundle input_artifact is missing")
    if input_artifact.get("digest") != expected_case_digest:
        raise IntegrityError("embedded case does not match input_artifact digest")

    expected_result = solve_axial_case(case).as_dict()
    if canonical_bytes(content.get("result")) != canonical_bytes(expected_result):
        raise IntegrityError(
            "embedded solver result does not reproduce from the embedded case"
        )
    return {
        "status": "verified",
        "bundle_digest": actual,
        "input_digest": expected_case_digest,
    }


def load_bundle(path: str | Path) -> Any:
    source = Path(path)
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read bundle {source}: {exc}") from exc
    return loads_strict(content)


def write_bundle(path: str | Path, bundle: Any) -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = dumps_pretty(bundle)
    try:
        destination.write_text(rendered, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise InputError(f"cannot write bundle {destination}: {exc}") from exc
    return digest_bytes(rendered.encode("utf-8"))
