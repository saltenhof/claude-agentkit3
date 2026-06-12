"""Story application service (story_context_manager BC).

This is the authoritative service for all Story lifecycle mutations.
Implements FK-91 §91.1a and formal.frontend-contracts.commands.

Mutation surface:
  - ``create_story``: POST /v1/stories
  - ``update_story_fields``: PATCH /v1/stories/{id}
  - ``approve_story``: POST /v1/stories/{id}/approve
  - ``reject_story``: POST /v1/stories/{id}/reject
  - ``cancel_story``: POST /v1/stories/{id}/cancel
  - ``set_story_field``: PUT /v1/stories/{id}/fields/{field_key}

Pipeline-only internal operations (not callable from frontend):
  - ``begin_progress``: Approved -> In Progress (FK-22 §22.4.3)
  - ``complete_story``: In Progress -> Done (formal.story-workflow.invariant.completion_only_after_closure)

Read operations:
  - ``get_story``: GET /v1/stories/{id}
  - ``get_story_detail``: GET /v1/stories/{id} (with spec)
  - ``list_stories``: GET /v1/stories
  - ``search_stories``: GET /v1/projects/{key}/stories/search
  - ``get_story_fields``: GET /v1/stories/{id}/fields
  - ``get_dependencies``: dependency reads

All mutating methods enforce op_id idempotency (FK-91 §91.1a Rule 5).
All status transitions are strictly validated (formal.frontend-contracts.invariant).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.core_types import StorySize
from agentkit.story_context_manager.errors import (
    ForbiddenError,
    InvalidStatusTransitionError,
    StoryNotFoundError,
    StoryProjectNotFoundError,
    StoryValidationError,
)
from agentkit.story_context_manager.idempotency import IdempotencyKeyStore
from agentkit.story_context_manager.patch_handlers import (
    _apply_updates,
    _get_project_repos,
)
from agentkit.story_context_manager.reset_transitions import (
    ResetTransitionMixin,
    is_story_runnable_status,
)
from agentkit.story_context_manager.story_model import (
    ChangeImpact,
    ConceptQuality,
    CreateStoryInput,
    RiskLevel,
    Story,
    StorySpecification,
    StoryStatus,
    WireStoryMode,
    WireStoryType,
    check_fast_mode_story_type,
)
from agentkit.story_context_manager.wire_adapter import (
    FORBIDDEN_PATCH_FIELDS,
    check_forbidden_fields,
    story_to_wire_summary,
    validate_repos_against_project,
    validate_repos_not_empty,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.execution_planning.repository import StoryDependencyRepository
    from agentkit.project_management.repository import ProjectRepository
    from agentkit.story_context_manager.idempotency import IdempotencyKeyRepository
    from agentkit.story_context_manager.story_repository import StoryRepository


# ---------------------------------------------------------------------------
# Allowed status transitions (canonical table from story.md §2.1.9)
# ---------------------------------------------------------------------------

# Maps (from_status, to_status) -> True for allowed transitions
_ALLOWED_TRANSITIONS: frozenset[tuple[StoryStatus, StoryStatus]] = frozenset({
    # Frontend-driven
    (StoryStatus.BACKLOG, StoryStatus.APPROVED),      # approve
    (StoryStatus.APPROVED, StoryStatus.BACKLOG),      # reject
    (StoryStatus.BACKLOG, StoryStatus.CANCELLED),     # cancel
    (StoryStatus.APPROVED, StoryStatus.CANCELLED),    # cancel
    # Pipeline-only
    (StoryStatus.APPROVED, StoryStatus.IN_PROGRESS),  # begin_progress
    (StoryStatus.IN_PROGRESS, StoryStatus.DONE),      # complete_story
    # AG3-071 administrative Story-Reset axis (FK-53 §53.7.2/§53.8/§53.9.2). These
    # are the ONLY legal reset transitions; the reset axis is deliberately NOT
    # wired into cancel/begin_progress/complete (it is driven by StoryResetService).
    (StoryStatus.IN_PROGRESS, StoryStatus.RESETTING),     # fence (Schritt 2)
    (StoryStatus.RESETTING, StoryStatus.IN_PROGRESS),     # success -> restartable base
    (StoryStatus.RESETTING, StoryStatus.RESET_FAILED),    # aborted reset
    (StoryStatus.RESET_FAILED, StoryStatus.RESETTING),    # resume same reset
})

_TERMINAL_STATUSES: frozenset[StoryStatus] = frozenset({
    StoryStatus.DONE,
    StoryStatus.CANCELLED,
})

# ``is_story_runnable_status`` (and its ``_RESET_NON_RUNNABLE_STATUSES`` table)
# is re-exported from this module so the Story-Reset admission helper keeps its
# historical import path. The owning unit is ``reset_transitions`` (AG3-071).
__all__ = ["StoryService", "is_story_runnable_status"]


def _check_transition(
    current: StoryStatus,
    target: StoryStatus,
    *,
    context: str = "",
) -> None:
    """Raise InvalidStatusTransitionError if transition is not allowed.

    Args:
        current: Current story status.
        target: Requested target status.
        context: Optional human-readable context for error messages.
    """
    if (current, target) not in _ALLOWED_TRANSITIONS:
        # Special-case inflight cancel to give a clearer error message
        if current is StoryStatus.IN_PROGRESS and target is StoryStatus.CANCELLED:
            raise InvalidStatusTransitionError(
                "A story that is In Progress cannot be directly cancelled. "
                "Use Story-Reset (FK-53) or Story-Exit (FK-58) for the "
                "official path.",
                detail={
                    "current_status": current.value,
                    "target_status": target.value,
                    "hint": "Use story-reset or story-exit",
                },
            )
        raise InvalidStatusTransitionError(
            f"Transition from {current.value!r} to {target.value!r} is "
            f"not permitted{': ' + context if context else ''}.",
            detail={
                "current_status": current.value,
                "target_status": target.value,
            },
        )


# ---------------------------------------------------------------------------
# StoryService
# ---------------------------------------------------------------------------


class StoryService(ResetTransitionMixin):
    """Authoritative story lifecycle service for story_context_manager BC.

    Dependencies injected at construction time following ARCH-26.
    All defaults are real implementations, not mocks.

    Args:
        story_repository: Story stammdaten persistence.
        project_repository: Project entity access (for archived/repos check).
        idempotency_repository: Idempotency key persistence.
        dependency_repository: Story dependency-edge read port (execution_planning
            ``StoryDependencyRepository``).  Used by
            ``list_stories_with_dependencies`` to materialize the
            ``Story.dependencies`` read-model join.  Defaults to the real
            ``StateBackendStoryDependencyRepository``.
        event_emitter: Callable that emits story_upserted events. Receives
            ``(project_key, story_display_id, wire_summary_dict)`` as args.
    """

    def __init__(
        self,
        *,
        story_repository: StoryRepository | None = None,
        project_repository: ProjectRepository | None = None,
        idempotency_repository: IdempotencyKeyRepository | None = None,
        dependency_repository: StoryDependencyRepository | None = None,
        event_emitter: Callable[[str, str, dict[str, object]], None] | None = None,
    ) -> None:
        if story_repository is None:
            from agentkit.state_backend.store.story_repository import (
                StateBackendStoryRepository,
            )
            story_repository = StateBackendStoryRepository()
        if idempotency_repository is None:
            from agentkit.state_backend.store.story_repository import (
                StateBackendIdempotencyKeyRepository,
            )
            idempotency_repository = StateBackendIdempotencyKeyRepository()
        if project_repository is None:
            from agentkit.state_backend.store.project_management_repository import (
                StateBackendProjectRepository,
            )
            project_repository = StateBackendProjectRepository()
        if dependency_repository is None:
            from agentkit.state_backend.store.story_dependency_repository import (
                StateBackendStoryDependencyRepository,
            )
            dependency_repository = StateBackendStoryDependencyRepository()

        self._story_repo: StoryRepository = story_repository
        self._project_repo: ProjectRepository = project_repository
        self._dependency_repo: StoryDependencyRepository = dependency_repository
        self._idempotency = IdempotencyKeyStore(idempotency_repository)
        self._emit = event_emitter if event_emitter is not None else _logging_emitter

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_story(self, story_display_id: str) -> Story | None:
        """Return a Story by display ID, or None if not found.

        Args:
            story_display_id: The story display ID (e.g. ``"AK3-042"``).
        """
        return self._story_repo.get_by_display_id(story_display_id)

    def get_story_or_raise(self, story_display_id: str) -> Story:
        """Return a Story or raise ``StoryNotFoundError`` (404).

        Args:
            story_display_id: The story display ID.

        Raises:
            ``StoryNotFoundError`` if the story does not exist.
        """
        story = self._story_repo.get_by_display_id(story_display_id)
        if story is None:
            raise StoryNotFoundError(
                f"Story {story_display_id!r} not found",
                detail={"story_display_id": story_display_id},
            )
        return story

    def get_story_detail(
        self, story_display_id: str
    ) -> tuple[Story, StorySpecification | None] | None:
        """Return a (Story, StorySpecification|None) tuple or None."""
        story = self._story_repo.get_by_display_id(story_display_id)
        if story is None:
            return None
        spec = self._story_repo.get_specification(story.story_uuid)
        return story, spec

    def list_stories(self, project_key: str) -> list[Story]:
        """Return all Stories for a project, ordered by story_number."""
        return self._story_repo.list_for_project(project_key)

    def list_stories_with_dependencies(self, project_key: str) -> list[Story]:
        """Return all Stories with their ``dependencies`` read-model join filled.

        ``Story.dependencies`` is a read-model join that does NOT live in the
        ``stories`` table; the authoritative source is the
        ``StoryDependencyRepository`` (execution_planning dependency edges).
        The plain :meth:`list_stories` read path returns stories with an empty
        ``dependencies`` list, which is correct for consumers that do not need
        the join but wrong for readiness-derived aggregations.

        This method is the authoritative dependency-aware Story read used by
        cross-BC consumers (e.g. project-management ``story_counters``).  Each
        story's ``dependencies`` is populated with the sorted display IDs of
        its direct predecessors (``depends_on_story_id`` of every edge whose
        ``story_id`` matches), so the resulting corpus satisfies
        ``frontend-contracts.invariant.counters_classification`` end to end.

        All dependency kinds are treated as predecessors, consistent with the
        execution-planning ``DependencyGraph`` predecessor semantics; kind-aware
        soft/hard distinctions are an execution-planning readiness concern and
        are out of scope for the wire-counter join.

        Args:
            project_key: Project key to scope the read.

        Returns:
            The project's stories (ordered by ``story_number``), each with its
            ``dependencies`` list materialized from the dependency store.
        """
        stories = self._story_repo.list_for_project(project_key)
        predecessors: dict[str, list[str]] = {}
        for edge in self._dependency_repo.list_for_project(project_key):
            predecessors.setdefault(edge.story_id, []).append(
                edge.depends_on_story_id
            )
        for story in stories:
            deps = predecessors.get(story.story_display_id)
            if deps:
                story.dependencies = sorted(set(deps))
        return stories

    def list_active_repos(self, project_key: str) -> set[str]:
        """Return the set of repositories referenced by any ``In Progress`` story.

        Used by the project-management PATCH-configuration guard
        (AG3-020 §2.1.3, AC4) to fail-closed when an operator tries to
        remove a repo that is still in active use.

        Args:
            project_key: Project key to scope the lookup.

        Returns:
            Set of repo identifiers from ``participating_repos`` across all
            ``In Progress`` stories in this project.  Empty set when no
            story is active.
        """
        active: set[str] = set()
        for story in self._story_repo.list_for_project(project_key):
            if story.status is StoryStatus.IN_PROGRESS:
                active.update(story.participating_repos)
        return active

    def search_stories(self, project_key: str, query: str) -> list[Story]:
        """Search Stories by query string across display_id, title, repos, module, epic."""
        return self._story_repo.search(project_key, query)

    def get_story_fields(self, story_display_id: str) -> dict[str, object]:
        """Return all story fields as a flat map.

        Args:
            story_display_id: Story display ID.

        Raises:
            ``StoryNotFoundError`` if the story does not exist.
        """
        story = self.get_story_or_raise(story_display_id)
        return story_to_wire_summary(story)

    # ------------------------------------------------------------------
    # create_story (POST /v1/stories)
    # ------------------------------------------------------------------

    def create_story(
        self,
        request: CreateStoryInput,
        *,
        op_id: str,
        correlation_id: str = "",
    ) -> Story:
        """Create a new Story in Backlog status.

        Implements FK-91 §91.1a and formal.frontend-contracts.command.create_story.
        Steps (story.md §2.1.15):
          1. Lookup Project (ProjectRepository).
          2. Archived project? -> forbidden (403).
          3. Validate repos against project configuration.
          4. Allocate story_number atomically.
          5. Materialize story_display_id.
          6. Persist Story + Specification.
          7. Persist idempotency record.
          8. Emit story_upserted.
          9. Return story_summary wire payload.

        Args:
            request: ``CreateStoryInput`` carrying all stammdaten fields.
                Wire-level validation (empty title/repos, enum coercion) is
                enforced by Pydantic at construction time.
            op_id: Idempotency key (required).
            correlation_id: Correlation ID for propagation.

        Returns:
            The created Story.

        Raises:
            ``StoryProjectNotFoundError`` (404).
            ``ForbiddenError`` (403) if project is archived.
            ``StoryValidationError`` (400) for repo-vs-project violations.
            ``IdempotencyMismatchError`` (409).
        """
        body = _create_story_body(request, op_id)
        cached, cached_payload = self._idempotency.check(op_id, body)
        if cached:
            return _resolve_cached_create(self._story_repo, cached_payload)

        project = self._project_repo.get(request.project_key)
        if project is None:
            raise StoryProjectNotFoundError(
                f"Project {request.project_key!r} does not exist",
                detail={"project_key": request.project_key},
            )
        if project.archived_at is not None:
            raise ForbiddenError(
                f"Project {request.project_key!r} is archived",
                detail={"project_key": request.project_key},
            )

        validate_repos_not_empty(request.repos)
        allowed_repos = _get_project_repos(project)
        if allowed_repos:
            validate_repos_against_project(request.repos, allowed_repos)

        # story_number / story_display_id are placeholders patched by create_story_atomic.
        story = Story(
            project_key=request.project_key,
            story_number=1,
            story_display_id="",
            title=request.title,
            story_type=request.story_type,
            status=StoryStatus.BACKLOG,
            size=request.size,
            mode=request.mode,
            epic=request.epic,
            module=request.module,
            participating_repos=list(request.repos),
            change_impact=request.change_impact,
            concept_quality=request.concept_quality,
            owner=request.owner,
            risk=request.risk,
            labels=list(request.labels),
            # AG3-057 ERROR-2 fix: persist Trigger 3 input from CreateStoryInput.
            new_structures=request.new_structures,
            # AG3-068 (FK-21 §21.12): persist the VectorDB-conflict producer flag.
            vectordb_conflict_resolved=request.vectordb_conflict_resolved,
            created_at=datetime.now(UTC),
        )
        default_spec = StorySpecification(need=None, solution=None, acceptance=[])

        self._story_repo.create_story_atomic(
            story,
            default_spec,
            story_id_prefix=project.story_id_prefix,
        )

        wire_summary = story_to_wire_summary(story)
        self._idempotency.record(
            op_id,
            body,
            _story_to_internal_snapshot(story),
            correlation_id=correlation_id,
        )
        self._emit(request.project_key, story.story_display_id, wire_summary)
        return story

    # ------------------------------------------------------------------
    # update_story_fields (PATCH /v1/stories/{id})
    # ------------------------------------------------------------------

    def update_story_fields(
        self,
        story_display_id: str,
        *,
        updates: dict[str, object],
        op_id: str,
        correlation_id: str = "",
    ) -> Story:
        """Update story stammdaten fields.

        Implements PATCH /v1/stories/{id}.
        Forbidden fields: status, created_at, completed_at (422).
        If repos is updated: min 1 entry required, must be in project config.

        Args:
            story_display_id: Story to update.
            updates: Dict of field names to new values (wire names).
            op_id: Idempotency key.
            correlation_id: Correlation ID.

        Returns:
            The updated Story.

        Raises:
            ``StoryNotFoundError`` (404).
            ``ForbiddenError`` (403) if project archived.
            ``ForbiddenFieldError`` (422) if forbidden field in updates.
            ``StoryValidationError`` (400).
            ``IdempotencyMismatchError`` (409).
        """
        # Check forbidden fields first (before idempotency)
        check_forbidden_fields(updates)

        body: dict[str, object] = {
            "story_id": story_display_id,
            **updates,
            "op_id": op_id,
        }
        cached, cached_payload = self._idempotency.check(op_id, body)
        if cached:
            # Befund 5: return CACHED snapshot, not live DB read.
            assert cached_payload is not None
            cached_story = _story_from_cached_payload(cached_payload)
            if cached_story is not None:
                return cached_story
            cached_id = str(cached_payload.get("story_id", story_display_id))
            story = self._story_repo.get_by_display_id(cached_id)
            if story is not None:
                return story
            raise StoryNotFoundError(f"Story {story_display_id!r} not found")

        story = self.get_story_or_raise(story_display_id)

        # Check project is not archived
        project = self._project_repo.get(story.project_key)
        if project is not None and project.archived_at is not None:
            raise ForbiddenError(
                f"Project {story.project_key!r} is archived",
                detail={"project_key": story.project_key},
            )

        # Apply updates
        story = _apply_updates(story, updates, project)
        # FIX-1 (FK-24 §24.3.3, AC7): a PATCH that sets mode/type must not leave a
        # fast story on a non-code-producing type. ``Story`` is mutated in place
        # (frozen=False), so the model_validator does not re-run automatically;
        # re-validate the post-patch combination fail-closed (wire boundary -> a
        # typed 400, not a bare ValueError).
        try:
            check_fast_mode_story_type(story.mode, story.story_type)
        except ValueError as exc:
            raise StoryValidationError(
                str(exc), detail={"field": "mode", "story_type": story.story_type.value}
            ) from exc

        self._story_repo.save(story)

        wire_summary = story_to_wire_summary(story)
        self._idempotency.record(
            op_id, body, _story_to_internal_snapshot(story),
            correlation_id=correlation_id,
        )
        self._emit(story.project_key, story_display_id, wire_summary)

        return story

    # ------------------------------------------------------------------
    # approve_story (POST /v1/stories/{id}/approve)
    # ------------------------------------------------------------------

    def approve_story(
        self,
        story_display_id: str,
        *,
        op_id: str,
        correlation_id: str = "",
    ) -> Story:
        """Approve a story (Backlog -> Approved).

        Args:
            story_display_id: Story to approve.
            op_id: Idempotency key.
            correlation_id: Correlation ID.

        Returns:
            Updated Story.

        Raises:
            ``StoryNotFoundError`` (404).
            ``InvalidStatusTransitionError`` (422) if not in Backlog.
            ``ForbiddenError`` (403) if project archived.
            ``IdempotencyMismatchError`` (409).
        """
        return self._status_transition(
            story_display_id,
            target=StoryStatus.APPROVED,
            op_id=op_id,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # reject_story (POST /v1/stories/{id}/reject)
    # ------------------------------------------------------------------

    def reject_story(
        self,
        story_display_id: str,
        *,
        op_id: str,
        correlation_id: str = "",
    ) -> Story:
        """Reject a story (Approved -> Backlog).

        Args:
            story_display_id: Story to reject.
            op_id: Idempotency key.
            correlation_id: Correlation ID.

        Returns:
            Updated Story.

        Raises:
            ``StoryNotFoundError`` (404).
            ``InvalidStatusTransitionError`` (422) if not in Approved.
            ``ForbiddenError`` (403) if project archived.
            ``IdempotencyMismatchError`` (409).
        """
        return self._status_transition(
            story_display_id,
            target=StoryStatus.BACKLOG,
            op_id=op_id,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # cancel_story (POST /v1/stories/{id}/cancel)
    # ------------------------------------------------------------------

    def cancel_story(
        self,
        story_display_id: str,
        *,
        reason: str | None = None,
        op_id: str,
        correlation_id: str = "",
    ) -> Story:
        """Cancel a story (Backlog|Approved -> Cancelled).

        In Progress or Done -> invalid_transition (422).

        Args:
            story_display_id: Story to cancel.
            reason: Optional cancellation reason (stored in blocker field).
            op_id: Idempotency key.
            correlation_id: Correlation ID.

        Returns:
            Updated Story.

        Raises:
            ``StoryNotFoundError`` (404).
            ``InvalidStatusTransitionError`` (422).
            ``ForbiddenError`` (403) if project archived.
            ``IdempotencyMismatchError`` (409).
        """
        body: dict[str, object] = {
            "story_id": story_display_id,
            "reason": reason,
            "op_id": op_id,
        }
        cached, cached_payload = self._idempotency.check(op_id, body)
        if cached:
            # Befund 5: return CACHED snapshot, not live DB read.
            assert cached_payload is not None
            cached_story = _story_from_cached_payload(cached_payload)
            if cached_story is not None:
                return cached_story
            cached_id = str(cached_payload.get("story_id", story_display_id))
            story = self._story_repo.get_by_display_id(cached_id)
            if story is not None:
                return story
            raise StoryNotFoundError(f"Story {story_display_id!r} not found")

        story = self.get_story_or_raise(story_display_id)
        _check_transition(story.status, StoryStatus.CANCELLED)

        project = self._project_repo.get(story.project_key)
        if project is not None and project.archived_at is not None:
            raise ForbiddenError(
                f"Project {story.project_key!r} is archived",
                detail={"project_key": story.project_key},
            )

        story.status = StoryStatus.CANCELLED
        if reason:
            story.blocker = reason
        self._story_repo.save(story)

        wire_summary = story_to_wire_summary(story)
        self._idempotency.record(
            op_id, body, _story_to_internal_snapshot(story),
            correlation_id=correlation_id,
        )
        self._emit(story.project_key, story_display_id, wire_summary)
        return story

    # ------------------------------------------------------------------
    # set_story_field (PUT /v1/stories/{id}/fields/{field_key})
    # ------------------------------------------------------------------

    def set_story_field(
        self,
        story_display_id: str,
        field_key: str,
        value: object,
        *,
        op_id: str,
        correlation_id: str = "",
    ) -> Story:
        """Set a single story field.

        Enforces the same forbidden_inputs as update_story_fields.

        Args:
            story_display_id: Story to update.
            field_key: Wire field name to update.
            value: New value.
            op_id: Idempotency key.
            correlation_id: Correlation ID.

        Returns:
            Updated Story.

        Raises:
            ``ForbiddenFieldError`` (422) for forbidden fields.
            ``StoryNotFoundError`` (404).
            ``StoryValidationError`` (400).
            ``IdempotencyMismatchError`` (409).
        """
        if field_key in FORBIDDEN_PATCH_FIELDS:
            from agentkit.story_context_manager.errors import ForbiddenFieldError
            raise ForbiddenFieldError(
                f"Field {field_key!r} is forbidden; "
                "use dedicated approve/reject/cancel endpoints for status changes",
                detail={"forbidden_field": field_key},
            )
        return self.update_story_fields(
            story_display_id,
            updates={field_key: value},
            op_id=op_id,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Pipeline-only operations
    # ------------------------------------------------------------------

    def begin_progress(self, story_display_id: str) -> Story:
        """Set story to In Progress (Approved -> In Progress).

        Called by Setup Phase after successful completion (FK-22 §22.4.3).
        NOT callable from the frontend. No op_id required (pipeline-internal).

        Args:
            story_display_id: Story to transition.

        Returns:
            Updated Story.

        Raises:
            ``StoryNotFoundError`` (404).
            ``InvalidStatusTransitionError`` (422) if not in Approved.
        """
        story = self.get_story_or_raise(story_display_id)
        _check_transition(story.status, StoryStatus.IN_PROGRESS, context="begin_progress")
        story.status = StoryStatus.IN_PROGRESS
        self._story_repo.save(story)
        wire_summary = story_to_wire_summary(story)
        self._emit(story.project_key, story_display_id, wire_summary)
        return story

    def complete_story(self, story_display_id: str) -> Story:
        """Set story to Done (In Progress -> Done).

        Called by Closure Sequence after successful closure
        (formal.story-workflow.invariant.completion_only_after_closure).
        NOT callable from the frontend.

        Args:
            story_display_id: Story to complete.

        Returns:
            Updated Story.

        Raises:
            ``StoryNotFoundError`` (404).
            ``InvalidStatusTransitionError`` (422) if not In Progress.
        """
        story = self.get_story_or_raise(story_display_id)
        _check_transition(story.status, StoryStatus.DONE, context="complete_story")
        story.status = StoryStatus.DONE
        story.completed_at = datetime.now(UTC)
        self._story_repo.save(story)
        wire_summary = story_to_wire_summary(story)
        self._emit(story.project_key, story_display_id, wire_summary)
        return story

    def administratively_cancel_for_story_exit(
        self,
        story_display_id: str,
        *,
        story_exit_record: object,
        story_exit_operation_committed: bool,
        principal: object,
        op_id: str,
        correlation_id: str = "",
    ) -> Story:
        """Administratively cancel an In Progress story for FK-58 story-exit.

        This is the dedicated story-exit transition. It deliberately does not add
        ``In Progress -> Cancelled`` to the generic transition table, so the
        frontend ``cancel_story`` surface remains fail-closed for in-flight
        stories.
        """

        if str(principal) != "human_cli":
            raise ForbiddenError(
                "Story-Exit administrative cancellation requires human_cli",
                detail={"principal": str(principal)},
            )
        if not story_exit_operation_committed:
            raise ForbiddenError(
                "Story-Exit administrative cancellation requires a committed "
                "story_exit fence operation",
                detail={"story_id": story_display_id, "op_id": op_id},
            )
        if not _valid_story_exit_record(story_exit_record, story_display_id, op_id):
            raise StoryValidationError(
                "Invalid StoryExitRecord for administrative cancellation",
                detail={"story_id": story_display_id, "op_id": op_id},
            )

        body: dict[str, object] = {
            "story_id": story_display_id,
            "op_id": op_id,
            "exit_id": str(getattr(story_exit_record, "exit_id", "")),
            "operation": "story_exit_admin_cancel",
        }
        cached, cached_payload = self._idempotency.check(op_id, body)
        if cached:
            assert cached_payload is not None
            cached_story = _story_from_cached_payload(cached_payload)
            if cached_story is not None:
                return cached_story

        story = self.get_story_or_raise(story_display_id)
        if story.status is StoryStatus.CANCELLED:
            self._idempotency.record(
                op_id,
                body,
                _story_to_internal_snapshot(story),
                correlation_id=correlation_id,
            )
            return story
        if story.status is not StoryStatus.IN_PROGRESS:
            raise InvalidStatusTransitionError(
                "Story-Exit administrative cancellation is only legal from "
                "In Progress or as an idempotent no-op on Cancelled.",
                detail={
                    "current_status": story.status.value,
                    "target_status": StoryStatus.CANCELLED.value,
                },
            )

        project = self._project_repo.get(story.project_key)
        if project is not None and project.archived_at is not None:
            raise ForbiddenError(
                f"Project {story.project_key!r} is archived",
                detail={"project_key": story.project_key},
            )

        story.status = StoryStatus.CANCELLED
        story.blocker = f"Story-Exit viability handoff ({op_id})"
        self._story_repo.save(story)
        wire_summary = story_to_wire_summary(story)
        self._idempotency.record(
            op_id, body, _story_to_internal_snapshot(story), correlation_id=correlation_id
        )
        self._emit(story.project_key, story_display_id, wire_summary)
        return story

    def administratively_cancel_for_story_split(
        self,
        story_display_id: str,
        *,
        story_split_record: object,
        story_split_operation_committed: bool,
        principal: object,
        op_id: str,
        correlation_id: str = "",
    ) -> Story:
        """Administratively cancel an In Progress story for an FK-54 story split.

        This is the dedicated administrative split-cancel transition (§54.8.7). It
        deliberately does NOT add ``In Progress -> Cancelled`` to the generic
        ``_ALLOWED_TRANSITIONS`` table, so the frontend ``cancel_story`` surface
        stays fail-closed for in-flight stories and this path is the ONLY way an
        in-progress source story reaches ``Cancelled`` via a split. It does not go
        through closure and does not reuse the ``cancel_story`` guard.

        Fail-closed preconditions:
          - ``principal`` must be ``human_cli`` (the human-started CLI path);
          - ``story_split_operation_committed`` must be ``True`` (the split fence
            is registered);
          - ``story_split_record`` must be a structurally valid split record for
            this story / ``op_id`` carrying ``exit_class=scope_split`` and
            ``terminal_state=Cancelled``.

        Args:
            story_display_id: The source story to cancel.
            story_split_record: The ``StorySplitRecord`` audit evidence.
            story_split_operation_committed: Whether the split fence is committed.
            principal: The acting principal (must be ``human_cli``).
            op_id: The split_id used as the idempotency key.
            correlation_id: Correlation ID for propagation.

        Returns:
            The cancelled (or idempotent no-op) Story.

        Raises:
            ForbiddenError: When principal/fence preconditions fail.
            StoryValidationError: When the split record is invalid.
            InvalidStatusTransitionError: When the story is not In Progress (and
                not already Cancelled).
        """
        if str(principal) != "human_cli":
            raise ForbiddenError(
                "Story-Split administrative cancellation requires human_cli",
                detail={"principal": str(principal)},
            )
        if not story_split_operation_committed:
            raise ForbiddenError(
                "Story-Split administrative cancellation requires a committed "
                "split fence operation",
                detail={"story_id": story_display_id, "op_id": op_id},
            )
        if not _valid_story_split_record(story_split_record, story_display_id, op_id):
            raise StoryValidationError(
                "Invalid StorySplitRecord for administrative cancellation",
                detail={"story_id": story_display_id, "op_id": op_id},
            )

        body: dict[str, object] = {
            "story_id": story_display_id,
            "op_id": op_id,
            "split_id": str(getattr(story_split_record, "split_id", "")),
            "operation": "story_split_admin_cancel",
        }
        cached, cached_payload = self._idempotency.check(op_id, body)
        if cached:
            assert cached_payload is not None
            cached_story = _story_from_cached_payload(cached_payload)
            if cached_story is not None:
                return cached_story

        story = self.get_story_or_raise(story_display_id)
        if story.status is StoryStatus.CANCELLED:
            self._idempotency.record(
                op_id,
                body,
                _story_to_internal_snapshot(story),
                correlation_id=correlation_id,
            )
            return story
        if story.status is not StoryStatus.IN_PROGRESS:
            raise InvalidStatusTransitionError(
                "Story-Split administrative cancellation is only legal from "
                "In Progress or as an idempotent no-op on Cancelled.",
                detail={
                    "current_status": story.status.value,
                    "target_status": StoryStatus.CANCELLED.value,
                },
            )

        project = self._project_repo.get(story.project_key)
        if project is not None and project.archived_at is not None:
            raise ForbiddenError(
                f"Project {story.project_key!r} is archived",
                detail={"project_key": story.project_key},
            )

        story.status = StoryStatus.CANCELLED
        story.blocker = f"Story-Split scope_split ({op_id})"
        self._story_repo.save(story)
        wire_summary = story_to_wire_summary(story)
        self._idempotency.record(
            op_id, body, _story_to_internal_snapshot(story), correlation_id=correlation_id
        )
        self._emit(story.project_key, story_display_id, wire_summary)
        return story

    def materialize_split_lineage(
        self,
        *,
        source_story_id: str,
        successor_ids: tuple[str, ...],
    ) -> None:
        """Persist the FK-54 §54.8.5 split lineage onto the REAL stories.

        Writes ``split_successors`` (the real, allocated successor ids) onto the
        source story and ``split_from`` (the source id) onto EACH successor. The
        ids passed here are the authoritative ``StoryService`` display ids — never
        the plan-local reference ids. Idempotent: re-running with the same inputs
        leaves the same lineage.

        This is the authoritative materialization step for
        ``formal.story-split.entities`` ``story_lineage`` and AC7. It is a pure
        stammdaten write (no status transition); the administrative cancel of the
        source is a separate step.

        Args:
            source_story_id: The cancelled source story display id.
            successor_ids: The real successor display ids (creation order).

        Raises:
            StoryNotFoundError: When the source or a successor does not exist.
        """
        source = self.get_story_or_raise(source_story_id)
        source.split_successors = list(successor_ids)
        self._story_repo.save(source)
        self._emit(
            source.project_key,
            source_story_id,
            story_to_wire_summary(source),
        )
        for successor_id in successor_ids:
            successor = self.get_story_or_raise(successor_id)
            successor.split_from = source_story_id
            self._story_repo.save(successor)
            self._emit(
                successor.project_key,
                successor_id,
                story_to_wire_summary(successor),
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _status_transition(
        self,
        story_display_id: str,
        *,
        target: StoryStatus,
        op_id: str,
        correlation_id: str = "",
    ) -> Story:
        """Generic status transition with idempotency check."""
        body: dict[str, object] = {
            "story_id": story_display_id,
            "target_status": target.value,
            "op_id": op_id,
        }
        cached, cached_payload = self._idempotency.check(op_id, body)
        if cached:
            # Befund 5: return CACHED snapshot, not live DB read.
            assert cached_payload is not None
            cached_story = _story_from_cached_payload(cached_payload)
            if cached_story is not None:
                return cached_story
            cached_id = str(cached_payload.get("story_id", story_display_id))
            story = self._story_repo.get_by_display_id(cached_id)
            if story is not None:
                return story
            raise StoryNotFoundError(f"Story {story_display_id!r} not found")

        story = self.get_story_or_raise(story_display_id)
        _check_transition(story.status, target)

        project = self._project_repo.get(story.project_key)
        if project is not None and project.archived_at is not None:
            raise ForbiddenError(
                f"Project {story.project_key!r} is archived",
                detail={"project_key": story.project_key},
            )

        story.status = target
        self._story_repo.save(story)

        wire_summary = story_to_wire_summary(story)
        self._idempotency.record(
            op_id, body, _story_to_internal_snapshot(story),
            correlation_id=correlation_id,
        )
        self._emit(story.project_key, story_display_id, wire_summary)
        return story


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _null_emitter(
    project_key: str,
    story_display_id: str,
    wire_summary: dict[str, object],
) -> None:
    """No-op event emitter. Use only in isolated unit tests that do not test events."""
    _ = project_key, story_display_id, wire_summary


_story_lifecycle_logger = __import__("logging").getLogger(
    "agentkit.story_context_manager.story_lifecycle"
)


def _logging_emitter(
    project_key: str,
    story_display_id: str,
    wire_summary: dict[str, object],
) -> None:
    """Default story_upserted emitter that logs the mutation.

    Records a structured INFO log entry for every story mutation.
    This is the default for production HTTP paths until a dedicated
    SSE/telemetry story_upserted projection is wired (FK-91 §91.8).

    Args:
        project_key: Project the story belongs to.
        story_display_id: Story display ID (e.g. ``"AK3-042"``).
        wire_summary: Wire-format story summary dict.
    """
    _story_lifecycle_logger.info(
        "story_upserted project=%s story_id=%s status=%s",
        project_key,
        story_display_id,
        wire_summary.get("status", "?"),
    )


def _create_story_body(request: CreateStoryInput, op_id: str) -> dict[str, object]:
    """Build the canonical idempotency body for ``create_story``."""
    return {
        "project_key": request.project_key,
        "title": request.title,
        "type": request.story_type.value,
        "repos": sorted(request.repos),
        "epic": request.epic,
        "module": request.module,
        "size": request.size.value,
        "mode": request.mode.value if request.mode else None,
        "change_impact": request.change_impact.value,
        "concept_quality": request.concept_quality.value,
        "owner": request.owner,
        "risk": request.risk.value,
        "labels": sorted(request.labels),
        # AG3-057 ERROR-2 fix: include Trigger 3 input in idempotency snapshot so
        # that a replay with a different new_structures value is caught as a mismatch.
        "new_structures": request.new_structures,
        # AG3-068: include the VectorDB-conflict producer flag so a replay with a
        # different value is caught as a mismatch.
        "vectordb_conflict_resolved": request.vectordb_conflict_resolved,
        "op_id": op_id,
    }


def _story_to_internal_snapshot(story: Story) -> dict[str, object]:
    """Serialise a Story to a full internal snapshot for idempotency records.

    Unlike ``story_to_wire_summary``, this snapshot includes ``story_uuid``
    and ``story_number`` so that replay can reconstruct the exact Story
    without a live DB read (Befund 5).

    Args:
        story: The Story entity to snapshot.

    Returns:
        A JSON-serialisable dict with all Story fields.
    """
    from agentkit.story_context_manager.wire_adapter import story_to_wire_summary

    wire = story_to_wire_summary(story)
    return {
        **wire,
        "_story_uuid": str(story.story_uuid),
        "_story_number": story.story_number,
        # AG3-057 residual fix: new_structures is an internal Trigger-3 flag, not
        # part of the public wire summary.  Persist it explicitly so that
        # _story_from_cached_payload() can reconstruct the field faithfully on
        # idempotent replay (otherwise cached replay always returns False).
        "new_structures": story.new_structures,
        # AG3-068: vectordb_conflict_resolved is an internal producer flag, not
        # part of the public wire summary; persist it explicitly so cached replay
        # reconstructs it faithfully.
        "vectordb_conflict_resolved": story.vectordb_conflict_resolved,
    }


def _to_list(value: object) -> list[object]:
    """Return ``value`` as a list, or an empty list if not iterable / None."""
    if isinstance(value, list):
        return value
    return []


def _story_from_cached_payload(payload: dict[str, object]) -> Story | None:
    """Reconstruct a Story from an idempotency result_payload snapshot.

    Returns ``None`` if the payload does not contain the required internal
    fields (legacy records without ``_story_uuid`` fall back to DB read).

    Args:
        payload: The ``result_payload`` from an IdempotencyRecord.

    Returns:
        Reconstructed Story, or ``None`` if snapshot is incomplete.
    """
    from datetime import datetime

    uuid_str = payload.get("_story_uuid")
    story_number = payload.get("_story_number")
    if not isinstance(uuid_str, str) or not isinstance(story_number, int):
        return None

    from uuid import UUID

    try:
        return Story(
            story_uuid=UUID(uuid_str),
            project_key=str(payload["project_key"]),
            story_number=story_number,
            story_display_id=str(payload["story_id"]),
            title=str(payload["title"]),
            story_type=WireStoryType(str(payload["type"])),
            status=StoryStatus(str(payload["status"])),
            size=StorySize(str(payload["size"])),
            mode=WireStoryMode(str(payload["mode"])) if payload.get("mode") else None,
            epic=str(payload.get("epic", "")),
            module=str(payload.get("module", "")),
            participating_repos=[str(r) for r in _to_list(payload.get("repos"))],
            change_impact=ChangeImpact(str(payload["change_impact"])),
            concept_quality=ConceptQuality(str(payload["concept_quality"])),
            owner=str(payload.get("owner", "")),
            risk=RiskLevel(str(payload["risk"])),
            blocker=str(payload["blocker"]) if payload.get("blocker") else None,
            labels=[str(lb) for lb in _to_list(payload.get("labels"))],
            wave=int(str(payload.get("wave", 0))),
            critical_path=bool(payload.get("critical_path", False)),
            # AG3-057 ERROR-2 fix: restore Trigger 3 input from idempotency snapshot.
            # Fail-closed default False for legacy snapshots without this field.
            new_structures=bool(payload.get("new_structures", False)),
            # AG3-068: restore the VectorDB-conflict producer flag; fail-closed
            # default False for legacy snapshots without this field.
            vectordb_conflict_resolved=bool(
                payload.get("vectordb_conflict_resolved", False)
            ),
            # AG3-072 (FK-54 §54.8.5): restore the split lineage so an idempotent
            # replay preserves split_from / split_successors. Fail-closed defaults
            # (None / []) for legacy snapshots without these fields.
            split_from=(
                str(payload["split_from"])
                if payload.get("split_from")
                else None
            ),
            split_successors=[
                str(sid) for sid in _to_list(payload.get("split_successors"))
            ],
            created_at=(
                datetime.fromisoformat(str(payload["created_at"]))
                if payload.get("created_at")
                else None
            ),
            completed_at=(
                datetime.fromisoformat(str(payload["completed_at"]))
                if payload.get("completed_at")
                else None
            ),
        )
    except (KeyError, ValueError):
        return None


def _resolve_cached_create(
    story_repo: StoryRepository,
    cached_payload: dict[str, object] | None,
) -> Story:
    """Return the cached story for an idempotent create_story replay (Befund 5)."""
    assert cached_payload is not None
    cached_story = _story_from_cached_payload(cached_payload)
    if cached_story is not None:
        return cached_story
    # Legacy records without internal fields: fall back to DB read.
    cached_display_id = str(cached_payload.get("story_id", ""))
    story = story_repo.get_by_display_id(cached_display_id)
    if story is not None:
        return story
    raise StoryNotFoundError(
        f"Idempotent replay: cached story {cached_display_id!r} not found",
    )


def _valid_story_exit_record(
    record: object,
    story_display_id: str,
    op_id: str,
) -> bool:
    """Validate the structural StoryExitRecord gate without owning the BC."""

    return (
        getattr(record, "producer_id", None) == "story_exit_service"
        and getattr(record, "exit_id", None) == op_id
        and getattr(record, "story_id", None) == story_display_id
        and str(getattr(record, "terminal_state", "")) == "Cancelled"
        and str(getattr(record, "exit_class", "")) == "viability_handoff"
    )


def _valid_story_split_record(
    record: object,
    story_display_id: str,
    op_id: str,
) -> bool:
    """Validate the structural StorySplitRecord gate without owning the BC.

    Mirrors :func:`_valid_story_exit_record`: a structural check that the record
    is the producer's own split artifact for this story/op, carrying the
    AG3-074-owned ``terminal_state=Cancelled`` + ``exit_class=scope_split`` axis.
    """

    return (
        getattr(record, "producer_id", None) == "story_split_service"
        and getattr(record, "split_id", None) == op_id
        and getattr(record, "source_story_id", None) == story_display_id
        and str(getattr(record, "terminal_state", "")) == "Cancelled"
        and str(getattr(record, "exit_class", "")) == "scope_split"
    )
