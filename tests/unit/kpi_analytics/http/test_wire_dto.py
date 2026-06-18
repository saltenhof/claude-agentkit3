"""Unit tests for kpi_analytics/http/wire_dto.py (AG3-116).

AC3: DTO mapping — FactStory/Guard/Pool/Pipeline/Corpus records map to
FK-62-named wire keys with correct value transformations.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
)
from agentkit.kpi_analytics.http.wire_dto import map_fact_row_to_wire

_NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
_END = datetime(2026, 3, 31, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# FactStory mapping
# ---------------------------------------------------------------------------


def test_fact_story_mapping_renames() -> None:
    """AC3 (story): story_mode→pipeline_mode, started_at→opened_at, etc."""
    record = FactStory(
        project_key="pk",
        story_id="S-1",
        story_type="implementation",
        story_size="M",
        story_mode="standard",
        started_at=_NOW,
        completed_at=_END,
        qa_rounds=5,
        are_gate_status="PASS",
        adversarial_findings=3,
        agentkit_version="3.0.0",
        agentkit_commit="abc",
    )
    wire = map_fact_row_to_wire(record)

    assert wire["pipeline_mode"] == "standard"
    assert wire["opened_at"] == _NOW.isoformat()
    assert wire["closed_at"] == _END.isoformat()
    assert wire["qa_round_count"] == 5
    assert wire["are_gate_passed"] == "PASS"
    assert wire["adversarial_findings_count"] == 3

    # Internal names must not be present
    assert "story_mode" not in wire
    assert "started_at" not in wire
    assert "completed_at" not in wire
    assert "qa_rounds" not in wire
    assert "are_gate_status" not in wire
    assert "adversarial_findings" not in wire
    assert "agentkit_version" not in wire
    assert "agentkit_commit" not in wire


def test_fact_story_null_optional_fields_preserved() -> None:
    """AC3 (story): None optional fields are preserved as None (not dropped)."""
    record = FactStory(
        project_key="pk",
        story_id="S-2",
        story_type="spike",
        story_size="S",
        story_mode=None,
        started_at=_NOW,
        completed_at=None,
        qa_rounds=0,
        are_gate_status=None,
        agentkit_version="3.0.0",
        agentkit_commit="abc",
    )
    wire = map_fact_row_to_wire(record)

    assert wire["pipeline_mode"] is None
    assert wire["closed_at"] is None
    assert wire["are_gate_passed"] is None


def test_fact_story_static_fields_unchanged() -> None:
    """AC3 (story): unchanged fields pass through with correct values."""
    record = FactStory(
        project_key="tenant-x",
        story_id="S-99",
        story_type="bug",
        story_size="L",
        started_at=_NOW,
        qa_rounds=2,
        compaction_count=3,
        llm_call_count=100,
        files_changed=12,
        agentkit_version="3.0.0",
        agentkit_commit="abc",
    )
    wire = map_fact_row_to_wire(record)

    assert wire["project_key"] == "tenant-x"
    assert wire["story_id"] == "S-99"
    assert wire["story_type"] == "bug"
    assert wire["story_size"] == "L"
    assert wire["compaction_count"] == 3
    assert wire["llm_call_count"] == 100
    assert wire["files_changed"] == 12


# ---------------------------------------------------------------------------
# FactGuardPeriod mapping
# ---------------------------------------------------------------------------


def test_fact_guard_mapping_renames() -> None:
    """AC3 (guard): guard_id→guard_key; period_end dropped."""
    record = FactGuardPeriod(
        project_key="pk",
        guard_id="arch_conformance",
        period_start=_NOW,
        period_end=_END,
        invocation_count=20,
        violation_count=5,
    )
    wire = map_fact_row_to_wire(record)

    assert wire["guard_key"] == "arch_conformance"
    assert wire["period_start"] == _NOW.isoformat()
    assert wire["invocation_count"] == 20
    assert wire["violation_count"] == 5

    assert "guard_id" not in wire
    assert "period_end" not in wire


# ---------------------------------------------------------------------------
# FactPoolPeriod mapping
# ---------------------------------------------------------------------------


def test_fact_pool_mapping_renames() -> None:
    """AC3 (pool): llm_role→pool_key; tokens/latency/period_end dropped."""
    record = FactPoolPeriod(
        project_key="pk",
        llm_role="orchestrator",
        period_start=_NOW,
        period_end=_END,
        call_count=55,
        token_input_total=9000,
        token_output_total=4000,
        avg_latency_ms=800,
    )
    wire = map_fact_row_to_wire(record)

    assert wire["pool_key"] == "orchestrator"
    assert wire["call_count"] == 55
    assert wire["period_start"] == _NOW.isoformat()

    assert "llm_role" not in wire
    assert "period_end" not in wire
    assert "token_input_total" not in wire
    assert "token_output_total" not in wire
    assert "avg_latency_ms" not in wire


# ---------------------------------------------------------------------------
# FactPipelinePeriod mapping
# ---------------------------------------------------------------------------


def test_fact_pipeline_mapping_renames() -> None:
    """AC3 (pipeline): stories_completed→story_count_closed, avg_qa_rounds→qa_round_avg."""
    record = FactPipelinePeriod(
        project_key="pk",
        period_start=_NOW,
        period_end=_END,
        stories_completed=14,
        stories_escalated=2,
        avg_qa_rounds=3.5,
        avg_phase_implementation_ms=60000,
    )
    wire = map_fact_row_to_wire(record)

    assert wire["story_count_closed"] == 14
    assert wire["qa_round_avg"] == 3.5
    assert wire["period_start"] == _NOW.isoformat()

    assert "stories_completed" not in wire
    assert "avg_qa_rounds" not in wire
    assert "stories_escalated" not in wire
    assert "period_end" not in wire
    assert "avg_phase_implementation_ms" not in wire


def test_fact_pipeline_qa_round_avg_none() -> None:
    """AC3 (pipeline): avg_qa_rounds=None → qa_round_avg=None."""
    record = FactPipelinePeriod(
        project_key="pk",
        period_start=_NOW,
        period_end=_END,
        stories_completed=0,
        stories_escalated=0,
        avg_qa_rounds=None,
    )
    wire = map_fact_row_to_wire(record)
    assert wire["qa_round_avg"] is None


# ---------------------------------------------------------------------------
# FactCorpusPeriod mapping
# ---------------------------------------------------------------------------


def test_fact_corpus_mapping_renames() -> None:
    """AC3 (corpus): incidents→new_incident_count, promoted→patterns_total_count, etc."""
    record = FactCorpusPeriod(
        project_key="pk",
        period_start=_NOW,
        period_end=_END,
        incidents_recorded=10,
        patterns_promoted=4,
        checks_approved=3,
    )
    wire = map_fact_row_to_wire(record)

    assert wire["new_incident_count"] == 10
    assert wire["patterns_total_count"] == 4
    assert wire["patterns_with_active_check"] == 3
    assert wire["period_start"] == _NOW.isoformat()

    assert "incidents_recorded" not in wire
    assert "patterns_promoted" not in wire
    assert "checks_approved" not in wire
    assert "period_end" not in wire


# ---------------------------------------------------------------------------
# Dispatch / fail-closed
# ---------------------------------------------------------------------------


def test_map_fact_row_dispatches_correctly_to_each_variant() -> None:
    """map_fact_row_to_wire dispatches to the correct mapping per variant."""
    story = FactStory(
        project_key="pk", story_id="S-1", story_type="implementation",
        story_size="S", started_at=_NOW, qa_rounds=1,
        agentkit_version="3.0.0", agentkit_commit="abc",
    )
    guard = FactGuardPeriod(
        project_key="pk", guard_id="g", period_start=_NOW, period_end=_END,
        invocation_count=1, violation_count=0,
    )
    pool = FactPoolPeriod(
        project_key="pk", llm_role="r", period_start=_NOW, period_end=_END,
        call_count=1, token_input_total=10, token_output_total=5,
    )
    pipeline = FactPipelinePeriod(
        project_key="pk", period_start=_NOW, period_end=_END,
        stories_completed=1, stories_escalated=0,
    )
    corpus = FactCorpusPeriod(
        project_key="pk", period_start=_NOW, period_end=_END,
        incidents_recorded=1, patterns_promoted=0, checks_approved=1,
    )

    assert "pipeline_mode" in map_fact_row_to_wire(story)
    assert "guard_key" in map_fact_row_to_wire(guard)
    assert "pool_key" in map_fact_row_to_wire(pool)
    assert "story_count_closed" in map_fact_row_to_wire(pipeline)
    assert "new_incident_count" in map_fact_row_to_wire(corpus)
