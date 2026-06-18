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
    """AC3 (story): FK-62 record fields → frozen AG3-116 wire keys."""
    record = FactStory(
        project_key="pk",
        story_id="S-1",
        story_type="implementation",
        story_size="M",
        pipeline_mode="standard",
        opened_at=_NOW,
        closed_at=_END,
        qa_round_count=5,
        are_gate_passed=True,
        adversarial_findings_count=3,
        computed_at=_END,
    )
    wire = map_fact_row_to_wire(record)

    assert wire["pipeline_mode"] == "standard"
    assert wire["opened_at"] == _NOW.isoformat()
    assert wire["closed_at"] == _END.isoformat()
    assert wire["qa_round_count"] == 5
    assert wire["are_gate_passed"] == "PASS"  # bool True maps to "PASS" (R2)
    assert wire["adversarial_findings_count"] == 3

    # Internal / renamed / dropped names must not be present
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
        pipeline_mode=None,
        opened_at=_NOW,
        closed_at=None,
        qa_round_count=0,
        are_gate_passed=None,
        computed_at=_NOW,
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
        opened_at=_NOW,
        qa_round_count=2,
        compaction_count=3,
        llm_call_count=100,
        files_changed=12,
        computed_at=_NOW,
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
        guard_key="arch_conformance",
        period_start=_NOW,
        invocation_count=20,
        violation_count=5,
        computed_at=_END,
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
        pool_key="orchestrator",
        period_start=_NOW,
        call_count=55,
        computed_at=_END,
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
        story_count=16,
        story_count_closed=14,
        qa_round_avg=3.5,
        computed_at=_END,
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
        story_count=0,
        story_count_closed=0,
        qa_round_avg=None,
        computed_at=_END,
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
        new_incident_count=10,
        patterns_total_count=4,
        patterns_with_active_check=3,
        computed_at=_END,
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
        story_size="S", opened_at=_NOW, qa_round_count=1, computed_at=_END,
    )
    guard = FactGuardPeriod(
        project_key="pk", guard_key="g", period_start=_NOW,
        invocation_count=1, violation_count=0, computed_at=_END,
    )
    pool = FactPoolPeriod(
        project_key="pk", pool_key="r", period_start=_NOW,
        call_count=1, computed_at=_END,
    )
    pipeline = FactPipelinePeriod(
        project_key="pk", period_start=_NOW,
        story_count=1, story_count_closed=1, computed_at=_END,
    )
    corpus = FactCorpusPeriod(
        project_key="pk", period_start=_NOW,
        new_incident_count=1, computed_at=_END,
    )

    assert "pipeline_mode" in map_fact_row_to_wire(story)
    assert "guard_key" in map_fact_row_to_wire(guard)
    assert "pool_key" in map_fact_row_to_wire(pool)
    assert "story_count_closed" in map_fact_row_to_wire(pipeline)
    assert "new_incident_count" in map_fact_row_to_wire(corpus)
