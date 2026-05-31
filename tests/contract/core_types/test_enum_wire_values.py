"""Contract-Tests fuer Wire-Werte der Kern-Enums (AG3-021 §2.1.9.2).

Pflichtliste: pro Enum eine Test-Funktion, die exakt die Set-of-Members
und den Member-Name-zu-Wire-Wert-Mapping vergleicht. Drift in einem
dieser Werte schlaegt sofort fehl — das ist der Sinn dieser Datei.

Die Pflichtliste folgt der Story-Tabelle in AG3-021 §2.1.9.2:

| Enum                  | Anzahl | Quelle                       |
|-----------------------|--------|------------------------------|
| Severity              | 3      | FK-27 §27.4.2                |
| QaContext             | 4      | bc-cut Z. 84-95              |
| PolicyVerdict         | 2      | FK-27 §27.7.2                |
| ExplorationGateStatus | 3      | FK-23 §23.5.0                |
| PauseReason           | 3      | FK-39 §39.2.2                |
| AttemptOutcome        | 6      | FK-39 §39.4.2                |
| FailureCause          | 16     | FK-39 §39.4.3                |
| ArtifactClass         | 9      | FK-71 §71.1.1 + FK-44 §44.6  |
| EnvelopeStatus        | 4      | FK-71 §71.2                  |
| StorySize             | 5      | DK-10 §10.4                  |
| StoryMode             | 3      | FK-24 §24.3.2 + AG3-018      |
| ClosureVerdict        | 2      | bc-cut §BC 8 Closure         |
| MergePolicy           | 2      | FK-29 §29.1.5                |
| StoryDependencyKind   | 8      | FK-70 §70.4.2                |
| FailureCategory       | 12     | FK-41 §41.4.1                |
| PromotionStatus       | 7      | FK-41 Glossar                |
| BlockingCategory      | 4      | FK-26 §26.8.2                |
| SpawnReason           | 3      | bc-cut §BC 6 + FK-26 §26.2   |
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping
    from enum import StrEnum

from agentkit.core_types import (
    ArtifactClass,
    AttemptOutcome,
    BlockingCategory,
    ClosureVerdict,
    EnvelopeStatus,
    ExplorationGateStatus,
    FailureCategory,
    FailureCause,
    MergePolicy,
    PauseReason,
    PolicyVerdict,
    PromotionStatus,
    QaContext,
    Severity,
    SpawnReason,
    StoryDependencyKind,
    StoryMode,
    StorySize,
)

# ---------------------------------------------------------------------------
# Erwartete Wire-Werte pro Enum (autoritativ aus AG3-021 §2.1.1.1).
# ---------------------------------------------------------------------------

_SEVERITY_EXPECTED: Final[Mapping[str, str]] = {
    "BLOCKING": "BLOCKING",
    "MAJOR": "MAJOR",
    "MINOR": "MINOR",
}

_QA_CONTEXT_EXPECTED: Final[Mapping[str, str]] = {
    "IMPLEMENTATION_INITIAL": "IMPLEMENTATION_INITIAL",
    "IMPLEMENTATION_REMEDIATION": "IMPLEMENTATION_REMEDIATION",
    "EXPLORATION_INITIAL": "EXPLORATION_INITIAL",
    "EXPLORATION_REMEDIATION": "EXPLORATION_REMEDIATION",
}

_POLICY_VERDICT_EXPECTED: Final[Mapping[str, str]] = {
    "PASS": "PASS",
    "FAIL": "FAIL",
}

_EXPLORATION_GATE_EXPECTED: Final[Mapping[str, str]] = {
    "PENDING": "pending",
    "APPROVED": "approved",
    "REJECTED": "rejected",
}

_PAUSE_REASON_EXPECTED: Final[Mapping[str, str]] = {
    "AWAITING_DESIGN_REVIEW": "AWAITING_DESIGN_REVIEW",
    "AWAITING_DESIGN_CHALLENGE": "AWAITING_DESIGN_CHALLENGE",
    "GOVERNANCE_INCIDENT": "GOVERNANCE_INCIDENT",
}

_ATTEMPT_OUTCOME_EXPECTED: Final[Mapping[str, str]] = {
    "COMPLETED": "COMPLETED",
    "FAILED": "FAILED",
    "ESCALATED": "ESCALATED",
    "SKIPPED": "SKIPPED",
    "YIELDED": "YIELDED",
    "BLOCKED": "BLOCKED",
}

_FAILURE_CAUSE_EXPECTED: Final[Mapping[str, str]] = {
    "GUARD_REJECTED": "GUARD_REJECTED",
    "STRUCTURAL_CHECK_FAIL": "STRUCTURAL_CHECK_FAIL",
    "SEMANTIC_REVIEW_FAIL": "SEMANTIC_REVIEW_FAIL",
    "ADVERSARIAL_FINDING": "ADVERSARIAL_FINDING",
    "POLICY_FAIL": "POLICY_FAIL",
    "WORKER_BLOCKED": "WORKER_BLOCKED",
    "INTEGRITY_FAIL": "INTEGRITY_FAIL",
    "MERGE_FAIL": "MERGE_FAIL",
    "PREFLIGHT_FAIL": "PREFLIGHT_FAIL",
    "MAX_ROUNDS_EXCEEDED": "MAX_ROUNDS_EXCEEDED",
    "TIMEOUT": "TIMEOUT",
    "GUARD_FAILED": "GUARD_FAILED",
    "HANDLER_EXCEPTION": "HANDLER_EXCEPTION",
    "PRECONDITION_FAILED": "PRECONDITION_FAILED",
    "HANDLER_REPORTED_FAILED": "HANDLER_REPORTED_FAILED",
    "HANDLER_REPORTED_ESCALATED": "HANDLER_REPORTED_ESCALATED",
}

_ARTIFACT_CLASS_EXPECTED: Final[Mapping[str, str]] = {
    "WORKER": "worker",
    "QA": "qa",
    "PIPELINE": "pipeline",
    "TELEMETRY": "telemetry",
    "GOVERNANCE": "governance",
    "ENTWURF": "entwurf",
    "HANDOVER": "handover",
    "ADVERSARIAL_TEST_SANDBOX": "adversarial_test_sandbox",
    "PROMPT_AUDIT": "prompt_audit",
}

_ENVELOPE_STATUS_EXPECTED: Final[Mapping[str, str]] = {
    "PASS": "PASS",
    "FAIL": "FAIL",
    "WARN": "WARN",
    "ERROR": "ERROR",
}

_STORY_SIZE_EXPECTED: Final[Mapping[str, str]] = {
    "XS": "XS",
    "S": "S",
    "M": "M",
    "L": "L",
    "XL": "XL",
}

_STORY_MODE_EXPECTED: Final[Mapping[str, str]] = {
    "EXECUTION": "execution",
    "EXPLORATION": "exploration",
    "FAST": "fast",
}

_CLOSURE_VERDICT_EXPECTED: Final[Mapping[str, str]] = {
    "COMPLETED": "COMPLETED",
    "ESCALATED": "ESCALATED",
}

_MERGE_POLICY_EXPECTED: Final[Mapping[str, str]] = {
    "FF_ONLY": "ff_only",
    "NO_FF": "no_ff",
}

_STORY_DEPENDENCY_KIND_EXPECTED: Final[Mapping[str, str]] = {
    "HARD_STORY_DEPENDENCY": "hard_story_dependency",
    "SOFT_STORY_DEPENDENCY": "soft_story_dependency",
    "SERIAL_EXECUTION_CONSTRAINT": "serial_execution_constraint",
    "MUTEX_CONSTRAINT": "mutex_constraint",
    "SHARED_CONTRACT_DEPENDENCY": "shared_contract_dependency",
    "SHARED_FILE_CONFLICT": "shared_file_conflict",
    "EXTERNAL_DEPENDENCY": "external_dependency",
    "HUMAN_GATE_DEPENDENCY": "human_gate_dependency",
}

_FAILURE_CATEGORY_EXPECTED: Final[Mapping[str, str]] = {
    "SCOPE_DRIFT": "scope_drift",
    "ARCHITECTURE_VIOLATION": "architecture_violation",
    "EVIDENCE_FABRICATION": "evidence_fabrication",
    "HALLUCINATION": "hallucination",
    "TEST_OMISSION": "test_omission",
    "ASSERTION_WEAKNESS": "assertion_weakness",
    "UNSAFE_REFACTOR": "unsafe_refactor",
    "POLICY_VIOLATION": "policy_violation",
    "TOOL_MISUSE": "tool_misuse",
    "STATE_DESYNC": "state_desync",
    "REQUIREMENTS_MISS": "requirements_miss",
    "REVIEW_EVASION": "review_evasion",
}

_PROMOTION_STATUS_EXPECTED: Final[Mapping[str, str]] = {
    "MONITORING": "monitoring",
    "DRAFT": "draft",
    "APPROVED": "approved",
    "ACTIVE": "active",
    "TUNED": "tuned",
    "RETIRED": "retired",
    "REJECTED": "rejected",
}

_BLOCKING_CATEGORY_EXPECTED: Final[Mapping[str, str]] = {
    "POLICY_CONFLICT": "POLICY_CONFLICT",
    "ENVIRONMENTAL": "ENVIRONMENTAL",
    "FIXABLE_LOCAL": "FIXABLE_LOCAL",
    "FIXABLE_CODE": "FIXABLE_CODE",
}

_SPAWN_REASON_EXPECTED: Final[Mapping[str, str]] = {
    "INITIAL": "initial",
    "PAUSED_RETRY": "paused_retry",
    "REMEDIATION": "remediation",
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _assert_wire_contract(
    enum_cls: type[StrEnum],
    expected: Mapping[str, str],
    *,
    expected_count: int,
) -> None:
    """Pin sowohl Member-Set als auch Member-Name->Wire-Wert-Mapping."""
    actual_mapping = {member.name: member.value for member in enum_cls}
    assert actual_mapping == dict(expected), (
        f"{enum_cls.__name__}: member-to-wire mapping drift; "
        f"actual={actual_mapping}, expected={dict(expected)}"
    )
    actual_value_set = {member.value for member in enum_cls}
    assert actual_value_set == set(expected.values()), (
        f"{enum_cls.__name__}: wire-value set drift; "
        f"actual={actual_value_set}, expected={set(expected.values())}"
    )
    assert len(enum_cls) == expected_count, (
        f"{enum_cls.__name__}: expected {expected_count} members, "
        f"got {len(enum_cls)}"
    )


# ---------------------------------------------------------------------------
# Pflichtliste — eine Funktion pro Enum.
# ---------------------------------------------------------------------------


def test_severity_wire_values() -> None:
    """FK-27 §27.4.2 — BLOCKING/MAJOR/MINOR (3 Werte, upper-case)."""
    _assert_wire_contract(Severity, _SEVERITY_EXPECTED, expected_count=3)


def test_qa_context_wire_values() -> None:
    """bc-cut Z. 84-95 — QaContext mit 4 upper-case Werten."""
    _assert_wire_contract(QaContext, _QA_CONTEXT_EXPECTED, expected_count=4)


def test_policy_verdict_wire_values() -> None:
    """FK-27 §27.7.2 — PASS/FAIL (kein PASS_WITH_WARNINGS)."""
    _assert_wire_contract(
        PolicyVerdict, _POLICY_VERDICT_EXPECTED, expected_count=2,
    )


def test_exploration_gate_wire_values() -> None:
    """FK-23 §23.5.0 — pending/approved/rejected (3 Werte, lower-case)."""
    _assert_wire_contract(
        ExplorationGateStatus, _EXPLORATION_GATE_EXPECTED, expected_count=3,
    )


def test_pause_reason_wire_values() -> None:
    """FK-39 §39.2.2 — drei upper-case PauseReason-Werte."""
    _assert_wire_contract(
        PauseReason, _PAUSE_REASON_EXPECTED, expected_count=3,
    )


def test_attempt_outcome_wire_values() -> None:
    """FK-39 §39.4.2 — sechs upper-case AttemptOutcome-Werte."""
    _assert_wire_contract(
        AttemptOutcome, _ATTEMPT_OUTCOME_EXPECTED, expected_count=6,
    )


def test_failure_cause_wire_values() -> None:
    """FK-39 §39.4.3 — sechzehn upper-case FailureCause-Werte."""
    _assert_wire_contract(
        FailureCause, _FAILURE_CAUSE_EXPECTED, expected_count=16,
    )


def test_artifact_class_wire_values() -> None:
    """FK-71 §71.1.1 + FK-44 §44.6 — neun lower-case ArtifactClass-Werte.

    AG3-015 ergaenzt ``prompt_audit`` (8 -> 9) fuer Prompt-Runtime-Audit-
    Records (Entscheidung 1).
    """
    _assert_wire_contract(
        ArtifactClass, _ARTIFACT_CLASS_EXPECTED, expected_count=9,
    )


def test_envelope_status_wire_values() -> None:
    """FK-71 §71.2 — vier upper-case EnvelopeStatus-Werte."""
    _assert_wire_contract(
        EnvelopeStatus, _ENVELOPE_STATUS_EXPECTED, expected_count=4,
    )


def test_story_size_wire_values() -> None:
    """DK-10 §10.4 — XS/S/M/L/XL (5 upper-case Werte)."""
    _assert_wire_contract(StorySize, _STORY_SIZE_EXPECTED, expected_count=5)


def test_story_mode_wire_values() -> None:
    """FK-24 §24.3.2 + AG3-018 — execution/exploration/fast (3 lower-case)."""
    _assert_wire_contract(StoryMode, _STORY_MODE_EXPECTED, expected_count=3)


def test_closure_verdict_wire_values() -> None:
    """bc-cut §BC 8 Closure — COMPLETED/ESCALATED (2 upper-case)."""
    _assert_wire_contract(
        ClosureVerdict, _CLOSURE_VERDICT_EXPECTED, expected_count=2,
    )


def test_merge_policy_wire_values() -> None:
    """FK-29 §29.1.5 — ff_only/no_ff (2 lower-case)."""
    _assert_wire_contract(
        MergePolicy, _MERGE_POLICY_EXPECTED, expected_count=2,
    )


def test_story_dependency_kind_wire_values() -> None:
    """FK-70 §70.4.2 — acht lower-case StoryDependencyKind-Werte."""
    _assert_wire_contract(
        StoryDependencyKind,
        _STORY_DEPENDENCY_KIND_EXPECTED,
        expected_count=8,
    )


def test_failure_category_wire_values() -> None:
    """FK-41 §41.4.1 — zwoelf lower-case FailureCategory-Werte."""
    _assert_wire_contract(
        FailureCategory, _FAILURE_CATEGORY_EXPECTED, expected_count=12,
    )


def test_promotion_status_wire_values() -> None:
    """FK-41 Glossar Z. 70-76 — sieben lower-case PromotionStatus-Werte."""
    _assert_wire_contract(
        PromotionStatus, _PROMOTION_STATUS_EXPECTED, expected_count=7,
    )


def test_blocking_category_wire_values() -> None:
    """FK-26 §26.8.2 — vier upper-case BlockingCategory-Werte."""
    _assert_wire_contract(
        BlockingCategory, _BLOCKING_CATEGORY_EXPECTED, expected_count=4,
    )


def test_spawn_reason_wire_values() -> None:
    """bc-cut §BC 6 + FK-26 §26.2 — drei lower-case SpawnReason-Werte."""
    _assert_wire_contract(
        SpawnReason, _SPAWN_REASON_EXPECTED, expected_count=3,
    )
