"""AG3-126 regression: build_project_read_model_routes honors store_dir.

Guards the AG3-126 AC3 wiring-purity gap found in adversarial review: the
composition-root ``build_project_read_model_routes(store_dir)`` threads
``store_dir`` into the project / config / are-link repositories but previously
left ``ReadModelRoutes.phase_state_loader`` on its cwd-defaulting default
factory. The phase-state read (``/stories/{id}/flow``) then resolved against
``Path.cwd()`` instead of the configured store root, reading the WRONG SQLite DB.

This test persists a phase-state under ``tmp_path`` ONLY, runs from a DIFFERENT
empty CWD, and asserts the route's ``phase_state_loader`` resolves against the
injected ``store_dir`` (``tmp_path``) — never CWD.

The round-2 adversarial review (Codex) found that the SAME builder still wired
``story_service=StoryService()`` with NO store_dir, so its
``StateBackendStoryRepository`` defaulted to ``Path.cwd()``. ``_handle_flow``
calls ``story_service.get_story`` BEFORE the (already-fixed) phase_state_loader,
so the FULL ``/flow`` read could still return ``story_not_found`` for a story
persisted only under ``store_dir``. ``test_build_routes_full_flow_route_*``
drives the complete route through the builder and proves the story RESOLVES.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import build_project_read_model_routes
from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus
from agentkit.backend.project_management.entities import ProjectConfiguration
from agentkit.backend.project_management.lifecycle import create_project
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.pipeline_runtime_store import save_phase_state
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    InMemoryInflightIdempotencyGuard,
)
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.backend.state_backend.store.story_dependency_repository import (
    StateBackendStoryDependencyRepository,
)
from agentkit.backend.state_backend.store.story_read_repository import (
    StateBackendStoryReadRepository,
)
from agentkit.backend.state_backend.store.story_repository import (
    StateBackendStoryRepository,
)
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import CreateStoryInput

if TYPE_CHECKING:
    from pathlib import Path

from tests.phase_state_factory import make_phase_state

_STORY = "AG3-126"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()


def test_read_model_routes_phase_state_loader_honors_store_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    # Persist the phase-state under store_dir ONLY.
    save_phase_state(
        store_dir,
        make_phase_state(
            story_id=_STORY,
            phase="implementation",
            status=PhaseStatus.IN_PROGRESS,
        ),
    )

    # Run from a DIFFERENT empty CWD: a cwd-defaulting read (store_dir=None)
    # would resolve here (Path.cwd()) and find nothing.
    monkeypatch.chdir(cwd)

    # Guard the premise: the persisted state is NOT in CWD, so the cwd-defaulting
    # default (the pre-fix behavior) genuinely sees None.
    assert StateBackendStoryReadRepository().load_phase_state(_STORY) is None

    routes = build_project_read_model_routes(store_dir=store_dir)
    phase_state = routes.phase_state_loader(_STORY)

    assert phase_state is not None, (
        "phase_state_loader must resolve against the injected store_dir, "
        "not Path.cwd()"
    )
    assert phase_state.phase == "implementation"
    assert phase_state.status is PhaseStatus.IN_PROGRESS


def _store_scoped_story_service(store_dir: Path) -> StoryService:
    """Build a StoryService whose every state-backend repo targets store_dir."""
    return StoryService(
        story_repository=StateBackendStoryRepository(store_dir),
        project_repository=StateBackendProjectRepository(store_dir),
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        dependency_repository=StateBackendStoryDependencyRepository(store_dir),
        event_emitter=lambda *_: None,
    )


def _seed_project(store_dir: Path, *, key: str, prefix: str) -> None:
    config = ProjectConfiguration(
        repo_url="",
        default_branch="main",
        default_worker_count=1,
        repositories=["repo-a"],
    )
    StateBackendProjectRepository(store_dir).save(
        create_project(key, "Tenant A", prefix, config, repositories=["repo-a"]),
    )


def test_build_routes_full_flow_route_resolves_story_from_store_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """FULL /flow read through build_project_read_model_routes(store_dir).

    Round-2 regression: ``_handle_flow`` calls ``story_service.get_story`` BEFORE
    the phase_state_loader. Persist project + story + phase-state under
    ``store_dir`` ONLY, run from a DIFFERENT empty CWD, and drive the complete
    route. With the cwd-defaulting ``StoryService()`` (pre-fix) the story read
    resolves against ``Path.cwd()`` and returns ``story_not_found``; after the
    fix the builder threads ``store_dir`` into every state-backend repo the
    service uses for reads, so the route RESOLVES the story and renders the
    persisted phases.
    """
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    _seed_project(store_dir, key="tenant-a", prefix="AG3")
    svc = _store_scoped_story_service(store_dir)
    story = svc.create_story(
        CreateStoryInput(
            project_key="tenant-a",
            title="Full-route flow story",
            type="implementation",
            repos=["repo-a"],
        ),
        op_id="op-full-flow",
    )
    # In Progress so position-based flow derivation runs over the phase state.
    svc.approve_story(story.story_display_id, op_id="op-approve-full-flow")
    svc.begin_progress(story.story_display_id)

    save_phase_state(
        store_dir,
        make_phase_state(
            story_id=story.story_display_id,
            phase="implementation",
            status=PhaseStatus.IN_PROGRESS,
        ),
    )

    # Run from a DIFFERENT empty CWD: a cwd-defaulting story read (the pre-fix
    # StoryService()) would resolve here and never find the story.
    monkeypatch.chdir(cwd)

    # Guard the premise: a cwd-defaulting story service genuinely sees nothing.
    assert _store_scoped_story_service(cwd).get_story(story.story_display_id) is None

    routes = build_project_read_model_routes(store_dir=store_dir)
    response = routes.handle_get(
        f"/v1/projects/tenant-a/stories/{story.story_display_id}/flow",
        {},
        "req-full-flow",
    )

    assert response is not None
    assert response.status_code == HTTPStatus.OK, (
        f"FULL /flow read must RESOLVE the store-scoped story, got "
        f"{response.status_code}: {response.body.decode('utf-8')}"
    )
    import json

    body = json.loads(response.body.decode("utf-8"))
    snapshot = body["story_flow_snapshot"]
    assert snapshot["story_id"] == story.story_display_id
    phases = {p["phase"]: p for p in snapshot["phases"]}
    # Persisted implementation phase-state renders as active (not all-pending).
    assert phases["implementation"]["state"] == "active"
    assert phases["setup"]["state"] == "done"
