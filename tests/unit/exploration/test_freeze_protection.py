"""The freeze makes the change-frame write-protected (AG3-047 / FK-23 §23.4.3).

Proves the closed loop: the freeze trigger (``DesignFreezeMarker``) derives the
guard-context freeze signals from the persisted frozen frame, and the REAL
``ArtifactGuard`` (governance) then BLOCKS a sub-agent write to the protected
``change_frame.json`` once ``change_frame_frozen=true``. Before the freeze (an
explicitly-not-frozen frame) the same write is allowed (FK-25 §25.4.2 editable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from tests.exploration_change_frame_fixture import EXAMPLE_RUN_ID, example_change_frame

from agentkit.core_types.qa_artifact_names import CHANGE_FRAME_FILE
from agentkit.exploration.freeze import DesignFreezeMarker
from agentkit.governance.guards.artifact_guard import ArtifactGuard
from agentkit.governance.protocols import ViolationType

if TYPE_CHECKING:
    from agentkit.exploration.change_frame import ChangeFrame


@dataclass
class _RecordingWriter:
    written: list[ChangeFrame] = field(default_factory=list)

    def write_change_frame_file(
        self, story_dir: Path, *, story_id: str, run_id: str, frame: ChangeFrame
    ) -> Path:
        del story_dir, story_id, run_id
        self.written.append(frame)
        return Path("_temp/qa") / CHANGE_FRAME_FILE


def _subagent_write_context(
    story_id: str, *, freeze_signals: dict[str, object]
) -> dict[str, object]:
    """Build a sub-agent change_frame.json write context + freeze signals."""
    return {
        "operating_mode": "story_execution",
        "principal_kind": "subagent",
        "active_story_id": story_id,
        "file_path": f"_temp/qa/{story_id}/{CHANGE_FRAME_FILE}",
        **freeze_signals,
    }


def test_frozen_change_frame_write_is_blocked() -> None:
    """After freeze, a sub-agent write to change_frame.json is BLOCKED."""
    frozen = example_change_frame(story_id="AG3-047").model_copy(
        update={"frozen": True}
    )
    signals = DesignFreezeMarker.guard_context_signals(frozen)
    guard = ArtifactGuard()

    verdict = guard.evaluate(
        "file_write",
        _subagent_write_context("AG3-047", freeze_signals=signals),
    )

    assert verdict.allowed is False
    assert verdict.violation_type is ViolationType.ARTIFACT_TAMPERING


def test_unfrozen_change_frame_write_is_allowed() -> None:
    """Before freeze (explicitly not frozen), the same write is allowed."""
    unfrozen = example_change_frame(story_id="AG3-047")  # frozen=False
    signals = DesignFreezeMarker.guard_context_signals(unfrozen)
    guard = ArtifactGuard()

    verdict = guard.evaluate(
        "file_write",
        _subagent_write_context("AG3-047", freeze_signals=signals),
    )

    assert verdict.allowed is True


def test_unknown_freeze_state_is_blocked_fail_closed() -> None:
    """An unknown freeze state (no signals) is blocked fail-closed (ARCH-48)."""
    guard = ArtifactGuard()

    verdict = guard.evaluate(
        "file_write",
        _subagent_write_context("AG3-047", freeze_signals={}),
    )

    assert verdict.allowed is False
    assert verdict.violation_type is ViolationType.ARTIFACT_TAMPERING


def test_real_freeze_marker_produces_blocking_signals() -> None:
    """The freeze marker's OWN output (not a hand-built frame) drives the block."""
    writer = _RecordingWriter()
    marker = DesignFreezeMarker(writer=writer, clock=lambda: datetime.now(UTC))
    frozen = marker.freeze(
        example_change_frame(story_id="AG3-047"),
        Path("story"),
        story_id="AG3-047",
        run_id=EXAMPLE_RUN_ID,
    )
    signals = DesignFreezeMarker.guard_context_signals(frozen)

    verdict = ArtifactGuard().evaluate(
        "file_write",
        _subagent_write_context("AG3-047", freeze_signals=signals),
    )

    assert verdict.allowed is False
