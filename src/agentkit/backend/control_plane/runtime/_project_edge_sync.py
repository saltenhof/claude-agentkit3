"""ProjectEdge sync and operation-query facade methods."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    ProjectEdgeSyncRequest,
)
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord

from ._edge_bundles import _build_edge_bundle, _next_binding_version
from ._operation_records import _replayed_result

if TYPE_CHECKING:
    from agentkit.backend.control_plane.repository import (
        ControlPlaneRuntimeRepository,
    )

logger = logging.getLogger(__name__)

class _ProjectEdgeSyncMixin:
    """Project-edge sync + operation-read service methods (AG3-147 mixin).

    Cohesive bounded ``project_edge_sync`` + ``GET operations/{op_id}`` read,
    split out of :class:`ControlPlaneRuntimeService` for cohesion
    (PY_CLASS_MAX_LOC_800; no behaviour change). The concrete runtime supplies
    the shared dependencies below.
    """

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository

        def _require_postgres_backend_on_first_use(self) -> None: ...

    def sync_project_edge(
        self,
        request: ProjectEdgeSyncRequest,
    ) -> ControlPlaneMutationResult:
        self._require_postgres_backend_on_first_use()
        now = datetime.now(tz=UTC)
        binding = self._repo.load_binding(request.session_id)
        if binding is None or binding.project_key != request.project_key:
            lock = StoryExecutionLockRecord(
                project_key=request.project_key,
                story_id="",
                run_id="",
                lock_type="story_execution",
                status="INACTIVE",
                worktree_roots=(),
                binding_version=_next_binding_version(binding.binding_version if binding is not None else None),
                activated_at=now,
                updated_at=now,
                deactivated_at=now,
            )
            bundle = _build_edge_bundle(
                binding=None,
                lock=lock,
                sync_class=request.freshness_class,
                now=now,
            )
            return ControlPlaneMutationResult(
                status="synced",
                op_id=request.op_id,
                operation_kind="project_edge_sync",
                edge_bundle=bundle,
            )

        lock_record = self._repo.load_lock(
            binding.project_key,
            binding.story_id,
            binding.run_id,
            "story_execution",
        )
        qa_lock_record = self._repo.load_lock(
            binding.project_key,
            binding.story_id,
            binding.run_id,
            "qa_artifact_write",
        )
        if lock_record is None:
            lock = StoryExecutionLockRecord(
                project_key=binding.project_key,
                story_id=binding.story_id,
                run_id=binding.run_id,
                lock_type="story_execution",
                status="INVALID",
                worktree_roots=binding.worktree_roots,
                binding_version=binding.binding_version,
                activated_at=now,
                updated_at=now,
            )
        else:
            lock = lock_record
        new_owner_ref = None
        if (
            binding.status == "revoked"
            and binding.revocation_reason == "ownership_transferred"
        ):
            active = self._repo.load_active_ownership(
                binding.project_key,
                binding.story_id,
            )
            if (
                active is not None
                and active.run_id == binding.run_id
                and active.owner_session_id != binding.session_id
            ):
                new_owner_ref = active.owner_session_id
        bundle = _build_edge_bundle(
            binding=binding,
            lock=lock,
            qa_lock=qa_lock_record,
            sync_class=request.freshness_class,
            now=now,
            tombstone_worktree_roots=(
                binding.worktree_roots if binding.status == "revoked" else ()
            ),
            new_owner_ref=new_owner_ref,
        )
        return ControlPlaneMutationResult(
            status="synced",
            op_id=request.op_id,
            operation_kind="project_edge_sync",
            run_id=binding.run_id,
            edge_bundle=bundle,
        )

    def get_operation(self, op_id: str) -> ControlPlaneMutationResult | None:
        self._require_postgres_backend_on_first_use()
        record = self._repo.load_operation(op_id)
        if record is None:
            return None
        if record.status == "claimed":
            #: ERROR-4: an in-flight claim placeholder is not a reconcilable op yet.
            return None
        #: AG3-138 (AC5, FK-91 §91.1a Rule 17): ``_replayed_result`` surfaces an
        #: ``aborted`` / ``repair`` / ``failed`` terminal state VERBATIM (a
        #: visible, auditable reconcile/repair state, SEVERITY-SEMANTIK) and
        #: only echoes the ordinary success statuses as ``replayed``.
        return _replayed_result(record.response_payload)
