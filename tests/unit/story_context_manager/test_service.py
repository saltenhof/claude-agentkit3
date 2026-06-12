"""Unit tests for StoryService (story_context_manager BC).

Tests the authoritative story lifecycle service including:
- create_story: idempotency, validation, status assignment
- approve/reject/cancel: status transitions with idempotency
- begin_progress / complete_story: pipeline-only transitions
- get_story / list_stories / search_stories: read operations
- event emission via injected callable
"""

from __future__ import annotations

import pytest

from agentkit.governance.principal_capabilities.principals import Principal
from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.story_context_manager.errors import (
    ForbiddenError,
    ForbiddenFieldError,
    IdempotencyMismatchError,
    InvalidStatusTransitionError,
    StoryNotFoundError,
    StoryProjectNotFoundError,
    StoryValidationError,
)
from agentkit.story_context_manager.idempotency import InMemoryIdempotencyKeyRepository
from agentkit.story_context_manager.service import StoryService
from agentkit.story_context_manager.story_model import (
    CreateStoryInput,
    Story,
    StoryStatus,
    WireStoryType,
)
from agentkit.story_context_manager.story_repository import InMemoryStoryRepository
from agentkit.story_exit import (
    AdmissibilityAssessment,
    AlternativeReview,
    ExitClass,
    ExitReason,
    StoryExitRecord,
    TerminalState,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _InMemoryProjectRepository:
    """Minimal in-memory ProjectRepository for tests."""

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
                    repositories=["ak3", "ak3-frontend"],
                ),
            ),
        }

    def get(self, key: str) -> Project | None:
        return self._projects.get(key)

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return list(self._projects.values())

    def save(self, project: Project) -> None:
        self._projects[project.key] = project


def _make_service(
    *,
    stories: InMemoryStoryRepository | None = None,
    project_repo: _InMemoryProjectRepository | None = None,
    emitted: list[tuple[str, str, dict[str, object]]] | None = None,
) -> StoryService:
    """Create a StoryService backed by in-memory stores."""
    captured: list[tuple[str, str, dict[str, object]]] = (
        emitted if emitted is not None else []
    )

    def _emit(
        project_key: str,
        story_display_id: str,
        wire_summary: dict[str, object],
    ) -> None:
        captured.append((project_key, story_display_id, wire_summary))

    return StoryService(
        story_repository=stories or InMemoryStoryRepository(),
        project_repository=project_repo or _InMemoryProjectRepository(),
        idempotency_repository=InMemoryIdempotencyKeyRepository(),
        event_emitter=_emit,
    )


def _create_story(
    svc: StoryService,
    *,
    project_key: str = "ak3",
    title: str = "Test story",
    repos: list[str] | None = None,
    op_id: str = "op-001",
) -> Story:
    return svc.create_story(
        CreateStoryInput(
            project_key=project_key,
            title=title,
            story_type=WireStoryType.IMPLEMENTATION,
            repos=repos or ["ak3"],
        ),
        op_id=op_id,
    )


def _story_exit_record(story_id: str) -> StoryExitRecord:
    from datetime import UTC, datetime

    return StoryExitRecord(
        exit_id="exit-1",
        project_key="ak3",
        story_id=story_id,
        run_id="run-1",
        session_id="sess-1",
        reason=ExitReason.SOLUTION_VIABILITY_REQUIRES_HUMAN_DESIGN,
        principal=Principal.HUMAN_CLI,
        terminal_state=TerminalState.CANCELLED,
        exit_class=ExitClass.VIABILITY_HANDOFF,
        admissibility_assessment=AdmissibilityAssessment(
            normal_difficulty_excluded=True,
            mere_agent_uncertainty_excluded=True,
            usual_remediation_excluded=True,
            split_or_replan_excluded=True,
        ),
        alternative_review=AlternativeReview(
            standard_contract_checked=True,
            standard_contract_rejection_reason="filled",
            reclassification_checked=True,
            reclassification_rejection_reason="filled",
            split_checked=True,
            split_rejection_reason="filled",
        ),
        created_at=datetime(2026, 6, 9, 12, 0, tzinfo=UTC),
    )


def _story_split_record(story_id: str, *, split_id: str = "split-1") -> object:
    from datetime import UTC, datetime

    from agentkit.story_context_manager.terminal_state import (
        ExitClass as TExitClass,
    )
    from agentkit.story_context_manager.terminal_state import (
        TerminalState as TTerminalState,
    )
    from agentkit.story_split import StorySplitRecord
    from agentkit.story_split.models import SplitStatus

    return StorySplitRecord(
        split_id=split_id,
        project_key="ak3",
        source_story_id=story_id,
        requested_by="human_cli",
        reason="scope_explosion",
        plan_ref="abc123",
        status=SplitStatus.COMMITTED,
        successor_ids=("AK3-201", "AK3-202"),
        superseded_by=("AK3-201", "AK3-202"),
        terminal_state=TTerminalState.CANCELLED,
        exit_class=TExitClass.SCOPE_SPLIT,
        created_at=datetime(2026, 6, 9, 12, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# create_story
# ---------------------------------------------------------------------------


def test_create_story_returns_story_in_backlog() -> None:
    svc = _make_service()

    story = _create_story(svc, title="Initial story")

    assert story.status == StoryStatus.BACKLOG
    assert story.title == "Initial story"
    assert story.project_key == "ak3"
    # AG3-050: display-ID is materialized via the single formatter
    # (FK-02 §2.11.2) with min-width 3 padding.
    assert story.story_display_id == "AK3-001"
    assert story.story_number == 1


def test_create_story_allocates_monotone_story_numbers() -> None:
    svc = _make_service()

    s1 = _create_story(svc, title="Story 1", op_id="op-001")
    s2 = _create_story(svc, title="Story 2", op_id="op-002")
    s3 = _create_story(svc, title="Story 3", op_id="op-003")

    assert s1.story_number == 1
    assert s2.story_number == 2
    assert s3.story_number == 3


def test_create_story_emits_story_upserted_event() -> None:
    emitted: list[tuple[str, str, dict[str, object]]] = []
    svc = _make_service(emitted=emitted)

    story = _create_story(svc, title="Emitter test")

    assert len(emitted) == 1
    project_key, story_id, wire = emitted[0]
    assert project_key == "ak3"
    assert story_id == story.story_display_id
    assert wire["status"] == "Backlog"


def test_create_story_idempotent_same_body_returns_cached() -> None:
    svc = _make_service()

    s1 = _create_story(svc, op_id="op-idem-001")
    s2 = _create_story(svc, op_id="op-idem-001")  # same op_id, same body

    assert s1.story_display_id == s2.story_display_id
    assert s1.story_uuid == s2.story_uuid


def test_create_story_idempotency_mismatch_raises() -> None:
    svc = _make_service()

    _create_story(svc, title="First title", op_id="op-conflict-001")

    with pytest.raises(IdempotencyMismatchError):
        _create_story(svc, title="Different title", op_id="op-conflict-001")


def test_create_story_unknown_project_raises() -> None:
    svc = _make_service()

    with pytest.raises(StoryProjectNotFoundError):
        svc.create_story(
            CreateStoryInput(
                project_key="NONEXISTENT",
                title="Orphan story",
                story_type=WireStoryType.IMPLEMENTATION,
                repos=["repo"],
            ),
            op_id="op-001",
        )


def test_create_story_archived_project_raises() -> None:
    from datetime import UTC, datetime

    from agentkit.project_management.entities import Project, ProjectConfiguration

    project_repo = _InMemoryProjectRepository()
    archived = Project(
        key="arch",
        name="Archived",
        story_id_prefix="ARCH",
        configuration=ProjectConfiguration(
            repo_url="",
            default_branch="main",
            default_worker_count=1,
            repositories=["repo"],
        ),
        archived_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    project_repo._projects["arch"] = archived

    svc = _make_service(project_repo=project_repo)

    with pytest.raises(ForbiddenError):
        svc.create_story(
            CreateStoryInput(
                project_key="arch",
                title="Story on archived project",
                story_type=WireStoryType.IMPLEMENTATION,
                repos=["repo"],
            ),
            op_id="op-001",
        )


def test_create_story_empty_title_raises() -> None:
    """Title validation happens at the DTO boundary (Pydantic ValidationError)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="title"):
        CreateStoryInput(
            project_key="ak3",
            title="   ",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
        )


def test_create_story_empty_repos_raises() -> None:
    """Repos validation happens at the DTO boundary (Pydantic ValidationError)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="repos"):
        CreateStoryInput(
            project_key="ak3",
            title="No repos story",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=[],
        )


# ---------------------------------------------------------------------------
# approve / reject / cancel
# ---------------------------------------------------------------------------


def test_approve_story_transitions_backlog_to_approved() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")

    approved = svc.approve_story(story.story_display_id, op_id="op-approve")

    assert approved.status == StoryStatus.APPROVED


def test_reject_story_transitions_approved_to_backlog() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")

    rejected = svc.reject_story(story.story_display_id, op_id="op-reject")

    assert rejected.status == StoryStatus.BACKLOG


def test_cancel_story_from_backlog() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")

    cancelled = svc.cancel_story(
        story.story_display_id, reason="No longer needed", op_id="op-cancel"
    )

    assert cancelled.status == StoryStatus.CANCELLED
    assert cancelled.blocker == "No longer needed"


def test_cancel_story_from_approved() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")

    cancelled = svc.cancel_story(story.story_display_id, op_id="op-cancel")

    assert cancelled.status == StoryStatus.CANCELLED


def test_approve_already_done_story_raises() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)
    svc.complete_story(story.story_display_id)

    with pytest.raises(InvalidStatusTransitionError):
        svc.approve_story(story.story_display_id, op_id="op-approve-again")


def test_cancel_in_progress_story_raises_informative() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)

    with pytest.raises(InvalidStatusTransitionError, match="In Progress"):
        svc.cancel_story(story.story_display_id, op_id="op-cancel")


def test_approve_story_not_found_raises() -> None:
    svc = _make_service()

    with pytest.raises(StoryNotFoundError):
        svc.approve_story("AK3-999", op_id="op-approve")


# ---------------------------------------------------------------------------
# begin_progress / complete_story (pipeline-only)
# ---------------------------------------------------------------------------


def test_begin_progress_transitions_approved_to_in_progress() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")

    in_progress = svc.begin_progress(story.story_display_id)

    assert in_progress.status == StoryStatus.IN_PROGRESS


def test_complete_story_transitions_in_progress_to_done() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)

    done = svc.complete_story(story.story_display_id)

    assert done.status == StoryStatus.DONE
    assert done.completed_at is not None


def test_begin_progress_on_backlog_raises() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")

    with pytest.raises(InvalidStatusTransitionError):
        svc.begin_progress(story.story_display_id)


def test_complete_story_without_begin_progress_raises() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")

    with pytest.raises(InvalidStatusTransitionError):
        svc.complete_story(story.story_display_id)


def test_administrative_story_exit_cancel_in_progress_is_gated() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)

    cancelled = svc.administratively_cancel_for_story_exit(
        story.story_display_id,
        story_exit_record=_story_exit_record(story.story_display_id),
        story_exit_operation_committed=True,
        principal=Principal.HUMAN_CLI,
        op_id="exit-1",
    )

    assert cancelled.status == StoryStatus.CANCELLED
    assert cancelled.blocker == "Story-Exit viability handoff (exit-1)"


def test_administrative_story_exit_cancel_is_idempotent_on_cancelled() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)
    record = _story_exit_record(story.story_display_id)

    first = svc.administratively_cancel_for_story_exit(
        story.story_display_id,
        story_exit_record=record,
        story_exit_operation_committed=True,
        principal=Principal.HUMAN_CLI,
        op_id="exit-1",
    )
    second = svc.administratively_cancel_for_story_exit(
        story.story_display_id,
        story_exit_record=record,
        story_exit_operation_committed=True,
        principal=Principal.HUMAN_CLI,
        op_id="exit-1",
    )

    assert first.status == StoryStatus.CANCELLED
    assert second.status == StoryStatus.CANCELLED


def test_administrative_story_exit_cancel_requires_committed_fence() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)

    with pytest.raises(ForbiddenError, match="committed"):
        svc.administratively_cancel_for_story_exit(
            story.story_display_id,
            story_exit_record=_story_exit_record(story.story_display_id),
            story_exit_operation_committed=False,
            principal=Principal.HUMAN_CLI,
            op_id="exit-1",
        )


def test_administrative_story_exit_cancel_rejects_non_human_principal() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)

    with pytest.raises(ForbiddenError, match="human_cli"):
        svc.administratively_cancel_for_story_exit(
            story.story_display_id,
            story_exit_record=_story_exit_record(story.story_display_id),
            story_exit_operation_committed=True,
            principal=Principal.ORCHESTRATOR,
            op_id="exit-1",
        )


def test_administrative_story_split_cancel_in_progress_is_gated() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)

    cancelled = svc.administratively_cancel_for_story_split(
        story.story_display_id,
        story_split_record=_story_split_record(
            story.story_display_id, split_id="split-1"
        ),
        story_split_operation_committed=True,
        principal=Principal.HUMAN_CLI,
        op_id="split-1",
    )

    assert cancelled.status == StoryStatus.CANCELLED
    assert cancelled.blocker == "Story-Split scope_split (split-1)"


def test_administrative_story_split_cancel_is_idempotent_on_cancelled() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)
    record = _story_split_record(story.story_display_id, split_id="split-1")

    first = svc.administratively_cancel_for_story_split(
        story.story_display_id,
        story_split_record=record,
        story_split_operation_committed=True,
        principal=Principal.HUMAN_CLI,
        op_id="split-1",
    )
    second = svc.administratively_cancel_for_story_split(
        story.story_display_id,
        story_split_record=record,
        story_split_operation_committed=True,
        principal=Principal.HUMAN_CLI,
        op_id="split-1",
    )

    assert first.status == StoryStatus.CANCELLED
    assert second.status == StoryStatus.CANCELLED


def test_administrative_story_split_cancel_requires_committed_fence() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)

    with pytest.raises(ForbiddenError, match="committed"):
        svc.administratively_cancel_for_story_split(
            story.story_display_id,
            story_split_record=_story_split_record(story.story_display_id),
            story_split_operation_committed=False,
            principal=Principal.HUMAN_CLI,
            op_id="split-1",
        )


def test_administrative_story_split_cancel_rejects_non_human_principal() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)

    with pytest.raises(ForbiddenError, match="human_cli"):
        svc.administratively_cancel_for_story_split(
            story.story_display_id,
            story_split_record=_story_split_record(story.story_display_id),
            story_split_operation_committed=True,
            principal=Principal.ORCHESTRATOR,
            op_id="split-1",
        )


def test_administrative_story_split_cancel_rejects_invalid_record() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    svc.begin_progress(story.story_display_id)

    # A story_exit record (wrong producer / exit_class) must be rejected.
    with pytest.raises(StoryValidationError, match="StorySplitRecord"):
        svc.administratively_cancel_for_story_split(
            story.story_display_id,
            story_split_record=_story_exit_record(story.story_display_id),
            story_split_operation_committed=True,
            principal=Principal.HUMAN_CLI,
            op_id="split-1",
        )


def test_administrative_story_split_cancel_rejects_backlog_story() -> None:
    # Frontend cancel-guard semantics are NOT reused: a never-started story is
    # not a valid In Progress split source.
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")

    with pytest.raises(InvalidStatusTransitionError):
        svc.administratively_cancel_for_story_split(
            story.story_display_id,
            story_split_record=_story_split_record(story.story_display_id),
            story_split_operation_committed=True,
            principal=Principal.HUMAN_CLI,
            op_id="split-1",
        )


def test_begin_progress_emits_event() -> None:
    emitted: list[tuple[str, str, dict[str, object]]] = []
    svc = _make_service(emitted=emitted)
    story = _create_story(svc, op_id="op-create")
    svc.approve_story(story.story_display_id, op_id="op-approve")
    emitted.clear()

    svc.begin_progress(story.story_display_id)

    assert len(emitted) == 1
    assert emitted[0][2]["status"] == "In Progress"


# ---------------------------------------------------------------------------
# update_story_fields (PATCH)
# ---------------------------------------------------------------------------


def test_update_story_fields_updates_title() -> None:
    svc = _make_service()
    story = _create_story(svc, title="Original title", op_id="op-create")

    updated = svc.update_story_fields(
        story.story_display_id,
        updates={"title": "Updated title"},
        op_id="op-patch",
    )

    assert updated.title == "Updated title"


def test_update_story_fields_forbidden_field_raises() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")

    with pytest.raises(ForbiddenFieldError):
        svc.update_story_fields(
            story.story_display_id,
            updates={"status": "Approved"},
            op_id="op-patch-forbidden",
        )


def test_update_story_fields_updates_repos() -> None:
    svc = _make_service()
    story = _create_story(svc, repos=["ak3"], op_id="op-create")

    updated = svc.update_story_fields(
        story.story_display_id,
        updates={"repos": ["ak3", "ak3-frontend"]},
        op_id="op-patch-repos",
    )

    assert updated.participating_repos == ["ak3", "ak3-frontend"]


def test_update_story_fields_empty_repos_raises() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")

    with pytest.raises(StoryValidationError, match="repos"):
        svc.update_story_fields(
            story.story_display_id,
            updates={"repos": []},
            op_id="op-patch-empty-repos",
        )


# ---------------------------------------------------------------------------
# set_story_field (PUT)
# ---------------------------------------------------------------------------


def test_set_story_field_updates_single_field() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")

    updated = svc.set_story_field(
        story.story_display_id,
        "title",
        "New title via PUT",
        op_id="op-put",
    )

    assert updated.title == "New title via PUT"


def test_set_story_field_forbidden_status_raises() -> None:
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")

    with pytest.raises(ForbiddenFieldError):
        svc.set_story_field(
            story.story_display_id,
            "status",
            "Approved",
            op_id="op-put-status",
        )


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def test_get_story_returns_story_by_display_id() -> None:
    svc = _make_service()
    created = _create_story(svc, op_id="op-create")

    found = svc.get_story(created.story_display_id)

    assert found is not None
    assert found.story_uuid == created.story_uuid


def test_get_story_missing_returns_none() -> None:
    svc = _make_service()

    result = svc.get_story("AK3-999")

    assert result is None


def test_list_stories_returns_project_stories_ordered() -> None:
    svc = _make_service()
    _create_story(svc, title="Story 1", op_id="op-001")
    _create_story(svc, title="Story 2", op_id="op-002")
    _create_story(svc, title="Story 3", op_id="op-003")

    stories = svc.list_stories("ak3")

    assert len(stories) == 3
    assert [s.story_number for s in stories] == [1, 2, 3]


def test_list_stories_excludes_other_projects() -> None:
    from agentkit.project_management.entities import Project, ProjectConfiguration

    project_repo = _InMemoryProjectRepository()
    project_repo._projects["beta"] = Project(
        key="beta",
        name="Beta",
        story_id_prefix="BETA",
        configuration=ProjectConfiguration(
            repo_url="",
            default_branch="main",
            default_worker_count=1,
            repositories=["beta-repo"],
        ),
    )
    svc = _make_service(project_repo=project_repo)
    _create_story(svc, project_key="ak3", op_id="op-ak3")
    svc.create_story(
        CreateStoryInput(
            project_key="beta",
            title="Beta story",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["beta-repo"],
        ),
        op_id="op-beta",
    )

    ak3_stories = svc.list_stories("ak3")
    beta_stories = svc.list_stories("beta")

    assert len(ak3_stories) == 1
    assert len(beta_stories) == 1
    assert ak3_stories[0].project_key == "ak3"
    assert beta_stories[0].project_key == "beta"


def test_search_stories_finds_by_title_substring() -> None:
    svc = _make_service()
    _create_story(svc, title="Implement story service", op_id="op-001")
    _create_story(svc, title="Fix preflight logic", op_id="op-002")

    results = svc.search_stories("ak3", "service")

    assert len(results) == 1
    assert "service" in results[0].title.lower()


def test_get_story_fields_returns_wire_dict() -> None:
    svc = _make_service()
    story = _create_story(svc, title="Fields test", op_id="op-create")

    fields = svc.get_story_fields(story.story_display_id)

    assert fields["story_id"] == story.story_display_id
    assert fields["status"] == "Backlog"


# ---------------------------------------------------------------------------
# AG3-020/AG3-014 Integration: repo validation now live (Befund 3 fixed)
# ---------------------------------------------------------------------------


def test_create_story_unknown_repo_is_blocked() -> None:
    """AG3-014 AC6: creating a story with a repo not in project config is rejected.

    This test verifies that the AG3-014 Befund 3 fix is complete:
    _get_project_repos now returns project.configuration.repositories,
    so validate_repos_against_project blocks unknown repos.
    """
    svc = _make_service()

    with pytest.raises(StoryValidationError) as exc_info:
        svc.create_story(
            CreateStoryInput(
                project_key="ak3",
                title="Story with unknown repo",
                story_type=WireStoryType.IMPLEMENTATION,
                repos=["nicht-existent"],
            ),
            op_id="op-unknown-repo",
        )

    detail = exc_info.value.args[0] if exc_info.value.args else ""
    # detail.unknown_repos must be populated
    assert "unknown_repos" in str(exc_info.value.__dict__.get("detail", {})) or \
           "nicht-existent" in str(detail) or \
           hasattr(exc_info.value, "detail") and "unknown_repos" in str(getattr(exc_info.value, "detail", ""))


def test_create_story_known_repo_is_allowed() -> None:
    """AG3-014 AC6 happy path: a story with a repo in project config is accepted."""
    svc = _make_service()

    story = svc.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Story with known repo",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
        ),
        op_id="op-known-repo",
    )

    assert story.participating_repos == ["ak3"]


def test_update_story_fields_unknown_repo_is_blocked() -> None:
    """AG3-014 AC6: updating a story's repos to include an unknown repo is rejected."""
    svc = _make_service()
    story = _create_story(svc, repos=["ak3"], op_id="op-create")

    with pytest.raises(StoryValidationError):
        svc.update_story_fields(
            story.story_display_id,
            updates={"repos": ["ak3", "nicht-existent"]},
            op_id="op-update-unknown",
        )


def test_get_story_fields_not_found_raises() -> None:
    svc = _make_service()

    with pytest.raises(StoryNotFoundError):
        svc.get_story_fields("AK3-999")


# ---------------------------------------------------------------------------
# AG3-057 residual: new_structures preserved across idempotent cached replay
# ---------------------------------------------------------------------------


def test_create_story_idempotent_replay_preserves_new_structures() -> None:
    """Second call with the same op_id must return new_structures=True.

    Regression test for the AG3-057 residual bug where
    _story_to_internal_snapshot() omitted new_structures, so
    _story_from_cached_payload() always reconstructed it as False.
    """
    svc = _make_service()

    first = svc.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Trigger 3 replay story",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
            new_structures=True,
        ),
        op_id="op-replay-new-structures",
    )

    # Idempotent replay: same op_id → must return cached result
    second = svc.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Trigger 3 replay story",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
            new_structures=True,
        ),
        op_id="op-replay-new-structures",
    )

    assert first.new_structures is True, "First call must return new_structures=True"
    assert second.new_structures is True, (
        "Cached replay must also return new_structures=True "
        "(failed before fix: _story_to_internal_snapshot omitted new_structures)"
    )
    assert first.story_uuid == second.story_uuid, "Must be same story (idempotent)"


# ---------------------------------------------------------------------------
# AG3-068: vectordb_conflict_resolved is a typed, persisted Story field
# ---------------------------------------------------------------------------


def test_vectordb_conflict_resolved_persists_as_typed_field() -> None:
    """AC5: the flag is a typed, persisted Story attribute (no shadow field)."""
    svc = _make_service()
    created = svc.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Story with resolved vectordb conflict",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
            vectordb_conflict_resolved=True,
        ),
        op_id="op-vectordb-flag",
    )
    assert created.vectordb_conflict_resolved is True
    loaded = svc.get_story(created.story_display_id)
    assert loaded is not None
    assert loaded.vectordb_conflict_resolved is True


def test_vectordb_conflict_resolved_replay_preserves_flag() -> None:
    """Idempotent replay reconstructs the flag faithfully (not a default False)."""
    svc = _make_service()
    first = svc.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Vectordb flag replay story",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
            vectordb_conflict_resolved=True,
        ),
        op_id="op-vectordb-flag-replay",
    )
    second = svc.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Vectordb flag replay story",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
            vectordb_conflict_resolved=True,
        ),
        op_id="op-vectordb-flag-replay",
    )
    assert first.vectordb_conflict_resolved is True
    assert second.vectordb_conflict_resolved is True
    assert first.story_uuid == second.story_uuid


def test_vectordb_conflict_resolved_defaults_false() -> None:
    """A PASS / unset path leaves the flag False (fail-closed default)."""
    svc = _make_service()
    created = svc.create_story(
        CreateStoryInput(
            project_key="ak3",
            title="Story without conflict",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
        ),
        op_id="op-no-conflict",
    )
    assert created.vectordb_conflict_resolved is False


def test_get_story_detail_returns_story_and_spec() -> None:
    """create_story must persist a default StorySpecification (Befund 2).

    story.md §2.1.3 AC5: spec is never None after creation.
    """
    svc = _make_service()
    story = _create_story(svc, op_id="op-create")

    result = svc.get_story_detail(story.story_display_id)

    assert result is not None
    story_out, spec = result
    assert story_out.story_display_id == story.story_display_id
    # Befund 2: spec must be present (default created by create_story)
    assert spec is not None
