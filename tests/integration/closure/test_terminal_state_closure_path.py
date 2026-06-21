"""AG3-074 #4 — normal closure drives the result axis only to Done.

These tests exercise REAL production code (no fantasised pipeline state):

  - the genuine closure-step-4 function
    ``agentkit.backend.closure.phase._transition_story_done`` (called by
    ``ClosurePhaseHandler.on_enter`` step 4) delegating to the single
    ``StoryService.complete_story`` ``In Progress -> Done`` path; and
  - the existing administrative ``StoryService.cancel_story`` path
    (``Backlog|Approved -> Cancelled``).

#4 invariant (FK-59 §59.8 #4): after normal closure the consolidated result
axis is ``Done``, never ``Cancelled``. The administrative ``cancel_story`` path
is a DELINEATED non-closure path and stays allowed: there ``Cancelled`` (and
thus ``derive_terminal_state == Cancelled``) is a VALID result.
"""

from __future__ import annotations

from agentkit.backend.closure.phase import ClosureConfig, _transition_story_done
from agentkit.backend.project_management.entities import (
    Project,
    ProjectConfiguration,
)
from agentkit.backend.story_context_manager.idempotency import (
    InMemoryIdempotencyKeyRepository,
)
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import (
    CreateStoryInput,
    Story,
    StoryStatus,
    WireStoryType,
)
from agentkit.backend.story_context_manager.story_repository import InMemoryStoryRepository
from agentkit.backend.story_context_manager.terminal_state import (
    TerminalState,
    derive_terminal_state,
)


class _InMemoryProjectRepository:
    """Minimal in-memory ProjectRepository (real service collaborator)."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {
            "ak3": Project(
                key="ak3",
                name="AgentKit 3",
                story_id_prefix="AK3",
                configuration=ProjectConfiguration(
                    repo_url="",
                    default_branch="main",
                    default_worker_count=2,
                    repositories=["ak3"],
                ),
            ),
        }

    def get(self, key: str) -> Project | None:
        return self._projects.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return list(self._projects.values())

    def save(self, project: Project) -> None:
        self._projects[project.key] = project


def _make_service(repo: InMemoryStoryRepository) -> StoryService:
    return StoryService(
        story_repository=repo,
        project_repository=_InMemoryProjectRepository(),
        idempotency_repository=InMemoryIdempotencyKeyRepository(),
        event_emitter=lambda *_args: None,
    )


def _create_in_progress_story(svc: StoryService) -> Story:
    story = svc.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Closure axis story",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
        ),
        op_id="op-create",
    )
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)
    return svc.get_story_or_raise(story.story_display_id)


def test_normal_closure_drives_result_axis_to_done_only() -> None:
    """#4 (AC5): real closure-step-4 path yields terminal_state=Done, never Cancelled."""
    repo = InMemoryStoryRepository()
    svc = _make_service(repo)
    story = _create_in_progress_story(svc)
    assert derive_terminal_state(story.status) is TerminalState.OPEN

    # Real closure-step-4 function (ClosurePhaseHandler.on_enter step 4 ->
    # _transition_story_done -> complete_story).
    cfg = ClosureConfig(story_service=svc)
    transition_error = _transition_story_done(cfg, story.story_display_id)
    assert transition_error is None

    closed = svc.get_story_or_raise(story.story_display_id)
    assert closed.status is StoryStatus.DONE
    assert derive_terminal_state(closed.status) is TerminalState.DONE
    # Normal closure NEVER yields Cancelled.
    assert derive_terminal_state(closed.status) is not TerminalState.CANCELLED


def test_cancel_story_delineation_stays_allowed_and_yields_cancelled() -> None:
    """Delineation/regression: admin cancel_story (Backlog|Approved -> Cancelled)
    stays allowed; derive_terminal_state == Cancelled is a VALID NON-closure result.
    """
    repo = InMemoryStoryRepository()
    svc = _make_service(repo)

    # From Backlog.
    backlog_story = svc.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Backlog cancel",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
        ),
        op_id="op-create-backlog",
    )
    assert backlog_story.status is StoryStatus.BACKLOG
    cancelled_from_backlog = svc.cancel_story(
        backlog_story.story_display_id, op_id="op-cancel-backlog"
    )
    assert cancelled_from_backlog.status is StoryStatus.CANCELLED
    assert (
        derive_terminal_state(cancelled_from_backlog.status)
        is TerminalState.CANCELLED
    )

    # From Approved.
    approved_story = svc.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Approved cancel",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
        ),
        op_id="op-create-approved",
    )
    svc.approve_story(approved_story.story_display_id, op_id="op-approve")
    cancelled_from_approved = svc.cancel_story(
        approved_story.story_display_id, op_id="op-cancel-approved"
    )
    assert cancelled_from_approved.status is StoryStatus.CANCELLED
    assert (
        derive_terminal_state(cancelled_from_approved.status)
        is TerminalState.CANCELLED
    )
