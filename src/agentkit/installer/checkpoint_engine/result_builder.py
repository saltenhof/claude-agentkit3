"""Helpers for building :class:`CheckpointResult` objects in handlers.

Centralises the timing wrapper and — crucially — the FK-50 §50.2 dry-run result
contract (story §2.1.3): in ``dry_run`` mode a handler reports the status the
real ``register`` run WOULD produce, performs no mutation, marks ``detail`` with
the plan marker and (for a planned ``CREATED``/``UPDATED``) sets the stable
``reason`` token ``planned_no_mutation``. Putting the contract in one place keeps
every handler's dry-run behaviour identical and testable.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentkit.installer.checkpoint_engine.reasons import (
    DRY_RUN_PLAN_MARKER,
    REASON_PLANNED_NO_MUTATION,
)
from agentkit.installer.registration import CheckpointResult, CheckpointStatus

if TYPE_CHECKING:
    from agentkit.installer.checkpoint_engine.execution_mode import ExecutionMode


def elapsed_ms(start: float) -> int:
    """Return whole milliseconds elapsed since ``start`` (``time.monotonic``)."""
    return int((time.monotonic() - start) * 1000)


def make_result(
    checkpoint: str,
    *,
    status: CheckpointStatus,
    detail: str | None = None,
    reason: str | None = None,
    start: float,
) -> CheckpointResult:
    """Build a :class:`CheckpointResult` with a measured duration.

    Args:
        checkpoint: Stable checkpoint node id.
        status: The outcome status.
        detail: Human-readable description.
        reason: Machine-readable reason (mandatory for SKIPPED/FAILED).
        start: ``time.monotonic()`` captured at handler entry.

    Returns:
        The constructed result.
    """
    return CheckpointResult(
        checkpoint=checkpoint,
        status=status,
        detail=detail,
        reason=reason,
        duration_ms=elapsed_ms(start),
    )


def planned_result(
    checkpoint: str,
    *,
    planned_status: CheckpointStatus,
    detail: str,
    skip_reason: str | None = None,
    start: float,
) -> CheckpointResult:
    """Build a dry-run plan result honouring the FK-50 §50.2 contract.

    The handler computed the status the real ``register`` run would produce
    (``planned_status``) WITHOUT mutating. This wraps that into the dry-run
    result contract (story §2.1.3):

    * ``CREATED``/``UPDATED`` planned mutation -> ``reason=planned_no_mutation``,
      ``detail`` prefixed with the plan marker.
    * ``SKIPPED`` -> the SAME ``skip_reason`` as the register run would carry
      (e.g. ``vectordb_disabled``/``not_applicable``/``reserved``), ``detail``
      prefixed with the plan marker.
    * ``PASS`` -> already satisfied; no reason needed, ``detail`` plan-marked.

    Args:
        checkpoint: Stable checkpoint node id.
        planned_status: The status the real register run would produce.
        detail: Human-readable plan description (the marker is prepended).
        skip_reason: The register-run skip reason; REQUIRED when
            ``planned_status`` is ``SKIPPED`` (the model rejects a reasonless
            skip).
        start: ``time.monotonic()`` captured at handler entry.

    Returns:
        The dry-run plan :class:`CheckpointResult`.

    Raises:
        ValueError: When ``planned_status`` is ``SKIPPED`` but no ``skip_reason``
            is supplied (the dry-run plan must mirror the real skip reason).
    """
    marked_detail = f"{DRY_RUN_PLAN_MARKER} {detail}"
    if planned_status in (CheckpointStatus.CREATED, CheckpointStatus.UPDATED):
        reason: str | None = REASON_PLANNED_NO_MUTATION
    elif planned_status is CheckpointStatus.SKIPPED:
        if not skip_reason:
            raise ValueError(
                "planned_result(SKIPPED) requires the register-run skip_reason "
                "so the dry-run plan mirrors it (FK-50 §50.2)."
            )
        reason = skip_reason
    elif planned_status is CheckpointStatus.FAILED:
        # A dry-run never asserts a FAILED plan for a mutation; callers map a
        # would-fail precondition to FAILED with its own reason explicitly.
        reason = skip_reason
    else:  # PASS
        reason = None
    return CheckpointResult(
        checkpoint=checkpoint,
        status=planned_status,
        detail=marked_detail,
        reason=reason,
        duration_ms=elapsed_ms(start),
    )


def is_dry_run(mode: ExecutionMode) -> bool:
    """Return whether ``mode`` is the plan-only dry-run mode."""
    from agentkit.installer.checkpoint_engine.execution_mode import ExecutionMode

    return mode is ExecutionMode.DRY_RUN


__all__ = ["elapsed_ms", "is_dry_run", "make_result", "planned_result"]
