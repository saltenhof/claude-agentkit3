"""Fast closure materialization for non-story-scoped runs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
)
from agentkit.backend.control_plane.records import (
    BindingDeleteScope,
)

from ._edge_bundles import _build_fast_edge_bundle
from ._operation_records import _control_plane_request_body_hash, _operation_record

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.backend.control_plane.repository import (
        ControlPlaneRuntimeRepository,
    )

logger = logging.getLogger(__name__)

def _complete_fast_closure(
    repo: ControlPlaneRuntimeRepository,
    *,
    run_id: str,
    request: ClosureCompleteRequest,
    now: datetime,
    expected_ownership_epoch: int,
) -> ControlPlaneMutationResult:
    """No-op closure for a fast story (FK-24 §24.3.4; ``no_locks_active``).

    A fast story never created a session binding or story/QA lock-records at
    setup, so closure deactivates NOTHING: it creates no ``story_execution`` /
    ``qa_artifact_write`` lock-records and emits NO story-execution deactivation
    events. It returns an ``ai_augmented`` bundle with no session and no locks.
    Any session binding that may exist is still cleaned up, but a fast run holds
    none, so this is a pure no-op for the guard regime.

    ERROR-2 fix (#2): the op-row commit and the (best-effort) binding deletion run
    in ONE atomic transaction with the collision gate FIRST, so a closure reusing a
    LIVE ``claimed`` start's op_id raises :class:`ControlPlaneClaimCollisionError`
    (handled fail-closed by :meth:`complete_closure`) with the binding deletion
    rolled back too -- no orphan teardown even on the fast path.
    """
    bundle = _build_fast_edge_bundle(
        project_key=request.project_key,
        sync_class="mutation",
        now=now,
    )
    result = ControlPlaneMutationResult(
        status="committed",
        op_id=request.op_id,
        operation_kind="closure_complete",
        run_id=run_id,
        phase="closure",
        edge_bundle=bundle,
        ownership_epoch=expected_ownership_epoch,
    )
    record = _operation_record(
        op_id=request.op_id,
        project_key=request.project_key,
        story_id=request.story_id,
        run_id=run_id,
        session_id=request.session_id,
        operation_kind="closure_complete",
        phase="closure",
        result=result,
        now=now,
        request_body_hash=_control_plane_request_body_hash(request, operation_kind="closure_complete", phase="closure"),
    )
    repo.commit_operation_with_side_effects(
        record,
        binding_to_save=None,
        #: AG3-054 run-scoping: a fast run holds no binding, so this delete is a
        #: benign no-op for THIS run. But it stays run-scoped so a session that a
        #: DIFFERENT (standard) run has since rebound is NEVER torn down by this
        #: fast closure -- a foreign binding fails closed at the store and rolls back.
        binding_to_delete=BindingDeleteScope(
            session_id=request.session_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
        ),
        locks=(),
        events=(),
        expected_ownership_epoch=expected_ownership_epoch,
    )
    return result
