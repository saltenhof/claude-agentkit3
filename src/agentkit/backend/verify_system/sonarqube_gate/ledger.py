"""Accepted-exception ledger artefact (FK-33 §33.6.4).

The ledger is the single versioned source of truth for deliberate
SonarQube exceptions ("Accepted" issues). Each entry carries a robust,
refactor-stable identity (NOT ``issueKey``/line number). Its hash is
bound into the commit-bound attestation (FK-33 §33.6.3,
``exception_ledger_hash``).

Out of scope here (AG3-052 §2.2): the six-eyes quorum PROCESS (how the
``approved_by[3]`` votes are collected/enforced). This story owns the
ledger artefact + the mandatory ``approved_by[3]`` fields + the
deterministic reconciler contract (``reconciler.py``).
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, field_validator

from agentkit.backend.verify_system.sonarqube_gate.errors import LedgerInvalidError

#: Number of independent approvals required (six-eyes: proposer + 2 QA).
_REQUIRED_APPROVERS = 3


class AcceptedExceptionLedgerEntry(BaseModel):
    """One accepted-exception ledger entry (FK-33 §33.6.4 fields).

    Identity is ``normalized_code_fingerprint`` (formal entity identity
    key). Matching against current Sonar issues uses the stable triple
    (``rule_key`` + ``normalized_code_fingerprint`` +
    ``expected_message_pattern``), never ``issueKey``/line.

    Attributes:
        rule_key: SonarQube rule key (e.g. ``python:S1192``).
        file_path: Repo-relative file path of the accepted issue.
        normalized_code_fingerprint: Refactor-stable fingerprint of the
            offending code block (identity key).
        expected_message_pattern: Regex/glob the issue message must match.
        rationale: Semantic justification for the acceptance.
        approved_by: Exactly three independent approvers (six-eyes).
        approved_commit: Commit at which the acceptance was approved.
        expiry: Expiry / ``review_after`` marker (ISO date or empty).
        scope: ``branch-only`` or ``main-eligible``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_key: str
    file_path: str
    normalized_code_fingerprint: str
    expected_message_pattern: str
    rationale: str
    approved_by: tuple[str, ...]
    approved_commit: str
    expiry: str
    scope: str

    @field_validator("approved_by")
    @classmethod
    def _exactly_three_distinct(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """FK-33 §33.6.4: exactly three distinct, non-empty approvers."""
        if len(value) != _REQUIRED_APPROVERS:
            msg = (
                f"approved_by requires exactly {_REQUIRED_APPROVERS} approvers "
                f"(six-eyes, FK-33 §33.6.4); got {len(value)}"
            )
            raise LedgerInvalidError(msg)
        if any(not approver.strip() for approver in value):
            raise LedgerInvalidError("approved_by entries must be non-empty (FK-33 §33.6.4)")
        if len(set(value)) != _REQUIRED_APPROVERS:
            raise LedgerInvalidError(
                "approved_by must be three DISTINCT approvers; no agent may "
                "approve its own exception (FK-33 §33.6.4)"
            )
        return value

    @field_validator("scope")
    @classmethod
    def _known_scope(cls, value: str) -> str:
        """FK-33 §33.6.4: scope is ``branch-only`` or ``main-eligible``."""
        if value not in ("branch-only", "main-eligible"):
            raise LedgerInvalidError(
                f"scope must be 'branch-only' or 'main-eligible'; got {value!r}"
            )
        return value


class AcceptedExceptionLedger(BaseModel):
    """Versioned accepted-exception ledger document (FK-33 §33.6.4).

    Attributes:
        schema_version: Ledger schema version.
        entries: The accepted-exception entries.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0"
    entries: tuple[AcceptedExceptionLedgerEntry, ...] = ()

    def content_hash(self) -> str:
        """Stable SHA-256 over the canonical ledger content.

        Bound into the attestation as ``exception_ledger_hash``
        (FK-33 §33.6.3). Deterministic across runs: entries are sorted by
        identity and serialised with sorted keys.

        Returns:
            64-char lowercase SHA-256 hex digest.
        """
        ordered = sorted(
            (entry.model_dump(mode="json") for entry in self.entries),
            key=lambda item: str(item["normalized_code_fingerprint"]),
        )
        material = json.dumps(
            {"schema_version": self.schema_version, "entries": ordered},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


__all__ = [
    "AcceptedExceptionLedger",
    "AcceptedExceptionLedgerEntry",
]
