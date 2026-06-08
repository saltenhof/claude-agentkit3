"""Repository surface for control-plane runtime lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.state_backend.store import (
    append_execution_event_global,
    claim_control_plane_operation_global,
    commit_control_plane_operation_with_side_effects_global,
    delete_control_plane_operation_global,
    delete_session_run_binding_global,
    finalize_control_plane_operation_global,
    finalize_control_plane_start_phase_global,
    has_committed_control_plane_operation_for_run_global,
    has_committed_story_exit_operation_for_run_global,
    load_control_plane_operation_global,
    load_session_run_binding_global,
    load_story_execution_lock_global,
    release_control_plane_operation_global,
    save_control_plane_operation_global,
    save_session_run_binding_global,
    save_story_execution_lock_global,
    takeover_control_plane_operation_global,
)
from agentkit.story.repository import StoryRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.control_plane.records import (
        ControlPlaneOperationRecord,
        SessionRunBindingRecord,
    )
    from agentkit.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.telemetry.contract.records import ExecutionEventRecord


def _load_story_context_via_story_surface(
    project_key: str,
    story_id: str,
) -> StoryContext | None:
    """Resolve a StoryContext through the sanctioned story read surface.

    Architecture Conformance AC004 (``architecture-conformance.rule.
    story_read_surface``): the global story read loader
    (``load_story_context_global``) may only be imported from
    ``agentkit.state_backend`` / ``agentkit.story.repository``. The control
    plane therefore consumes it via :class:`agentkit.story.repository.
    StoryRepository`, never by importing the loader symbol directly.
    """
    return StoryRepository().load_story_context(project_key, story_id)


@dataclass(frozen=True)
class ControlPlaneRuntimeRepository:
    """Persistence dependencies for runtime mutations and sync."""

    load_operation: Callable[[str], ControlPlaneOperationRecord | None] = (
        load_control_plane_operation_global
    )
    save_operation: Callable[[ControlPlaneOperationRecord], None] = (
        save_control_plane_operation_global
    )
    #: AG3-054 leased claim: atomically claim an op_id BEFORE dispatch with a
    #: per-call owner-token lease. Returns ``True`` iff this caller inserted the
    #: ``claimed`` row (won the claim). A loser inspects the row (terminal=>replay,
    #: live claim=>in-flight reject, expired claim=>CAS takeover). Backed by an
    #: ``INSERT ... ON CONFLICT DO NOTHING`` at the store.
    claim_operation: Callable[[ControlPlaneOperationRecord], bool] = (
        claim_control_plane_operation_global
    )
    #: AG3-054 leased claim: CAS-take over an EXPIRED claim. Re-stamps the lease to
    #: the record's owner ONLY if the row is still the exact observed ``claimed``
    #: placeholder (same owner + lease instant). Returns ``True`` iff taken over.
    takeover_operation: Callable[..., bool] = takeover_control_plane_operation_global
    #: AG3-054 leased claim: ownership-scoped terminal write. Writes the terminal
    #: result + clears ``claimed_by`` ONLY when the row is still ``claimed`` by the
    #: owner token. Returns ``True`` iff this owner's terminal write applied.
    finalize_operation: Callable[..., bool] = finalize_control_plane_operation_global
    #: AG3-054 (#1): ownership-scoped, atomic start_phase finalize. CAS-finalizes
    #: the claimed op AND materializes its side effects (binding/locks/events) in
    #: ONE transaction, gated on still owning the claim. A loser (lease taken over)
    #: writes NOTHING (the transaction rolls back). Returns ``True`` iff applied.
    finalize_start_phase: Callable[..., bool] = (
        finalize_control_plane_start_phase_global
    )
    #: AG3-054 (#2): ownership-collision-gated, atomic complete/fail/closure commit.
    #: The conditional op-row upsert (refuses to clobber a LIVE ``claimed`` start
    #: lease -> ``ControlPlaneClaimCollisionError``) and the mutation's side effects
    #: (binding create/delete, lock records, lifecycle events) commit in ONE
    #: transaction with the collision gate FIRST. A collision rolls back EVERYTHING,
    #: so a rejected complete/fail/closure leaves NO orphan side effect (ERROR-2).
    commit_operation_with_side_effects: Callable[..., None] = (
        commit_control_plane_operation_with_side_effects_global
    )
    #: AG3-054 leased claim: ownership-scoped release. Deletes the row ONLY when it
    #: is still ``claimed`` by the owner token (never a terminal / foreign row).
    release_operation: Callable[..., None] = release_control_plane_operation_global
    #: AG3-054 (#3): run-scoped admission evidence -- whether a COMMITTED op exists
    #: for THIS exact ``(project_key, story_id, run_id)``.
    has_committed_operation_for_run: Callable[[str, str, str], bool] = (
        has_committed_control_plane_operation_for_run_global
    )
    #: FK-58 run-terminal evidence: a committed ``story_exit`` operation marks the
    #: run terminal/non-resumable and must be consulted before admission evidence.
    has_committed_story_exit_operation_for_run: Callable[[str, str, str], bool] = (
        has_committed_story_exit_operation_for_run_global
    )
    #: AG3-054: unconditional delete for administrative recovery only (the
    #: productive release path is ``release_operation``). Idempotent.
    delete_operation: Callable[[str], None] = delete_control_plane_operation_global
    load_binding: Callable[[str], SessionRunBindingRecord | None] = (
        load_session_run_binding_global
    )
    save_binding: Callable[[SessionRunBindingRecord], None] = (
        save_session_run_binding_global
    )
    delete_binding: Callable[[str], None] = delete_session_run_binding_global
    load_lock: Callable[[str, str, str, str], StoryExecutionLockRecord | None] = (
        load_story_execution_lock_global
    )
    save_lock: Callable[[StoryExecutionLockRecord], None] = (
        save_story_execution_lock_global
    )
    append_event: Callable[[ExecutionEventRecord], None] = append_execution_event_global
    #: Authoritative server-side resolver for the run ``StoryContext`` keyed by
    #: ``(project_key, story_id)``. AG3-018 (FK-24 §24.3.4): the control plane
    #: reads the operating mode from the state-backend record, NEVER from an
    #: agent-supplied request field (which would be forgeable). Used by
    #: ``_mutate_phase`` to decide whether story-scoped session/locks are
    #: materialized for a fast story.
    load_story_context: Callable[[str, str], StoryContext | None] = (
        _load_story_context_via_story_surface
    )
