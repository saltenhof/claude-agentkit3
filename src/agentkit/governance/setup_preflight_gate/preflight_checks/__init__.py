"""Preflight check submodules — one file per check (FK-22 §22.3.1, AG3-034 AK2).

Each submodule exposes ``def check(ctx: PreflightContext) -> PreflightCheckResult``.
The aggregation order and exception handling live in
:mod:`agentkit.governance.setup_preflight_gate.preflight`.
"""

from __future__ import annotations

__all__ = [
    "dependencies_done",
    "no_active_runtime_residue",
    "no_competing_story_mode_active",
    "no_execution_artifacts",
    "no_scope_overlap",
    "no_stale_worktree",
    "no_story_branch",
    "status_approved",
    "story_attributes_consistent",
    "story_exists",
]
