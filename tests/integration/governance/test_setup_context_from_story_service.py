"""Integration test — Setup builds the StoryContext from the AK3 Story-Service.

AG3-120 AC2/AC3 (real components, no fakes): AK3 owns the user story via
``story_id``; GitHub is only the code backend (FK-12 §12.1.1, FK-91 §91.2
rule 9). The setup context-build step (``build_story_context``) is exercised
against a REAL ``StoryService`` backed by a REAL SQLite state-backend — no
fake/in-memory repo (testing-guardrails §2) — proving:

* AC2: a code-producing story's context is built purely from ``story_id`` +
  the Story-Service record, with NO GitHub issue read (the setup package no
  longer imports/exposes ``get_issue``); the persisted context carries no
  ``issue_nr``.
* AC3: an unresolvable AK3 story identity fails Setup closed
  (``StoryModeResolutionError``) — a missing GitHub issue is no longer a
  failure reason; the missing identity is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.governance.errors import StoryModeResolutionError
from agentkit.backend.governance.setup_preflight_gate import context_builder
from agentkit.backend.governance.setup_preflight_gate.context_builder import (
    build_story_context,
)
from agentkit.backend.project_management.entities import ProjectConfiguration
from agentkit.backend.project_management.lifecycle import create_project
from agentkit.backend.state_backend.store import facade
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.backend.state_backend.store.story_dependency_repository import (
    StateBackendStoryDependencyRepository,
)
from agentkit.backend.state_backend.store.story_repository import (
    StateBackendIdempotencyKeyRepository,
    StateBackendStoryRepository,
)
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import (
    CreateStoryInput,
    WireStoryType,
)
from agentkit.backend.story_context_manager.types import StoryType

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT = "tenant-a"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    facade.reset_backend_cache_for_tests()


def _story_service(tmp_path: Path) -> StoryService:
    return StoryService(
        story_repository=StateBackendStoryRepository(tmp_path),
        project_repository=StateBackendProjectRepository(tmp_path),
        idempotency_repository=StateBackendIdempotencyKeyRepository(tmp_path),
        dependency_repository=StateBackendStoryDependencyRepository(tmp_path),
        event_emitter=lambda *_: None,
    )


def _seed_project(tmp_path: Path) -> None:
    repo = StateBackendProjectRepository(tmp_path)
    config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        default_worker_count=2,
        repositories=["repo-a"],
    )
    repo.save(
        create_project(_PROJECT, "Tenant A", "AG3", config, repositories=["repo-a"]),
    )


def test_setup_builds_context_from_story_service_without_github(tmp_path: Path) -> None:
    """AC2: a code-producing story's context is built from the real Story-Service.

    The created story is read back through ``build_story_context`` with a REAL
    ``StoryService`` + SQLite backend — no GitHub issue, no fake repo.
    """
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)
    created = svc.create_story(
        CreateStoryInput(
            project_key=_PROJECT,
            title="Code-producing story without any GitHub issue",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["repo-a"],
        ),
        op_id="op-ac2-001",
    )

    ctx = build_story_context(
        tmp_path,
        _PROJECT,
        created.story_display_id,
        story_service=svc,
    )

    assert ctx.story_id == created.story_display_id
    assert ctx.story_type is StoryType.IMPLEMENTATION
    assert ctx.title == "Code-producing story without any GitHub issue"
    assert ctx.project_root == tmp_path
    # The GitHub-issue-derived story key is fully gone from the model.
    assert not hasattr(ctx, "issue_nr")


def test_setup_package_no_longer_reads_github_issues() -> None:
    """AC2: the setup context builder no longer imports/exposes ``get_issue``.

    The GitHub issue CRUD adapter was removed; the github package exports only
    the code-backend client surface.
    """
    from agentkit.integration_clients import github

    assert not hasattr(context_builder, "get_issue")
    assert not hasattr(github, "get_issue")
    assert "get_issue" not in getattr(github, "__all__", [])


def test_setup_fails_closed_on_unresolvable_story_identity(tmp_path: Path) -> None:
    """AC3: an unknown AK3 story identity fails Setup closed (real Story-Service).

    A missing GitHub issue is no longer a failure reason; an unresolvable
    ``story_id`` is. The fail-closed gate raises ``StoryModeResolutionError``
    rather than fabricating stammdaten.
    """
    _seed_project(tmp_path)
    svc = _story_service(tmp_path)

    with pytest.raises(StoryModeResolutionError):
        build_story_context(
            tmp_path,
            _PROJECT,
            "AG3-99999",
            story_service=svc,
        )
