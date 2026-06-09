"""PostCompact hook: increment story-scoped compaction epoch."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from agentkit.pipeline_engine.compaction_resilience.epoch_store import (
    CompactionEpochRepository,
    build_epoch_repository,
)
from agentkit.pipeline_engine.compaction_resilience.hook_io import (
    hook_cwd,
    load_json_file,
    read_hook_input,
    warn,
)
from agentkit.pipeline_engine.compaction_resilience.models import StoryMarker
from agentkit.pipeline_engine.compaction_resilience.paths import STORY_MARKER_FILENAME

if TYPE_CHECKING:
    from pathlib import Path


def run(
    data: dict[str, Any],
    *,
    repository: CompactionEpochRepository | None = None,
) -> int | None:
    """Process one PostCompact event. Returns the new epoch, if incremented."""
    cwd = hook_cwd(data)
    marker_path = find_story_marker(cwd)
    if marker_path is None:
        warn("no .agentkit-story.json marker found; no epoch update")
        return None
    payload = load_json_file(marker_path)
    if payload is None:
        warn("story marker is unreadable; no epoch update")
        return None
    try:
        marker = StoryMarker.model_validate(payload)
    except ValidationError as exc:
        warn(f"story marker validation failed: {exc}; no epoch update")
        return None
    repo = repository or build_epoch_repository(marker_path.parent)
    try:
        return repo.increment_epoch(marker.project_key, marker.story_id)
    except Exception as exc:  # noqa: BLE001
        warn(f"epoch store increment failed: {exc}; fail-open")
        return None


def find_story_marker(cwd: Path) -> Path | None:
    """Walk upward from ``cwd`` to find the nearest story marker."""
    for candidate in (cwd, *cwd.parents):
        marker = candidate / STORY_MARKER_FILENAME
        if marker.is_file():
            return marker
    return None


def main() -> None:
    """CLI entry point. Always exits 0 per FK-36 fail-open hook contract."""
    try:
        run(read_hook_input())
    except Exception as exc:  # noqa: BLE001
        warn(f"unexpected epoch_writer failure: {exc}; fail-open")
    sys.exit(0)


if __name__ == "__main__":
    main()
