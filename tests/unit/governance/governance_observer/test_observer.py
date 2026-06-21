"""Integration-style unit tests for GovernanceObserver (FK-35 §35.3).

Tests inject fakes AT THE LLM BOUNDARY (ScriptedAdjudicator) and
AT THE READ BOUNDARY (ScriptedEventReader) — never through domain logic.

Covers:
- AC2/AC9: fail-closed validation on CANDIDATE-construction read (round-4 fix)
- AC3: threshold trigger -> adjudication called
- AC4: immediate-stop bypass (NO adjudication call)
- AC5: cooldown per-signal-type (same blocked / other allowed)
- AC7: failure-corpus handoff only >= medium (low => none)
- AC8: four EventType emissions with mandatory payload fields
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from tests.unit.governance.governance_observer.conftest import (
    ScriptedAdjudicator,
    ScriptedEventReader,
)

from agentkit.backend.governance.governance_observer.models import (
    AdjudicationIncidentType,
    AdjudicationRecommendedAction,
    AdjudicationSeverity,
    GovernanceAdjudicationVerdict,
    GovernanceMeasure,
)
from agentkit.backend.governance.governance_observer.observer import GovernanceObserver
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import EventType

_PROJECT = "PRJ"
_STORY = "AG3-085"
_RUN = "run-001"
_SIGNAL_A = "orchestrator_code_read_write"
_SIGNAL_B = "qa_fail_repeated"


def _make_signal_payloads(
    count: int, points_each: int = 10, signal: str = _SIGNAL_A
) -> list[dict]:
    return [
        {"risk_points": points_each, "signal_type": signal, "actor": "test-agent"}
        for _ in range(count)
    ]


def _make_observer(
    signal_payloads: list[dict] | None = None,
    last_adjudication_ts: dict[str, float] | None = None,
    verdict: GovernanceAdjudicationVerdict | None = None,
    failure_corpus: object | None = None,
) -> tuple[GovernanceObserver, MemoryEmitter, ScriptedAdjudicator]:
    emitter = MemoryEmitter()
    adjudicator = ScriptedAdjudicator(verdict=verdict)
    reader = ScriptedEventReader(
        signal_payloads=signal_payloads or [],
        last_adjudication_ts=last_adjudication_ts or {},
    )
    observer = GovernanceObserver(
        reader=reader,
        adjudicator=adjudicator,
        emitter=emitter,
        failure_corpus=failure_corpus,
    )
    return observer, emitter, adjudicator


# ---------------------------------------------------------------------------
# AC3 — threshold trigger
# ---------------------------------------------------------------------------

def test_threshold_not_reached_returns_log_only() -> None:
    """Score below threshold returns GOVERNANCE_LOG_ONLY without adjudication (AC3)."""
    # 2 events * 10 pts = 20, below default threshold of 30
    observer, emitter, adjudicator = _make_observer(
        signal_payloads=_make_signal_payloads(2, points_each=10)
    )
    measure = observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)
    assert measure == GovernanceMeasure.GOVERNANCE_LOG_ONLY
    assert adjudicator.call_count == 0


def test_threshold_reached_triggers_adjudication(default_verdict: GovernanceAdjudicationVerdict) -> None:
    """Score >= threshold triggers adjudication (AC3)."""
    # 4 events * 10 pts = 40, above default threshold of 30
    observer, emitter, adjudicator = _make_observer(
        signal_payloads=_make_signal_payloads(4, points_each=10),
        verdict=default_verdict,
    )
    measure = observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)
    assert adjudicator.call_count == 1
    assert measure != GovernanceMeasure.GOVERNANCE_LOG_ONLY


# ---------------------------------------------------------------------------
# AC4 — immediate-stop bypass (no adjudication)
# ---------------------------------------------------------------------------

def test_immediate_stop_signal_governance_file_manipulation() -> None:
    """Governance-file-manipulation triggers stop_process WITHOUT adjudication (AC4)."""
    observer, emitter, adjudicator = _make_observer()
    measure = observer.handle_signal(
        _PROJECT, _STORY, _RUN, signal_type_wire="governance_file_manipulation"
    )
    assert measure == GovernanceMeasure.STOP_PROCESS
    assert adjudicator.call_count == 0


def test_immediate_stop_signal_secret_access() -> None:
    """Secret-access triggers stop_process WITHOUT adjudication (AC4)."""
    observer, emitter, adjudicator = _make_observer()
    measure = observer.handle_signal(
        _PROJECT, _STORY, _RUN, signal_type_wire="secret_access"
    )
    assert measure == GovernanceMeasure.STOP_PROCESS
    assert adjudicator.call_count == 0


def test_immediate_stop_emits_measure_applied() -> None:
    """Immediate stop emits governance_measure_applied (AC8)."""
    observer, emitter, adjudicator = _make_observer()
    observer.handle_signal(
        _PROJECT, _STORY, _RUN, signal_type_wire="governance_file_manipulation"
    )
    event_types = [e.event_type for e in emitter._events]
    assert EventType.GOVERNANCE_MEASURE_APPLIED in event_types


# ---------------------------------------------------------------------------
# AC5 — cooldown per signal type
# ---------------------------------------------------------------------------

def _recent_ts() -> float:
    return datetime.now(UTC).timestamp() - 10


def test_same_signal_blocked_by_cooldown(default_verdict: GovernanceAdjudicationVerdict) -> None:
    """Same signal type in cooldown returns GOVERNANCE_LOG_ONLY, no adjudication (AC5)."""
    observer, emitter, adjudicator = _make_observer(
        signal_payloads=_make_signal_payloads(4, points_each=10),
        last_adjudication_ts={_SIGNAL_A: _recent_ts()},
        verdict=default_verdict,
    )
    measure = observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)
    assert measure == GovernanceMeasure.GOVERNANCE_LOG_ONLY
    assert adjudicator.call_count == 0


def test_different_signal_not_blocked_by_cooldown_of_other(
    default_verdict: GovernanceAdjudicationVerdict,
) -> None:
    """Different signal type is NOT blocked when SIGNAL_A is in cooldown (AC5)."""
    observer, emitter, adjudicator = _make_observer(
        signal_payloads=_make_signal_payloads(4, points_each=10),
        last_adjudication_ts={_SIGNAL_A: _recent_ts()},  # Only SIGNAL_A in cooldown
        verdict=default_verdict,
    )
    # SIGNAL_B is not in cooldown -> adjudication should proceed
    observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_B)
    assert adjudicator.call_count == 1


def test_no_incident_opened_emitted_while_in_cooldown(
    default_verdict: GovernanceAdjudicationVerdict,
) -> None:
    """governance_incident_opened MUST NOT be emitted while in cooldown (ERROR2 fix).

    Story §2.1.3: the GovernanceIncidentCandidate is created only when score >=
    risk_threshold AND NOT in cooldown.  Emitting incident_opened before the
    cooldown check would produce duplicate telemetry on every signal inside the
    window — a FK-91 contract violation.  The cooldown check must happen BEFORE
    the candidate is built and incident_opened is emitted.
    """
    observer, emitter, adjudicator = _make_observer(
        signal_payloads=_make_signal_payloads(4, points_each=10),
        last_adjudication_ts={_SIGNAL_A: _recent_ts()},
        verdict=default_verdict,
    )
    observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)
    # In cooldown -> NO incident_opened should have been emitted
    event_types = [e.event_type for e in emitter._events]
    assert EventType.GOVERNANCE_INCIDENT_OPENED not in event_types, (
        "governance_incident_opened MUST NOT be emitted during cooldown — "
        "cooldown check must precede candidate creation (story §2.1.3)"
    )


def test_incident_opened_emitted_for_different_signal_not_in_cooldown(
    default_verdict: GovernanceAdjudicationVerdict,
) -> None:
    """governance_incident_opened IS emitted for a signal type not in cooldown (AC5/AC8).

    Proves the cooldown reorder does not suppress incident_opened for signal
    types outside the cooldown window.
    """
    observer, emitter, adjudicator = _make_observer(
        signal_payloads=_make_signal_payloads(4, points_each=10),
        last_adjudication_ts={_SIGNAL_A: _recent_ts()},  # Only SIGNAL_A in cooldown
        verdict=default_verdict,
    )
    # SIGNAL_B is not in cooldown -> incident_opened SHOULD be emitted
    observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_B)
    event_types = [e.event_type for e in emitter._events]
    assert EventType.GOVERNANCE_INCIDENT_OPENED in event_types, (
        "governance_incident_opened must be emitted when signal type is not in cooldown"
    )


# ---------------------------------------------------------------------------
# AC7 — failure-corpus handoff only >= medium
# ---------------------------------------------------------------------------

def test_corpus_handoff_for_medium_severity() -> None:
    """Severity=medium triggers failure-corpus handoff (AC7)."""
    corpus = MagicMock()
    verdict = GovernanceAdjudicationVerdict(
        incident_type=AdjudicationIncidentType.ROLE_VIOLATION,
        severity=AdjudicationSeverity.MEDIUM,
        confidence=0.7,
        evidence_summary="Medium severity.",
        recommended_action=AdjudicationRecommendedAction.DOCUMENT_INCIDENT,
    )
    observer, _, _ = _make_observer(
        signal_payloads=_make_signal_payloads(4, points_each=10),
        verdict=verdict,
        failure_corpus=corpus,
    )
    observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)
    corpus.record_incident.assert_called_once()


def test_corpus_handoff_for_high_severity() -> None:
    """Severity=high triggers failure-corpus handoff (AC7)."""
    corpus = MagicMock()
    verdict = GovernanceAdjudicationVerdict(
        incident_type=AdjudicationIncidentType.SCOPE_DRIFT,
        severity=AdjudicationSeverity.HIGH,
        confidence=0.85,
        evidence_summary="High severity.",
        recommended_action=AdjudicationRecommendedAction.INCREASE_MONITORING,
    )
    observer, _, _ = _make_observer(
        signal_payloads=_make_signal_payloads(4, points_each=10),
        verdict=verdict,
        failure_corpus=corpus,
    )
    observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)
    corpus.record_incident.assert_called_once()


def test_no_corpus_handoff_for_low_severity() -> None:
    """Severity=low does NOT trigger failure-corpus handoff (AC7)."""
    corpus = MagicMock()
    verdict = GovernanceAdjudicationVerdict(
        incident_type=AdjudicationIncidentType.ROLE_VIOLATION,
        severity=AdjudicationSeverity.LOW,
        confidence=0.4,
        evidence_summary="Low severity.",
        recommended_action=AdjudicationRecommendedAction.LOG_ONLY,
    )
    observer, _, _ = _make_observer(
        signal_payloads=_make_signal_payloads(4, points_each=10),
        verdict=verdict,
        failure_corpus=corpus,
    )
    observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)
    corpus.record_incident.assert_not_called()


# ---------------------------------------------------------------------------
# AC8 — four EventType emissions with mandatory payload fields
# ---------------------------------------------------------------------------

def _events_by_type(emitter: MemoryEmitter) -> dict:
    return {e.event_type: e for e in emitter._events}


def test_incident_opened_event_emitted_with_mandatory_payload(
    default_verdict: GovernanceAdjudicationVerdict,
) -> None:
    """governance_incident_opened emitted with risk_score, event_count, dominant_signals (AC8)."""
    observer, emitter, _ = _make_observer(
        signal_payloads=_make_signal_payloads(4, points_each=10),
        verdict=default_verdict,
    )
    observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)
    events = _events_by_type(emitter)
    assert EventType.GOVERNANCE_INCIDENT_OPENED in events
    payload = events[EventType.GOVERNANCE_INCIDENT_OPENED].payload
    assert "risk_score" in payload
    assert "event_count" in payload
    assert "dominant_signals" in payload


def test_adjudication_event_emitted_with_mandatory_payload(
    default_verdict: GovernanceAdjudicationVerdict,
) -> None:
    """governance_adjudication emitted with all mandatory fields (AC8)."""
    observer, emitter, _ = _make_observer(
        signal_payloads=_make_signal_payloads(4, points_each=10),
        verdict=default_verdict,
    )
    observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)
    events = _events_by_type(emitter)
    assert EventType.GOVERNANCE_ADJUDICATION in events
    payload = events[EventType.GOVERNANCE_ADJUDICATION].payload
    assert "incident_type" in payload
    assert "severity" in payload
    assert "confidence" in payload
    assert "recommended_action" in payload
    assert "signal_type" in payload


def test_measure_applied_event_emitted_with_mandatory_payload(
    default_verdict: GovernanceAdjudicationVerdict,
) -> None:
    """governance_measure_applied emitted with measure and severity (AC8)."""
    observer, emitter, _ = _make_observer(
        signal_payloads=_make_signal_payloads(4, points_each=10),
        verdict=default_verdict,
    )
    observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)
    events = _events_by_type(emitter)
    assert EventType.GOVERNANCE_MEASURE_APPLIED in events
    payload = events[EventType.GOVERNANCE_MEASURE_APPLIED].payload
    assert "measure" in payload
    assert "severity" in payload


def test_governance_signal_event_type_exists_in_catalog() -> None:
    """GOVERNANCE_SIGNAL is in the EventType catalog (consumed, not emitted by observer)."""
    assert EventType.GOVERNANCE_SIGNAL.value == "governance_signal"


def test_all_four_governance_event_types_exist() -> None:
    """All four FK-91 governance EventTypes exist in the catalog (AC8)."""
    assert EventType.GOVERNANCE_SIGNAL.value == "governance_signal"
    assert EventType.GOVERNANCE_ADJUDICATION.value == "governance_adjudication"
    assert EventType.GOVERNANCE_INCIDENT_OPENED.value == "governance_incident_opened"
    assert EventType.GOVERNANCE_MEASURE_APPLIED.value == "governance_measure_applied"


# ---------------------------------------------------------------------------
# AC9 — unknown signal type -> hard reject
# ---------------------------------------------------------------------------

def test_unknown_signal_type_raises_value_error() -> None:
    """handle_signal with unknown signal type raises ValueError (AC9)."""
    observer, _, _ = _make_observer()
    with pytest.raises(ValueError, match="Unknown governance signal type"):
        observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire="totally_unknown")


# ---------------------------------------------------------------------------
# AC2/AC9 — fail-closed on CANDIDATE-construction window (round-4 regression)
#
# Prior to the round-4 fix, _build_candidate issued a SECOND unvalidated
# read_governance_signals() call, so a malformed payload that caused the score
# read to raise could still slip through if the window happened to look
# valid at score time but malformed at candidate time — or (more practically)
# the helpers _dominant_signals / _time_span_s / _summarise_payloads silently
# accepted and coerced malformed rows (unknown signal_type => ignored; float
# risk_points => coerced).  The fix: single validated read in
# _process_scored_signal; _build_candidate receives pre-validated payloads.
#
# These tests prove that handle_signal RAISES BEFORE any emission or
# adjudication call when the WINDOW (used for candidate construction as well
# as scoring) contains a malformed payload.
# ---------------------------------------------------------------------------

def test_unknown_signal_type_in_window_raises_before_adjudication() -> None:
    """Window row with unknown signal_type causes handle_signal to raise before
    adjudication or any telemetry emission (AC2/AC9 candidate-path fix).

    The malformed payload has enough points to exceed the threshold, so without
    fail-closed validation the observer would proceed to adjudication.  With the
    fix, _validate_window_payloads raises immediately and the adjudicator is
    never called.
    """
    from agentkit.backend.governance.governance_observer.score import GovernanceSignalPayloadError

    # Mix one valid row (above threshold alone) with one unknown-signal row.
    # The unknown row in the same window must trigger fail-closed rejection.
    malformed_payloads = [
        {"risk_points": 40, "signal_type": _SIGNAL_A, "actor": "agent"},
        {"risk_points": 5, "signal_type": "totally_unknown_in_candidate_window", "actor": "agent"},
    ]
    observer, emitter, adjudicator = _make_observer(signal_payloads=malformed_payloads)

    with pytest.raises(GovernanceSignalPayloadError):
        observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)

    # No telemetry must have been emitted before the raise.
    assert len(emitter._events) == 0, (
        "No events must be emitted when the window contains a malformed payload"
    )
    # Adjudicator must NOT have been called.
    assert adjudicator.call_count == 0, (
        "Adjudicator must NOT be called when payload validation raises fail-closed"
    )


def test_non_int_risk_points_in_window_raises_before_adjudication() -> None:
    """Window row with float risk_points causes handle_signal to raise before
    adjudication or any telemetry emission (AC2/AC9 candidate-path fix).

    The old _summarise_payloads accepted floats via ``int(rp)`` coercion.
    With the fix, _validate_window_payloads raises fail-closed before any
    candidate construction, incident_opened emission, or adjudication call.
    """
    from agentkit.backend.governance.governance_observer.score import GovernanceSignalPayloadError

    # One valid high-score row plus one row with a float risk_points (forbidden).
    malformed_payloads = [
        {"risk_points": 40, "signal_type": _SIGNAL_A, "actor": "agent"},
        {"risk_points": 3.5, "signal_type": _SIGNAL_A, "actor": "agent"},  # float — not allowed
    ]
    observer, emitter, adjudicator = _make_observer(signal_payloads=malformed_payloads)

    with pytest.raises(GovernanceSignalPayloadError):
        observer.handle_signal(_PROJECT, _STORY, _RUN, signal_type_wire=_SIGNAL_A)

    # No telemetry emitted before the raise.
    assert len(emitter._events) == 0, (
        "No events must be emitted when the window contains a malformed payload"
    )
    # Adjudicator must NOT have been called.
    assert adjudicator.call_count == 0, (
        "Adjudicator must NOT be called when payload validation raises fail-closed"
    )
