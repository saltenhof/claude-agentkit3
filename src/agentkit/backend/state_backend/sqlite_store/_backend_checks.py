"""SQLite backend predicate helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._runtime_rows import load_phase_state_row
from ._story_project_rows import load_story_context_row

if TYPE_CHECKING:
    from pathlib import Path

# Backend predicate helpers (kept as thin wrappers for driver-level checks)
# ---------------------------------------------------------------------------


def backend_has_valid_context(story_dir: Path) -> bool:
    return load_story_context_row(story_dir) is not None


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return load_phase_state_row(story_dir) is not None
