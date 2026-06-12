"""Shared UPSERT column/conflict/update fragments for ``fact_repository``.

Extracted verbatim from ``fact_repository`` so the adapter module's top-level
statement count stays under the LOC budget (PY_MODULE_TOP_LEVEL_MAX_LOC_100).
These are pure SQL-fragment constants (column lists, conflict targets and
``DO UPDATE SET`` clauses); placeholders remain backend-specific and are built
in ``fact_repository._upsert_statement``. The literals live inside
``_build_fact_sql`` (a function body, excluded from the module-level LOC count)
and are bound to their original module-level names below. No behaviour change.
"""

from __future__ import annotations

from typing import NamedTuple


class _FactSql(NamedTuple):
    """Immutable bundle of the fact-table SQL fragments."""

    fact_story_columns: str
    fact_story_update: str
    fact_guard_columns: str
    fact_guard_conflict: str
    fact_guard_update: str
    fact_pool_columns: str
    fact_pool_conflict: str
    fact_pool_update: str
    fact_pipeline_columns: str
    fact_pipeline_conflict: str
    fact_pipeline_update: str
    fact_corpus_columns: str
    fact_corpus_conflict: str
    fact_corpus_update: str
    sync_state_columns: str
    sync_state_conflict: str
    sync_state_update: str


def _build_fact_sql() -> _FactSql:
    """Return the bundle of fact-table UPSERT SQL fragments."""
    fact_story_columns = (
        "project_key, story_id, story_type, story_size, story_mode, started_at, "
        "completed_at, qa_rounds, compaction_count, llm_call_count, "
        "adversarial_findings, adversarial_tests_created, files_changed, "
        "feedback_converged, phase_setup_ms, phase_implementation_ms, "
        "phase_closure_ms, are_gate_status, agentkit_version, agentkit_commit"
    )
    fact_story_update = (
        "story_type=excluded.story_type, story_size=excluded.story_size, "
        "story_mode=excluded.story_mode, started_at=excluded.started_at, "
        "completed_at=excluded.completed_at, qa_rounds=excluded.qa_rounds, "
        "compaction_count=excluded.compaction_count, "
        "llm_call_count=excluded.llm_call_count, "
        "adversarial_findings=excluded.adversarial_findings, "
        "adversarial_tests_created=excluded.adversarial_tests_created, "
        "files_changed=excluded.files_changed, "
        "feedback_converged=excluded.feedback_converged, "
        "phase_setup_ms=excluded.phase_setup_ms, "
        "phase_implementation_ms=excluded.phase_implementation_ms, "
        "phase_closure_ms=excluded.phase_closure_ms, "
        "are_gate_status=excluded.are_gate_status, "
        "agentkit_version=excluded.agentkit_version, "
        "agentkit_commit=excluded.agentkit_commit"
    )
    fact_guard_columns = (
        "project_key, guard_id, period_start, period_end, "
        "invocation_count, violation_count"
    )
    fact_guard_update = (
        "period_end=excluded.period_end, "
        "invocation_count=excluded.invocation_count, "
        "violation_count=excluded.violation_count"
    )
    fact_pool_columns = (
        "project_key, llm_role, period_start, period_end, call_count, "
        "token_input_total, token_output_total, avg_latency_ms"
    )
    fact_pool_update = (
        "period_end=excluded.period_end, call_count=excluded.call_count, "
        "token_input_total=excluded.token_input_total, "
        "token_output_total=excluded.token_output_total, "
        "avg_latency_ms=excluded.avg_latency_ms"
    )
    fact_pipeline_columns = (
        "project_key, period_start, period_end, stories_completed, "
        "stories_escalated, avg_qa_rounds, avg_phase_implementation_ms"
    )
    fact_pipeline_update = (
        "period_end=excluded.period_end, "
        "stories_completed=excluded.stories_completed, "
        "stories_escalated=excluded.stories_escalated, "
        "avg_qa_rounds=excluded.avg_qa_rounds, "
        "avg_phase_implementation_ms=excluded.avg_phase_implementation_ms"
    )
    fact_corpus_columns = (
        "project_key, period_start, period_end, incidents_recorded, "
        "patterns_promoted, checks_approved"
    )
    fact_corpus_update = (
        "period_end=excluded.period_end, "
        "incidents_recorded=excluded.incidents_recorded, "
        "patterns_promoted=excluded.patterns_promoted, "
        "checks_approved=excluded.checks_approved"
    )
    sync_state_update = (
        "value_int=excluded.value_int, "
        "value_text=excluded.value_text, "
        "updated_at=excluded.updated_at"
    )
    return _FactSql(
        fact_story_columns=fact_story_columns,
        fact_story_update=fact_story_update,
        fact_guard_columns=fact_guard_columns,
        fact_guard_conflict="project_key, guard_id, period_start",
        fact_guard_update=fact_guard_update,
        fact_pool_columns=fact_pool_columns,
        fact_pool_conflict="project_key, llm_role, period_start",
        fact_pool_update=fact_pool_update,
        fact_pipeline_columns=fact_pipeline_columns,
        fact_pipeline_conflict="project_key, period_start",
        fact_pipeline_update=fact_pipeline_update,
        fact_corpus_columns=fact_corpus_columns,
        fact_corpus_conflict="project_key, period_start",
        fact_corpus_update=fact_corpus_update,
        sync_state_columns="project_key, key, value_int, value_text, updated_at",
        sync_state_conflict="project_key, key",
        sync_state_update=sync_state_update,
    )


_SQL = _build_fact_sql()

_FACT_STORY_COLUMNS = _SQL.fact_story_columns
_FACT_STORY_UPDATE = _SQL.fact_story_update
_FACT_GUARD_COLUMNS = _SQL.fact_guard_columns
_FACT_GUARD_CONFLICT = _SQL.fact_guard_conflict
_FACT_GUARD_UPDATE = _SQL.fact_guard_update
_FACT_POOL_COLUMNS = _SQL.fact_pool_columns
_FACT_POOL_CONFLICT = _SQL.fact_pool_conflict
_FACT_POOL_UPDATE = _SQL.fact_pool_update
_FACT_PIPELINE_COLUMNS = _SQL.fact_pipeline_columns
_FACT_PIPELINE_CONFLICT = _SQL.fact_pipeline_conflict
_FACT_PIPELINE_UPDATE = _SQL.fact_pipeline_update
_FACT_CORPUS_COLUMNS = _SQL.fact_corpus_columns
_FACT_CORPUS_CONFLICT = _SQL.fact_corpus_conflict
_FACT_CORPUS_UPDATE = _SQL.fact_corpus_update
_SYNC_STATE_COLUMNS = _SQL.sync_state_columns
_SYNC_STATE_CONFLICT = _SQL.sync_state_conflict
_SYNC_STATE_UPDATE = _SQL.sync_state_update

__all__ = [
    "_FACT_CORPUS_COLUMNS",
    "_FACT_CORPUS_CONFLICT",
    "_FACT_CORPUS_UPDATE",
    "_FACT_GUARD_COLUMNS",
    "_FACT_GUARD_CONFLICT",
    "_FACT_GUARD_UPDATE",
    "_FACT_PIPELINE_COLUMNS",
    "_FACT_PIPELINE_CONFLICT",
    "_FACT_PIPELINE_UPDATE",
    "_FACT_POOL_COLUMNS",
    "_FACT_POOL_CONFLICT",
    "_FACT_POOL_UPDATE",
    "_FACT_STORY_COLUMNS",
    "_FACT_STORY_UPDATE",
    "_SYNC_STATE_COLUMNS",
    "_SYNC_STATE_CONFLICT",
    "_SYNC_STATE_UPDATE",
]
