"""Worker-health projection and tool-call-log artifacts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.boundary.filesystem import atomic_write_json
from agentkit.backend.config.worker_health import WorkerHealthConfig
from agentkit.backend.implementation.worker_health.models import AgentHealthState, ToolCallRecord
from agentkit.backend.installer.paths import qa_story_dir

if TYPE_CHECKING:
    from pathlib import Path

AGENT_HEALTH_FILE = "agent-health.json"
TOOL_CALL_LOG_FILE = "tool-call-log.jsonl"


def export_agent_health(
    *,
    project_root: Path,
    state: AgentHealthState,
) -> Path:
    """Write the deterministic read-only health projection from backend state."""

    path = qa_story_dir(project_root, state.story_id) / AGENT_HEALTH_FILE
    payload = state.model_dump(mode="json")
    atomic_write_json(path, payload)
    return path


def append_tool_call_log(
    *,
    project_root: Path,
    story_id: str,
    record: ToolCallRecord,
    config: WorkerHealthConfig | None = None,
) -> Path:
    """Append and trim the forensic tool-call JSONL log."""

    worker_health = config or WorkerHealthConfig()
    path = qa_story_dir(project_root, story_id) / TOOL_CALL_LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _read_rows(path)
    rows.append(record.model_dump(mode="json"))
    rows = rows[-worker_health.tool_call_log.max_entries :]
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def load_tool_call_window(path: Path) -> list[ToolCallRecord]:
    """Load the current tool-call window from the JSONL artifact."""

    return [ToolCallRecord.model_validate(row) for row in _read_rows(path)]


def _read_rows(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows
