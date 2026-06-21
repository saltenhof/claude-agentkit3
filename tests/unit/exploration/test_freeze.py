"""Unit tests for DesignFreezeMarker (FK-23 §23.4.3, AG3-047 AC6).

Verifies the freeze builds a frozen successor (``frozen=True``, ``frozen_at`` from
the INJECTED clock), persists it via the writer port, and emits the guard-context
freeze signals. Real :class:`ChangeFrame`; a first-class in-test writer (records
the write -- the only stub allowed: the FS boundary port).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from tests.exploration_change_frame_fixture import EXAMPLE_RUN_ID, example_change_frame

from agentkit.backend.exploration.freeze import DesignFreezeMarker

if TYPE_CHECKING:
    from agentkit.backend.exploration.change_frame import ChangeFrame

_FROZEN_AT = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)


@dataclass
class _RecordingWriter:
    """First-class in-test ChangeFrameWriter (records the persisted frame)."""

    written: list[ChangeFrame] = field(default_factory=list)

    def write_change_frame_file(
        self, story_dir: Path, *, story_id: str, run_id: str, frame: ChangeFrame
    ) -> Path:
        del story_dir, story_id, run_id
        self.written.append(frame)
        return Path("_temp/qa") / "change_frame.json"


def test_freeze_sets_frozen_and_frozen_at() -> None:
    """freeze() builds a frozen successor with frozen=True + injected frozen_at."""
    writer = _RecordingWriter()
    marker = DesignFreezeMarker(writer=writer, clock=lambda: _FROZEN_AT)
    frame = example_change_frame(story_id="AG3-047")
    assert frame.frozen is False

    frozen = marker.freeze(
        frame, Path("story"), story_id="AG3-047", run_id=EXAMPLE_RUN_ID
    )

    assert frozen.frozen is True
    assert frozen.frozen_at == _FROZEN_AT
    # The original frame is unchanged (immutable successor build).
    assert frame.frozen is False


def test_freeze_persists_via_writer() -> None:
    """The frozen frame is materialized through the injected writer port."""
    writer = _RecordingWriter()
    marker = DesignFreezeMarker(writer=writer, clock=lambda: _FROZEN_AT)

    marker.freeze(
        example_change_frame(story_id="AG3-047"),
        Path("story"),
        story_id="AG3-047",
        run_id=EXAMPLE_RUN_ID,
    )

    assert len(writer.written) == 1
    assert writer.written[0].frozen is True


def test_guard_context_signals_from_frozen_frame() -> None:
    """guard_context_signals feeds change_frame_frozen + freeze_known=True."""
    writer = _RecordingWriter()
    marker = DesignFreezeMarker(writer=writer, clock=lambda: _FROZEN_AT)
    frozen = marker.freeze(
        example_change_frame(story_id="AG3-047"),
        Path("story"),
        story_id="AG3-047",
        run_id=EXAMPLE_RUN_ID,
    )

    signals = DesignFreezeMarker.guard_context_signals(frozen)

    assert signals == {
        "change_frame_frozen": True,
        "change_frame_freeze_known": True,
    }
