"""Integration: the ``skill_usage_check`` guard-hook is dispatched through the
REAL ``run_hook`` pre-dispatch and consumes the REAL Skills binding surface
(AG3-086 AC2 / AC2b, FK-43 §43.6.2 / F-43-030).

A bound matching skill + an ad-hoc tool call -> fail-closed BLOCK from the
governance owner that emits an ``integrity_violation`` (``guard="skill_usage_check"``,
NO ``stage``). The same ad-hoc call with NO bound skill -> allow (the norm cannot
force usage of an unbound skill).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.backend.governance.guard_evaluation import HookEvent
from agentkit.backend.governance.runner import run_hook
from agentkit.backend.skills.binding import (
    SkillBinding,
    SkillBindingMode,
    SkillLifecycleStatus,
)
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.skill_binding_repository import (
    StateBackendSkillBindingRepository,
)
from agentkit.backend.telemetry.events import EventType, validate_event_payload
from agentkit.backend.telemetry.storage import StateBackendEmitter
from agentkit.harness_client.projectedge.client import LocalEdgePublisher

if TYPE_CHECKING:
    from collections.abc import Generator

_STORY = "AG3-300"
_RUN = "run-300"
_SESSION = "sess-300"


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _publish_binding(project_root: Path, worktree: str) -> None:
    project_key = project_root.stem
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    bundle = EdgeBundle(
        current=EdgePointer(
            project_key=project_key,
            export_version="edge-300",
            operating_mode="story_execution",
            bundle_dir="_temp/governance/bundles/edge-300",
            sync_after=now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=SessionRunBindingView(
            session_id=_SESSION,
            project_key=project_key,
            story_id=_STORY,
            run_id=_RUN,
            principal_type="worker",
            worktree_roots=[worktree],
            binding_version="bind-300",
            operating_mode="story_execution",
        ),
        lock=StoryExecutionLockView(
            project_key=project_key,
            story_id=_STORY,
            run_id=_RUN,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=[worktree],
            binding_version="bind-300",
            activated_at=now,
            updated_at=now,
        ),
        qa_lock=None,
    )
    LocalEdgePublisher(project_root=project_root).publish(bundle)


def _bind_skill(project_root: Path, skill_name: str) -> None:
    StateBackendSkillBindingRepository(project_root).save(
        SkillBinding(
            binding_id=f"bid-{skill_name}",
            project_key=project_root.stem,
            skill_name=skill_name,
            bundle_id="bundle-x",
            bundle_version="4.0.0",
            target_path=project_root / ".claude" / "skills" / skill_name,
            binding_mode=SkillBindingMode.JUNCTION,
            status=SkillLifecycleStatus.VERIFIED,
            pinned_at=datetime.now(UTC),
        )
    )


def _bash_event(worktree: str, command: str) -> HookEvent:
    return HookEvent.model_validate(
        {
            "operation": "bash_command",
            "freshness_class": "guarded_read",
            "cwd": worktree,
            "session_id": _SESSION,
            "principal_kind": "subagent",
            "cli_args": ["--ak3-principal-attest", "worker"],
            "operation_args": {"command": command},
        }
    )


def _violations(project_root: Path) -> list[object]:
    story_dir = project_root / "stories" / _STORY
    return [
        e.payload
        for e in StateBackendEmitter(
            story_dir, default_project_key=project_root.stem
        ).query(_STORY, EventType.INTEGRITY_VIOLATION)
    ]


def test_bound_skill_ad_hoc_call_blocks_and_emits_integrity_violation(
    tmp_path: Path,
) -> None:
    worktree = str(tmp_path / "worktree")
    Path(worktree).mkdir()
    _publish_binding(tmp_path, worktree)
    _bind_skill(tmp_path, "semantic-review")

    verdict = run_hook(
        "skill_usage_check",
        _bash_event(worktree, "agentkit semantic-review --file src/x.py"),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "skill_usage_check"
    payloads = _violations(tmp_path)
    assert len(payloads) == 1
    assert payloads[0]["guard"] == "skill_usage_check"  # type: ignore[index]
    assert "stage" not in payloads[0]  # type: ignore[operator]
    validate_event_payload(EventType.INTEGRITY_VIOLATION, payloads[0])  # type: ignore[arg-type]


def test_unbound_skill_ad_hoc_call_allows(tmp_path: Path) -> None:
    worktree = str(tmp_path / "worktree")
    Path(worktree).mkdir()
    _publish_binding(tmp_path, worktree)
    # No _bind_skill -> the matching skill is NOT bound -> allow.

    verdict = run_hook(
        "skill_usage_check",
        _bash_event(worktree, "agentkit semantic-review --file src/x.py"),
        phase="pre",
        project_root=tmp_path,
    )

    assert verdict.allowed is True
    assert _violations(tmp_path) == []


def test_skill_marker_present_allows(tmp_path: Path) -> None:
    worktree = str(tmp_path / "worktree")
    Path(worktree).mkdir()
    _publish_binding(tmp_path, worktree)
    _bind_skill(tmp_path, "semantic-review")

    event = HookEvent.model_validate(
        {
            "operation": "bash_command",
            "freshness_class": "guarded_read",
            "cwd": worktree,
            "session_id": _SESSION,
            "principal_kind": "subagent",
            "cli_args": [
                "--ak3-principal-attest",
                "worker",
                "--via-skill=semantic-review",
            ],
            "operation_args": {"command": "agentkit semantic-review --file src/x.py"},
        }
    )
    verdict = run_hook(
        "skill_usage_check", event, phase="pre", project_root=tmp_path
    )

    assert verdict.allowed is True
    assert _violations(tmp_path) == []
