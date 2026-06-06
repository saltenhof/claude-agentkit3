"""Integration: ``review_guard`` is a PreToolUse BLOCKING hook (AG3-036 FIX-1/FIX-2).

FK-68 §68.3.1 / AG3-036 §2.1.5: the double-role ReviewGuard owns the
``review_guard`` pre-hook. The runner resolves the story binding from the local
edge bundle, resolves the mandatory reviewer roles AUTHORITATIVELY from
``pipeline.review.required_roles`` (NOT a forgeable ``operation_args`` payload),
builds the guard over the canonical state backend and returns its verdict. A
DENY blocks the ``git commit`` BEFORE it runs (a PostToolUse DENY could not —
fail-open).

Wiring + ordering:
- ``review_guard`` lives in ``PRE_HOOK_IDS`` (not ``POST_HOOK_IDS``).
- The pre dispatch runs AFTER capability enforcement (AG3-032 fail-closed
  ordering NOT regressed). The capability layer has its own end-to-end tests
  (``test_hook_wrapper.py``); here we isolate the review-guard wiring by letting
  the capability step ALLOW (return ``None``) so the review-guard verdict is the
  one ``run_hook`` surfaces — proving the DENY actually blocks the commit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.governance import runner as runner_mod
from agentkit.governance.guard_evaluation import HookEvent
from agentkit.governance.runner import POST_HOOK_IDS, PRE_HOOK_IDS, run_hook
from agentkit.projectedge.client import LocalEdgePublisher
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.state_backend.store.story_repository import StateBackendStoryRepository
from agentkit.story_context_manager.story_model import Story, WireStoryType
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.storage import StateBackendEmitter

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "tenant-a"
_STORY = "AG3-100"
_RUN = "run-100"
_SESSION = "sess-001"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.fixture()
def _capability_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the review-guard wiring: let capability enforcement ALLOW.

    The capability layer legitimately runs FIRST and would default-deny a
    ``git commit`` in a synthetic worktree; its own enforcement is covered by
    ``test_hook_wrapper.py``. Returning ``None`` (matrix-permitted) lets the
    pre dispatch reach ``_run_review_guard`` so we verify the review-guard
    verdict is the one ``run_hook`` surfaces.
    """
    monkeypatch.setattr(
        runner_mod,
        "_run_capability_enforcement",
        lambda event, *, project_root: None,
    )


def _write_project_config(project_root: Path, *, required_roles: list[str]) -> None:
    """Write a minimal project.yaml carrying pipeline.review.required_roles."""
    import yaml

    config_dir = project_root / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.yaml").write_text(
        yaml.safe_dump(
            {
                "project_key": _PROJECT,
                "project_name": "Tenant A",
                "repositories": [{"name": "repo", "path": str(project_root / "repo")}],
                # concept-only avoids the code-producing sonarqube/ci stanza
                # requirement; the review.required_roles authority is what matters.
                "story_types": ["concept"],
                "pipeline": {"review": {"required_roles": list(required_roles)}},
            }
        ),
        encoding="utf-8",
    )


def _save_story(
    project_root: Path, story_type: WireStoryType = WireStoryType.IMPLEMENTATION
) -> None:
    """Persist a canonical Story record into the story store (default: code-producing)."""
    StateBackendStoryRepository(project_root).save(
        Story(
            project_key=_PROJECT,
            story_number=100,
            story_display_id=_STORY,
            title="t",
            story_type=story_type,
            participating_repos=["repo"],
            created_at=datetime.now(UTC),
        ),
    )


def _publish_story_binding(project_root: Path, worktree: str) -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bundle = EdgeBundle(
        current=EdgePointer(
            project_key=_PROJECT,
            export_version="edge-001",
            operating_mode="story_execution",
            bundle_dir="_temp/governance/bundles/edge-001",
            sync_after=now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=SessionRunBindingView(
            session_id=_SESSION,
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            principal_type="worker",
            worktree_roots=[worktree],
            binding_version="bind-001",
            operating_mode="story_execution",
        ),
        lock=StoryExecutionLockView(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=[worktree],
            binding_version="bind-001",
            activated_at=now,
            updated_at=now,
        ),
        qa_lock=None,
    )
    LocalEdgePublisher(project_root=project_root).publish(bundle)


def _commit_event(worktree: str) -> HookEvent:
    return HookEvent.model_validate(
        {
            "operation": "bash_command",
            "freshness_class": "guarded_read",
            "cwd": worktree,
            "session_id": _SESSION,
            "principal_kind": "subagent",
            "operation_args": {"command": "git commit -m 'inc'"},
        }
    )


def test_review_guard_is_a_pre_hook_not_post() -> None:
    # FIX-1: review_guard moved from POST to PRE so a DENY blocks the commit.
    assert "review_guard" in PRE_HOOK_IDS
    assert "review_guard" not in POST_HOOK_IDS


def test_review_guard_denies_on_missing_role(
    tmp_path: Path, _capability_allows: None
) -> None:
    worktree = str(tmp_path / "worktree")
    _write_project_config(tmp_path, required_roles=["qa"])
    _save_story(tmp_path)
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook(
        "review_guard",
        _commit_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )

    # The DENY blocks the commit BEFORE it runs (fail-closed pre-dispatch).
    assert verdict.allowed is False
    assert verdict.guard_name == "review_guard"
    assert "review_not_compliant" in (verdict.message or "")


def test_review_guard_allows_when_role_compliant(
    tmp_path: Path, _capability_allows: None
) -> None:
    worktree = str(tmp_path / "worktree")
    _write_project_config(tmp_path, required_roles=["qa"])
    _save_story(tmp_path)
    _publish_story_binding(tmp_path, worktree)

    # Seed a qa review_compliant event into the canonical backend.
    story_dir = tmp_path / "stories" / _STORY
    StateBackendEmitter(story_dir, default_project_key=_PROJECT).emit(
        Event(
            story_id=_STORY,
            event_type=EventType.REVIEW_COMPLIANT,
            timestamp=datetime.now(UTC),
            project_key=_PROJECT,
            run_id=_RUN,
            payload={"reviewer_role": "qa"},
        )
    )

    verdict = run_hook(
        "review_guard",
        _commit_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is True
    assert verdict.guard_name == "review_guard"


def test_review_guard_allows_when_no_binding(
    tmp_path: Path, _capability_allows: None
) -> None:
    # No published binding -> the pre-hook stays observational (allow); the
    # capability chain already governs an inconsistent binding fail-closed.
    verdict = run_hook(
        "review_guard",
        HookEvent.model_validate(
            {
                "operation": "bash_command",
                "freshness_class": "guarded_read",
                "cwd": str(tmp_path),
                "operation_args": {"command": "git commit -m x"},
            }
        ),
        phase="pre",
        project_root=tmp_path,
    )
    assert verdict.allowed is True


def test_review_guard_denies_when_config_unavailable_for_code_story(
    tmp_path: Path, _capability_allows: None
) -> None:
    # FIX-2 fail-closed: an active code-producing story whose review config
    # cannot be loaded must NOT silently allow.
    worktree = str(tmp_path / "worktree")
    _save_story(tmp_path)  # implementation story, but NO project.yaml
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook(
        "review_guard",
        _commit_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "review_guard"
    assert "review_config_unavailable" in (verdict.message or "")


def test_review_guard_denies_on_unresolved_story_type(
    tmp_path: Path, _capability_allows: None
) -> None:
    # FIX-C: an ACTIVE binding whose story record is UNRESOLVED (binding published
    # but NO Story record -> missing record) must fail-closed BLOCK, NOT downgrade
    # to a non-code allow.
    worktree = str(tmp_path / "worktree")
    _write_project_config(tmp_path, required_roles=["qa"])
    _publish_story_binding(tmp_path, worktree)  # no _save_story -> UNRESOLVED

    verdict = run_hook(
        "review_guard",
        _commit_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "review_guard"
    assert "story_type_unresolved" in (verdict.message or "")


def test_review_guard_denies_on_empty_required_roles_for_code_story(
    tmp_path: Path, _capability_allows: None
) -> None:
    # FIX-C: a RESOLVED code story with EMPTY required_roles provides no coverage
    # and must NOT be treated as fully compliant -> fail-closed BLOCK.
    worktree = str(tmp_path / "worktree")
    _write_project_config(tmp_path, required_roles=[])
    _save_story(tmp_path)  # implementation (code-producing)
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook(
        "review_guard",
        _commit_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "review_guard"
    assert "review_required_roles_empty" in (verdict.message or "")


def test_review_guard_allows_non_code_story(
    tmp_path: Path, _capability_allows: None
) -> None:
    # FIX-C: a RESOLVED non-code story takes the non_code_story allow path
    # (distinct from the UNRESOLVED block) regardless of required_roles config.
    worktree = str(tmp_path / "worktree")
    _write_project_config(tmp_path, required_roles=["qa"])
    _save_story(tmp_path, WireStoryType.RESEARCH)
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook(
        "review_guard",
        _commit_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is True
    assert verdict.guard_name == "review_guard"


def test_capability_block_precedes_review_guard(tmp_path: Path) -> None:
    # AG3-032 fail-closed ordering NOT regressed: WITHOUT the capability bypass a
    # synthetic-worktree git commit is blocked by the capability layer FIRST
    # (the review guard never softens a hard capability DENY).
    worktree = str(tmp_path / "worktree")
    _write_project_config(tmp_path, required_roles=["qa"])
    _save_story(tmp_path)
    _publish_story_binding(tmp_path, worktree)

    verdict = run_hook(
        "review_guard",
        _commit_event(worktree),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "principal_capability"
