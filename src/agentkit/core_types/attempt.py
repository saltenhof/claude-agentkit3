"""AttemptOutcome und FailureCause — Audit-Log-Klassifikation.

Source of truth:
- AttemptOutcome: FK-39 §39.4.2, Z. 391-402.
- FailureCause: FK-39 §39.4.3, Z. 404-422 (16 Werte).

`AttemptRecord` dokumentiert jeden Phase-Durchlauf typisiert. Die
`AttemptRecord`-Schema-Anpassung selbst gehoert zu AG3-025; diese
Datei stellt nur die Enum-Verfuegbarkeit her.
"""

from __future__ import annotations

from enum import StrEnum


class AttemptOutcome(StrEnum):
    """Phase-Durchlauf-Ergebnis pro FK-39 §39.4.2.

    Attributes:
        COMPLETED: Phase-Versuch erfolgreich abgeschlossen.
        FAILED: Phase-Versuch fehlgeschlagen (Remediation moeglich).
        ESCALATED: Phase-Versuch eskaliert (menschliche Intervention).
        SKIPPED: Phase wurde uebersprungen (z.B. Exploration im
            Execution-Mode).
        YIELDED: Phase in PAUSED-Zustand uebergegangen.
        BLOCKED: Phase durch Guard oder Precondition blockiert.
    """

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    SKIPPED = "SKIPPED"
    YIELDED = "YIELDED"
    BLOCKED = "BLOCKED"


class FailureCause(StrEnum):
    """Failure-Ursache pro FK-39 §39.4.3 (16 Werte).

    Verbindlich ist FK-39 §39.4.3; der historische Story-Header sprach
    von 15 Werten — die Konzept-Tabelle hat 16.

    Attributes:
        GUARD_REJECTED: Transition-Guard hat den Phaseneintritt abgelehnt.
        STRUCTURAL_CHECK_FAIL: Verify-Schicht 1 (deterministisch)
            fehlgeschlagen.
        SEMANTIC_REVIEW_FAIL: Verify-Schicht 2 (LLM-Review) fehlgeschlagen.
        ADVERSARIAL_FINDING: Verify-Schicht 3 (Adversarial) hat Befunde.
        POLICY_FAIL: Verify-Schicht 4 (Policy Engine) hat FAIL entschieden.
        WORKER_BLOCKED: Worker meldet unloesbaren Constraint.
        INTEGRITY_FAIL: Integrity-Gate in Closure fehlgeschlagen.
        MERGE_FAIL: Merge-Konflikt in Closure.
        PREFLIGHT_FAIL: Preflight-Checks in Setup fehlgeschlagen.
        MAX_ROUNDS_EXCEEDED: Feedback-Runden-Limit erreicht.
        TIMEOUT: Phase hat Zeitlimit ueberschritten.
        GUARD_FAILED: Guard-Funktion hat eine unerwartete Exception
            geworfen (technischer Fehler).
        HANDLER_EXCEPTION: Unerwartete Exception im Phase-Handler.
        PRECONDITION_FAILED: Semantische Precondition nicht erfuellt
            (FK-45 §45.2).
        HANDLER_REPORTED_FAILED: Handler hat selbst FAILED gemeldet.
        HANDLER_REPORTED_ESCALATED: Handler hat selbst ESCALATED gemeldet.
    """

    GUARD_REJECTED = "GUARD_REJECTED"
    STRUCTURAL_CHECK_FAIL = "STRUCTURAL_CHECK_FAIL"
    SEMANTIC_REVIEW_FAIL = "SEMANTIC_REVIEW_FAIL"
    ADVERSARIAL_FINDING = "ADVERSARIAL_FINDING"
    POLICY_FAIL = "POLICY_FAIL"
    WORKER_BLOCKED = "WORKER_BLOCKED"
    INTEGRITY_FAIL = "INTEGRITY_FAIL"
    MERGE_FAIL = "MERGE_FAIL"
    PREFLIGHT_FAIL = "PREFLIGHT_FAIL"
    MAX_ROUNDS_EXCEEDED = "MAX_ROUNDS_EXCEEDED"
    TIMEOUT = "TIMEOUT"
    GUARD_FAILED = "GUARD_FAILED"
    HANDLER_EXCEPTION = "HANDLER_EXCEPTION"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    HANDLER_REPORTED_FAILED = "HANDLER_REPORTED_FAILED"
    HANDLER_REPORTED_ESCALATED = "HANDLER_REPORTED_ESCALATED"
