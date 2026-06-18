"""Pydantic record models for the analytics fact tables (FK-62 §62.2).

These frozen, ``extra="forbid"`` models are the typed shape of the five fact
tables plus ``sync_state`` (FK-62 §62.2.7). They carry the full FK-62 §62.2
column set (AG3-117 reconciliation): renames, new columns, drops and the
``are_gate_passed`` bool type-change are all applied here. The RefreshWorker
fill-logic for the still-defaulting new columns is AG3-082 territory.

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

    Primary key: ``(project_key, story_id)`` (FK-62 §62.2.1).
    Written/updated at story closure by the RefreshWorker. Carries the full
    FK-62 §62.2.1 column set (AG3-117 reconciliation); the RefreshWorker
    fill-logic for the still-defaulting columns is AG3-082 territory.
    """

    model_config = _RECORD_CONFIG

    project_key: str
    story_id: str
    story_type: str
    story_size: str
    pipeline_mode: str | None = None
    opened_at: datetime
    closed_at: datetime | None = None

    # Domain 1: story sizing
    processing_time_ms: int | None = None
    compaction_count: int = 0
    qa_round_count: int = 0
    feedback_converged: bool | None = None
    blocked_ac_count: int = 0
    blocked_ac_detail_json: str | None = None

    # Domain 2: LLM selection
    llm_call_count: int = 0

    # Domain 5: QA effectiveness
    adversarial_findings_count: int = 0
    adversarial_tests_created: int = 0
    adversarial_hit_rate: float | None = None
    findings_fully_resolved: int = 0
    findings_partially_resolved: int = 0
    findings_not_resolved: int = 0

    # Status (also for escalated/paused stories)
    final_status: str | None = None

    # Domain 8: ARE
    are_gate_passed: bool | None = None
    are_total_requirements: int | None = None
    are_covered_requirements: int | None = None

    # Domain 10: process efficiency
    files_changed: int = 0
    increment_count: int = 0
    phase_setup_ms: int | None = None
    phase_exploration_ms: int | None = None
    phase_implementation_ms: int | None = None
    phase_verify_ms: int | None = None
    phase_closure_ms: int | None = None

    # Meta
    computed_at: datetime


class FactGuardPeriod(BaseModel):
    """One row per guard per period (FK-62 §62.2.2).

    Primary key: ``(project_key, guard_key, period_start)``.
    """

    model_config = _RECORD_CONFIG

    project_key: str
    guard_key: str
    period_start: datetime
    period_grain: str = "week"

    # Domain 3: governance
    invocation_count: int = 0
    violation_count: int = 0
    violation_rate: float | None = None
    violation_stage_escape: int = 0
    violation_stage_schema: int = 0
    violation_stage_template: int = 0
    escape_detection_count: int = 0

    # Meta
    computed_at: datetime


class FactPoolPeriod(BaseModel):
    """One row per LLM pool per period (FK-62 §62.2.3).

    Primary key: ``(project_key, pool_key, period_start)``.
    ``response_time_p95_ms`` is INVENTAR (FK-62 §62.2.3) — not a column yet.
    """

    model_config = _RECORD_CONFIG

    project_key: str
    pool_key: str
    period_start: datetime
    period_grain: str = "week"

    # Domain 2: LLM performance
    call_count: int = 0
    response_time_p50_ms: int | None = None
    verdict_adopted_count: int = 0
    verdict_total_count: int = 0
    finding_true_positive_count: int = 0
    finding_false_positive_count: int = 0
    quorum_triggered_count: int = 0

    # Domain 6: review quality
    template_finding_rate_json: str | None = None

    # Meta
    computed_at: datetime


class FactPipelinePeriod(BaseModel):
    """One row per period of global pipeline KPIs (FK-62 §62.2.4).

    Primary key: ``(project_key, period_start)``.
    """

    model_config = _RECORD_CONFIG

    project_key: str
    period_start: datetime
    period_grain: str = "week"

    # Domain 1: story sizing
    story_count: int = 0
    story_count_closed: int = 0
    execution_count: int = 0
    exploration_count: int = 0
    stage_miss_count: int = 0
    stage_miss_detail_json: str | None = None

    # Domain 3: governance
    impact_violation_count: int = 0
    impact_check_count: int = 0
    integrity_gate_block_count: int = 0
    integrity_gate_total_count: int = 0

    # Domain 4: document fidelity
    doc_fidelity_conflict_by_level_json: str | None = None

    # Domain 5: QA effectiveness
    first_pass_count: int = 0
    finding_survival_count: int = 0
    finding_total_count: int = 0
    effective_check_ids_json: str | None = None

    # Domain 7: VectorDB
    vectordb_total_hits: int = 0
    vectordb_above_threshold: int = 0
    vectordb_classified_conflict: int = 0
    vectordb_duplicate_detected: int = 0

    # Domain 10: process efficiency
    processing_time_avg_ms: int | None = None
    processing_time_variance_ms2: float | None = None
    qa_round_avg: float | None = None

    # Meta
    computed_at: datetime


class FactCorpusPeriod(BaseModel):
    """One row per period of failure-corpus KPIs (FK-62 §62.2.5).

    Primary key: ``(project_key, period_start)``.
    """

    model_config = _RECORD_CONFIG

    project_key: str
    period_start: datetime
    period_grain: str = "month"

    # Domain 9: failure corpus
    new_incident_count: int = 0
    patterns_total_count: int = 0
    patterns_with_active_check: int = 0

    # Meta
    computed_at: datetime


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
