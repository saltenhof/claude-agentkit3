"""FailureCategory and IncidentStatus — failure-corpus classification.

Source of truth:
- FailureCategory: FK-41 §41.4.1 — concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md
  (12 values). Reconciled with bc-cut-decisions §BC 13.
- IncidentStatus: FK-41 §41.3.1 + glossary `exported_terms.incident-status.values`
  (4 values: observed/promoted/closed_one_off/archived). AG3-028 CONFLICT-1
  (user decision 2026-06-01) replaces the earlier umbrella enum
  ``PromotionStatus`` (one enum for three entities) with three
  entity-scoped lifecycle enums. ``IncidentStatus`` is the only enum
  with a functional producer (``record_incident``/``fc_incidents.incident_status``)
  and is therefore materialized in this story; ``PatternStatus``/``CheckStatus``
  follow with their producers (PatternPromotion/CheckFactory) in follow-up
  stories (ZERO DEBT: no dead code).
"""

from __future__ import annotations

from enum import StrEnum


class FailureCategory(StrEnum):
    """Failure category per FK-41 §41.4.1 (12 values).

    The list below is exhaustive; older values circulating from repo
    history are not part of FK-41 §41.4.1 and are dropped without
    replacement.

    Attributes:
        SCOPE_DRIFT: Story scope exceeded or left.
        ARCHITECTURE_VIOLATION: Architecture concept violated.
        EVIDENCE_FABRICATION: Evidence fabricated or manipulated.
        HALLUCINATION: LLM hallucination (invented facts).
        TEST_OMISSION: Mandatory tests omitted.
        ASSERTION_WEAKNESS: Tests too weak (false-negative risk).
        UNSAFE_REFACTOR: Refactoring without a safety net.
        POLICY_VIOLATION: Guardrail or policy violation.
        TOOL_MISUSE: Wrong tool usage by the worker.
        STATE_DESYNC: Inconsistent state (code vs. telemetry vs. doc).
        REQUIREMENTS_MISS: ARE requirement overlooked.
        REVIEW_EVASION: Review obligation circumvented.
    """

    SCOPE_DRIFT = "scope_drift"
    ARCHITECTURE_VIOLATION = "architecture_violation"
    EVIDENCE_FABRICATION = "evidence_fabrication"
    HALLUCINATION = "hallucination"
    TEST_OMISSION = "test_omission"
    ASSERTION_WEAKNESS = "assertion_weakness"
    UNSAFE_REFACTOR = "unsafe_refactor"
    POLICY_VIOLATION = "policy_violation"
    TOOL_MISUSE = "tool_misuse"
    STATE_DESYNC = "state_desync"
    REQUIREMENTS_MISS = "requirements_miss"
    REVIEW_EVASION = "review_evasion"


class IncidentStatus(StrEnum):
    """Incident lifecycle per FK-41 §41.3.1 + glossary ``incident-status``.

    The list below is exhaustive (4 values). Transitions are exclusively
    forward-directed. AG3-028 CONFLICT-1: replaces the earlier umbrella
    enum ``PromotionStatus``.

    Attributes:
        OBSERVED: Recorded and classified — required fields are enforced
            on write, there is no unclassified raw state (default for new
            incidents).
        PROMOTED: Adopted into a pattern (additionally derivable from a set
            ``pattern_ref``).
        CLOSED_ONE_OFF: Reviewed, no prevention value.
        ARCHIVED: Only historically relevant.
    """

    OBSERVED = "observed"
    PROMOTED = "promoted"
    CLOSED_ONE_OFF = "closed_one_off"
    ARCHIVED = "archived"


class PatternStatus(StrEnum):
    """Pattern lifecycle per FK-41 §41.3.2 + glossary ``pattern-status``.

    The list below is exhaustive (4 values). Transitions are exclusively
    forward-directed. AG3-028 CONFLICT-1: one of the three entity-scoped
    lifecycle enums that replace the earlier umbrella enum
    ``PromotionStatus``. The progress of a derived check is NOT a pattern
    state, but is derivable via ``check_ref`` to :class:`CheckStatus`
    (FK-41 §41.3.2).

    Materialized with AG3-040 sub-block (b) (fc_patterns table + repository
    skeleton); the functional producer (``PatternPromotion``) follows in a
    follow-up story (FK-41 §41.5), the full promotion logic is out of scope.

    Attributes:
        CANDIDATE: Proposed from clustering, not yet confirmed.
        ACCEPTED: Human-confirmed, check derivation possible. No pattern
            becomes ``accepted`` without ``confirmed_by = human`` (FK-41 §41.3.2).
        REJECTED: Discarded in review.
        RETIRED: No longer relevant.
    """

    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RETIRED = "retired"


class CheckStatus(StrEnum):
    """Check lifecycle per FK-41 §41.3.3 + glossary ``check-status``.

    The list below is exhaustive (5 values). Transitions are exclusively
    forward-directed, except the human recall of an auto-deactivation
    (FK-41 §41.6.7). AG3-028 CONFLICT-1: one of the three entity-scoped
    lifecycle enums that replace the earlier umbrella enum
    ``PromotionStatus``.

    Materialized with AG3-040 sub-block (b) (fc_check_proposals table +
    repository skeleton); the functional producer (``CheckFactory``) follows
    in a follow-up story (FK-41 §41.6), the full check-factory logic is out
    of scope.

    Attributes:
        DRAFT: Specification created.
        APPROVED: Human-approved (``approved_by = human``, FK-41
            §41.3.3).
        ACTIVE: Active in the pipeline (its effectiveness is necessarily
            recorded — no separate observation state).
        REJECTED: Discarded in review.
        RETIRED: Deactivated (irrelevant or too many false positives).
    """

    DRAFT = "draft"
    APPROVED = "approved"
    ACTIVE = "active"
    REJECTED = "rejected"
    RETIRED = "retired"


class CheckType(StrEnum):
    """Check type of a generated check proposal per FK-41 §41.3.3/§41.6.3.

    The list below is exhaustive (6 values). The check type is assigned in
    FK-41 §41.6.3 deterministically (no LLM) from the failure category.

    Materialized with AG3-040 sub-block (b) (fc_check_proposals table +
    repository skeleton); the deterministic type assignment (FK-41 §41.6.3) is
    the task of the ``CheckFactory`` follow-up story (out of scope).

    Attributes:
        CHANGED_FILE_POLICY: scope_drift / unsafe_refactor.
        ARTIFACT_COMPLETENESS: evidence_fabrication / review_evasion /
            requirements_miss.
        TEST_OBLIGATION: test_omission / assertion_weakness.
        SENSITIVE_PATH_GUARD: policy_violation / tool_misuse.
        FORBIDDEN_DEPENDENCY: architecture_violation.
        FIXTURE_REPLAY: hallucination / state_desync.
    """

    CHANGED_FILE_POLICY = "Changed-File-Policy"
    ARTIFACT_COMPLETENESS = "Artifact-Completeness"
    TEST_OBLIGATION = "Test-Obligation"
    SENSITIVE_PATH_GUARD = "Sensitive-Path-Guard"
    FORBIDDEN_DEPENDENCY = "Forbidden-Dependency"
    FIXTURE_REPLAY = "Fixture-Replay"
