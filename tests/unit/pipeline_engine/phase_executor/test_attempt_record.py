"""Unit tests for AttemptRecord (AG3-025 §2.1.1, FK-39 §39.4.1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.core_types.attempt import AttemptOutcome, FailureCause
from agentkit.pipeline_engine.phase_executor import PhaseName
from agentkit.pipeline_engine.phase_executor.records import AttemptRecord

_NOW = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
_LATER = datetime(2026, 1, 15, 10, 5, 0, tzinfo=UTC)


def _completed_record(**kwargs: object) -> AttemptRecord:
    """Return a valid COMPLETED AttemptRecord with defaults."""
    defaults: dict[str, object] = {
        "run_id": "run-test",
        "phase": PhaseName.SETUP,
        "attempt": 1,
        "outcome": AttemptOutcome.COMPLETED,
        "failure_cause": None,
        "started_at": _NOW,
        "ended_at": _LATER,
    }
    defaults.update(kwargs)
    return AttemptRecord(**defaults)


def _failed_record(**kwargs: object) -> AttemptRecord:
    """Return a valid FAILED AttemptRecord with defaults."""
    defaults: dict[str, object] = {
        "run_id": "run-test",
        "phase": PhaseName.IMPLEMENTATION,
        "attempt": 1,
        "outcome": AttemptOutcome.FAILED,
        "failure_cause": FailureCause.HANDLER_REPORTED_FAILED,
        "started_at": _NOW,
        "ended_at": _LATER,
    }
    defaults.update(kwargs)
    return AttemptRecord(**defaults)


class TestAttemptRecordPflichtfelder:
    """AK1: AttemptRecord traegt alle FK-39-Pflichtfelder."""

    def test_all_required_fields_present(self) -> None:
        record = _completed_record()
        assert record.run_id == "run-test"
        assert record.phase == PhaseName.SETUP
        assert record.attempt == 1
        assert record.outcome == AttemptOutcome.COMPLETED
        assert record.failure_cause is None
        assert record.started_at == _NOW
        assert record.ended_at == _LATER

    def test_detail_defaults_to_none(self) -> None:
        record = _completed_record()
        assert record.detail is None

    def test_detail_can_be_set(self) -> None:
        record = _completed_record(detail={"guard_evaluations": [], "artifacts_produced": ["x.md"]})
        assert record.detail is not None
        assert "guard_evaluations" in record.detail


class TestAttemptRecordFrozenExtraForbid:
    """AK1: frozen=True, extra='forbid'."""

    def test_frozen(self) -> None:
        from pydantic import ValidationError
        record = _completed_record()
        with pytest.raises(ValidationError, match="frozen"):
            record.run_id = "changed"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            AttemptRecord(  # type: ignore[call-arg]
                run_id="r",
                phase=PhaseName.SETUP,
                attempt=1,
                outcome=AttemptOutcome.COMPLETED,
                failure_cause=None,
                started_at=_NOW,
                ended_at=_LATER,
                unknown_field="oops",
            )


class TestAttemptValidatorAttemptGe1:
    """attempt muss >= 1 sein."""

    def test_attempt_1_valid(self) -> None:
        record = _completed_record(attempt=1)
        assert record.attempt == 1

    def test_attempt_0_invalid(self) -> None:
        with pytest.raises(ValidationError, match="attempt"):
            _completed_record(attempt=0)

    def test_attempt_negative_invalid(self) -> None:
        with pytest.raises(ValidationError, match="attempt"):
            _completed_record(attempt=-1)


class TestAttemptValidatorEndedAtGeStartedAt:
    """ended_at muss >= started_at sein."""

    def test_equal_timestamps_valid(self) -> None:
        record = _completed_record(started_at=_NOW, ended_at=_NOW)
        assert record.ended_at == record.started_at

    def test_ended_before_started_invalid(self) -> None:
        with pytest.raises(ValidationError, match="ended_at"):
            _completed_record(started_at=_LATER, ended_at=_NOW)


class TestFailureCauseConsistency:
    """AK2: failure_cause gesetzt iff outcome in {FAILED, BLOCKED, ESCALATED}."""

    @pytest.mark.parametrize("outcome", [
        AttemptOutcome.FAILED,
        AttemptOutcome.BLOCKED,
        AttemptOutcome.ESCALATED,
    ])
    def test_failure_outcome_requires_cause(self, outcome: AttemptOutcome) -> None:
        with pytest.raises(ValidationError, match="failure_cause"):
            AttemptRecord(
                run_id="r",
                phase=PhaseName.SETUP,
                attempt=1,
                outcome=outcome,
                failure_cause=None,
                started_at=_NOW,
                ended_at=_LATER,
            )

    @pytest.mark.parametrize("outcome", [
        AttemptOutcome.COMPLETED,
        AttemptOutcome.SKIPPED,
        AttemptOutcome.YIELDED,
    ])
    def test_success_outcome_forbids_cause(self, outcome: AttemptOutcome) -> None:
        with pytest.raises(ValidationError, match="failure_cause"):
            AttemptRecord(
                run_id="r",
                phase=PhaseName.SETUP,
                attempt=1,
                outcome=outcome,
                failure_cause=FailureCause.HANDLER_EXCEPTION,
                started_at=_NOW,
                ended_at=_LATER,
            )

    def test_failed_with_cause_valid(self) -> None:
        record = _failed_record()
        assert record.failure_cause == FailureCause.HANDLER_REPORTED_FAILED

    def test_escalated_with_cause_valid(self) -> None:
        record = AttemptRecord(
            run_id="r",
            phase=PhaseName.IMPLEMENTATION,
            attempt=1,
            outcome=AttemptOutcome.ESCALATED,
            failure_cause=FailureCause.HANDLER_REPORTED_ESCALATED,
            started_at=_NOW,
            ended_at=_LATER,
        )
        assert record.outcome == AttemptOutcome.ESCALATED
        assert record.failure_cause == FailureCause.HANDLER_REPORTED_ESCALATED

    def test_blocked_with_cause_valid(self) -> None:
        record = AttemptRecord(
            run_id="r",
            phase=PhaseName.SETUP,
            attempt=1,
            outcome=AttemptOutcome.BLOCKED,
            failure_cause=FailureCause.PRECONDITION_FAILED,
            started_at=_NOW,
            ended_at=_LATER,
        )
        assert record.outcome == AttemptOutcome.BLOCKED
        assert record.failure_cause == FailureCause.PRECONDITION_FAILED

    def test_yielded_no_cause_valid(self) -> None:
        record = AttemptRecord(
            run_id="r",
            phase=PhaseName.IMPLEMENTATION,
            attempt=1,
            outcome=AttemptOutcome.YIELDED,
            failure_cause=None,
            started_at=_NOW,
            ended_at=_LATER,
        )
        assert record.outcome == AttemptOutcome.YIELDED
        assert record.failure_cause is None

    def test_completed_no_cause_valid(self) -> None:
        record = _completed_record()
        assert record.failure_cause is None


class TestAttemptCorrelationId:
    """attempt_correlation_id() gibt '{run_id}-{phase}-{attempt}' zurueck."""

    def test_correlation_id_format(self) -> None:
        record = _completed_record(run_id="run-123", phase=PhaseName.SETUP, attempt=2)
        assert record.attempt_correlation_id() == "run-123-setup-2"


class TestDetailJson:
    """detail_json() serialisiert detail-Dict oder gibt None zurueck."""

    def test_none_detail_returns_none(self) -> None:
        record = _completed_record()
        assert record.detail_json() is None

    def test_dict_detail_returns_json_string(self) -> None:
        import json
        record = _completed_record(detail={"key": "value"})
        result = record.detail_json()
        assert result is not None
        parsed = json.loads(result)
        assert parsed["key"] == "value"
