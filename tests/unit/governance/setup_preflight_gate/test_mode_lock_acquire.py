"""Setup-phase mode-lock acquire wiring tests (AG3-018 DELTA-E, FK-24 §24.3.3).

Setup atomically ACQUIRES the project mode-lock on the preflight PASS success
path (the enforcement half of the between-modes mutex). Idempotent per story via
a durable acquire marker: a re-run does not double-increment the holder count.
An opposite mode already held fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.backend.governance.setup_preflight_gate.mode_lock_marker import (
    acquired_mode,
    mode_lock_acquired,
)
from agentkit.backend.governance.setup_preflight_gate.phase import (
    SetupConfig,
    SetupPhaseHandler,
)
from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus
from agentkit.backend.state_backend.store.mode_lock_repository import ModeLockConflictError
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import WireStoryMode
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class _RecordingModeLockRepo:
    """Recording mode-lock repository double (acquire path)."""

    conflict: bool = False
    acquired: list[tuple[str, str]] = field(default_factory=list)
    released: list[tuple[str, str]] = field(default_factory=list)

    def read_lock(self, project_key: str) -> object:
        del project_key
        return None

    def acquire(self, project_key: str, mode: str) -> object:
        if self.conflict:
            raise ModeLockConflictError("opposite mode held")
        self.acquired.append((project_key, mode))
        return object()

    def release(self, project_key: str, mode: str) -> object:
        self.released.append((project_key, mode))
        return object()


def _handler(repo: _RecordingModeLockRepo, project_root: Path) -> SetupPhaseHandler:
    cfg = SetupConfig(
        project_root=project_root,
        story_id="AG3-018",
    )

    class _Ctx:
        def save(self, story_dir: Path, ctx: object) -> None:
            del story_dir, ctx

    return SetupPhaseHandler(
        cfg,
        context_repository=_Ctx(),  # type: ignore[arg-type]
        mode_lock_repository=repo,  # type: ignore[arg-type]
    )


def _ctx(mode: WireStoryMode) -> StoryContext:
    return StoryContext(
        project_key="proj",
        story_id="AG3-018",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        mode=mode,
    )


def test_acquire_fast_records_mode_and_marker(tmp_path: Path) -> None:
    repo = _RecordingModeLockRepo()
    handler = _handler(repo, tmp_path)
    err = handler._acquire_mode_lock(_ctx(WireStoryMode.FAST), tmp_path)  # noqa: SLF001
    assert err is None
    assert repo.acquired == [("proj", "fast")]
    assert mode_lock_acquired(tmp_path) is True
    assert acquired_mode(tmp_path) == "fast"


def test_acquire_standard_records_standard(tmp_path: Path) -> None:
    repo = _RecordingModeLockRepo()
    handler = _handler(repo, tmp_path)
    err = handler._acquire_mode_lock(_ctx(WireStoryMode.STANDARD), tmp_path)  # noqa: SLF001
    assert err is None
    assert repo.acquired == [("proj", "standard")]


def test_acquire_is_idempotent_per_story(tmp_path: Path) -> None:
    repo = _RecordingModeLockRepo()
    handler = _handler(repo, tmp_path)
    handler._acquire_mode_lock(_ctx(WireStoryMode.FAST), tmp_path)  # noqa: SLF001
    # A re-run (durable marker present) must NOT double-acquire.
    handler._acquire_mode_lock(_ctx(WireStoryMode.FAST), tmp_path)  # noqa: SLF001
    assert repo.acquired == [("proj", "fast")]


def test_acquire_conflict_fails_closed(tmp_path: Path) -> None:
    repo = _RecordingModeLockRepo(conflict=True)
    handler = _handler(repo, tmp_path)
    err = handler._acquire_mode_lock(_ctx(WireStoryMode.FAST), tmp_path)  # noqa: SLF001
    assert err is not None
    assert err.status is PhaseStatus.FAILED
    assert any("no_competing_story_mode_active" in e for e in err.errors)
    # No marker written when the acquire failed.
    assert mode_lock_acquired(tmp_path) is False


def test_compensate_releases_freshly_acquired_holder(tmp_path: Path) -> None:
    """FIX-3: a begin_progress failure after a fresh acquire compensates (releases).

    The compensation path releases the holder this run took and clears the marker
    so the mutex does not leak a holder for a story that never went In Progress.
    """
    repo = _RecordingModeLockRepo()
    handler = _handler(repo, tmp_path)
    ctx = _ctx(WireStoryMode.FAST)
    assert handler._acquire_mode_lock(ctx, tmp_path) is None  # noqa: SLF001
    assert repo.acquired == [("proj", "fast")]
    assert mode_lock_acquired(tmp_path) is True
    # Simulate the on_enter compensation after begin_progress failed.
    handler._compensate_mode_lock(ctx, tmp_path)  # noqa: SLF001
    assert repo.released == [("proj", "fast")]
    # Marker cleared -> Closure owes no further release (no double-release).
    assert mode_lock_acquired(tmp_path) is False
    assert acquired_mode(tmp_path) is None


def test_acquire_skipped_without_repository(tmp_path: Path) -> None:
    cfg = SetupConfig(project_root=tmp_path)

    class _Ctx:
        def save(self, story_dir: Path, ctx: object) -> None:
            del story_dir, ctx

    handler = SetupPhaseHandler(cfg, context_repository=_Ctx())  # type: ignore[arg-type]
    err = handler._acquire_mode_lock(_ctx(WireStoryMode.FAST), tmp_path)  # noqa: SLF001
    assert err is None
    assert mode_lock_acquired(tmp_path) is False
