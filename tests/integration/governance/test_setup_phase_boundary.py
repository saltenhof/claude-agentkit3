"""Integration test — Setup phase boundary drives the REAL handler (AG3-120).

AG3-120 AC2/AC3 at the *phase boundary* (testing-guardrails §1/§3): instead of
calling ``build_story_context`` directly, this test drives the real
``SetupPhaseHandler.on_enter(...)`` (wired through the composition root) with a
REAL ``StoryService`` backed by a REAL SQLite state-backend — no fake/in-memory
repo. AK3 owns the user story via ``story_id``; GitHub is only the code backend
(FK-12 §12.1.1, FK-91 §91.2 rule 9).

* AC2: a code-producing story runs through Setup with NO issue input; the
  enriched, persisted context is built from ``story_id`` + Story-Service
  attributes (the setup package no longer imports/exposes ``get_issue``), and
  the persisted context carries no ``issue_nr``.
* AC3: an unknown/unresolvable ``story_id`` FAILS CLOSED at the phase boundary
  (negative-path test) — a missing GitHub issue is no longer a failure reason.

This is the non-e2e companion to ``tests/e2e/github_live/test_setup_phase.py``:
it is hermetic to ``tmp_path`` (the StoryService is bound to ``tmp_path`` and
injected via ``SetupConfig`` so preflight, context-build and ``begin_progress``
all read/write the per-test SQLite backend, never the global cwd store).
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.backend.bootstrap.composition_root import build_setup_phase_handler
from agentkit.backend.governance.setup_preflight_gate import context_builder
from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig
from agentkit.backend.governance.setup_preflight_gate.preflight import PreflightCheckId
from agentkit.backend.installer import InstallConfig, install_agentkit
from agentkit.backend.installer.paths import story_dir
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus
from agentkit.backend.state_backend.store import (
    facade,
    read_story_context_record,
)
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    InMemoryInflightIdempotencyGuard,
)
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.backend.state_backend.store.story_dependency_repository import (
    StateBackendStoryDependencyRepository,
)
from agentkit.backend.state_backend.store.story_repository import (
    StateBackendStoryRepository,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import (
    Story,
    StoryStatus,
    WireStoryType,
)
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "test"
_SEED_NAMESPACE = uuid5(NAMESPACE_URL, "agentkit3-ag3120-setup-boundary")


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    facade.reset_backend_cache_for_tests()
    yield
    facade.reset_backend_cache_for_tests()


def _init_repo(root: Path) -> None:
    """Init a real git repo (Preflight Check 7 reads it, AG3-034 Finding B)."""
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "t@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)


def _story_service(project_root: Path) -> StoryService:
    """Build a REAL StoryService bound to ``project_root`` (no fake repo)."""
    return StoryService(
        story_repository=StateBackendStoryRepository(project_root),
        project_repository=StateBackendProjectRepository(project_root),
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        dependency_repository=StateBackendStoryDependencyRepository(project_root),
        event_emitter=lambda *_: None,
    )


def _seed_approved_story(
    project_root: Path,
    *,
    story_display_id: str,
    story_number: int,
    title: str,
) -> None:
    """Persist an APPROVED Story via the real tmp_path-bound repository."""
    story = Story(
        story_uuid=uuid5(_SEED_NAMESPACE, story_display_id),
        project_key=_PROJECT,
        story_number=story_number,
        story_display_id=story_display_id,
        title=title,
        story_type=WireStoryType.IMPLEMENTATION,
        status=StoryStatus.APPROVED,
        participating_repos=["agentkit3-testbed"],
        created_at=datetime.now(UTC),
    )
    StateBackendStoryRepository(project_root).save(story)


def _install(project_root: Path) -> None:
    install_agentkit(
        InstallConfig(
            project_key=_PROJECT,
            project_name=_PROJECT,
            project_root=project_root,
            github_owner="acme",  # AG3-039 R6: CP 7 coordinates are MANDATORY
            github_repo="demo",
            sonarqube_available=False,  # AG3-052: conscious opt-out, no live Sonar
            ci_available=False,  # AG3-056: conscious opt-out, no live Jenkins
        )
    )


def test_setup_phase_builds_context_from_story_service_no_issue(
    tmp_path: Path,
) -> None:
    """AC2: a code-producing story runs through the REAL setup phase, no issue.

    The enriched context is built from ``story_id`` + the Story-Service record;
    the setup package reads no GitHub issue and the persisted context carries no
    ``issue_nr``.
    """
    _install(tmp_path)
    _init_repo(tmp_path)

    svc = _story_service(tmp_path)
    _seed_approved_story(
        tmp_path,
        story_display_id="TEST-001",
        story_number=1,
        title="Code-producing story without any GitHub issue",
    )

    config = SetupConfig(
        project_root=tmp_path,
        story_id="TEST-001",
        create_worktree=False,
        story_service=svc,  # hermetic: the handler reads/writes tmp_path
    )
    handler = build_setup_phase_handler(config, store_dir=tmp_path)

    ctx = StoryContext(
        project_key=_PROJECT,
        story_id="TEST-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=tmp_path,
    )
    state = make_phase_state(
        story_id="TEST-001", phase="setup", status=PhaseStatus.IN_PROGRESS
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

    assert result.status is PhaseStatus.COMPLETED, result.errors
    # The enriched context was persisted from the Story-Service record.
    s_dir = story_dir(tmp_path, "TEST-001")
    loaded = read_story_context_record(s_dir)
    assert loaded is not None
    assert loaded.story_id == "TEST-001"
    assert loaded.title == "Code-producing story without any GitHub issue"
    assert not hasattr(loaded, "issue_nr")
    # The setup package no longer reads GitHub issues.
    assert not hasattr(context_builder, "get_issue")
    # begin_progress ran: the story is now In Progress (FK-22 §22.4.3).
    transitioned = svc.get_story("TEST-001")
    assert transitioned is not None
    assert transitioned.status is StoryStatus.IN_PROGRESS


def test_setup_phase_fails_closed_on_unresolvable_story_identity(
    tmp_path: Path,
) -> None:
    """AC3: an unknown ``story_id`` fails Setup closed at the phase boundary.

    No Story-Service record is seeded, so the preflight identity gate
    (STORY_EXISTS) fails closed -- a missing GitHub issue is no longer a failure
    reason; the unresolvable AK3 story identity is (testing-guardrails §1/§3).
    """
    _install(tmp_path)
    _init_repo(tmp_path)

    svc = _story_service(tmp_path)  # empty: no seeded story

    config = SetupConfig(
        project_root=tmp_path,
        story_id="FAIL-404",
        create_worktree=False,
        story_service=svc,
    )
    handler = build_setup_phase_handler(config, store_dir=tmp_path)

    ctx = StoryContext(
        project_key=_PROJECT,
        story_id="FAIL-404",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=tmp_path,
    )
    state = make_phase_state(
        story_id="FAIL-404", phase="setup", status=PhaseStatus.IN_PROGRESS
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

    assert result.status is PhaseStatus.FAILED
    assert len(result.errors) > 0

    # Prove the SPECIFIC fail-closed identity gate fired -- not just "any" setup
    # failure. The STORY_EXISTS preflight check (FK-22 §22.3.1, Check 1) must be
    # the failing check, and its message must name the unknown story_id as not
    # found in the StoryService (story_exists.py builds exactly that detail).
    story_exists_id = PreflightCheckId.STORY_EXISTS.value
    identity_errors = [
        e for e in result.errors if e.startswith(f"{story_exists_id}:")
    ]
    assert identity_errors, (
        f"expected a {story_exists_id!r} failure, got errors: {result.errors}"
    )
    assert any(
        "not found in StoryService" in e and "FAIL-404" in e for e in identity_errors
    ), f"expected a story-not-found-in-StoryService message, got: {identity_errors}"

    # Fail-closed: no enriched StoryContext was persisted for the unknown story.
    assert read_story_context_record(story_dir(tmp_path, "FAIL-404")) is None
