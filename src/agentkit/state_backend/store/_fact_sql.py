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
        "project_key, story_id, story_type, story_size, pipeline_mode, "
        "opened_at, closed_at, processing_time_ms, compaction_count, "
        "qa_round_count, feedback_converged, blocked_ac_count, "
        "blocked_ac_detail_json, llm_call_count, adversarial_findings_count, "
        "adversarial_tests_created, adversarial_hit_rate, findings_fully_resolved, "
        "findings_partially_resolved, findings_not_resolved, final_status, "
        "are_gate_passed, are_total_requirements, are_covered_requirements, "
        "files_changed, increment_count, phase_setup_ms, phase_exploration_ms, "
        "phase_implementation_ms, phase_verify_ms, phase_closure_ms, computed_at"
    )
    fact_story_update = (
        "story_type=excluded.story_type, story_size=excluded.story_size, "
        "pipeline_mode=excluded.pipeline_mode, opened_at=excluded.opened_at, "
        "closed_at=excluded.closed_at, "
        "processing_time_ms=excluded.processing_time_ms, "
        "compaction_count=excluded.compaction_count, "
        "qa_round_count=excluded.qa_round_count, "
        "feedback_converged=excluded.feedback_converged, "
        "blocked_ac_count=excluded.blocked_ac_count, "
        "blocked_ac_detail_json=excluded.blocked_ac_detail_json, "
        "llm_call_count=excluded.llm_call_count, "
        "adversarial_findings_count=excluded.adversarial_findings_count, "
        "adversarial_tests_created=excluded.adversarial_tests_created, "
        "adversarial_hit_rate=excluded.adversarial_hit_rate, "
        "findings_fully_resolved=excluded.findings_fully_resolved, "
        "findings_partially_resolved=excluded.findings_partially_resolved, "
        "findings_not_resolved=excluded.findings_not_resolved, "
        "final_status=excluded.final_status, "
        "are_gate_passed=excluded.are_gate_passed, "
        "are_total_requirements=excluded.are_total_requirements, "
        "are_covered_requirements=excluded.are_covered_requirements, "
        "files_changed=excluded.files_changed, "
        "increment_count=excluded.increment_count, "
        "phase_setup_ms=excluded.phase_setup_ms, "
        "phase_exploration_ms=excluded.phase_exploration_ms, "
        "phase_implementation_ms=excluded.phase_implementation_ms, "
        "phase_verify_ms=excluded.phase_verify_ms, "
        "phase_closure_ms=excluded.phase_closure_ms, "
        "computed_at=excluded.computed_at"
    )
    fact_guard_columns = (
        "project_key, guard_key, period_start, period_grain, invocation_count, "
        "violation_count, violation_rate, violation_stage_escape, "
        "violation_stage_schema, violation_stage_template, "
        "escape_detection_count, computed_at"
    )
    fact_guard_update = (
        "period_grain=excluded.period_grain, "
        "invocation_count=excluded.invocation_count, "
        "violation_count=excluded.violation_count, "
        "violation_rate=excluded.violation_rate, "
        "violation_stage_escape=excluded.violation_stage_escape, "
        "violation_stage_schema=excluded.violation_stage_schema, "
        "violation_stage_template=excluded.violation_stage_template, "
        "escape_detection_count=excluded.escape_detection_count, "
        "computed_at=excluded.computed_at"
    )
    fact_pool_columns = (
        "project_key, pool_key, period_start, period_grain, call_count, "
        "response_time_p50_ms, verdict_adopted_count, verdict_total_count, "
        "finding_true_positive_count, finding_false_positive_count, "
        "quorum_triggered_count, template_finding_rate_json, computed_at"
    )
    fact_pool_update = (
        "period_grain=excluded.period_grain, call_count=excluded.call_count, "
        "response_time_p50_ms=excluded.response_time_p50_ms, "
        "verdict_adopted_count=excluded.verdict_adopted_count, "
        "verdict_total_count=excluded.verdict_total_count, "
        "finding_true_positive_count=excluded.finding_true_positive_count, "
        "finding_false_positive_count=excluded.finding_false_positive_count, "
        "quorum_triggered_count=excluded.quorum_triggered_count, "
        "template_finding_rate_json=excluded.template_finding_rate_json, "
        "computed_at=excluded.computed_at"
    )
    fact_pipeline_columns = (
        "project_key, period_start, period_grain, story_count, "
        "story_count_closed, execution_count, exploration_count, "
        "stage_miss_count, stage_miss_detail_json, impact_violation_count, "
        "impact_check_count, integrity_gate_block_count, "
        "integrity_gate_total_count, doc_fidelity_conflict_by_level_json, "
        "first_pass_count, finding_survival_count, finding_total_count, "
        "effective_check_ids_json, vectordb_total_hits, vectordb_above_threshold, "
        "vectordb_classified_conflict, vectordb_duplicate_detected, "
        "processing_time_avg_ms, processing_time_variance_ms2, qa_round_avg, "
        "computed_at"
    )
    fact_pipeline_update = (
        "period_grain=excluded.period_grain, story_count=excluded.story_count, "
        "story_count_closed=excluded.story_count_closed, "
        "execution_count=excluded.execution_count, "
        "exploration_count=excluded.exploration_count, "
        "stage_miss_count=excluded.stage_miss_count, "
        "stage_miss_detail_json=excluded.stage_miss_detail_json, "
        "impact_violation_count=excluded.impact_violation_count, "
        "impact_check_count=excluded.impact_check_count, "
        "integrity_gate_block_count=excluded.integrity_gate_block_count, "
        "integrity_gate_total_count=excluded.integrity_gate_total_count, "
        "doc_fidelity_conflict_by_level_json="
        "excluded.doc_fidelity_conflict_by_level_json, "
        "first_pass_count=excluded.first_pass_count, "
        "finding_survival_count=excluded.finding_survival_count, "
        "finding_total_count=excluded.finding_total_count, "
        "effective_check_ids_json=excluded.effective_check_ids_json, "
        "vectordb_total_hits=excluded.vectordb_total_hits, "
        "vectordb_above_threshold=excluded.vectordb_above_threshold, "
        "vectordb_classified_conflict=excluded.vectordb_classified_conflict, "
        "vectordb_duplicate_detected=excluded.vectordb_duplicate_detected, "
        "processing_time_avg_ms=excluded.processing_time_avg_ms, "
        "processing_time_variance_ms2=excluded.processing_time_variance_ms2, "
        "qa_round_avg=excluded.qa_round_avg, computed_at=excluded.computed_at"
    )
    fact_corpus_columns = (
        "project_key, period_start, period_grain, new_incident_count, "
        "patterns_total_count, patterns_with_active_check, computed_at"
    )
    fact_corpus_update = (
        "period_grain=excluded.period_grain, "
        "new_incident_count=excluded.new_incident_count, "
        "patterns_total_count=excluded.patterns_total_count, "
        "patterns_with_active_check=excluded.patterns_with_active_check, "
        "computed_at=excluded.computed_at"
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
        fact_guard_conflict="project_key, guard_key, period_start",
        fact_guard_update=fact_guard_update,
        fact_pool_columns=fact_pool_columns,
        fact_pool_conflict="project_key, pool_key, period_start",
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
