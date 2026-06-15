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

from pydantic import BaseModel, ConfigDict, field_validator

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

    @field_validator("start", "end", mode="after")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        """Reject naive datetimes (fail-closed — ambiguous UTC vs. local time).

        Uses ``mode="after"`` so the validator runs on the final parsed
        ``datetime`` value — this catches both an already-typed naive
        ``datetime`` object AND a naive ISO-8601 string that Pydantic would
        otherwise parse into a naive ``datetime`` after the "before" stage.
        """
        if value.tzinfo is None:
            raise ValueError(
                "PeriodFilter timestamps must be timezone-aware (tzinfo must not be None)"
            )
        return value


class EntityFilter(BaseModel):
    """Optional entity-scoping filter for KPI queries (FK-63 §63.4.2).

    Narrows KPI results to a specific guard or LLM pool.  Both fields are
    optional; supply at most one to avoid contradictory constraints.
    """

    model_config = _RECORD_CONFIG

    guard: str | None = None
    pool: str | None = None


class StoryFilter(BaseModel):
    """Optional story-attribute filter for KPI queries (FK-63 §63.4.2).

    Narrows KPI results to stories with specific ``story_type`` or
    ``story_size``.  Both fields are optional.
    """

    model_config = _RECORD_CONFIG

    story_type: str | None = None
    story_size: str | None = None


class KpiQueryFilter(BaseModel):
    """Typed KPI query filter model (FK-63 §63.3.3 / §63.4.2).

    Binds the FK-63 §63.4.2 query parameters into a validated, deterministic
    filter object.  Fail-closed: invalid or contradictory inputs are rejected
    at model-validation time — no silent softening.

    Rules enforced at construction:
    - ``period`` is mandatory; ``start`` must be strictly before ``end``.
    - ``entity_filter.guard`` and ``entity_filter.pool`` are mutually
      exclusive (specifying both is contradictory for a single KPI dimension).
    - ``comparison_period``, when provided, must be a non-overlapping window
      that ends at or before ``period.start``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    period: PeriodFilter
    entity_filter: EntityFilter = EntityFilter()
    story_filter: StoryFilter = StoryFilter()
    comparison_period: PeriodFilter | None = None

    def model_post_init(self, __context: object) -> None:
        """Validate cross-field constraints (fail-closed)."""
        if self.period.start >= self.period.end:
            raise ValueError(
                f"KpiQueryFilter.period.start must be < period.end; "
                f"got start={self.period.start!r}, end={self.period.end!r}"
            )
        if (
            self.entity_filter.guard is not None
            and self.entity_filter.pool is not None
        ):
            raise ValueError(
                "KpiQueryFilter.entity_filter: 'guard' and 'pool' are mutually exclusive"
            )
        if self.comparison_period is not None:
            if self.comparison_period.start >= self.comparison_period.end:
                raise ValueError(
                    "KpiQueryFilter.comparison_period.start must be < comparison_period.end"
                )
            if self.comparison_period.end > self.period.start:
                raise ValueError(
                    "KpiQueryFilter.comparison_period must end at or before period.start "
                    f"(comparison_period.end={self.comparison_period.end!r}, "
                    f"period.start={self.period.start!r})"
                )


__all__ = [
    "EntityFilter",
    "FactCorpusPeriod",
    "FactGuardPeriod",
    "FactPipelinePeriod",
    "FactPoolPeriod",
    "FactStory",
    "GuardInvocationCounter",
    "KpiQueryFilter",
    "PeriodFilter",
    "StoryFilter",
    "SyncState",
]
