"""Durable project mode-lock acquire marker (FK-24 §24.3.3, AG3-018).

The project mode-lock acquire/release (the enforcement half of the Fast/Standard
between-modes mutex) must be IDEMPOTENT across re-runs and recovery/resume: a
re-entered Setup must not double-acquire (double-increment the holder count) and
a resumed Closure must not double-release (drive the count below the true number
of holders).

This module owns a discardable, short-TTL read projection of the mode held by a
story-run. The canonical recovery truth is the central
``project_mode_lock_holders`` row. Setup and Closure compare this projection with
that row and fail closed when it is missing or divergent; they never fall back to
the marker as authoritative state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.paths import state_backend_dir
from agentkit.backend.story_context_manager.story_model import WireStoryMode

if TYPE_CHECKING:
    from pathlib import Path

#: Plain-text marker (the file content IS the acquired mode wire value). A
#: plain-text sidecar avoids a json decision-path read in this truth-boundary-
#: protected governance module (concept-code-contracts TB001).
_MARKER_FILE = "mode-lock-acquired"
_VALID_MODES: frozenset[str] = frozenset(m.value for m in WireStoryMode)


def _marker_path(story_dir: Path) -> Path:
    """Resolve the durable acquire-marker path for ``story_dir``."""
    return state_backend_dir(story_dir) / _MARKER_FILE


def mode_lock_acquired(story_dir: Path) -> bool:
    """Whether the local mode-lock read projection exists.

    Args:
        story_dir: The story working directory.

    Returns:
        ``True`` iff the acquire marker exists for this story.
    """
    return _marker_path(story_dir).is_file()


def acquired_mode(story_dir: Path) -> str | None:
    """Return the mode this story acquired, or ``None`` when no marker exists.

    Args:
        story_dir: The story working directory.

    Returns:
        The recorded ``mode`` (``"standard"`` / ``"fast"``), or ``None`` when no
        acquire marker is present (this story never acquired -> no release owed).
    """
    path = _marker_path(story_dir)
    if not path.is_file():
        return None
    try:
        mode = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return mode if mode in _VALID_MODES else None


def record_mode_lock_acquired(story_dir: Path, *, mode: str) -> None:
    """Write the discardable projection after a successful central acquire.

    Args:
        story_dir: The story working directory.
        mode: The acquired fast/standard ``mode`` (``"standard"`` / ``"fast"``).
    """
    path = _marker_path(story_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mode, encoding="utf-8")


def clear_mode_lock_marker(story_dir: Path) -> None:
    """Remove the durable acquire marker (FIX-3 acquire compensation).

    Used when Setup acquired the mode-lock but a SUBSEQUENT step (the status
    transition) failed: the acquired holder is released and the marker cleared so
    the story is recovery-consistent (no marker => no release owed at Closure;
    the holder was already given back here). Idempotent: a missing marker is a
    no-op.

    Args:
        story_dir: The story working directory.
    """
    path = _marker_path(story_dir)
    path.unlink(missing_ok=True)


__all__ = [
    "acquired_mode",
    "clear_mode_lock_marker",
    "mode_lock_acquired",
    "record_mode_lock_acquired",
]
