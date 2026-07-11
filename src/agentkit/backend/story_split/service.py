"""Story-split service implementing the canonical FK-54 §54 split contract.

The ``StorySplitService`` is the administrative ``scope_explosion`` recovery
component of the story-lifecycle BC. It is NOT a pipeline step, NOT an override
and NOT a reset: the source story's audit/telemetry is preserved (no full purge),
the story stays in the index as ``Cancelled`` + ``superseded_by`` and is ended
via the dedicated administrative split-cancel path — never via closure and never
via the frontend ``cancel_story`` guard.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Protocol, TypeVar

from agentkit.backend.control_plane.disown import build_disown_plan
from agentkit.backend.control_plane.object_claims import (
    ObjectClaimStorePort,
    acquire_story_claim,
    release_story_claim,
    story_claim_key,
)
from agentkit.backend.control_plane.ownership import (
    BindingRevocationReason,
    BindingStatus,
)
from agentkit.backend.control_plane.records import ControlPlaneOperationRecord
from agentkit.backend.core_types import StoryDependencyKind, StorySize
from agentkit.backend.core_types.freeze import FreezeKind
from agentkit.backend.execution_planning.entities import StoryDependency
from agentkit.backend.governance.principal_capabilities.principals import Principal
from agentkit.backend.story_context_manager.story_model import (
    ChangeImpact,
    ConceptQuality,
    CreateStoryInput,
    RiskLevel,
    StoryStatus,
    WireStoryType,
)
from agentkit.backend.story_context_manager.terminal_state import ExitClass, TerminalState
from agentkit.backend.story_split.models import (
    SPLIT_CANCEL_REASON,
    SplitPlan,
    SplitStatus,
    StorySplitRecord,
    SuccessorStory,
    compute_plan_ref,
    derive_split_id,
)
from agentkit.backend.story_split.rebinding import (
    EdgeMutation,
    RebindingError,
    RebindingPlan,
    plan_rebinding,
    validate_rebinding_plan,
)
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.story_context_manager.story_model import Story


_T = TypeVar("_T")


class StorySplitError(RuntimeError):
    """Fail-closed story-split rejection (entry gate / plan / invariants)."""


@dataclass(frozen=True)
class SplitSourceState:
    """Service-owned evidence of the source story's pre-split situation (§54.4).

    Attributes:
        scope_explosion_established: Whether the FK-25 detection established a
            ``scope_explosion`` for this story.
        paused_with_scope_explosion: Whether the typical prior state holds
            (``PAUSED`` with ``escalation_class: scope_explosion``).
        competing_admin_operation_active: Whether a competing administrative
            operation (e.g. an active reset / exit) is in flight for this story.
    """

    scope_explosion_established: bool
    paused_with_scope_explosion: bool
    competing_admin_operation_active: bool


class _StoryServicePort(Protocol):
    def get_story(self, story_display_id: str) -> Story | None:
        """Return the source story, or ``None`` when unknown."""

    def list_stories(self, project_key: str) -> list[Story]:
        """List all stories of the project (used to reconstruct successors)."""

    def create_story(
        self, request: CreateStoryInput, *, op_id: str, correlation_id: str = ...
    ) -> Story:
        """Create a successor story via the Story-Creation contract."""

    def materialize_split_lineage(
        self,
        *,
        source_story_id: str,
        successor_ids: tuple[str, ...],
    ) -> None:
        """Persist split_successors on the source + split_from on each successor."""

    def materialize_split_source_lineage(
        self,
        *,
        source_story_id: str,
        successor_ids: tuple[str, ...],
    ) -> None:
        """Persist the source side of the split lineage."""

    def materialize_split_successor_lineage(
        self,
        *,
        successor_story_id: str,
        source_story_id: str,
    ) -> None:
        """Persist one successor side of the split lineage."""

    def administratively_cancel_for_story_split(
        self,
        story_display_id: str,
        *,
        story_split_record: object,
        story_split_operation_committed: bool,
        principal: object,
        op_id: str,
    ) -> Story:
        """Administratively cancel the source story for a validated split."""


class _DependencyPort(Protocol):
    def list_for_project(self, project_key: str) -> list[StoryDependency]:
        """List all dependency edges of the project graph."""

    def add(self, edge: StoryDependency, *, project_key: str) -> None:
        """Persist one dependency edge."""

    def remove(
        self, story_id: str, depends_on_story_id: str, kind: StoryDependencyKind
    ) -> None:
        """Remove one dependency edge."""


class _PhaseStateQuiescePort(Protocol):
    def purge_run(self, project_key: str, story_id: str, run_id: str) -> int:
        """Purge the steering ``phase_state_projection`` rows (§54.8.3)."""


class _GovernanceQuiescePort(Protocol):
    def deactivate_locks(self, story_id: str) -> object:
        """Deactivate locks/leases and remove worktree/branch exports."""


class _SuccessorExportPort(Protocol):
    def export(self, *, story_id: str, story_dir: Path) -> object:
        """Export ``story.md`` for a successor and trigger AG3-068 reindexing."""


class _SupersededIndexPort(Protocol):
    def mark_superseded(
        self, *, story_id: str, superseded_by: tuple[str, ...]
    ) -> int:
        """Reindex the cancelled source as ``superseded_by=[...]`` (§54.8.6).

        FAIL-CLOSED: the underlying source re-export/reindex
        (``export_story_md``) signals failure by RETURNING ``success=False``,
        NOT by raising. The adapter MUST propagate that real failure (raise)
        instead of reporting ``0``/success — a swallowed source export failure
        would leave the source un-exported / un-indexed while the split finalizes
        as successful (§54.5 / AK5 / AK12). On success it returns the count of
        reindexed objects (>= 1); ``0`` is never a success.
        """


class _SplitFreezeStorePort(Protocol):
    """Canonical freeze-family persistence consumed by the split saga."""

    def set_freeze(
        self,
        story_id: str,
        *,
        frozen_at: str,
        freeze_reason: str,
        freeze_version: int,
        kind: FreezeKind = ...,
    ) -> object:
        """Enter one audited freeze-family member."""

    def read_freeze(
        self,
        story_id: str,
        kind: FreezeKind = ...,
    ) -> object | None:
        """Read one active freeze-family member."""

    def clear_freeze(
        self,
        story_id: str,
        kind: FreezeKind = ...,
    ) -> int:
        """Resolve exactly one freeze-family member."""


@dataclass(frozen=True)
class StorySplitRequest:
    """Human-CLI request for a story split (§54.6 — no split_id)."""

    project_key: str
    source_story_id: str
    plan: SplitPlan
    plan_text: str
    reason: str
    requested_by: str
    run_id: str
    principal: Principal


@dataclass(frozen=True)
class StorySplitResult:
    """Successful story-split result."""

    split_id: str
    record: StorySplitRecord
    successor_ids: tuple[str, ...]
    rebinding_plan: RebindingPlan
    resumed: bool


class StorySplitService:
    """Orchestrates the canonical FK-54 §54.8 7-step split transaction."""

    def __init__(
        self,
        *,
        control_plane_repository: ControlPlaneRuntimeRepository,
        story_service: _StoryServicePort,
        dependency_repository: _DependencyPort,
        phase_state_quiesce: _PhaseStateQuiescePort,
        governance: _GovernanceQuiescePort,
        successor_export: _SuccessorExportPort,
        superseded_index: _SupersededIndexPort,
        stories_root: Path,
        source_state_loader: Callable[[StorySplitRequest], SplitSourceState],
        freeze_store: _SplitFreezeStorePort,
        object_claim_store: ObjectClaimStorePort,
        backend_instance_id: str,
        instance_incarnation: int,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo = control_plane_repository
        self._story_service = story_service
        self._dependency_repo = dependency_repository
        self._phase_state_quiesce = phase_state_quiesce
        self._governance = governance
        self._successor_export = successor_export
        self._superseded_index = superseded_index
        self._stories_root = stories_root
        self._source_state_loader = source_state_loader
        self._freeze_store = freeze_store
        self._object_claim_store = object_claim_store
        self._backend_instance_id = backend_instance_id
        self._instance_incarnation = instance_incarnation
        self._now_fn = now_fn or (lambda: datetime.now(tz=UTC))

    def _run_claimed_step(
        self,
        request: StorySplitRequest,
        *,
        story_id: str,
        op_id: str,
        mutation: Callable[[], _T],
    ) -> _T:
        """Run one bounded saga mutation under its per-story object claim."""
        key = story_claim_key(request.project_key, story_id)
        conflict = acquire_story_claim(
            self._object_claim_store,
            key,
            op_id=op_id,
            backend_instance_id=self._backend_instance_id,
            instance_incarnation=self._instance_incarnation,
            now=self._now_fn(),
        )
        if conflict is not None:
            raise StorySplitError(
                "story-split saga step could not acquire the per-story object "
                f"claim for {story_id!r} (op_id={op_id!r}, "
                f"retry_after_seconds={conflict.retry_after_seconds})",
            )
        try:
            return mutation()
        finally:
            release_story_claim(self._object_claim_store, key, op_id=op_id)

    def _admin_freeze_reason(self, split_id: str) -> str:
        """Return the split-bound reason used to validate re-entrant entry."""
        return f"story_split:{split_id}:administrative_saga"

    def _enter_admin_freeze(
        self,
        request: StorySplitRequest,
        *,
        split_id: str,
        now: datetime,
    ) -> None:
        """Enter or re-use this split's audited, non-expiring admin freeze."""
        reason = self._admin_freeze_reason(split_id)

        def _enter() -> None:
            existing = self._freeze_store.read_freeze(
                request.source_story_id,
                FreezeKind.SPLIT_ADMIN_FREEZE,
            )
            if existing is not None:
                existing_reason = getattr(existing, "freeze_reason", None)
                if existing_reason != reason:
                    raise StorySplitError(
                        "source story already has a foreign split_admin_freeze",
                    )
                return
            self._freeze_store.set_freeze(
                request.source_story_id,
                frozen_at=now.isoformat(),
                freeze_reason=reason,
                freeze_version=1,
                kind=FreezeKind.SPLIT_ADMIN_FREEZE,
            )

        self._run_claimed_step(
            request,
            story_id=request.source_story_id,
            op_id=f"{split_id}:admin-freeze-enter",
            mutation=_enter,
        )

    def _clear_admin_freeze(
        self,
        request: StorySplitRequest,
        *,
        split_id: str,
    ) -> None:
        """Resolve only this saga's admin freeze after durable finalization."""
        existing = self._freeze_store.read_freeze(
            request.source_story_id,
            FreezeKind.SPLIT_ADMIN_FREEZE,
        )
        if existing is None:
            return
        if getattr(existing, "freeze_reason", None) != self._admin_freeze_reason(
            split_id
        ):
            raise StorySplitError(
                "refusing to clear a foreign split_admin_freeze during finalization",
            )
        cleared = self._freeze_store.clear_freeze(
            request.source_story_id,
            FreezeKind.SPLIT_ADMIN_FREEZE,
        )
        if cleared != 1:
            raise StorySplitError(
                "split_admin_freeze resolution affected an unexpected row count",
            )

    def split_story(self, request: StorySplitRequest) -> StorySplitResult:
        """Execute the FK-54 §54.8 split with a deterministic resume key.

        Order is fixed (§54.8): entry gate -> register/fence -> quiesce ->
        successor creation -> rebinding + lineage -> superseded reindex ->
        administrative split-cancel. A second run with the same ``--story`` /
        ``--plan`` resolves to the same ``split_id`` and RESUMES (no double
        successor creation, no double rebinding, no second cancel).

        Args:
            request: The validated human-CLI split request.

        Returns:
            The :class:`StorySplitResult`.

        Raises:
            StorySplitError: On any fail-closed rejection (entry gate, plan,
                rebinding invariants); no partial mutation is committed past the
                point of rejection.
        """
        plan_ref = compute_plan_ref(request.plan_text)
        split_id = derive_split_id(
            request.project_key, request.source_story_id, plan_ref
        )
        now = self._now_fn()

        # Resume: a committed fence with this split_id replays without re-mutating.
        # A FINALIZED fence is a pure no-op replay; a committed-but-unfinalized
        # fence (a prior run that crashed mid-sequence) CONVERGES — it continues
        # the remaining §54.8 steps idempotently to completion (AK11), it never
        # dead-ends and never fabricates plan-local ids (the real allocated ids
        # are reconstructed from the durable checkpoint / store).
        existing = self._repo.load_operation(split_id)
        if existing is not None and existing.status == "committed":
            return self._resume(request, existing, plan_ref, split_id)

        # Step 0: entry gate (HARD, fail-closed, BEFORE any mutation, §54.4). This
        # validates the WHOLE rebinding plan up-front against the existing graph
        # (all five outcome/process invariants), so a plan that would fail
        # rebinding is rejected with NO successors created/exported and the source
        # untouched. A rejection persists a status=failed split record (§54.4 /
        # AK3) before raising, so the resume key still resolves to an audit trail.
        self._entry_gate(request, plan_ref, split_id=split_id, now=now)

        # Step 1: enter the audited, non-expiring administrative freeze. It is
        # the saga-duration admission blocker; serialization remains bounded to
        # the individual mutations below.
        self._enter_admin_freeze(request, split_id=split_id, now=now)

        # Step 2: atomically register the committed marker, revoke the binding,
        # and terminalize ownership under this step's short source-story claim.
        self._run_claimed_step(
            request,
            story_id=request.source_story_id,
            op_id=f"{split_id}:terminal-transition",
            mutation=lambda: self._commit_terminal_transition(
                request,
                split_id=split_id,
                plan_ref=plan_ref,
                now=now,
            ),
        )

        # Steps 3-7 run through the single resume-safe sequence so a crash at any
        # point converges identically on rerun.
        return self._run_split_to_completion(
            request,
            split_id=split_id,
            plan_ref=plan_ref,
            now=now,
            known_successor_ids={},
            resumed=False,
        )

    # ------------------------------------------------------------------
    # Resume-safe forward sequence (steps 3-7) — idempotent + convergent
    # ------------------------------------------------------------------

    def _run_split_to_completion(
        self,
        request: StorySplitRequest,
        *,
        split_id: str,
        plan_ref: str,
        now: datetime,
        known_successor_ids: dict[str, str],
        resumed: bool,
    ) -> StorySplitResult:
        """Drive §54.8 steps 3-7 idempotently from any partial-progress point.

        Every step is a no-op when it has already been applied, so this method
        is safe to (re-)enter both on the first run and on a convergent resume of
        a crashed run:

          * step 3 quiesce — re-purging an already-quiesced run / re-deactivating
            locks is a no-op at the owner;
          * step 4 successor creation — the Story-Creation contract is op_id
            idempotent, so re-creating an already-created successor returns the
            SAME real id (no duplicate). ``known_successor_ids`` seeds the
            plan-id -> real-id map reconstructed from the durable checkpoint;
          * step 5 rebinding — the resolved edge-mutation plan is checkpointed
            onto the fence BEFORE the first edge mutation and applied
            idempotently (remove-if-present / add-if-absent), so a crash anywhere
            inside the apply converges by replaying the checkpointed plan; a
            fully rebound graph is detected and skipped;
          * step 5b lineage / step 6 cancel / step 7 reindex — all idempotent on
            the already-materialized state.

        Args:
            request: The validated split request.
            split_id: The deterministic split fence id.
            plan_ref: The plan content hash.
            now: The split timestamp.
            known_successor_ids: ``plan_id -> real_id`` reconstructed from the
                durable checkpoint (empty on the first run).
            resumed: Whether this invocation is a convergent resume.

        Returns:
            The completed :class:`StorySplitResult`.
        """
        # Step 3: quiesce the steering runtime (phase_state_projection + locks).
        # NOT a full analytics purge — audit/telemetry are preserved (§54.9).
        self._run_claimed_step(
            request,
            story_id=request.source_story_id,
            op_id=f"{split_id}:quiesce",
            mutation=lambda: (
                self._phase_state_quiesce.purge_run(
                    request.project_key,
                    request.source_story_id,
                    request.run_id,
                ),
                self._governance.deactivate_locks(request.source_story_id),
            ),
        )

        # Step 4: create successors in Backlog via the Story-Creation contract.
        # The contract atomically allocates each successor's authoritative
        # display id; ``plan_id -> created_id`` maps the plan-local reference id
        # onto the real id used by lineage / rebinding / superseded_by. The REAL
        # ids are checkpointed onto the durable fence AS they are allocated, so a
        # crash before finalize still persists what was created.
        plan_to_created = self._create_successors(
            request,
            split_id=split_id,
            plan_ref=plan_ref,
            now=now,
            known_successor_ids=known_successor_ids,
        )
        successor_ids = tuple(
            plan_to_created[s.story_id] for s in request.plan.successors
        )

        # Step 5: dependency rebinding (only AFTER successors exist) + lineage.
        # The plan was already validated in the entry gate against the plan-local
        # ids; re-deriving with the real allocated ids is a deterministic remap
        # that cannot newly fail (the validation is a bijection on a valid plan).
        # The fully-resolved edge-mutation plan is CHECKPOINTED onto the durable
        # fence BEFORE the first edge mutation, and applied idempotently
        # (remove-if-present / add-if-absent), so a crash at ANY point inside the
        # apply converges on rerun. On a convergent resume of an already-rebound
        # graph this is a no-op.
        rebinding_plan = self._apply_rebinding(
            request,
            successor_ids,
            plan_to_created,
            split_id=split_id,
            plan_ref=plan_ref,
            now=now,
        )

        # Step 5b: materialize the AK7 lineage on the REAL stories — split_from on
        # each successor, split_successors on the source — using the allocated ids
        # (never the plan ids). Idempotent.
        self._run_claimed_step(
            request,
            story_id=request.source_story_id,
            op_id=f"{split_id}:lineage:source",
            mutation=lambda: self._story_service.materialize_split_source_lineage(
                source_story_id=request.source_story_id,
                successor_ids=successor_ids,
            ),
        )
        for index, successor_id in enumerate(successor_ids):
            self._run_claimed_step(
                request,
                story_id=successor_id,
                op_id=f"{split_id}:lineage:successor:{index}:{successor_id}",
                mutation=partial(
                    self._story_service.materialize_split_successor_lineage,
                    successor_story_id=successor_id,
                    source_story_id=request.source_story_id,
                ),
            )

        # Build the committed record (CONSUMES AG3-074 result axis).
        record = _committed_split_result_record(
            request=request,
            split_id=split_id,
            plan_ref=plan_ref,
            successor_ids=successor_ids,
            created_at=now,
        )

        # Step 6: controlled termination via the administrative split-cancel path.
        # This MUST run BEFORE the superseded reindex so the (re-)export/reindex in
        # step 7 observes the source already Cancelled — the final indexed source
        # state is Cancelled WITH superseded_by, not a stale In Progress (§54.8.7).
        # Idempotent on an already-Cancelled source (no second cancel transition).
        self._run_claimed_step(
            request,
            story_id=request.source_story_id,
            op_id=f"{split_id}:source-cancel",
            mutation=lambda: self._administratively_cancel(
                request,
                record,
                split_id=split_id,
            ),
        )

        # Step 7: reindex the now-Cancelled source as superseded_by (NOT deleted,
        # §54.8.6). Ordered after the administrative cancel so both the Cancelled
        # status and superseded_by are reflected in the final indexed state.
        # FAIL-CLOSED (§54.5 / AK5 / AK12): a real source export/reindex failure
        # propagates (the adapter raises rather than returning 0). Defense in
        # depth, a reported count of 0 is treated as a failed reindex too, so the
        # split never finalizes on an un-indexed source. A raised/failed source
        # reindex strands the fence committed-but-unfinalized; a later rerun
        # RESUMES and re-attempts this reindex idempotently.
        reindexed = self._run_claimed_step(
            request,
            story_id=request.source_story_id,
            op_id=f"{split_id}:source-reindex",
            mutation=lambda: self._superseded_index.mark_superseded(
                story_id=request.source_story_id,
                superseded_by=successor_ids,
            ),
        )
        if reindexed < 1:
            raise StorySplitError(
                "source superseded reindex reported 0 reindexed objects for "
                f"{request.source_story_id!r} (fail-closed: the cancelled source "
                "must stay indexed as superseded_by, §54.8.6)",
            )

        # Finalize the fence record with the resolved successors so a later
        # resume (AC11) replays the exact committed result as a pure no-op.
        self._run_claimed_step(
            request,
            story_id=request.source_story_id,
            op_id=f"{split_id}:finalize",
            mutation=lambda: self._finalize_fence(
                request,
                split_id=split_id,
                record=record,
                now=now,
            ),
        )

        return StorySplitResult(
            split_id=split_id,
            record=record,
            successor_ids=successor_ids,
            rebinding_plan=rebinding_plan,
            resumed=resumed,
        )

    # ------------------------------------------------------------------
    # Step 0: entry gate (§54.4)
    # ------------------------------------------------------------------

    def _entry_gate(
        self,
        request: StorySplitRequest,
        plan_ref: str,
        *,
        split_id: str,
        now: datetime,
    ) -> None:
        """Fail-closed entry gate; rejects with NO partial mutation (§54.4).

        On any rejection a ``status=failed`` :class:`StorySplitRecord` is
        persisted (capturing the failed precondition) BEFORE the
        :class:`StorySplitError` is raised, so a rejected precondition leaves an
        auditable failed record and the deterministic split_id resume key still
        resolves (formal ``story-split.transition.requested_to_failed``, AK3).
        The whole rebinding plan is validated up-front so a rebinding-invalid plan
        is a clean fail-closed reject with no successors created and the source
        untouched.
        """
        try:
            self._check_entry_preconditions(request, plan_ref)
        except StorySplitError as exc:
            self._record_failed_split(
                request, plan_ref, split_id=split_id, now=now, reason=str(exc)
            )
            raise

    def _check_entry_preconditions(
        self, request: StorySplitRequest, plan_ref: str
    ) -> None:
        """Run every fail-closed §54.4 precondition (raises on the first failure)."""
        if request.principal is not Principal.HUMAN_CLI:
            raise StorySplitError(
                "split entry gate rejected: split requires Principal.HUMAN_CLI "
                "(explicit human split approval)",
            )
        if request.plan.source_story_id != request.source_story_id:
            raise StorySplitError(
                "split entry gate rejected: --story does not match the plan's "
                f"source_story_id ({request.plan.source_story_id!r})",
            )
        if request.plan.project_key != request.project_key:
            raise StorySplitError(
                "split entry gate rejected: --plan project_key does not match "
                f"the bound project ({request.plan.project_key!r})",
            )
        if not plan_ref:
            raise StorySplitError("split entry gate rejected: empty plan reference")
        source = self._story_service.get_story(request.source_story_id)
        if source is None:
            raise StorySplitError(
                "split entry gate rejected: source story "
                f"{request.source_story_id!r} is unknown",
            )
        # FAIL-CLOSED (§54.4 / §54.8.7): the administrative split-cancel path is
        # only legal from In Progress, so a source in any other status is rejected
        # AT THE GATE with zero mutation — never stranded mid-flow at step 6 after
        # successors were already created (an unrecoverable half-split).
        if str(source.status) != StoryStatus.IN_PROGRESS.value:
            raise StorySplitError(
                "split entry gate rejected: source story "
                f"{request.source_story_id!r} is {str(source.status)!r}, but the "
                "administrative split-cancel path (§54.8.7) requires In Progress",
            )
        state = self._source_state_loader(request)
        if not state.scope_explosion_established:
            raise StorySplitError(
                "split entry gate rejected: no established scope_explosion for "
                f"{request.source_story_id!r}",
            )
        if not state.paused_with_scope_explosion:
            raise StorySplitError(
                "split entry gate rejected: source story is not in the typical "
                "PAUSED / escalation_class=scope_explosion prior state",
            )
        if state.competing_admin_operation_active:
            raise StorySplitError(
                "split entry gate rejected: a competing administrative operation "
                f"is active for {request.source_story_id!r}",
            )
        # Validate the WHOLE rebinding plan up-front (all five invariants) against
        # the existing graph using the PLAN-LOCAL successor ids. Membership /
        # stale / silent-drop / fanout / cycle checks need only the declared
        # successor SET and the pre-existing edges, none of which depend on the
        # real allocated ids — so a rebinding-invalid plan fails closed HERE,
        # before any successor is created or exported.
        self._validate_plan_rebinding(request)

    def _validate_plan_rebinding(self, request: StorySplitRequest) -> None:
        """Up-front rebinding validation with plan-local successor ids (§54.4)."""
        existing_edges = tuple(
            self._dependency_repo.list_for_project(request.project_key)
        )
        plan_successor_ids = tuple(
            s.story_id for s in request.plan.successors
        )
        rebinding_entries = tuple(
            (
                entry.dependent_story_id,
                entry.old_dependency,
                tuple(entry.new_dependencies),
            )
            for entry in request.plan.dependency_rebinding
        )
        try:
            validate_rebinding_plan(
                source_story_id=request.source_story_id,
                successor_ids=plan_successor_ids,
                rebinding_entries=rebinding_entries,
                existing_edges=existing_edges,
            )
        except RebindingError as exc:
            raise StorySplitError(
                f"split entry gate rejected: dependency rebinding invalid: {exc}",
            ) from exc

    def _record_failed_split(
        self,
        request: StorySplitRequest,
        plan_ref: str,
        *,
        split_id: str,
        now: datetime,
        reason: str,
    ) -> StorySplitRecord:
        """Persist a ``status=failed`` split record for a rejected precondition.

        The failed record carries NO exit_class/terminal_state (no mutation
        happened) but records the rejection reason and resolves under the same
        deterministic ``split_id`` resume key. It is stored as a ``failed`` fence
        operation so a later run with the same ``--story``/``--plan`` can find the
        audit trail. Storing the failed record never mutates the source story.
        """
        record = StorySplitRecord(
            split_id=split_id,
            project_key=request.project_key,
            source_story_id=request.source_story_id,
            requested_by=request.requested_by,
            reason=request.reason,
            plan_ref=plan_ref,
            status=SplitStatus.FAILED,
            rejection_reason=reason,
            created_at=now,
        )
        op_record = _split_operation_record(
            request=request,
            split_id=split_id,
            plan_ref=plan_ref,
            now=now,
            status="failed",
            extra_payload={"rejection_reason": reason},
        )
        self._repo.commit_operation_with_side_effects(
            op_record,
            binding_to_save=None,
            binding_to_delete=None,
            locks=(),
            events=(),
        )
        return record

    # ------------------------------------------------------------------
    # Step 1+2: register + fence
    # ------------------------------------------------------------------

    def _commit_terminal_transition(
        self,
        request: StorySplitRequest,
        *,
        split_id: str,
        plan_ref: str,
        now: datetime,
    ) -> None:
        """Commit marker, binding revocation, and ownership status atomically."""
        existing = self._repo.load_operation(split_id)
        committed_existing: ControlPlaneOperationRecord | None = None
        if existing is not None:
            same_split = (
                existing.operation_kind == "story_split"
                and existing.project_key == request.project_key
                and existing.story_id == request.source_story_id
            )
            if existing.status == "committed" and same_split:
                committed_existing = existing
            # A prior ``failed`` audit record for THIS split_id (a rejected
            # earlier run, §54.4) is overwritten by the real commit; it never
            # counts as a foreign collision. Any other occupant is a collision.
            elif not (existing.status == "failed" and same_split):
                raise StorySplitError(
                    "split fence collides with a foreign operation",
                )
        op_record = _committed_split_record(
            request=request,
            split_id=split_id,
            plan_ref=plan_ref,
            now=now,
        )
        active = self._repo.load_active_ownership(
            request.project_key,
            request.source_story_id,
        )
        if active is None:
            if committed_existing is not None:
                return
            self._repo.commit_operation_with_side_effects(
                op_record,
                binding_to_save=None,
                binding_to_delete=None,
                locks=(),
                events=(),
            )
            return
        if active.run_id != request.run_id:
            raise StorySplitError("split disown active ownership belongs to another run")
        binding = self._repo.load_binding(active.owner_session_id)
        if (
            binding is None
            or binding.status != BindingStatus.ACTIVE.value
            or binding.project_key != request.project_key
            or binding.story_id != request.source_story_id
            or binding.run_id != request.run_id
        ):
            raise StorySplitError("split disown requires the exact active owner binding")
        plan = build_disown_plan(
            binding,
            BindingRevocationReason.STORY_SPLIT,
            now,
        )
        op_record = (
            replace(
                committed_existing,
                response_payload={
                    **committed_existing.response_payload,
                    "revocation_reason": plan.reconcile_reason,
                },
                updated_at=now,
            )
            if committed_existing is not None
            else _committed_split_record(
                request=request,
                split_id=split_id,
                plan_ref=plan_ref,
                now=now,
                extra_payload={"revocation_reason": plan.reconcile_reason},
            )
        )
        event = ExecutionEventRecord(
            project_key=request.project_key,
            story_id=request.source_story_id,
            run_id=request.run_id,
            event_id=f"{split_id}:session-disowned",
            event_type=EventType.SESSION_DISOWNED.value,
            occurred_at=now,
            source_component="story_split_service",
            severity="INFO",
            payload=plan.audit_payload,
        )
        self._repo.commit_operation_with_side_effects(
            op_record,
            binding_to_save=plan.revoked_binding,
            binding_to_delete=None,
            locks=(),
            events=(event,),
            ownership_status_target=plan.ownership_status_target,
        )

    def _finalize_fence(
        self,
        request: StorySplitRequest,
        *,
        split_id: str,
        record: StorySplitRecord,
        now: datetime,
    ) -> None:
        """Persist the resolved successor ids onto the committed fence record."""
        op_record = _committed_split_record(
            request=request,
            split_id=split_id,
            plan_ref=record.plan_ref,
            now=now,
            extra_payload={"successor_ids": list(record.successor_ids)},
        )
        self._repo.commit_operation_with_side_effects(
            op_record,
            binding_to_save=None,
            binding_to_delete=None,
            locks=(),
            events=(),
            command_id="story_split_finalize",
        )
        self._clear_admin_freeze(request, split_id=split_id)

    # ------------------------------------------------------------------
    # Step 4: successor creation via the Story-Creation contract
    # ------------------------------------------------------------------

    def _create_successors(
        self,
        request: StorySplitRequest,
        *,
        split_id: str,
        plan_ref: str,
        now: datetime,
        known_successor_ids: dict[str, str],
    ) -> dict[str, str]:
        """Create successors in Backlog (§54.8.4) + export ``story.md``.

        The actor is the official ``StorySplitService`` system path, so creation
        is script-driven. Each successor is created via the same Story-Creation
        contract as a normal story and then exported (the export triggers the
        AG3-068 reindex as a hard blocker).

        Idempotent + checkpointed: the Story-Creation contract is op_id
        idempotent, so re-creating an already-created successor returns the SAME
        real id (no duplicate). The REAL allocated id is checkpointed onto the
        durable fence payload IMMEDIATELY after each ``create_story`` succeeds —
        BEFORE the crash-prone export — so a crash mid-sequence still persists the
        real ids allocated so far. On a convergent resume ``known_successor_ids``
        seeds the already-allocated mapping; re-running yields the identical ids.

        Returns:
            A ``plan_id -> created_display_id`` map. The Story-Creation contract
            allocates the authoritative project-monotone display id; the plan's
            ``successors[].story_id`` is the plan-local reference key.
        """
        source = self._story_service.get_story(request.source_story_id)
        if source is None:  # pragma: no cover - gate already guaranteed presence
            raise StorySplitError("source story vanished between gate and creation")
        plan_to_created: dict[str, str] = dict(known_successor_ids)
        for index, successor in enumerate(request.plan.successors):
            created = self._story_service.create_story(
                _build_successor_input(source, successor),
                op_id=f"{split_id}:successor:{index}:{successor.story_id}",
            )
            # The REAL allocated display id, always — never a silent fallback to
            # the plan-local reference id (the contract returns a Story).
            created_id = str(created.story_display_id)
            if plan_to_created.get(successor.story_id) != created_id:
                plan_to_created[successor.story_id] = created_id
                # Checkpoint the REAL allocated ids onto the durable fence BEFORE
                # the crash-prone export, so a mid-sequence fault leaves a record
                # the convergent resume reconstructs from (never plan-local ids).
                self._run_claimed_step(
                    request,
                    story_id=request.source_story_id,
                    op_id=f"{split_id}:successor-checkpoint:{index}",
                    mutation=lambda: self._checkpoint_successors(
                        request,
                        split_id=split_id,
                        plan_ref=plan_ref,
                        now=now,
                        plan_to_created=plan_to_created,
                    ),
                )
            self._run_claimed_step(
                request,
                story_id=created_id,
                op_id=f"{split_id}:successor-export:{index}:{created_id}",
                mutation=partial(self._export_successor, created_id),
            )
        return plan_to_created

    def _checkpoint_successors(
        self,
        request: StorySplitRequest,
        *,
        split_id: str,
        plan_ref: str,
        now: datetime,
        plan_to_created: dict[str, str],
    ) -> None:
        """Persist the real ``plan_id -> real_id`` map onto the committed fence.

        Written incrementally during successor creation so a crash before
        ``_finalize_fence`` still leaves the durable fence carrying the REAL
        allocated ids (under ``successor_map``). The convergent resume reads this
        checkpoint to reconstruct the already-created successors and continue —
        it NEVER fabricates plan-local ids. The fence stays ``committed`` and
        unfinalized (no ``successor_ids``) until step 7 completes.
        """
        op_record = _committed_split_record(
            request=request,
            split_id=split_id,
            plan_ref=plan_ref,
            now=now,
            extra_payload={"successor_map": dict(plan_to_created)},
        )
        self._repo.commit_operation_with_side_effects(
            op_record,
            binding_to_save=None,
            binding_to_delete=None,
            locks=(),
            events=(),
        )

    def _export_successor(self, created_id: str) -> None:
        """Export the successor ``story.md`` (triggers AG3-068 reindex).

        FAIL-CLOSED (§54.5 / AK5 / AK12, FK-21 §21.11.4): the production
        ``export_story_md`` signals a missing story / write error / validation
        failure / VectorDB-indexing failure by RETURNING
        ``StoryMdExportResult(success=False)``, NOT by raising. A swallowed
        ``success=False`` would let a successor proceed un-exported / un-indexed
        through rebinding, cancel, reindex and ``_finalize_fence`` while the split
        reports success — a silent integration-consequences gap (FK-54 §54.11,
        "Integrationsfolgen"). So the result is
        inspected here and a failed export raises a typed split error BEFORE any
        downstream step runs.

        Because of the convergent-resume design (the fence is committed but NOT
        finalized at this point and the real successor ids are already
        checkpointed), a raised export failure strands the split as
        committed-but-unfinalized: a later rerun RESUMES and re-attempts this
        export idempotently. A transient failure that later succeeds converges on
        rerun; a persistent failure stays fail-closed and never silently
        finalizes.
        """
        story_dir = self._stories_root / created_id
        result = self._successor_export.export(
            story_id=created_id, story_dir=story_dir
        )
        _require_export_success(
            result,
            failure=(
                f"successor story.md export/reindex failed for {created_id!r}"
            ),
        )

    # ------------------------------------------------------------------
    # Step 5: dependency rebinding (after successors exist)
    # ------------------------------------------------------------------

    def _apply_rebinding(
        self,
        request: StorySplitRequest,
        successor_ids: tuple[str, ...],
        plan_to_created: dict[str, str],
        *,
        split_id: str,
        plan_ref: str,
        now: datetime,
    ) -> RebindingPlan:
        """Derive, checkpoint + apply the rebinding plan (crash-convergent).

        ``mapping_requires_successors_created`` holds by ordering (successors
        exist). The deterministic plan is derived first (pure, fail-closed on the
        six formal invariants); only a fully valid plan is applied. The plan-local
        successor reference ids in ``new_dependencies`` are translated to the
        authoritative created display ids.

        Crash-convergent by construction (second-QA finding F1; r6 multi-kind):

          * the fully-resolved edge-mutation plan (WITH the dependency kinds,
            which are unrecoverable from a half-mutated graph) is CHECKPOINTED
            onto the durable fence BEFORE the first edge mutation;
          * the durable checkpoint is the SINGLE source of convergence truth.
            On resume it is loaded and replayed verbatim; the apply is
            idempotent at the FULL dependency identity ``(dependent, target,
            kind)`` against the REAL store semantics (remove-if-present /
            add-if-absent — the production repository raises on a missing
            remove / duplicate add);
          * a rerun after a crash anywhere inside the apply therefore replays
            EVERY checkpointed ``(remove/add, kind)`` tuple to convergence: each
            step that is already satisfied is a no-op, so re-running any number
            of times leaves exactly the planned end-state (no dropped kind, no
            duplicate edge).

        There is deliberately NO kind-blind "graph already looks rebound"
        short-circuit: dependency identity includes ``kind``, so any
        convergence check that ignored a kind could finalize the split while a
        second required edge of a different kind is still missing (r6 Blocker).
        The kind-aware checkpoint replay is the only convergence gate.
        """
        existing_edges = tuple(
            self._dependency_repo.list_for_project(request.project_key)
        )
        rebinding_entries = tuple(
            (
                entry.dependent_story_id,
                entry.old_dependency,
                tuple(plan_to_created[dep] for dep in entry.new_dependencies),
            )
            for entry in request.plan.dependency_rebinding
        )
        plan = self._load_rebinding_plan_checkpoint(split_id, successor_ids)
        if plan is None:
            try:
                plan = plan_rebinding(
                    source_story_id=request.source_story_id,
                    successor_ids=successor_ids,
                    rebinding_entries=rebinding_entries,
                    existing_edges=existing_edges,
                )
            except RebindingError as exc:
                raise StorySplitError(
                    f"dependency rebinding rejected: {exc}"
                ) from exc
            if plan.removals or plan.additions:
                self._run_claimed_step(
                    request,
                    story_id=request.source_story_id,
                    op_id=f"{split_id}:rebinding-checkpoint",
                    mutation=lambda: self._checkpoint_rebinding_plan(
                        request,
                        split_id=split_id,
                        plan_ref=plan_ref,
                        now=now,
                        plan_to_created=plan_to_created,
                        plan=plan,
                    ),
                )

        present = {
            (e.story_id, e.depends_on_story_id, e.kind.value) for e in existing_edges
        }
        for removal in plan.removals:
            if (
                removal.story_id,
                removal.depends_on_story_id,
                removal.kind.value,
            ) in present:
                self._run_claimed_step(
                    request,
                    story_id=removal.story_id,
                    op_id=(
                        f"{split_id}:rebind:remove:{removal.story_id}:"
                        f"{removal.depends_on_story_id}:{removal.kind.value}"
                    ),
                    mutation=partial(
                        self._dependency_repo.remove,
                        removal.story_id,
                        removal.depends_on_story_id,
                        removal.kind,
                    ),
                )
        created_at = self._now_fn()
        for addition in plan.additions:
            if (
                addition.story_id,
                addition.depends_on_story_id,
                addition.kind.value,
            ) not in present:
                self._run_claimed_step(
                    request,
                    story_id=addition.story_id,
                    op_id=(
                        f"{split_id}:rebind:add:{addition.story_id}:"
                        f"{addition.depends_on_story_id}:{addition.kind.value}"
                    ),
                    mutation=partial(
                        self._dependency_repo.add,
                        StoryDependency(
                            story_id=addition.story_id,
                            depends_on_story_id=addition.depends_on_story_id,
                            kind=addition.kind,
                            created_at=created_at,
                        ),
                        project_key=request.project_key,
                    ),
                )
        return plan

    def _checkpoint_rebinding_plan(
        self,
        request: StorySplitRequest,
        *,
        split_id: str,
        plan_ref: str,
        now: datetime,
        plan_to_created: dict[str, str],
        plan: RebindingPlan,
    ) -> None:
        """Persist the resolved edge-mutation plan onto the committed fence.

        Written ONCE, before the first edge mutation. The checkpoint carries the
        dependency ``kind`` of every removal/addition — the one piece of
        information that is unrecoverable from a half-mutated graph (the old edge
        whose kind the addition inherits may already be deleted). The
        ``successor_map`` is re-asserted so a later resume keeps the successor
        reconstruction cross-checks (the fence stays committed-but-unfinalized).
        """
        op_record = _committed_split_record(
            request=request,
            split_id=split_id,
            plan_ref=plan_ref,
            now=now,
            extra_payload={
                "successor_map": dict(plan_to_created),
                "rebinding_plan": _serialize_rebinding_plan(plan),
            },
        )
        self._repo.commit_operation_with_side_effects(
            op_record,
            binding_to_save=None,
            binding_to_delete=None,
            locks=(),
            events=(),
        )

    def _load_rebinding_plan_checkpoint(
        self, split_id: str, successor_ids: tuple[str, ...]
    ) -> RebindingPlan | None:
        """Load the checkpointed edge-mutation plan from the durable fence.

        Returns ``None`` when no rebinding checkpoint exists (first run, or the
        prior run crashed before deriving the plan — the graph is then still
        pristine and the normal derivation applies). A present checkpoint was
        derived from the entry-gate-validated plan against the pristine graph; it
        is replayed verbatim (idempotently) instead of re-deriving against a
        possibly half-mutated graph. Fails closed on a structurally corrupt
        checkpoint or one whose addition targets are not the created successors.
        """
        operation = self._repo.load_operation(split_id)
        if operation is None:
            return None
        payload = (
            operation.response_payload
            if isinstance(operation.response_payload, dict)
            else {}
        )
        raw = payload.get("rebinding_plan")
        if raw is None:
            return None
        return _deserialize_rebinding_plan(raw, successor_ids)

    # ------------------------------------------------------------------
    # Step 7: controlled termination
    # ------------------------------------------------------------------

    def _administratively_cancel(
        self,
        request: StorySplitRequest,
        record: StorySplitRecord,
        *,
        split_id: str,
    ) -> None:
        """Cancel the source via the administrative split-cancel path (§54.8.7)."""
        operation = self._repo.load_operation(split_id)
        committed = (
            operation is not None
            and operation.status == "committed"
            and operation.operation_kind == "story_split"
            and operation.project_key == request.project_key
            and operation.story_id == request.source_story_id
            and operation.run_id == request.run_id
        )
        story = self._story_service.administratively_cancel_for_story_split(
            request.source_story_id,
            story_split_record=record,
            story_split_operation_committed=committed,
            principal=request.principal,
            op_id=split_id,
        )
        if str(getattr(story, "status", "")) != "Cancelled":
            raise StorySplitError(
                "split teardown requires the source story status Cancelled",
            )

    # ------------------------------------------------------------------
    # Resume
    # ------------------------------------------------------------------

    def _resume(
        self,
        request: StorySplitRequest,
        operation: ControlPlaneOperationRecord,
        plan_ref: str,
        split_id: str,
    ) -> StorySplitResult:
        """Replay a committed split idempotently (AC11) — no-op OR convergent.

        Two cases for a committed fence under this resume key:

        * **Finalized** — the payload carries the resolved ``successor_ids``
          (``_finalize_fence`` writes them only after cancel + reindex). The split
          already ran to completion: this is a pure no-op replay (no re-creation,
          no re-rebinding, no second cancel). The result mirrors the original
          commit so the CLI is idempotent.

        * **Committed-but-unfinalized** — a prior run committed the fence but
          crashed mid-sequence. Per AK11 this is a CONVERGENT resume, NOT a
          dead-end: the real allocated successor ids are reconstructed from the
          durable ``successor_map`` checkpoint (cross-checked against stories
          carrying ``split_from == source``), and the remaining §54.8 steps run
          IDEMPOTENTLY to completion. No fabricated plan-local ids are ever used —
          the reconstruction relies solely on REAL persisted ids, and the
          Story-Creation op_id idempotency guarantees no duplicate successor.

        It fails closed ONLY when the persisted partial state is genuinely
        inconsistent with the current plan (a checkpoint pointing at a plan id the
        plan no longer declares, or at a successor story that has vanished) — and
        then it says why.
        """
        # §54.4 (c) holds for EVERY run, including a convergent resume: the human
        # split approval (Principal.HUMAN_CLI) is re-asserted BEFORE any resumed
        # mutation. A committed fence is no license for a non-human principal to
        # drive the remaining steps.
        if request.principal is not Principal.HUMAN_CLI:
            raise StorySplitError(
                "resume rejected: split resume requires Principal.HUMAN_CLI "
                "(explicit human split approval, §54.4)",
            )
        if operation.story_id != request.source_story_id or (
            operation.project_key != request.project_key
        ):
            raise StorySplitError(
                "resume rejected: committed fence belongs to a different story",
            )
        payload = (
            operation.response_payload
            if isinstance(operation.response_payload, dict)
            else {}
        )
        raw_ids = payload.get("successor_ids")
        if isinstance(raw_ids, list):
            # A crash can occur after durable finalization but before the
            # kind-scoped clear. Reconcile that narrow window idempotently.
            self._clear_admin_freeze(request, split_id=split_id)
            return self._replay_finalized(
                request,
                operation,
                plan_ref,
                split_id,
                raw_ids,
            )
        # Committed-but-unfinalized: converge from the durable checkpoint.
        # R2 also repairs a legacy R1 marker-only crash before any resumed saga
        # mutation: the existing marker is rewritten with revocation + terminal
        # ownership status in one operation-ledger transaction.
        self._enter_admin_freeze(
            request,
            split_id=split_id,
            now=operation.created_at,
        )
        self._run_claimed_step(
            request,
            story_id=request.source_story_id,
            op_id=f"{split_id}:terminal-transition",
            mutation=lambda: self._commit_terminal_transition(
                request,
                split_id=split_id,
                plan_ref=plan_ref,
                now=operation.created_at,
            ),
        )
        known = self._reconstruct_successor_checkpoint(request, payload)
        return self._run_split_to_completion(
            request,
            split_id=split_id,
            plan_ref=plan_ref,
            now=operation.created_at,
            known_successor_ids=known,
            resumed=True,
        )

    def _replay_finalized(
        self,
        request: StorySplitRequest,
        operation: ControlPlaneOperationRecord,
        plan_ref: str,
        split_id: str,
        raw_ids: list[object],
    ) -> StorySplitResult:
        """Pure no-op replay of a FINALIZED committed split (no re-mutation)."""
        successor_ids = tuple(str(item) for item in raw_ids)
        record = _committed_split_result_record(
            request=request,
            split_id=split_id,
            plan_ref=plan_ref,
            successor_ids=successor_ids,
            created_at=operation.created_at,
        )
        return StorySplitResult(
            split_id=split_id,
            record=record,
            successor_ids=successor_ids,
            rebinding_plan=RebindingPlan(removals=(), additions=()),
            resumed=True,
        )

    def _reconstruct_successor_checkpoint(
        self,
        request: StorySplitRequest,
        payload: dict[str, object],
    ) -> dict[str, str]:
        """Reconstruct ``plan_id -> real_id`` from the durable checkpoint.

        Reads the incremental ``successor_map`` checkpoint persisted during a
        prior run's successor creation. Every reconstructed real id is validated
        against the live store — it must be a real, existing story carrying
        ``split_from == source`` (or not yet linked but present). This NEVER
        fabricates plan-local ids; an entry whose plan id is unknown to the
        current plan, or whose real story has vanished, is a genuinely
        inconsistent partial state and fails closed.

        Returns:
            The validated ``plan_id -> real_id`` map (possibly empty when the
            prior run crashed before creating any successor — a clean, recoverable
            state the convergent run simply re-creates from).
        """
        raw_map = payload.get("successor_map")
        if raw_map is None:
            return {}
        if not isinstance(raw_map, dict):
            raise StorySplitError(
                "resume rejected: split fence checkpoint is malformed "
                "(successor_map is not a mapping) — partial state is inconsistent",
            )
        plan_ids = {s.story_id for s in request.plan.successors}
        # Cross-check: stories already carrying split_from == source corroborate
        # the checkpoint (an already-linked successor of a prior run). Existence in
        # the store is the hard precondition; this set is the §54.8.4 corroboration.
        linked_successors = {
            story.story_display_id
            for story in self._story_service.list_stories(request.project_key)
            if getattr(story, "split_from", None) == request.source_story_id
        }
        reconstructed: dict[str, str] = {}
        for plan_id, real_id in raw_map.items():
            plan_key = str(plan_id)
            real = str(real_id)
            if plan_key not in plan_ids:
                raise StorySplitError(
                    "resume rejected: split fence checkpoint references an "
                    f"unknown plan successor {plan_key!r} — the persisted partial "
                    "state is inconsistent with the supplied --plan",
                )
            story = self._story_service.get_story(real)
            if story is None and real not in linked_successors:
                raise StorySplitError(
                    "resume rejected: split fence checkpoint points at successor "
                    f"{real!r} which no longer exists — partial state is "
                    "irrecoverable",
                )
            # A checkpointed successor is either already linked (split_from set) or
            # freshly created but not yet linked; in both cases re-running creation
            # with the deterministic op_id reuses this exact id (no duplicate).
            reconstructed[plan_key] = real
        return reconstructed


def _split_operation_record(
    *,
    request: StorySplitRequest,
    split_id: str,
    plan_ref: str,
    now: datetime,
    status: str,
    extra_payload: dict[str, object] | None = None,
) -> ControlPlaneOperationRecord:
    """Build a story-split fence record from the shared §54.8 boilerplate.

    Every §54.8 fence write (initial commit, incremental successor/rebinding
    checkpoints, finalization, and the ``failed`` rejection audit) shares the
    identical operation envelope and base response payload; only ``status`` and
    the per-step ``extra_payload`` keys differ. Centralising the construction
    keeps the persisted fence shape identical across all writes.
    """
    response_payload: dict[str, object] = {
        "status": status,
        "op_id": split_id,
        "operation_kind": "story_split",
        "plan_ref": plan_ref,
        "requested_by": request.requested_by,
    }
    if extra_payload:
        response_payload.update(extra_payload)
    return ControlPlaneOperationRecord(
        op_id=split_id,
        project_key=request.project_key,
        story_id=request.source_story_id,
        run_id=request.run_id,
        session_id=None,
        operation_kind="story_split",
        phase=None,
        status=status,
        response_payload=response_payload,
        created_at=now,
        updated_at=now,
    )


def _committed_split_record(
    *,
    request: StorySplitRequest,
    split_id: str,
    plan_ref: str,
    now: datetime,
    extra_payload: dict[str, object] | None = None,
) -> ControlPlaneOperationRecord:
    """Build a ``committed`` story-split fence record (see ``_split_operation_record``)."""
    return _split_operation_record(
        request=request,
        split_id=split_id,
        plan_ref=plan_ref,
        now=now,
        status="committed",
        extra_payload=extra_payload,
    )


def _committed_split_result_record(
    *,
    request: StorySplitRequest,
    split_id: str,
    plan_ref: str,
    successor_ids: tuple[str, ...],
    created_at: datetime,
) -> StorySplitRecord:
    """Build the COMMITTED split record (CONSUMES the AG3-074 result axis).

    Used both on the live success path and on the finalized no-op resume replay,
    keeping the persisted record identity (status / terminal_state / exit_class /
    superseded_by) identical between a first run and its idempotent replay.
    """
    return StorySplitRecord(
        split_id=split_id,
        project_key=request.project_key,
        source_story_id=request.source_story_id,
        requested_by=request.requested_by,
        reason=request.reason,
        plan_ref=plan_ref,
        status=SplitStatus.COMMITTED,
        successor_ids=successor_ids,
        superseded_by=successor_ids,
        terminal_state=TerminalState.CANCELLED,
        exit_class=ExitClass.SCOPE_SPLIT,
        created_at=created_at,
    )


def _build_successor_input(
    source: Story, successor: SuccessorStory
) -> CreateStoryInput:
    """Build the Story-Creation input for one successor from the source."""
    return CreateStoryInput.model_validate(
        {
            "project_key": source.project_key,
            "title": successor.title,
            "type": source.story_type.value
            if isinstance(source.story_type, WireStoryType)
            else str(source.story_type),
            "repos": list(source.participating_repos),
            "epic": source.epic,
            "module": source.module,
            "size": source.size.value
            if isinstance(source.size, StorySize)
            else str(source.size),
            "change_impact": source.change_impact.value
            if isinstance(source.change_impact, ChangeImpact)
            else str(source.change_impact),
            "concept_quality": source.concept_quality.value
            if isinstance(source.concept_quality, ConceptQuality)
            else str(source.concept_quality),
            "owner": source.owner,
            "risk": source.risk.value
            if isinstance(source.risk, RiskLevel)
            else str(source.risk),
            "labels": list(source.labels),
        }
    )


def _require_export_success(result: object, *, failure: str) -> None:
    """Fail closed when a story.md export/reindex result reports failure.

    The production ``export_story_md`` returns a
    :class:`~agentkit.backend.story_creation.story_md_export.StoryMdExportResult`
    whose ``success`` flag is ``False`` on ANY blocker (missing story, write
    error, < 500 bytes / missing-frontmatter validation, VectorDB indexing
    failure) WITHOUT raising. Every export/reindex call site in the split flow
    routes its result through this guard so a ``success=False`` is never
    swallowed — it raises a :class:`StorySplitError` carrying the underlying
    ``error`` detail, keeping the split fail-closed (no partial mutation past
    the point of rejection, §54.5 / AK5 / AK12).
    """
    if not getattr(result, "success", False):
        detail = str(getattr(result, "error", "") or "no detail reported")
        raise StorySplitError(f"{failure}: {detail}")


def _serialize_rebinding_plan(plan: RebindingPlan) -> dict[str, object]:
    """Serialize a resolved edge-mutation plan for the durable fence checkpoint.

    The serialized form carries the dependency ``kind`` of every removal/addition
    — the one piece of information that is unrecoverable from a half-mutated
    graph (the old edge whose kind the addition inherits may already be deleted).
    """
    return {
        "removals": [
            [m.story_id, m.depends_on_story_id, m.kind.value]
            for m in plan.removals
        ],
        "additions": [
            [m.story_id, m.depends_on_story_id, m.kind.value]
            for m in plan.additions
        ],
    }


def _deserialize_rebinding_plan(
    raw: object, successor_ids: tuple[str, ...]
) -> RebindingPlan:
    """Reconstruct a checkpointed edge-mutation plan, replaying it verbatim.

    Fails closed on a structurally corrupt checkpoint or one whose addition
    targets are not the created successors.
    """
    try:
        if not isinstance(raw, dict):
            raise TypeError("rebinding_plan is not a mapping")
        removals = tuple(
            EdgeMutation(
                story_id=str(story_id),
                depends_on_story_id=str(depends_on),
                kind=StoryDependencyKind(str(kind)),
            )
            for story_id, depends_on, kind in raw.get("removals") or ()
        )
        additions = tuple(
            EdgeMutation(
                story_id=str(story_id),
                depends_on_story_id=str(depends_on),
                kind=StoryDependencyKind(str(kind)),
            )
            for story_id, depends_on, kind in raw.get("additions") or ()
        )
    except (TypeError, ValueError) as exc:
        raise StorySplitError(
            "resume rejected: split fence rebinding checkpoint is malformed "
            f"— partial state is inconsistent ({exc})",
        ) from exc
    allowed_targets = set(successor_ids)
    for addition in additions:
        if addition.depends_on_story_id not in allowed_targets:
            raise StorySplitError(
                "resume rejected: split fence rebinding checkpoint targets "
                f"{addition.depends_on_story_id!r} which is not a created "
                "successor — partial state is inconsistent",
            )
    return RebindingPlan(removals=removals, additions=additions)


__all__ = [
    "SPLIT_CANCEL_REASON",
    "SplitSourceState",
    "StorySplitError",
    "StorySplitRequest",
    "StorySplitResult",
    "StorySplitService",
]
