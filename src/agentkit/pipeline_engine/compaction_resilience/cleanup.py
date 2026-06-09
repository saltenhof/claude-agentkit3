"""SubagentStop hook: remove per-agent FK-36 runtime files."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from agentkit.pipeline_engine.compaction_resilience.hook_io import (
    hook_cwd,
    read_hook_input,
    warn,
)
from agentkit.pipeline_engine.compaction_resilience.models import valid_agent_id
from agentkit.pipeline_engine.compaction_resilience.paths import (
    active_path,
    first_tool_path,
    manifest_path,
    recovered_path,
)

if TYPE_CHECKING:
    from pathlib import Path


def run(data: dict[str, Any], *, project_root: Path | None = None) -> int:
    """Delete manifest/marker files for one agent. Returns removed file count."""
    agent_id = str(data.get("agent_id") or "")
    if not valid_agent_id(agent_id):
        warn("invalid or missing agent_id; rejecting before path construction")
        return 0
    root = project_root or hook_cwd(data)
    removed = 0
    for path in (
        manifest_path(root, agent_id),
        recovered_path(root, agent_id),
        first_tool_path(root, agent_id),
        active_path(root, agent_id),
    ):
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            continue
        except OSError as exc:
            warn(f"could not remove {path}: {exc}; fail-open")
    return removed


def main() -> None:
    """CLI entry point. Always exits 0 per FK-36 fail-open hook contract."""
    try:
        run(read_hook_input())
    except Exception as exc:  # noqa: BLE001
        warn(f"unexpected cleanup failure: {exc}; fail-open")
    sys.exit(0)


if __name__ == "__main__":
    main()
