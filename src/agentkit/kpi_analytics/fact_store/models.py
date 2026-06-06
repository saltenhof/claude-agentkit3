"""Pydantic record models for the analytics fact tables (FK-62 §62.2).

These frozen, ``extra="forbid"`` models are the typed shape of the five fact
tables plus ``sync_state`` (FK-62 §62.2.7). They mirror the column subset pinned
in story AG3-038 §2.1.1 (the binding spec); FK-62 §62.2 carries the full KPI
inventory that the follow-up RefreshWorker story will populate.

Mandantenregel (FK-62 §62.2): ``project_key`` is the leading scope key on every
record, so analytics stays per-project isolable even on a central database.

This module is an A-bloodtype BC-Record carrier (no side effects, no I/O). It is
imported by the FactStore and by the FactRepository implementations through the
consumer-owned ``FactRepository`` Protocol (AC8 import boundary).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

_RECORD_CONFIG = ConfigDict(frozen=True, extra="forbid")


class FactStory(BaseModel):
    """One analytics row per completed story (grain: 1 row per story).

    Primary key: ``(project_key, story_id)`` (FK-62 §62.2.1, story §2.1.1).
    Written/updated at story closure by the (follow-up) RefreshWorker.
    """

    model_config = _RECORD_CONFIG

    project_key: str
    story_id: str
    story_type: str
    story_size: str
    story_mode: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    qa_rounds: int
    compaction_count: int | None = None
    llm_call_count: int | None = None
    adversarial_findings: int | None = None
    adversarial_tests_created: int | None = None
    files_changed: int | None = None
    feedback_converged: bool | None = None
    phase_setup_ms: int | None = None
    phase_implementation_ms: int | None = None
    phase_closure_ms: int | None = None
    are_gate_status: str | None = None
    agentkit_version: str
    agentkit_commit: str


class FactGuardPeriod(BaseModel):
    """One row per guard per period (FK-62 §62.2.2).

    Primary key: ``(project_key, guard_id, period_start)`` (story §2.1.1).
    """

    model_config = _RECORD_CONFIG

    project_key: str
    guard_id: str
    period_start: datetime
    period_end: datetime
    invocation_count: int
    violation_count: int


class FactPoolPeriod(BaseModel):
    """One row per LLM role/pool per period (FK-62 §62.2.3).

    Primary key: ``(project_key, llm_role, period_start)`` (story §2.1.1).
    """

    model_config = _RECORD_CONFIG

    project_key: str
    llm_role: str
    period_start: datetime
    period_end: datetime
    call_count: int
    token_input_total: int
    token_output_total: int
    avg_latency_ms: int | None = None


class FactPipelinePeriod(BaseModel):
    """One row per period of global pipeline KPIs (FK-62 §62.2.4).

    Primary key: ``(project_key, period_start)`` (story §2.1.1).
    """

    model_config = _RECORD_CONFIG

    project_key: str
    period_start: datetime
    period_end: datetime
    stories_completed: int
    stories_escalated: int
    avg_qa_rounds: float | None = None
    avg_phase_implementation_ms: int | None = None


class FactCorpusPeriod(BaseModel):
    """One row per period of failure-corpus KPIs (FK-62 §62.2.5).

    Primary key: ``(project_key, period_start)`` (story §2.1.1).
    """

    model_config = _RECORD_CONFIG

    project_key: str
    period_start: datetime
    period_end: datetime
    incidents_recorded: int
    patterns_promoted: int
    checks_approved: int


class SyncState(BaseModel):
    """A per-project sync cursor entry (FK-62 §62.2.7).

    Primary key: ``(project_key, key)``. ``sync_state`` is a generic key-value
    cursor store scoped per project — there is NO global refresh pointer across
    projects (FK-62 §62.2.7 / FK-60). Known ``key`` entries (FK-62 §62.2.7):

    - ``last_event_id`` — monotonic cursor over ``execution_events.event_id``
      (carried in ``value_text`` as the event-id string).
    - ``last_synced_at`` — ISO-8601 instant of the last sync (``value_text``).
    - ``schema_version`` — migration schema version (``value_int``, FK-62 §62.4.3).

    ``value_int`` and ``value_text`` are the two payload slots; a given key uses
    exactly one of them and leaves the other ``None``.
    """

    model_config = _RECORD_CONFIG

    project_key: str
    key: str
    value_int: int | None = None
    value_text: str | None = None
    updated_at: datetime


class GuardInvocationCounter(BaseModel):
    """A guard-invocation scratchpad counter row (FK-62 §62.2.6, FK-61 §61.4.3).

    Lightweight hot-path scratchpad written by the guard hooks (one UPSERT per
    guard call); the (follow-up) RefreshWorker drains it into
    ``fact_guard_period`` and deletes the processed rows. Weekly granularity in
    the key supports reset and weekly rollup.

    Primary key: ``(project_key, story_id, guard_key, week_start)`` (FK-62
    §62.2.6 / FK-61 §61.4.3 verbatim). ``invocations`` is the call count and
    ``blocks`` the blocking subset (violation-rate numerator).
    """

    model_config = _RECORD_CONFIG

    project_key: str
    story_id: str
    guard_key: str
    week_start: str
    invocations: int = 0
    blocks: int = 0
    updated_at: datetime


class PeriodFilter(BaseModel):
    """A half-open ``[start, end)`` period window for fact reads.

    Used by ``FactStore.list_*`` to bound period-grained reads. ``end`` is
    exclusive; both bounds are timezone-aware instants.
    """

    model_config = _RECORD_CONFIG

    start: datetime
    end: datetime


__all__ = [
    "FactCorpusPeriod",
    "FactGuardPeriod",
    "FactPipelinePeriod",
    "FactPoolPeriod",
    "FactStory",
    "GuardInvocationCounter",
    "PeriodFilter",
    "SyncState",
]
