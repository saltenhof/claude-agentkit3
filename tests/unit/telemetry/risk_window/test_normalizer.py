"""Unit tests for EventNormalizer + NormalizedEvent (FK-68 §68.8, AG3-037)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.core_types import Severity
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.risk_window.normalized_event import NormalizedEvent, RiskCategory
from agentkit.backend.telemetry.risk_window.normalizer import EventNormalizer


def _record(event_type: str, *, payload: dict[str, object] | None = None) -> ExecutionEventRecord:
    return ExecutionEventRecord(
        project_key="proj",
        story_id="AG3-001",
        run_id="run-001",
        event_id=f"evt-{event_type}",
        event_type=event_type,
        occurred_at=datetime(2026, 6, 6, tzinfo=UTC),
        source_component="test",
        severity="info",
        payload=payload or {},
    )


class _CollectingWriter:
    """First-class RiskWindowWriter fake (collects written events)."""

    def __init__(self) -> None:
        self.written: list[NormalizedEvent] = []

    def record_risk_window_event(self, event: NormalizedEvent) -> None:
        self.written.append(event)


# ---------------------------------------------------------------------------
# RiskCategory enum (AC6)
# ---------------------------------------------------------------------------


def test_risk_category_values() -> None:
    assert RiskCategory.SECURITY.value == "security"
    assert RiskCategory.INTEGRITY.value == "integrity"
    assert RiskCategory.OPERATIONAL.value == "operational"
    assert RiskCategory.BUDGET.value == "budget"


# ---------------------------------------------------------------------------
# Mapping per AC5
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("agent_start", RiskCategory.OPERATIONAL),
        ("agent_end", RiskCategory.OPERATIONAL),
        ("integrity_violation", RiskCategory.INTEGRITY),
        ("review_divergence", RiskCategory.INTEGRITY),
        ("web_call", RiskCategory.BUDGET),
    ],
)
def test_normalize_maps_to_expected_category(
    event_type: str, expected: RiskCategory
) -> None:
    result = EventNormalizer().normalize(_record(event_type))
    assert result is not None
    assert result.risk_category is expected
    assert result.source_event_type.value == event_type
    assert result.event_id == f"evt-{event_type}"
    assert result.story_id == "AG3-001"
    assert result.run_id == "run-001"


def test_normalize_severity_per_category() -> None:
    integrity = EventNormalizer().normalize(_record("integrity_violation"))
    operational = EventNormalizer().normalize(_record("agent_start"))
    assert integrity is not None and integrity.severity is Severity.MAJOR
    assert operational is not None and operational.severity is Severity.MINOR


def test_normalize_returns_none_for_non_risk_event() -> None:
    assert EventNormalizer().normalize(_record("flow_start")) is None
    assert EventNormalizer().normalize(_record("node_result")) is None


def test_normalize_returns_none_for_unknown_event_type() -> None:
    assert EventNormalizer().normalize(_record("not_a_real_event")) is None


def test_payload_excerpt_keeps_known_keys_only() -> None:
    record = _record(
        "integrity_violation",
        payload={"guard": "orchestrator_guard", "detail": "blocked", "secret": "x"},
    )
    result = EventNormalizer().normalize(record)
    assert result is not None
    assert result.payload_excerpt == {"guard": "orchestrator_guard", "detail": "blocked"}


def test_review_divergence_excerpt_uses_fk34_fields_only() -> None:
    record = _record(
        "review_divergence",
        payload={
            "reviewer_a": "qa",
            "reviewer_b": "security",
            "divergent": True,
            "quorum_triggered": True,
            "final_verdict": "FAIL",
        },
    )

    result = EventNormalizer().normalize(record)

    assert result is not None
    assert result.payload_excerpt == {
        "reviewer_a": "qa",
        "reviewer_b": "security",
        "divergent": True,
        "quorum_triggered": True,
        "final_verdict": "FAIL",
    }


# ---------------------------------------------------------------------------
# normalize_and_record write site (AC7 — write only)
# ---------------------------------------------------------------------------


def test_normalize_and_record_writes_risk_relevant_event() -> None:
    writer = _CollectingWriter()
    normalizer = EventNormalizer(risk_window_writer=writer)
    written = normalizer.normalize_and_record(_record("integrity_violation"))
    assert written is not None
    assert len(writer.written) == 1
    assert writer.written[0].risk_category is RiskCategory.INTEGRITY


def test_normalize_and_record_skips_non_risk_event() -> None:
    writer = _CollectingWriter()
    normalizer = EventNormalizer(risk_window_writer=writer)
    assert normalizer.normalize_and_record(_record("flow_start")) is None
    assert writer.written == []


def test_normalize_and_record_without_writer_fails_closed() -> None:
    normalizer = EventNormalizer()
    with pytest.raises(RuntimeError, match="RiskWindowWriter"):
        normalizer.normalize_and_record(_record("integrity_violation"))
