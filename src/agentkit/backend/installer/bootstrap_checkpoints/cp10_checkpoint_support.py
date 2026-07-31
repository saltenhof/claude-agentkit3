"""Small shared result/file helpers for the CP10 checkpoint family."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.installer.checkpoint_engine.result_builder import (
    is_dry_run,
    make_result,
    planned_result,
)
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.installer.checkpoint_engine.context import (
        CheckpointContext,
    )
    from agentkit.backend.installer.registration import CheckpointResult


def record_created_file(context: CheckpointContext, path: Path) -> None:
    """Record a written project-relative file exactly once."""
    relative = str(path.relative_to(context.project_root))
    if relative not in context.run_state.created_files:
        context.run_state.created_files.append(relative)


def skipped_result(
    node_id: str,
    context: CheckpointContext,
    *,
    detail: str,
    reason: str,
    start: float,
) -> CheckpointResult:
    """Build a SKIPPED result while preserving dry-run plan semantics."""
    if is_dry_run(context.mode):
        return planned_result(
            node_id,
            planned_status=CheckpointStatus.SKIPPED,
            detail=detail,
            skip_reason=reason,
            start=start,
        )
    return make_result(
        node_id,
        status=CheckpointStatus.SKIPPED,
        detail=detail,
        reason=reason,
        start=start,
    )


def planned_or_status(
    node_id: str,
    context: CheckpointContext,
    *,
    mutate_status: CheckpointStatus,
    detail: str,
    start: float,
) -> CheckpointResult:
    """Return the mutating status or its dry-run/VERIFY analogue."""
    if context.mode.mutations_allowed:
        return make_result(
            node_id,
            status=mutate_status,
            detail=detail,
            start=start,
        )
    if is_dry_run(context.mode):
        return planned_result(
            node_id,
            planned_status=mutate_status,
            detail=detail,
            start=start,
        )
    return make_result(
        node_id,
        status=CheckpointStatus.PASS,
        detail=detail,
        start=start,
    )


__all__ = ["planned_or_status", "record_created_file", "skipped_result"]
