"""Contract tests for AG3-116: KPI wire DTO (Anti-Corruption-Layer).

Pins the EXACT FK-62-named wire-key sets per dimension and verifies:
- AC2: exact wire-key set per dimension (not just presence); dropped fields absent.
- AC3: DTO mapping unit — internal record fields → FK-62 wire keys.
- AC1: routes.py uses map_fact_row_to_wire, not raw model_dump (source-level check).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
)
from agentkit.kpi_analytics.http.wire_dto import (
    WireKpiCorpusRow,
    WireKpiGuardRow,
    WireKpiPipelineRow,
    WireKpiPoolRow,
    WireKpiStoryRow,
    map_fact_row_to_wire,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_END = datetime(2026, 6, 30, tzinfo=UTC)

# ---------------------------------------------------------------------------
# AC2: exact wire-key set per dimension (not just presence)
# ---------------------------------------------------------------------------

# The FK-62-named wire-key sets for today's available fields.
# These are the single source of truth for the wire contract.

_EXPECTED_STORY_KEYS = frozenset({
    "project_key",
    "story_id",
    "story_type",
    "story_size",
    "pipeline_mode",
    "opened_at",
    "closed_at",
    "qa_round_count",
    "compaction_count",
    "llm_call_count",
    "adversarial_findings_count",
    "adversarial_tests_created",
    "files_changed",
    "feedback_converged",
    "phase_setup_ms",
    "phase_implementation_ms",
    "phase_closure_ms",
    "are_gate_passed",
})

_EXPECTED_GUARD_KEYS = frozenset({
    "project_key",
    "guard_key",
    "period_start",
    "invocation_count",
    "violation_count",
})

_EXPECTED_POOL_KEYS = frozenset({
    "project_key",
    "pool_key",
    "period_start",
    "call_count",
})

_EXPECTED_PIPELINE_KEYS = frozenset({
    "project_key",
    "period_start",
    "story_count_closed",
    "qa_round_avg",
})

_EXPECTED_CORPUS_KEYS = frozenset({
    "project_key",
    "period_start",
    "new_incident_count",
    "patterns_total_count",
    "patterns_with_active_check",
})

# FK-62-dropped fields that MUST NOT appear on the wire.
_DROPPED_FIELDS = frozenset({
    "token_input_total",
    "token_output_total",
    "avg_latency_ms",
    "agentkit_version",
    "agentkit_commit",
    "period_end",
    "stories_escalated",
    # Also internal names that are renamed:
    "story_mode",
    "started_at",
    "completed_at",
    "qa_rounds",
    "adversarial_findings",
    "are_gate_status",
    "guard_id",
    "llm_role",
    "stories_completed",
    "avg_qa_rounds",
    "incidents_recorded",
    "patterns_promoted",
    "checks_approved",
    "avg_phase_implementation_ms",
})


def _make_story() -> FactStory:
    return FactStory(
        project_key="tenant-a",
        story_id="AG3-001",
        story_type="implementation",
        story_size="M",
        story_mode="standard",
        started_at=_NOW,
        completed_at=_END,
        qa_rounds=3,
        compaction_count=1,
        llm_call_count=45,
        adversarial_findings=2,
        adversarial_tests_created=5,
        files_changed=8,
        feedback_converged=True,
        phase_setup_ms=1200,
        phase_implementation_ms=45000,
        phase_closure_ms=3000,
        are_gate_status="PASS",
        agentkit_version="3.0.0",
        agentkit_commit="abc123",
    )


def _make_guard() -> FactGuardPeriod:
    return FactGuardPeriod(
        project_key="tenant-a",
        guard_id="no_competing_mode",
        period_start=_NOW,
        period_end=_END,
        invocation_count=12,
        violation_count=3,
    )


def _make_pool() -> FactPoolPeriod:
    return FactPoolPeriod(
        project_key="tenant-a",
        llm_role="worker",
        period_start=_NOW,
        period_end=_END,
        call_count=99,
        token_input_total=1000,
        token_output_total=500,
        avg_latency_ms=1200,
    )


def _make_pipeline() -> FactPipelinePeriod:
    return FactPipelinePeriod(
        project_key="tenant-a",
        period_start=_NOW,
        period_end=_END,
        stories_completed=7,
        stories_escalated=1,
        avg_qa_rounds=2.5,
        avg_phase_implementation_ms=40000,
    )


def _make_corpus() -> FactCorpusPeriod:
    return FactCorpusPeriod(
        project_key="tenant-a",
        period_start=_NOW,
        period_end=_END,
        incidents_recorded=8,
        patterns_promoted=3,
        checks_approved=2,
    )


def test_story_wire_keys_exact() -> None:
    """AC2: FactStory → wire has exactly the FK-62-named story keys (no more, no less)."""
    wire = map_fact_row_to_wire(_make_story())
    actual = frozenset(wire.keys())
    assert actual == _EXPECTED_STORY_KEYS, (
        f"Story wire key mismatch.\n"
        f"  Missing: {_EXPECTED_STORY_KEYS - actual}\n"
        f"  Unexpected: {actual - _EXPECTED_STORY_KEYS}"
    )


def test_guard_wire_keys_exact() -> None:
    """AC2: FactGuardPeriod → wire has exactly the FK-62-named guard keys."""
    wire = map_fact_row_to_wire(_make_guard())
    actual = frozenset(wire.keys())
    assert actual == _EXPECTED_GUARD_KEYS, (
        f"Guard wire key mismatch.\n"
        f"  Missing: {_EXPECTED_GUARD_KEYS - actual}\n"
        f"  Unexpected: {actual - _EXPECTED_GUARD_KEYS}"
    )


def test_pool_wire_keys_exact() -> None:
    """AC2: FactPoolPeriod → wire has exactly the FK-62-named pool keys."""
    wire = map_fact_row_to_wire(_make_pool())
    actual = frozenset(wire.keys())
    assert actual == _EXPECTED_POOL_KEYS, (
        f"Pool wire key mismatch.\n"
        f"  Missing: {_EXPECTED_POOL_KEYS - actual}\n"
        f"  Unexpected: {actual - _EXPECTED_POOL_KEYS}"
    )


def test_pipeline_wire_keys_exact() -> None:
    """AC2: FactPipelinePeriod → wire has exactly the FK-62-named pipeline keys."""
    wire = map_fact_row_to_wire(_make_pipeline())
    actual = frozenset(wire.keys())
    assert actual == _EXPECTED_PIPELINE_KEYS, (
        f"Pipeline wire key mismatch.\n"
        f"  Missing: {_EXPECTED_PIPELINE_KEYS - actual}\n"
        f"  Unexpected: {actual - _EXPECTED_PIPELINE_KEYS}"
    )


def test_corpus_wire_keys_exact() -> None:
    """AC2: FactCorpusPeriod → wire has exactly the FK-62-named corpus keys."""
    wire = map_fact_row_to_wire(_make_corpus())
    actual = frozenset(wire.keys())
    assert actual == _EXPECTED_CORPUS_KEYS, (
        f"Corpus wire key mismatch.\n"
        f"  Missing: {_EXPECTED_CORPUS_KEYS - actual}\n"
        f"  Unexpected: {actual - _EXPECTED_CORPUS_KEYS}"
    )


@pytest.mark.parametrize("dropped_field", sorted(_DROPPED_FIELDS))
def test_dropped_fields_absent_from_all_wire_outputs(dropped_field: str) -> None:
    """AC2: FK-62-dropped / internal-renamed fields MUST NOT appear in any wire output."""
    for row in [_make_story(), _make_guard(), _make_pool(), _make_pipeline(), _make_corpus()]:
        wire = map_fact_row_to_wire(row)
        assert dropped_field not in wire, (
            f"Dropped/renamed field {dropped_field!r} leaked into wire output "
            f"for {type(row).__name__}. Wire keys: {sorted(wire.keys())}"
        )


# ---------------------------------------------------------------------------
# AC3: DTO mapping unit — correct value mapping per dimension
# ---------------------------------------------------------------------------


def test_story_dto_renames_applied_correctly() -> None:
    """AC3: FactStory(story_mode, started_at, are_gate_status) → DTO with FK-62 names."""
    record = FactStory(
        project_key="tenant-a",
        story_id="AG3-042",
        story_type="implementation",
        story_size="S",
        story_mode="fast-track",
        started_at=_NOW,
        completed_at=_END,
        qa_rounds=7,
        are_gate_status="PASS",
        agentkit_version="3.1.0",
        agentkit_commit="deadbeef",
    )
    wire = map_fact_row_to_wire(record)

    # Renames verified
    assert wire["pipeline_mode"] == "fast-track", "story_mode must be mapped to pipeline_mode"
    assert wire["opened_at"] == _NOW.isoformat(), "started_at must be mapped to opened_at"
    assert wire["closed_at"] == _END.isoformat(), "completed_at must be mapped to closed_at"
    assert wire["qa_round_count"] == 7, "qa_rounds must be mapped to qa_round_count"
    assert wire["are_gate_passed"] == "PASS", "are_gate_status must be mapped to are_gate_passed"

    # Dropped fields must not be present
    assert "story_mode" not in wire
    assert "started_at" not in wire
    assert "completed_at" not in wire
    assert "qa_rounds" not in wire
    assert "are_gate_status" not in wire
    assert "agentkit_version" not in wire
    assert "agentkit_commit" not in wire


def test_guard_dto_renames_applied_correctly() -> None:
    """AC3: FactGuardPeriod(guard_id) → DTO with guard_key; period_end absent."""
    record = _make_guard()
    wire = map_fact_row_to_wire(record)

    assert wire["guard_key"] == "no_competing_mode", "guard_id must be mapped to guard_key"
    assert "guard_id" not in wire
    assert "period_end" not in wire
    assert wire["invocation_count"] == 12
    assert wire["violation_count"] == 3


def test_pool_dto_renames_applied_correctly() -> None:
    """AC3: FactPoolPeriod(llm_role) → DTO with pool_key; tokens/latency/period_end absent."""
    record = _make_pool()
    wire = map_fact_row_to_wire(record)

    assert wire["pool_key"] == "worker", "llm_role must be mapped to pool_key"
    assert "llm_role" not in wire
    assert "period_end" not in wire
    assert "token_input_total" not in wire
    assert "token_output_total" not in wire
    assert "avg_latency_ms" not in wire
    assert wire["call_count"] == 99


def test_pipeline_dto_renames_applied_correctly() -> None:
    """AC3: FactPipelinePeriod(stories_completed, avg_qa_rounds) → FK-62 wire keys."""
    record = _make_pipeline()
    wire = map_fact_row_to_wire(record)

    assert wire["story_count_closed"] == 7, "stories_completed must map to story_count_closed"
    assert wire["qa_round_avg"] == 2.5, "avg_qa_rounds must map to qa_round_avg"
    assert "stories_completed" not in wire
    assert "avg_qa_rounds" not in wire
    assert "stories_escalated" not in wire
    assert "period_end" not in wire
    assert "avg_phase_implementation_ms" not in wire


def test_corpus_dto_renames_applied_correctly() -> None:
    """AC3: FactCorpusPeriod(incidents_recorded, patterns_promoted, checks_approved) → FK-62 keys."""
    record = _make_corpus()
    wire = map_fact_row_to_wire(record)

    assert wire["new_incident_count"] == 8, "incidents_recorded must map to new_incident_count"
    assert wire["patterns_total_count"] == 3, "patterns_promoted must map to patterns_total_count"
    assert wire["patterns_with_active_check"] == 2, "checks_approved must map to patterns_with_active_check"
    assert "incidents_recorded" not in wire
    assert "patterns_promoted" not in wire
    assert "checks_approved" not in wire
    assert "period_end" not in wire


def test_story_are_gate_passed_maps_none_faithfully() -> None:
    """AC3: are_gate_status=None → are_gate_passed=None (name-only rename, no value change)."""
    record = FactStory(
        project_key="tenant-a",
        story_id="AG3-099",
        story_type="spike",
        story_size="S",
        started_at=_NOW,
        qa_rounds=0,
        are_gate_status=None,
        agentkit_version="3.0.0",
        agentkit_commit="abc",
    )
    wire = map_fact_row_to_wire(record)
    assert wire["are_gate_passed"] is None


def test_story_are_gate_passed_maps_fail_value_faithfully() -> None:
    """AC3: are_gate_status='FAIL' → are_gate_passed='FAIL' (semantics faithful)."""
    record = FactStory(
        project_key="tenant-a",
        story_id="AG3-100",
        story_type="implementation",
        story_size="M",
        started_at=_NOW,
        qa_rounds=2,
        are_gate_status="FAIL",
        agentkit_version="3.0.0",
        agentkit_commit="abc",
    )
    wire = map_fact_row_to_wire(record)
    assert wire["are_gate_passed"] == "FAIL"


# ---------------------------------------------------------------------------
# AC1: routes.py must not use raw model_dump for fact rows (source-level check)
# ---------------------------------------------------------------------------


def test_routes_does_not_use_raw_model_dump_for_fact_rows() -> None:
    """AC1: _build_kpi_payload must not contain row.model_dump(mode='json') for fact rows.

    The only model_dump calls permitted in routes.py are those inside
    wire_dto.py (through map_fact_row_to_wire) and the DesignTokens edge
    (_handle_design_tokens uses .model_dump on typed token sub-models directly).
    """
    import inspect

    from agentkit.kpi_analytics.http.routes import KpiAnalyticsRoutes

    source = inspect.getsource(KpiAnalyticsRoutes._build_kpi_payload)
    # The raw per-row dump pattern must be gone.
    assert "row.model_dump" not in source, (
        "_build_kpi_payload must not use raw row.model_dump(mode='json'); "
        "use map_fact_row_to_wire instead (AG3-116 AC1)"
    )
    # The DTO mapper must be present.
    assert "map_fact_row_to_wire" in source, (
        "_build_kpi_payload must use map_fact_row_to_wire for fact-row serialization"
    )


# ---------------------------------------------------------------------------
# DTO model structure contracts (typed Pydantic, extra=forbid)
# ---------------------------------------------------------------------------


def test_wire_dto_models_are_pydantic_base_models() -> None:
    """All five wire DTO classes are Pydantic BaseModel instances."""
    from pydantic import BaseModel

    for cls in (WireKpiStoryRow, WireKpiGuardRow, WireKpiPoolRow, WireKpiPipelineRow, WireKpiCorpusRow):
        assert issubclass(cls, BaseModel), f"{cls.__name__} must be a Pydantic BaseModel"


def test_wire_dto_models_are_frozen_and_strict() -> None:
    """All wire DTO models are frozen=True, extra='forbid'."""
    for cls in (WireKpiStoryRow, WireKpiGuardRow, WireKpiPoolRow, WireKpiPipelineRow, WireKpiCorpusRow):
        config = cls.model_config
        assert config.get("frozen") is True, f"{cls.__name__}.frozen must be True"
        assert config.get("extra") == "forbid", f"{cls.__name__}.extra must be 'forbid'"


def test_map_fact_row_unknown_type_raises_type_error() -> None:
    """map_fact_row_to_wire raises TypeError on unknown DashboardFactRow variant (fail-closed)."""

    class _UnknownRow:
        pass

    import typing

    with pytest.raises(TypeError, match="Unknown DashboardFactRow variant"):
        map_fact_row_to_wire(typing.cast("FactStory", _UnknownRow()))
