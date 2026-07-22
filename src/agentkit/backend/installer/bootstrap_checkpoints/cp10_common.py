"""Shared CP10 result helpers (AG3-176 R14 — no God-file)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.installer.checkpoint_engine.result_builder import (
    is_dry_run,
    make_result,
    planned_result,
)
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from agentkit.backend.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.backend.installer.registration import CheckpointResult


def skipped(
    node_id: str,
    context: CheckpointContext,
    *,
    detail: str,
    reason: str,
    start: float,
) -> CheckpointResult:
    """Build a SKIPPED result honouring the dry-run plan contract."""
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


def feature_present_result(
    node_id: str,
    context: CheckpointContext,
    *,
    detail: str,
    start: float,
) -> CheckpointResult:
    """CREATED (register) / PASS (read-only) for an active feature checkpoint."""
    return planned_or_status(
        node_id,
        context,
        mutate_status=CheckpointStatus.CREATED,
        detail=detail,
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
    """Return ``mutate_status`` in register mode, else the plan/PASS analogue."""
    if context.mode.mutations_allowed:
        return make_result(node_id, status=mutate_status, detail=detail, start=start)
    if is_dry_run(context.mode):
        return planned_result(
            node_id, planned_status=mutate_status, detail=detail, start=start
        )
    return make_result(
        node_id, status=CheckpointStatus.PASS, detail=detail, start=start
    )


__all__ = [
    "feature_present_result",
    "planned_or_status",
    "skipped",
]
