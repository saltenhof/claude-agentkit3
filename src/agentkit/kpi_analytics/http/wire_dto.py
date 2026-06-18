"""Wire DTOs for the KPI analytics HTTP edge (FK-62 §62.2, AG3-116).

Anti-Corruption-Layer: typed wire contracts that decouple internal Fact-record
field names from the public JSON wire truth.  Internal Fact-records never leave
the process via raw model_dump; the mapping here is the single source of wire
keys per dimension.

Wire contract = FK-62-named projection of currently-available record fields:
- Fields that exist today in Fact-records are mapped to their FK-62 names now.
- Fields dropped by FK-62 are excluded from the wire (clean break, no ballast).
- Fields not yet produced by AG3-117/AG3-082 are absent (no invented fields).

This module is imported ONLY by kpi_analytics/http/routes.py — no other module
should depend on these wire types at runtime (they are HTTP-edge artifacts).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agentkit.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
)

if TYPE_CHECKING:
    from agentkit.kpi_analytics.views import DashboardFactRow

_WIRE_CONFIG = ConfigDict(frozen=True, extra="forbid")


class WireKpiStoryRow(BaseModel):
    """Wire DTO for a FactStory row (fact_story dimension).

    FK-62 §62.2.1 named projection of today's available FactStory fields.
    Dropped fields (no FK-62 equivalent): agentkit_version, agentkit_commit.
    Renamed fields: story_mode→pipeline_mode, started_at→opened_at,
    completed_at→closed_at, qa_rounds→qa_round_count,
    adversarial_findings→adversarial_findings_count,
    are_gate_status→are_gate_passed.
    """

    model_config = _WIRE_CONFIG

    project_key: str
    story_id: str
    story_type: str
    story_size: str
    pipeline_mode: str | None
    opened_at: str
    closed_at: str | None
    qa_round_count: int
    compaction_count: int | None
    llm_call_count: int | None
    adversarial_findings_count: int | None
    adversarial_tests_created: int | None
    files_changed: int | None
    feedback_converged: bool | None
    phase_setup_ms: int | None
    phase_implementation_ms: int | None
    phase_closure_ms: int | None
    are_gate_passed: str | None


class WireKpiGuardRow(BaseModel):
    """Wire DTO for a FactGuardPeriod row (guards dimension).

    FK-62 §62.2.2 named projection.  Dropped: period_end.
    Renamed: guard_id→guard_key.
    """

    model_config = _WIRE_CONFIG

    project_key: str
    guard_key: str
    period_start: str
    invocation_count: int
    violation_count: int


class WireKpiPoolRow(BaseModel):
    """Wire DTO for a FactPoolPeriod row (pools dimension).

    FK-62 §62.2.3 named projection.  Dropped: period_end, token_input_total,
    token_output_total, avg_latency_ms.  Renamed: llm_role→pool_key.
    """

    model_config = _WIRE_CONFIG

    project_key: str
    pool_key: str
    period_start: str
    call_count: int


class WireKpiPipelineRow(BaseModel):
    """Wire DTO for a FactPipelinePeriod row (pipeline dimension).

    FK-62 §62.2.4 named projection.  Dropped: period_end, stories_escalated,
    avg_phase_implementation_ms.  Renamed: stories_completed→story_count_closed,
    avg_qa_rounds→qa_round_avg.
    """

    model_config = _WIRE_CONFIG

    project_key: str
    period_start: str
    story_count_closed: int
    qa_round_avg: float | None


class WireKpiCorpusRow(BaseModel):
    """Wire DTO for a FactCorpusPeriod row (corpus dimension).

    FK-62 §62.2.5 named projection.  Dropped: period_end.
    Renamed: incidents_recorded→new_incident_count,
    patterns_promoted→patterns_total_count,
    checks_approved→patterns_with_active_check.
    """

    model_config = _WIRE_CONFIG

    project_key: str
    period_start: str
    new_incident_count: int
    patterns_total_count: int
    patterns_with_active_check: int


def _map_story(record: FactStory) -> dict[str, object]:
    """Map a FactStory record to its FK-62-named wire projection."""
    return WireKpiStoryRow(
        project_key=record.project_key,
        story_id=record.story_id,
        story_type=record.story_type,
        story_size=record.story_size,
        pipeline_mode=record.story_mode,
        opened_at=record.started_at.isoformat(),
        closed_at=record.completed_at.isoformat() if record.completed_at is not None else None,
        qa_round_count=record.qa_rounds,
        compaction_count=record.compaction_count,
        llm_call_count=record.llm_call_count,
        adversarial_findings_count=record.adversarial_findings,
        adversarial_tests_created=record.adversarial_tests_created,
        files_changed=record.files_changed,
        feedback_converged=record.feedback_converged,
        phase_setup_ms=record.phase_setup_ms,
        phase_implementation_ms=record.phase_implementation_ms,
        phase_closure_ms=record.phase_closure_ms,
        are_gate_passed=record.are_gate_status,
    ).model_dump(mode="json")


def _map_guard(record: FactGuardPeriod) -> dict[str, object]:
    """Map a FactGuardPeriod record to its FK-62-named wire projection."""
    return WireKpiGuardRow(
        project_key=record.project_key,
        guard_key=record.guard_id,
        period_start=record.period_start.isoformat(),
        invocation_count=record.invocation_count,
        violation_count=record.violation_count,
    ).model_dump(mode="json")


def _map_pool(record: FactPoolPeriod) -> dict[str, object]:
    """Map a FactPoolPeriod record to its FK-62-named wire projection."""
    return WireKpiPoolRow(
        project_key=record.project_key,
        pool_key=record.llm_role,
        period_start=record.period_start.isoformat(),
        call_count=record.call_count,
    ).model_dump(mode="json")


def _map_pipeline(record: FactPipelinePeriod) -> dict[str, object]:
    """Map a FactPipelinePeriod record to its FK-62-named wire projection."""
    return WireKpiPipelineRow(
        project_key=record.project_key,
        period_start=record.period_start.isoformat(),
        story_count_closed=record.stories_completed,
        qa_round_avg=record.avg_qa_rounds,
    ).model_dump(mode="json")


def _map_corpus(record: FactCorpusPeriod) -> dict[str, object]:
    """Map a FactCorpusPeriod record to its FK-62-named wire projection."""
    return WireKpiCorpusRow(
        project_key=record.project_key,
        period_start=record.period_start.isoformat(),
        new_incident_count=record.incidents_recorded,
        patterns_total_count=record.patterns_promoted,
        patterns_with_active_check=record.checks_approved,
    ).model_dump(mode="json")


def map_fact_row_to_wire(row: DashboardFactRow) -> dict[str, object]:
    """Dispatch a DashboardFactRow to the correct FK-62-named wire mapping.

    This is the single dispatch point for fact-row serialization at the HTTP
    edge.  Each dimension has a dedicated typed DTO; no raw model_dump leaks
    internal field names to the wire.

    Args:
        row: A typed fact record from the DashboardFactRow union.

    Returns:
        A plain dict with FK-62-named wire keys, ready for JSON serialization.

    Raises:
        TypeError: If an unknown DashboardFactRow variant is encountered
            (fail-closed — new variants must be explicitly mapped).
    """
    if isinstance(row, FactStory):
        return _map_story(row)
    if isinstance(row, FactGuardPeriod):
        return _map_guard(row)
    if isinstance(row, FactPoolPeriod):
        return _map_pool(row)
    if isinstance(row, FactPipelinePeriod):
        return _map_pipeline(row)
    if isinstance(row, FactCorpusPeriod):
        return _map_corpus(row)
    raise TypeError(
        f"Unknown DashboardFactRow variant: {type(row)!r}; "
        "add a mapping branch to map_fact_row_to_wire"
    )


__all__ = [
    "WireKpiCorpusRow",
    "WireKpiGuardRow",
    "WireKpiPipelineRow",
    "WireKpiPoolRow",
    "WireKpiStoryRow",
    "map_fact_row_to_wire",
]
