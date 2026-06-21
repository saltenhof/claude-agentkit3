"""DDL for the ten BC14 planning projection tables (SQLite + Postgres).

Extracted verbatim from ``planning_projection_repository`` so the adapter
module's top-level statement count stays under the LOC budget
(PY_MODULE_TOP_LEVEL_MAX_LOC_100). Schema owner remains BC14 (FK-70 §70.10.2);
this module carries only the idempotent ``CREATE TABLE IF NOT EXISTS`` truth and
is re-imported under its original names (no behaviour change).
"""

from __future__ import annotations


def _build_planning_ddl() -> tuple[str, ...]:
    """Return the ten ``CREATE TABLE IF NOT EXISTS`` statements (BC14 schema)."""
    return (
    """
    CREATE TABLE IF NOT EXISTS planning_planned_story (
        project_key TEXT NOT NULL,
        story_id TEXT NOT NULL,
        story_type TEXT NOT NULL,
        story_size TEXT NOT NULL,
        participating_repos_json TEXT NOT NULL,
        planning_status TEXT NOT NULL,
        is_hard_truth INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, story_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_dependency_edge (
        project_key TEXT NOT NULL,
        story_id TEXT NOT NULL,
        depends_on_story_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        rationale TEXT,
        is_hard_truth INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, story_id, depends_on_story_id, kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_blocking_condition (
        project_key TEXT NOT NULL,
        blocker_id TEXT NOT NULL,
        story_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        provenance TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        source_story_id TEXT,
        source_gate_id TEXT,
        detail TEXT,
        is_hard_truth INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, blocker_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_gate (
        project_key TEXT NOT NULL,
        gate_id TEXT NOT NULL,
        story_id TEXT NOT NULL,
        gate_kind TEXT NOT NULL,
        state TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        is_blocking INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, gate_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_scheduling_budget (
        project_key TEXT NOT NULL,
        budget_id TEXT NOT NULL,
        repo_parallel_cap INTEGER NOT NULL,
        merge_risk_cap INTEGER NOT NULL,
        api_rate_limit_cap INTEGER NOT NULL,
        llm_pool_cap INTEGER NOT NULL,
        ci_capacity_cap INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, budget_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_scheduling_policy (
        project_key TEXT NOT NULL,
        policy_id TEXT NOT NULL,
        may_parallelize_now INTEGER NOT NULL,
        budget_id TEXT NOT NULL,
        recommended_batch_limit INTEGER,
        reason_code TEXT NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, policy_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_rulebook_revision (
        project_key TEXT NOT NULL,
        rulebook_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        raw_syntax TEXT NOT NULL,
        updated_by_principal TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (project_key, rulebook_id, revision)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_rulebook_compile_result (
        project_key TEXT NOT NULL,
        rulebook_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        status TEXT NOT NULL,
        compiled_rules_json TEXT NOT NULL,
        errors_json TEXT NOT NULL,
        triggers_replan INTEGER NOT NULL,
        compiled_at TEXT NOT NULL,
        PRIMARY KEY (project_key, rulebook_id, revision)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_execution_plan (
        project_key TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        graph_revision INTEGER NOT NULL,
        readiness_revision INTEGER NOT NULL,
        scheduling_revision INTEGER NOT NULL,
        rulebook_revision INTEGER NOT NULL,
        critical_path_json TEXT NOT NULL,
        recommended_batch_json TEXT NOT NULL,
        max_allowed_batch_json TEXT NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, plan_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planning_execution_wave (
        project_key TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        wave_id TEXT NOT NULL,
        wave_order INTEGER NOT NULL,
        wave_state TEXT NOT NULL,
        candidate_story_ids_json TEXT NOT NULL,
        revision INTEGER NOT NULL,
        PRIMARY KEY (project_key, plan_id, wave_id)
    )
    """,
    )


_PLANNING_DDL_SQLITE: tuple[str, ...] = _build_planning_ddl()
# Postgres DDL: same shape, INTEGER->BOOLEAN for the flag columns is unnecessary
# (we store 0/1 ints there too for symmetry with the record bool<->int mapping).
_PLANNING_DDL_POSTGRES: tuple[str, ...] = _PLANNING_DDL_SQLITE

__all__ = ["_PLANNING_DDL_POSTGRES", "_PLANNING_DDL_SQLITE"]
