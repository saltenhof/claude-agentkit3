"""Typed exceptions of the failure-corpus BC (DK-07 §7.3.6 / FK-41 §41.4.3).

FAIL-CLOSED: an IngressCriteria reject is an exception with structured
``reason_codes`` — no silent discarding (guardrail FAIL CLOSED, AG3-028 AK#3).

ZERO DEBT (Codex-r2 remediation): every ``IncidentRejectReason`` is actually
reachable from the ``IngressCriteria`` implementation; there is no dead
reason_code anymore. The former ``BELOW_MIN_SEVERITY`` is removed — DK-07
§7.3.6 is explicitly a pure OR (severity is NO hard floor anymore).
"""

from __future__ import annotations

from enum import StrEnum


class IncidentRejectReason(StrEnum):
    """Structured reason why the IngressCriteria reject a candidate.

    The reason_codes mirror exactly the implemented DK-07 §7.3.6 criteria
    (pure OR of the four admission triggers) plus the exact-duplicate dedup.

    Attributes:
        NOT_SIGNIFICANT: NONE of the four DK-07 §7.3.6 admission criteria apply —
            i.e. severity < MEDIUM AND not merge-blocking AND rework <= 30min
            AND the error type is already in the corpus (not novel). Pure OR:
            a single satisfied criterion is enough for admission.
        DUPLICATE_WINDOW: Exact duplicate of an incident already persisted within
            the time window (dedup; separate reject reason).
    """

    NOT_SIGNIFICANT = "not_significant"
    DUPLICATE_WINDOW = "duplicate_window"


class FailureCorpusError(Exception):
    """Base class for all failure-corpus errors."""


class IncidentRejectedError(FailureCorpusError):
    """An incident candidate was rejected by the IngressCriteria.

    Carries the structured ``reason_codes`` so that caller BCs can react
    deterministically to the reason (instead of string parsing).

    Args:
        reason_codes: Non-empty sequence of the triggering reasons.
        detail: Optional human-readable additional description.

    Raises:
        ValueError: If ``reason_codes`` is empty (FAIL-CLOSED: a reject without
            a reason is a model error).
    """

    def __init__(
        self,
        reason_codes: tuple[IncidentRejectReason, ...],
        *,
        detail: str | None = None,
    ) -> None:
        if not reason_codes:
            raise ValueError("IncidentRejectedError requires at least one reason_code")
        self.reason_codes: tuple[IncidentRejectReason, ...] = tuple(reason_codes)
        self.detail = detail
        codes = ", ".join(code.value for code in self.reason_codes)
        message = f"incident candidate rejected: {codes}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


__all__ = [
    "FailureCorpusError",
    "IncidentRejectReason",
    "IncidentRejectedError",
]
