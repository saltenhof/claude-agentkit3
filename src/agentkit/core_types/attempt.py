"""AttemptOutcome and FailureCause — audit-log classification.

Source of truth:
- AttemptOutcome: FK-39 §39.4.2, lines 391-402.
- FailureCause: FK-39 §39.4.3, lines 404-422 (16 values).

`AttemptRecord` documents every phase run in a typed manner. The
`AttemptRecord` schema adjustment itself belongs to AG3-025; this file
only provides the enum availability.
"""

from __future__ import annotations

from enum import StrEnum


class AttemptOutcome(StrEnum):
    """Phase-run outcome per FK-39 §39.4.2.

    Attributes:
        COMPLETED: Phase attempt completed successfully.
        FAILED: Phase attempt failed (remediation possible).
        ESCALATED: Phase attempt escalated (human intervention).
        SKIPPED: Phase was skipped (e.g. exploration in execution
            mode).
        YIELDED: Phase transitioned to the PAUSED state.
        BLOCKED: Phase blocked by a guard or precondition.
    """

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    SKIPPED = "SKIPPED"
    YIELDED = "YIELDED"
    BLOCKED = "BLOCKED"


class FailureCause(StrEnum):
    """Failure cause per FK-39 §39.4.3 (16 values).

    FK-39 §39.4.3 is authoritative; the historical story header spoke of
    15 values — the concept table has 16.

    Attributes:
        GUARD_REJECTED: Transition guard rejected the phase entry.
        STRUCTURAL_CHECK_FAIL: Verify layer 1 (deterministic) failed.
        SEMANTIC_REVIEW_FAIL: Verify layer 2 (LLM review) failed.
        ADVERSARIAL_FINDING: Verify layer 3 (adversarial) has findings.
        POLICY_FAIL: Verify layer 4 (policy engine) decided FAIL.
        WORKER_BLOCKED: Worker reports an unsolvable constraint.
        INTEGRITY_FAIL: Integrity gate in closure failed.
        MERGE_FAIL: Merge conflict in closure.
        PREFLIGHT_FAIL: Preflight checks in setup failed.
        MAX_ROUNDS_EXCEEDED: Feedback-round limit reached.
        TIMEOUT: Phase exceeded the time limit.
        GUARD_FAILED: Guard function raised an unexpected exception
            (technical error).
        HANDLER_EXCEPTION: Unexpected exception in the phase handler.
        PRECONDITION_FAILED: Semantic precondition not fulfilled
            (FK-45 §45.2).
        HANDLER_REPORTED_FAILED: Handler reported FAILED itself.
        HANDLER_REPORTED_ESCALATED: Handler reported ESCALATED itself.
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
