"""Unit tests for the nine IntegrityGate dimensions (FK-35 §35.2.4, AG3-034).

These tests drive ``IntegrityGate.evaluate`` through a configurable recording
state-port test-double (story.md §8: build the gate with a stub repository) that
also serves the canonical QA ``ArtifactEnvelope`` objects each dimension now
verifies against (Remediation E-A: producer / status / depth / threshold, not
mere existence).  They cover every dimension's happy/fail path, the
mandatory-artifact pre-stage abort (AK6), the envelope field validation for both
mandatory QA artifacts (AK7 / E-F) and timestamp causality (AK9).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.artifacts.envelope import ArtifactEnvelope
from agentkit.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.core_types import ArtifactClass, EnvelopeStatus
from agentkit.core_types.qa_artifact_names import (
    ADVERSARIAL_PRODUCER,
    ADVERSARIAL_STAGE,
    QA_REVIEW_PRODUCER,
    QA_REVIEW_STAGE,
    SEMANTIC_REVIEW_PRODUCER,
    SEMANTIC_REVIEW_STAGE,
    STRUCTURAL_PRODUCER,
    STRUCTURAL_STAGE,
    VERIFY_DECISION_PRODUCER,
    VERIFY_DECISION_STAGE,
)
from agentkit.governance.integrity_gate import (
    IntegrityDimension,
    IntegrityGate,
    IntegrityGateStatus,
)
from agentkit.governance.integrity_gate.dimensions import (
    ENVELOPE_VIOLATION,
    TIMESTAMP_VIOLATION,
)
from agentkit.story_context_manager.types import StoryType

if TYPE_CHECKING:
    from pathlib import Path

#: Decision-record verdict payload read by Dim 7 (NO_VERIFY).
_PASS_PAYLOAD: dict[str, object] = {
    "status": "PASS",
    "passed": True,
    "major_threshold": 0,
}


def _decision_envelope_payload() -> dict[str, object]:
    """A substantive canonical decision payload (>200B, has major_threshold)."""
    return {
        "passed": True,
        "status": "PASS",
        "major_threshold": 0,
        "layers": [
            {"layer": "structural", "passed": True, "findings_count": 3,
             "metadata": {"total_checks": 6}},
            {"layer": "qa_review", "passed": True, "findings_count": 0,
             "metadata": {}},
            {"layer": "semantic_review", "passed": True, "findings_count": 0,
             "metadata": {}},
            {"layer": "adversarial", "passed": True, "findings_count": 0,
             "metadata": {}},
        ],
        "blocking_findings": [],
        "all_findings_count": 3,
        "summary": "All QA layers passed with no blocking findings.",
        "attempt_nr": 1,
    }


_T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
_T1 = datetime(2026, 6, 1, 13, 0, 0, tzinfo=UTC)


def _envelope(
    *,
    stage: str,
    producer_name: str,
    producer_type: ProducerType,
    status: EnvelopeStatus = EnvelopeStatus.PASS,
    payload: dict[str, object] | None = None,
    finished_at: datetime = _T1,
) -> ArtifactEnvelope:
    return ArtifactEnvelope(
        schema_version="3.0",
        story_id="AG3-001",
        run_id="run-1",
        stage=stage,
        attempt=1,
        producer=Producer(
            type=producer_type,
            name=producer_name,
            id=ProducerId(f"{producer_name}-1"),
        ),
        started_at=_T0,
        finished_at=finished_at,
        status=status,
        artifact_class=ArtifactClass.QA,
        payload=payload,
    )


def _deep_structural_payload() -> dict[str, object]:
    """A substantive structural payload (>500B serialized, >=5 checks)."""
    findings = [
        {
            "layer": "structural",
            "check": f"check_{i}",
            "severity": "MINOR",
            "message": f"informational finding number {i} with some descriptive text",
            "trust_class": "SYSTEM",
            "file_path": f"src/agentkit/module_{i}.py",
            "line_number": i,
            "suggestion": None,
        }
        for i in range(3)
    ]
    return {
        "layer": "structural",
        "passed": True,
        "attempt_nr": 1,
        "findings": findings,
        "metadata": {"total_checks": 6},
    }


def _default_envelopes() -> dict[str, ArtifactEnvelope]:
    """Canonical, FK-35-conformant QA envelopes for a passing impl story."""
    big_adversarial_payload = {
        "summary": "adversarial sparring run; "
        + ("edge case probe " * 20),
        "passed": True,
    }
    return {
        STRUCTURAL_STAGE: _envelope(
            stage=STRUCTURAL_STAGE,
            producer_name=STRUCTURAL_PRODUCER,
            producer_type=ProducerType.DETERMINISTIC,
            payload=_deep_structural_payload(),
            finished_at=_T0,
        ),
        QA_REVIEW_STAGE: _envelope(
            stage=QA_REVIEW_STAGE,
            producer_name=QA_REVIEW_PRODUCER,
            producer_type=ProducerType.LLM_REVIEWER,
            payload={"layer": "qa_review", "passed": True},
        ),
        SEMANTIC_REVIEW_STAGE: _envelope(
            stage=SEMANTIC_REVIEW_STAGE,
            producer_name=SEMANTIC_REVIEW_PRODUCER,
            producer_type=ProducerType.LLM_REVIEWER,
            payload={"layer": "semantic_review", "passed": True},
        ),
        ADVERSARIAL_STAGE: _envelope(
            stage=ADVERSARIAL_STAGE,
            producer_name=ADVERSARIAL_PRODUCER,
            producer_type=ProducerType.LLM_REVIEWER,
            payload=big_adversarial_payload,
        ),
        VERIFY_DECISION_STAGE: _envelope(
            stage=VERIFY_DECISION_STAGE,
            producer_name=VERIFY_DECISION_PRODUCER,
            producer_type=ProducerType.DETERMINISTIC,
            payload=_decision_envelope_payload(),
            finished_at=_T1,
        ),
    }


class _StubPort:
    """Configurable IntegrityGateStatePort test-double serving QA envelopes."""

    def __init__(self) -> None:
        self.structural = True
        self.context = True
        self.decision: dict[str, object] | None = dict(_PASS_PAYLOAD)
        self.envelopes: dict[str, ArtifactEnvelope] = _default_envelopes()
        #: Context record completion timestamp (FK-35 Dim 8): the context is
        #: built at setup (_T0), strictly before the decision flow_end (_T1).
        self.context_finished_at: datetime | None = _T0
        #: Context record field-validation problem (FK-35 Dim 2 / R2-F); None == valid.
        self.context_problem: str | None = None

    def resolve_runtime_scope(self, story_dir: object) -> object:
        from agentkit.exceptions import CorruptStateError

        raise CorruptStateError("no scope in stub")  # forces story_dir fallback

    def has_completed_snapshot(self, story_dir: object, phase: str) -> bool:
        _ = story_dir, phase
        return True

    def has_structural_artifact(self, story_dir: object) -> bool:
        _ = story_dir
        return self.structural

    def has_structural_artifact_for_scope(self, scope: object) -> bool:
        _ = scope
        return self.structural

    def has_valid_context(self, story_dir: object) -> bool:
        _ = story_dir
        return self.context

    def has_valid_phase_state(self, story_dir: object) -> bool:
        _ = story_dir
        return True

    def load_context_finished_at(
        self, story_dir: object, scope: object
    ) -> datetime | None:
        _ = story_dir, scope
        return self.context_finished_at

    def validate_context_record(
        self, story_dir: object, scope: object
    ) -> str | None:
        _ = story_dir, scope
        return self.context_problem

    def load_latest_verify_decision(
        self, story_dir: object
    ) -> dict[str, object] | None:
        _ = story_dir
        return self.decision

    def load_latest_verify_decision_for_scope(
        self, scope: object
    ) -> dict[str, object] | None:
        _ = scope
        return self.decision

    def read_phase_state_record(self, story_dir: object) -> object | None:
        _ = story_dir
        return None

    def find_latest_qa_envelope(
        self, story_dir: object, scope: object, stage: str
    ) -> ArtifactEnvelope | None:
        _ = story_dir, scope
        return self.envelopes.get(stage)


class _NotApplicableSonarPort:
    """Resolves Dim 9 NOT_APPLICABLE so these tests isolate Dim 1-8."""

    def resolve_dim9_outcome(self, gate_ctx: object) -> object:
        from agentkit.governance.integrity_gate.dim9_sonar import Dim9Resolution
        from agentkit.verify_system.sonarqube_gate import SonarApplicability

        _ = gate_ctx
        return Dim9Resolution(
            applicability=SonarApplicability.NOT_APPLICABLE_UNAVAILABLE,
            outcome=None,
        )


def _gate(port: _StubPort, **kwargs: object) -> IntegrityGate:
    # Wire a NOT_APPLICABLE Dim-9 port so these Dim 1-8 tests are not polluted
    # by the (separately tested) Sonar dimension.
    kwargs.setdefault("sonar_port", _NotApplicableSonarPort())
    return IntegrityGate(port, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Happy path: all eight non-Sonar dimensions pass for implementation
# ---------------------------------------------------------------------------


def test_all_dimensions_pass_for_implementation(tmp_path: Path) -> None:
    result = _gate(_StubPort()).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    assert result.overall is IntegrityGateStatus.PASS
    assert result.failure_reason is None
    assert set(result.dimension_results) == {
        IntegrityDimension.NO_QA_ARTIFACTS,
        IntegrityDimension.DECISION_INVALID,
        IntegrityDimension.CONTEXT_INVALID,
        IntegrityDimension.STRUCTURAL_SHALLOW,
        IntegrityDimension.NO_LLM_REVIEW,
        IntegrityDimension.NO_ADVERSARIAL,
        IntegrityDimension.NO_VERIFY,
        IntegrityDimension.TIMESTAMP_INVERSION,
        IntegrityDimension.CONFLICT_FREEZE_PROOF,
    }


# ---------------------------------------------------------------------------
# Dim 1/2/4 mandatory-artifact pre-stage (FK-35 §35.2.3, AK6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attr", "reason"),
    [
        ("structural", "MISSING_STRUCTURAL"),
        ("context", "MISSING_CONTEXT"),
    ],
)
def test_missing_mandatory_artifact_aborts(
    tmp_path: Path, attr: str, reason: str
) -> None:
    port = _StubPort()
    setattr(port, attr, False)
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    assert result.overall is IntegrityGateStatus.FAIL
    assert result.failure_reason == reason
    assert reason in result.missing_artifacts
    assert IntegrityDimension.STRUCTURAL_SHALLOW in result.blocked_dimensions
    assert IntegrityDimension.STRUCTURAL_SHALLOW not in result.dimension_results


def test_missing_decision_aborts(tmp_path: Path) -> None:
    port = _StubPort()
    port.decision = None
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    assert result.overall is IntegrityGateStatus.FAIL
    assert result.failure_reason == "MISSING_DECISION"


# ---------------------------------------------------------------------------
# Dim 1 + Dim 4 envelope field validation (FK-71 §71.2, AK7 / E-F)
# ---------------------------------------------------------------------------


class _BoomValidator:
    def __init__(self, fail_stage: str) -> None:
        self.fail_stage = fail_stage

    def validate(self, envelope: object) -> None:
        stage = getattr(envelope, "stage", None)
        if stage == self.fail_stage:
            raise ValueError("missing required field")


def test_structural_envelope_violation_fails_closed(tmp_path: Path) -> None:
    result = _gate(
        _StubPort(),
        envelope_validator=_BoomValidator(STRUCTURAL_STAGE),
    ).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    assert result.overall is IntegrityGateStatus.FAIL
    assert result.failure_reason == ENVELOPE_VIOLATION
    struct = result.dimension_results[IntegrityDimension.NO_QA_ARTIFACTS]
    assert struct.failure_reason == ENVELOPE_VIOLATION


def test_decision_envelope_violation_fails_closed(tmp_path: Path) -> None:
    # E-F: the DECISION mandatory artifact is ALSO envelope-validated, not only
    # the structural one.
    result = _gate(
        _StubPort(),
        envelope_validator=_BoomValidator(VERIFY_DECISION_STAGE),
    ).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    assert result.overall is IntegrityGateStatus.FAIL
    assert result.failure_reason == ENVELOPE_VIOLATION
    decision = result.dimension_results[IntegrityDimension.DECISION_INVALID]
    assert decision.failure_reason == ENVELOPE_VIOLATION


def test_context_record_field_violation_fails_closed(tmp_path: Path) -> None:
    # R2-F: the CONTEXT mandatory artifact (Dim 2) is field-validated too, not
    # only the QA envelopes.  An invalid context record fails closed with
    # ENVELOPE_VIOLATION.
    port = _StubPort()
    port.context_problem = "context record has no resolvable run_id"
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    assert result.overall is IntegrityGateStatus.FAIL
    assert result.failure_reason == ENVELOPE_VIOLATION
    context = result.dimension_results[IntegrityDimension.CONTEXT_INVALID]
    assert context.failure_reason == ENVELOPE_VIOLATION
    assert "run_id" in context.detail


def test_envelope_validation_passes_when_validator_accepts(tmp_path: Path) -> None:
    class _OkValidator:
        def validate(self, envelope: object) -> None:
            _ = envelope

    result = _gate(
        _StubPort(),
        envelope_validator=_OkValidator(),
    ).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    assert result.overall is IntegrityGateStatus.PASS


# ---------------------------------------------------------------------------
# Dim 3 STRUCTURAL_SHALLOW (FK-35 §35.2.4: >500B, >=5 checks, producer)
# ---------------------------------------------------------------------------


def test_dim3_fails_when_structural_too_shallow(tmp_path: Path) -> None:
    port = _StubPort()
    # Replace the structural envelope with a stub (tiny payload, few checks).
    port.envelopes[STRUCTURAL_STAGE] = _envelope(
        stage=STRUCTURAL_STAGE,
        producer_name=STRUCTURAL_PRODUCER,
        producer_type=ProducerType.DETERMINISTIC,
        payload={"layer": "structural", "passed": True, "metadata": {"total_checks": 1}},
        finished_at=_T0,
    )
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    dim3 = result.dimension_results[IntegrityDimension.STRUCTURAL_SHALLOW]
    assert dim3.passed is False
    assert "checks 1 < 5" in dim3.detail
    assert "<= 500B" in dim3.detail


def test_dim3_fails_on_foreign_producer(tmp_path: Path) -> None:
    port = _StubPort()
    payload = _deep_structural_payload()
    port.envelopes[STRUCTURAL_STAGE] = _envelope(
        stage=STRUCTURAL_STAGE,
        producer_name="worker-impl",  # not the structural QA producer
        producer_type=ProducerType.WORKER,
        payload=payload,
        finished_at=_T0,
    )
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    dim3 = result.dimension_results[IntegrityDimension.STRUCTURAL_SHALLOW]
    assert dim3.passed is False
    assert "producer" in dim3.detail


# ---------------------------------------------------------------------------
# Dim 4 DECISION_INVALID depth (FK-35 §35.2.4: >200B, major_threshold, producer)
# ---------------------------------------------------------------------------


def test_dim4_fails_when_decision_missing_major_threshold(tmp_path: Path) -> None:
    port = _StubPort()
    payload = _decision_envelope_payload()
    del payload["major_threshold"]
    port.envelopes[VERIFY_DECISION_STAGE] = _envelope(
        stage=VERIFY_DECISION_STAGE,
        producer_name=VERIFY_DECISION_PRODUCER,
        producer_type=ProducerType.DETERMINISTIC,
        payload=payload,
        finished_at=_T1,
    )
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    assert result.overall is IntegrityGateStatus.FAIL
    dim4 = result.dimension_results[IntegrityDimension.DECISION_INVALID]
    assert dim4.passed is False
    assert "missing major_threshold" in dim4.detail


def test_dim4_fails_on_foreign_producer(tmp_path: Path) -> None:
    port = _StubPort()
    port.envelopes[VERIFY_DECISION_STAGE] = _envelope(
        stage=VERIFY_DECISION_STAGE,
        producer_name="worker-impl",  # not the policy producer
        producer_type=ProducerType.WORKER,
        payload=_decision_envelope_payload(),
        finished_at=_T1,
    )
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    dim4 = result.dimension_results[IntegrityDimension.DECISION_INVALID]
    assert dim4.passed is False
    assert "producer" in dim4.detail


# ---------------------------------------------------------------------------
# Dim 5 NO_LLM_REVIEW (qa-review + semantic-review present with results)
# ---------------------------------------------------------------------------


def test_dim5_fails_when_semantic_review_missing(tmp_path: Path) -> None:
    port = _StubPort()
    del port.envelopes[SEMANTIC_REVIEW_STAGE]
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    dim5 = result.dimension_results[IntegrityDimension.NO_LLM_REVIEW]
    assert dim5.passed is False
    assert SEMANTIC_REVIEW_STAGE in dim5.detail


def test_dim5_fails_when_review_status_error(tmp_path: Path) -> None:
    # ERROR == "no LLM result" (FK-35 §35.2.4 Dim 5 "Status != SKIPPED").
    port = _StubPort()
    port.envelopes[QA_REVIEW_STAGE] = _envelope(
        stage=QA_REVIEW_STAGE,
        producer_name=QA_REVIEW_PRODUCER,
        producer_type=ProducerType.LLM_REVIEWER,
        status=EnvelopeStatus.ERROR,
        payload={"layer": "qa_review"},
    )
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    dim5 = result.dimension_results[IntegrityDimension.NO_LLM_REVIEW]
    assert dim5.passed is False
    assert "no review result" in dim5.detail


# ---------------------------------------------------------------------------
# Dim 6 NO_ADVERSARIAL (envelope >200B, adversarial producer)
# ---------------------------------------------------------------------------


def test_dim6_fails_when_adversarial_missing(tmp_path: Path) -> None:
    port = _StubPort()
    del port.envelopes[ADVERSARIAL_STAGE]
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    dim6 = result.dimension_results[IntegrityDimension.NO_ADVERSARIAL]
    assert dim6.passed is False
    assert "absent" in dim6.detail


def test_dim6_fails_when_adversarial_too_small(tmp_path: Path) -> None:
    port = _StubPort()
    port.envelopes[ADVERSARIAL_STAGE] = _envelope(
        stage=ADVERSARIAL_STAGE,
        producer_name=ADVERSARIAL_PRODUCER,
        producer_type=ProducerType.LLM_REVIEWER,
        payload={"ok": True},  # tiny
    )
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    dim6 = result.dimension_results[IntegrityDimension.NO_ADVERSARIAL]
    assert dim6.passed is False
    assert "<= 200B" in dim6.detail


# ---------------------------------------------------------------------------
# Dim 7 QA-subflow flow_end
# ---------------------------------------------------------------------------


def test_dim7_fails_when_decision_not_pass(tmp_path: Path) -> None:
    port = _StubPort()
    port.decision = {"status": "FAIL", "passed": False, "major_threshold": 0}
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    assert result.overall is IntegrityGateStatus.FAIL
    dim7 = result.dimension_results[IntegrityDimension.NO_VERIFY]
    assert dim7.passed is False


# ---------------------------------------------------------------------------
# Dim 8 timestamp causality (FK-35 §35.2.4 Z. 274: context < decision, AK9)
# ---------------------------------------------------------------------------


def test_dim8_passes_when_context_before_decision(tmp_path: Path) -> None:
    # Context built at _T0 (setup), decision flow_end at _T1 (later) -> causality
    # holds (context.finished_at < decision.finished_at).
    result = _gate(_StubPort()).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    dim8 = result.dimension_results[IntegrityDimension.TIMESTAMP_INVERSION]
    assert dim8.passed is True


def test_dim8_fails_on_context_after_decision_inversion(tmp_path: Path) -> None:
    # REAL context-vs-decision inversion (FK-35 §35.2.4 Z. 274): the CONTEXT
    # record is finalised (13:00) AFTER the policy DECISION envelope (12:30) ->
    # the policy decided before the context existed.  The structural envelope is
    # left untouched and EARLY, proving Dim 8 reads the CONTEXT record (not the
    # structural envelope, the round-1 bug).
    port = _StubPort()
    port.context_finished_at = datetime(2026, 6, 1, 13, 0, 0, tzinfo=UTC)
    port.envelopes[VERIFY_DECISION_STAGE] = _envelope(
        stage=VERIFY_DECISION_STAGE,
        producer_name=VERIFY_DECISION_PRODUCER,
        producer_type=ProducerType.DETERMINISTIC,
        payload=_decision_envelope_payload(),
        finished_at=datetime(2026, 6, 1, 12, 30, 0, tzinfo=UTC),
    )
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    assert result.overall is IntegrityGateStatus.FAIL
    dim8 = result.dimension_results[IntegrityDimension.TIMESTAMP_INVERSION]
    assert dim8.failure_reason == TIMESTAMP_VIOLATION
    assert "context.finished_at" in dim8.detail


def test_dim8_reads_context_not_structural_envelope(tmp_path: Path) -> None:
    # Regression guard for the round-1 bug: Dim 8 must read the CONTEXT record,
    # NOT the structural envelope.  Here the structural envelope is finalised
    # LATE (after the decision) while the context is EARLY -> if Dim 8 still read
    # structural it would (wrongly) flag an inversion; against the context it
    # passes.
    port = _StubPort()
    port.context_finished_at = datetime(2026, 6, 1, 11, 0, 0, tzinfo=UTC)  # early
    port.envelopes[STRUCTURAL_STAGE] = _envelope(
        stage=STRUCTURAL_STAGE,
        producer_name=STRUCTURAL_PRODUCER,
        producer_type=ProducerType.DETERMINISTIC,
        payload=_deep_structural_payload(),
        finished_at=datetime(2026, 6, 1, 14, 0, 0, tzinfo=UTC),  # AFTER decision
    )
    # decision flow_end at _T1 (13:00), after the context (11:00) -> causality ok.
    result = _gate(port).evaluate(tmp_path, StoryType.IMPLEMENTATION)
    dim8 = result.dimension_results[IntegrityDimension.TIMESTAMP_INVERSION]
    assert dim8.passed is True
