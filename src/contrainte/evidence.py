from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .canonical import digest_bytes
from .errors import InputError, IntegrityError
from .units import Quantity

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class EvidenceKind(str, Enum):
    SYNTHETIC = "synthetic"
    SOURCE_DOCUMENT = "source_document"
    DATABASE_RECORD = "database_record"
    STANDARD = "standard"
    TEST_RECORD = "test_record"
    SUPPLIER_DECLARATION = "supplier_declaration"


class ClaimBasis(str, Enum):
    MEASURED = "measured"
    SUPPLIER_DECLARED = "supplier_declared"
    STANDARD_SPECIFIED = "standard_specified"
    COMPUTED = "computed"
    CRITICALLY_EVALUATED = "critically_evaluated"
    PREDICTED = "predicted"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    AI_PROPOSED = "ai_proposed"


class ClaimStatus(str, Enum):
    PROPOSED = "proposed"
    VERIFIED = "verified"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    kind: EvidenceKind
    title: str
    authority: str
    locator: str
    revision: str
    retrieved_at: str
    content: str
    content_digest: str

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> EvidenceRef:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        required = (
            "evidence_id",
            "kind",
            "title",
            "authority",
            "locator",
            "revision",
            "retrieved_at",
            "content",
            "content_digest",
        )
        for name in required:
            if not isinstance(raw.get(name), str) or not raw[name]:
                raise InputError(f"{field}.{name} must be a non-empty string")
        try:
            kind = EvidenceKind(raw["kind"])
        except ValueError as exc:
            raise InputError(f"{field}.kind is unsupported: {raw['kind']!r}") from exc
        _require_zoned_timestamp(raw["retrieved_at"], f"{field}.retrieved_at")
        if not _DIGEST_PATTERN.fullmatch(raw["content_digest"]):
            raise InputError(
                f"{field}.content_digest must be a lowercase SHA-256 digest"
            )
        actual = digest_bytes(raw["content"].encode("utf-8"))
        if actual != raw["content_digest"]:
            raise IntegrityError(
                f"{field} content digest mismatch: declared {raw['content_digest']}, actual {actual}"
            )
        return cls(
            evidence_id=raw["evidence_id"],
            kind=kind,
            title=raw["title"],
            authority=raw["authority"],
            locator=raw["locator"],
            revision=raw["revision"],
            retrieved_at=raw["retrieved_at"],
            content=raw["content"],
            content_digest=raw["content_digest"],
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "title": self.title,
            "authority": self.authority,
            "locator": self.locator,
            "revision": self.revision,
            "retrieved_at": self.retrieved_at,
            "content": self.content,
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True)
class Claim:
    claim_id: str
    subject: str
    property_name: str
    quantity: Quantity
    basis: ClaimBasis
    status: ClaimStatus
    evidence_ids: tuple[str, ...]
    applicability: Mapping[str, str]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> Claim:
        if not isinstance(raw, dict):
            raise InputError(f"{field} must be an object")
        for name in ("claim_id", "subject", "property", "basis", "status"):
            if not isinstance(raw.get(name), str) or not raw[name]:
                raise InputError(f"{field}.{name} must be a non-empty string")
        try:
            basis = ClaimBasis(raw["basis"])
        except ValueError as exc:
            raise InputError(f"{field}.basis is unsupported: {raw['basis']!r}") from exc
        try:
            status = ClaimStatus(raw["status"])
        except ValueError as exc:
            raise InputError(
                f"{field}.status is unsupported: {raw['status']!r}"
            ) from exc
        evidence_ids = raw.get("evidence_ids")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            raise InputError(f"{field}.evidence_ids must be a non-empty list")
        if not all(isinstance(item, str) and item for item in evidence_ids):
            raise InputError(f"{field}.evidence_ids must contain non-empty strings")
        applicability = raw.get("applicability", {})
        if not isinstance(applicability, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in applicability.items()
        ):
            raise InputError(f"{field}.applicability must map strings to strings")
        return cls(
            claim_id=raw["claim_id"],
            subject=raw["subject"],
            property_name=raw["property"],
            quantity=Quantity.from_dict(raw.get("quantity"), field=f"{field}.quantity"),
            basis=basis,
            status=status,
            evidence_ids=tuple(evidence_ids),
            applicability=applicability,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "subject": self.subject,
            "property": self.property_name,
            "quantity": self.quantity.as_dict(),
            "basis": self.basis.value,
            "status": self.status.value,
            "evidence_ids": list(self.evidence_ids),
            "applicability": dict(self.applicability),
        }


@dataclass(frozen=True)
class DerivedClaim:
    claim_id: str
    subject: str
    property_name: str
    quantity: Quantity
    parent_claim_ids: tuple[str, ...]
    equation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "subject": self.subject,
            "property": self.property_name,
            "quantity": self.quantity.as_dict(),
            "basis": ClaimBasis.COMPUTED.value,
            "status": ClaimStatus.VERIFIED.value,
            "parent_claim_ids": list(self.parent_claim_ids),
            "equation": self.equation,
        }


def validate_claim_evidence(
    claims: Mapping[str, Claim], evidence: Mapping[str, EvidenceRef]
) -> None:
    if len(claims) != len({claim.claim_id for claim in claims.values()}):
        raise InputError("claim identifiers must be unique")
    for name, claim in claims.items():
        if name != claim.property_name:
            raise InputError(
                f"claim key {name!r} does not match property {claim.property_name!r}"
            )
        missing = [item for item in claim.evidence_ids if item not in evidence]
        if missing:
            raise InputError(
                f"claim {claim.claim_id!r} references missing evidence: {', '.join(missing)}"
            )


def _require_zoned_timestamp(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InputError(f"{field} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputError(f"{field} must include a time-zone offset")


def require_zoned_timestamp(value: str, field: str) -> None:
    _require_zoned_timestamp(value, field)
