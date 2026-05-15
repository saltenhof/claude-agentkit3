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

from agentkit.story_context_manager.errors import (
    ForbiddenError,
    ForbiddenFieldError,
    InvalidStatusTransitionError,
    StoryNotFoundError,
    StoryProjectNotFoundError,
    StoryValidationError,
)
from agentkit.story_context_manager.idempotency import (
    IdempotencyKeyStore,
    InMemoryIdempotencyKeyRepository,
)
from agentkit.story_context_manager.story_model import (
    ChangeImpact,
    ConceptQuality,
    RiskLevel,
    Story,
    StorySpecification,
    StoryStatus,
    WireStoryMode,
    WireStorySize,
    WireStoryType,
)
from agentkit.story_context_manager.story_repository import (
    InMemoryStoryRepository,
    StoryRepository,
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

    from agentkit.project_management.repository import ProjectRepository
    from agentkit.story_context_manager.idempotency import IdempotencyKeyRepository


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
})

_TERMINAL_STATUSES: frozenset[StoryStatus] = frozenset({
    StoryStatus.DONE,
    StoryStatus.CANCELLED,
})


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
    if current is target:
        # Idempotent repeat on same status — OK for terminal-safe semantics
        return
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


class StoryService:
    """Authoritative story lifecycle service for story_context_manager BC.

    Dependencies injected at construction time following ARCH-26.
    All defaults are real implementations, not mocks.

    Args:
        story_repository: Story stammdaten persistence.
        project_repository: Project entity access (for archived/repos check).
        idempotency_repository: Idempotency key persistence.
        event_emitter: Callable that emits story_upserted events. Receives
            ``(project_key, story_display_id, wire_summary_dict)`` as args.
    """

    def __init__(
        self,
        *,
        story_repository: StoryRepository | None = None,
        project_repository: ProjectRepository | None = None,
        idempotency_repository: IdempotencyKeyRepository | None = None,
        event_emitter: Callable[[str, str, dict[str, object]], None] | None = None,
    ) -> None:
        if story_repository is None:
            story_repository = InMemoryStoryRepository()
        if idempotency_repository is None:
            idempotency_repository = InMemoryIdempotencyKeyRepository()
        if project_repository is None:
            from agentkit.state_backend.store.project_management_repository import (
                StateBackendProjectRepository,
            )
            project_repository = StateBackendProjectRepository()

        self._story_repo: StoryRepository = story_repository
        self._project_repo: ProjectRepository = project_repository
        self._idempotency = IdempotencyKeyStore(idempotency_repository)
        self._emit = event_emitter or _null_emitter

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
        *,
        project_key: str,
        title: str,
        story_type: WireStoryType,
        repos: list[str],
        epic: str = "",
        module: str = "",
        size: WireStorySize = WireStorySize.M,
        mode: WireStoryMode | None = None,
        change_impact: ChangeImpact = ChangeImpact.LOCAL,
        concept_quality: ConceptQuality = ConceptQuality.MEDIUM,
        owner: str = "",
        risk: RiskLevel = RiskLevel.LOW,
        labels: list[str] | None = None,
        op_id: str,
        correlation_id: str = "",
    ) -> Story:
        """Create a new Story in Backlog status.

        Implements FK-91 §91.1a and formal.frontend-contracts.command.create_story.
        Steps (story.md §2.1.15):
          1. Lookup Project (ProjectRepository).
          2. Archived project? -> forbidden (403).
          3. Validate repos.
          4. Allocate story_number atomically.
          5. Materialize story_display_id.
          6. Persist Story + Specification.
          7. Persist idempotency record.
          8. Emit story_upserted.
          9. Return story_summary wire payload.

        Args:
            project_key: Project identifier.
            title: Story title (required, non-empty).
            story_type: Wire story type.
            repos: Participating repos (wire name; min 1).
            epic: Epic label.
            module: Module label.
            size: Wire story size (default M).
            mode: standard/fast or None (treated as standard).
            change_impact: Change impact classification.
            concept_quality: Concept quality classification.
            owner: Owner identifier.
            risk: Risk level.
            labels: Optional labels list.
            op_id: Idempotency key (required).
            correlation_id: Correlation ID for propagation.

        Returns:
            The created Story.

        Raises:
            ``StoryNotFoundError`` (wrapped as story_not_found in HTTP).
            ``StoryProjectArchivedError`` / ``ForbiddenError`` (403).
            ``StoryValidationError`` (400).
            ``IdempotencyMismatchError`` (409).
        """
        # Build a canonical body dict for idempotency check
        body: dict[str, object] = {
            "project_key": project_key,
            "title": title,
            "type": story_type.value,
            "repos": sorted(repos),
            "epic": epic,
            "module": module,
            "size": size.value,
            "mode": mode.value if mode else None,
            "change_impact": change_impact.value,
            "concept_quality": concept_quality.value,
            "owner": owner,
            "risk": risk.value,
            "labels": sorted(labels or []),
            "op_id": op_id,
        }
        cached, cached_payload = self._idempotency.check(
            op_id, body, correlation_id=correlation_id
        )
        if cached:
            # Return the cached story
            assert cached_payload is not None
            cached_display_id = str(cached_payload.get("story_id", ""))
            story = self._story_repo.get_by_display_id(cached_display_id)
            if story is not None:
                return story
            # Fallback: reconstruct from payload (shouldn't happen normally)
            raise StoryNotFoundError(
                f"Idempotent replay: cached story {cached_display_id!r} not found",
            )

        # -- 1. Lookup project --
        project = self._project_repo.get(project_key)
        if project is None:
            raise StoryProjectNotFoundError(
                f"Project {project_key!r} does not exist",
                detail={"project_key": project_key},
            )

        # -- 2. Archived check --
        if project.archived_at is not None:
            raise ForbiddenError(
                f"Project {project_key!r} is archived",
                detail={"project_key": project_key},
            )

        # -- 3. Validate title --
        if not title.strip():
            raise StoryValidationError(
                "title must not be empty",
                detail={"field": "title"},
            )

        # -- 4. Validate repos --
        validate_repos_not_empty(repos)
        # Project configuration may list allowed repos; validate if present
        allowed_repos = _get_project_repos(project)
        if allowed_repos:
            validate_repos_against_project(repos, allowed_repos)

        # -- 5. Allocate story_number atomically --
        story_number = self._story_repo.allocate_next_story_number(project_key)

        # -- 6. Materialize display ID --
        story_display_id = f"{project.story_id_prefix}-{story_number}"

        # -- 7. Build Story --
        now = datetime.now(UTC)
        story = Story(
            project_key=project_key,
            story_number=story_number,
            story_display_id=story_display_id,
            title=title,
            story_type=story_type,
            status=StoryStatus.BACKLOG,
            size=size,
            mode=mode,
            epic=epic,
            module=module,
            participating_repos=list(repos),
            change_impact=change_impact,
            concept_quality=concept_quality,
            owner=owner,
            risk=risk,
            labels=list(labels or []),
            created_at=now,
        )

        # -- 8. Persist --
        self._story_repo.save(story)

        # -- 9. Persist idempotency --
        wire_summary = story_to_wire_summary(story)
        self._idempotency.record(
            op_id,
            body,
            {"story_id": story_display_id, **wire_summary},
            correlation_id=correlation_id,
        )

        # -- 10. Emit event --
        self._emit(project_key, story_display_id, wire_summary)

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
        cached, cached_payload = self._idempotency.check(
            op_id, body, correlation_id=correlation_id
        )
        if cached:
            assert cached_payload is not None
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

        self._story_repo.save(story)

        wire_summary = story_to_wire_summary(story)
        self._idempotency.record(
            op_id, body, {"story_id": story_display_id, **wire_summary},
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
        cached, cached_payload = self._idempotency.check(
            op_id, body, correlation_id=correlation_id
        )
        if cached:
            assert cached_payload is not None
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
            op_id, body, {"story_id": story_display_id, **wire_summary},
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

    def begin_progress(
        self,
        story_display_id: str,
        *,
        correlation_id: str = "",
    ) -> Story:
        """Set story to In Progress (Approved -> In Progress).

        Called by Setup Phase after successful completion (FK-22 §22.4.3).
        NOT callable from the frontend. No op_id required (pipeline-internal).

        Args:
            story_display_id: Story to transition.
            correlation_id: Correlation ID for telemetry.

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

    def complete_story(
        self,
        story_display_id: str,
        *,
        correlation_id: str = "",
    ) -> Story:
        """Set story to Done (In Progress -> Done).

        Called by Closure Sequence after successful closure
        (formal.story-workflow.invariant.completion_only_after_closure).
        NOT callable from the frontend.

        Args:
            story_display_id: Story to complete.
            correlation_id: Correlation ID for telemetry.

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
        cached, cached_payload = self._idempotency.check(
            op_id, body, correlation_id=correlation_id
        )
        if cached:
            assert cached_payload is not None
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
            op_id, body, {"story_id": story_display_id, **wire_summary},
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
    """No-op event emitter (used as default in tests and when telemetry is off)."""
    _ = project_key, story_display_id, wire_summary


def _get_project_repos(project: object) -> list[str]:
    """Extract the list of allowed repos from a Project entity.

    The Project.configuration does not have a ``repositories`` field
    in the current schema (it has ``repo_url`` etc.). We return [] to
    indicate "no restriction" until the schema is extended.
    """
    # ProjectConfiguration currently has: repo_url, default_branch,
    # are_url, default_worker_count. No repositories list yet.
    # Returning [] means: all repos are allowed (no restriction).
    return []


def _apply_updates(
    story: Story,
    updates: dict[str, object],
    project: object,
) -> Story:
    """Apply wire-level field updates to a Story.

    Only touches fields that are present in ``updates``.
    Validates enum values and repos constraints.

    Args:
        story: Current Story instance (mutable).
        updates: Wire field name -> new value.
        project: Project entity (for repo validation).

    Returns:
        The mutated Story (same object, modified in place).

    Raises:
        ``StoryValidationError`` for invalid field values.
    """
    from agentkit.story_context_manager.wire_adapter import (
        parse_wire_change_impact,
        parse_wire_concept_quality,
        parse_wire_risk_level,
        parse_wire_story_mode,
        parse_wire_story_size,
        parse_wire_story_type,
    )

    for field_key, value in updates.items():
        if field_key == "title":
            if not isinstance(value, str) or not value.strip():
                raise StoryValidationError(
                    "title must be a non-empty string",
                    detail={"field": "title"},
                )
            story.title = value
        elif field_key == "epic":
            story.epic = str(value) if value is not None else ""
        elif field_key == "module":
            story.module = str(value) if value is not None else ""
        elif field_key == "type":
            story.story_type = parse_wire_story_type(str(value))
        elif field_key == "size":
            story.size = parse_wire_story_size(str(value))
        elif field_key == "mode":
            story.mode = parse_wire_story_mode(
                str(value) if value is not None else None
            )
        elif field_key == "repos":
            if not isinstance(value, list):
                raise StoryValidationError(
                    "repos must be a list",
                    detail={"field": "repos"},
                )
            repos = [str(r) for r in value]
            validate_repos_not_empty(repos)
            allowed = _get_project_repos(project)
            if allowed:
                validate_repos_against_project(repos, allowed)
            story.participating_repos = repos
        elif field_key == "change_impact":
            story.change_impact = parse_wire_change_impact(str(value))
        elif field_key == "concept_quality":
            story.concept_quality = parse_wire_concept_quality(str(value))
        elif field_key == "owner":
            story.owner = str(value) if value is not None else ""
        elif field_key == "risk":
            story.risk = parse_wire_risk_level(str(value))
        elif field_key == "blocker":
            story.blocker = str(value) if value is not None else None
        elif field_key == "labels":
            if not isinstance(value, list):
                raise StoryValidationError(
                    "labels must be a list",
                    detail={"field": "labels"},
                )
            story.labels = [str(label) for label in value]
        elif field_key == "wave":
            if not isinstance(value, int):
                raise StoryValidationError(
                    "wave must be an integer",
                    detail={"field": "wave"},
                )
            story.wave = value
        elif field_key == "critical_path":
            story.critical_path = bool(value)
        elif field_key == "op_id":
            pass  # op_id is not a story field
        elif field_key in FORBIDDEN_PATCH_FIELDS:
            raise ForbiddenFieldError(
                f"Field {field_key!r} is forbidden in updates",
                detail={"forbidden_field": field_key},
            )
        else:
            # Unknown field -- ignore silently per REST PATCH semantics
            pass

    return story
