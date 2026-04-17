"""Persistence helpers for flow-oriented runtime records."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from agentkit.phase_state_store.models import (
    FlowExecution,
    NodeExecutionLedger,
    OverrideRecord,
)

if TYPE_CHECKING:
    from pathlib import Path


def atomic_write_json(path: Path, data: dict[str, object]) -> None:
    """Write JSON atomically without depending on pipeline state helpers."""

    from agentkit.utils.io import atomic_write_text

    content = json.dumps(data, indent=2, sort_keys=True, default=str)
    atomic_write_text(path, content)


def load_json_safe(path: Path) -> dict[str, object] | None:
    """Load JSON object from disk, returning None when absent or invalid."""

    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _serialize_dataclass(obj: Any) -> dict[str, object]:
    data = cast("dict[str, object]", asdict(obj))
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


def _parse_int(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    try:
        return int(cast("Any", value))
    except (TypeError, ValueError):
        return default


_EPOCH = datetime.fromisoformat("1970-01-01T00:00:00+00:00")


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value)


def _safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def save_flow_execution(story_dir: Path, record: FlowExecution) -> None:
    """Persist the current flow execution record."""

    atomic_write_json(story_dir / "flow-execution.json", _serialize_dataclass(record))


def load_flow_execution(story_dir: Path) -> FlowExecution | None:
    """Load the current flow execution record if present."""

    data = load_json_safe(story_dir / "flow-execution.json")
    if data is None:
        return None
    try:
        return FlowExecution(
            project_key=str(data["project_key"]),
            story_id=str(data["story_id"]),
            run_id=str(data["run_id"]),
            flow_id=str(data["flow_id"]),
            level=str(data["level"]),
            owner=str(data["owner"]),
            parent_flow_id=(
                str(data["parent_flow_id"]) if data.get("parent_flow_id") else None
            ),
            status=str(data.get("status", "READY")),
            current_node_id=(
                str(data["current_node_id"]) if data.get("current_node_id") else None
            ),
            attempt_no=_parse_int(data.get("attempt_no"), 1),
            started_at=_parse_datetime(data.get("started_at")) or _EPOCH,
            finished_at=_parse_datetime(data.get("finished_at")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_node_execution_ledger(story_dir: Path, record: NodeExecutionLedger) -> None:
    """Persist a node execution ledger under a flow-scoped path."""

    ledgers_dir = story_dir / "node-ledgers" / _safe_component(record.flow_id)
    ledgers_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        ledgers_dir / f"{_safe_component(record.node_id)}.json",
        _serialize_dataclass(record),
    )


def load_node_execution_ledger(
    story_dir: Path,
    flow_id: str,
    node_id: str,
) -> NodeExecutionLedger | None:
    """Load a node execution ledger if present."""

    path = (
        story_dir
        / "node-ledgers"
        / _safe_component(flow_id)
        / f"{_safe_component(node_id)}.json"
    )
    data = load_json_safe(path)
    if data is None:
        return None
    try:
        return NodeExecutionLedger(
            project_key=str(data["project_key"]),
            story_id=str(data["story_id"]),
            run_id=str(data["run_id"]),
            flow_id=str(data["flow_id"]),
            node_id=str(data["node_id"]),
            execution_count=_parse_int(data.get("execution_count"), 0),
            success_count=_parse_int(data.get("success_count"), 0),
            last_outcome=(
                str(data["last_outcome"]) if data.get("last_outcome") else None
            ),
            last_attempt_no=(
                _parse_int(data.get("last_attempt_no"), 0)
                if data.get("last_attempt_no")
                else None
            ),
            last_executed_at=_parse_datetime(data.get("last_executed_at")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_override_record(story_dir: Path, record: OverrideRecord) -> None:
    """Persist an override record under an append-only style directory."""

    overrides_dir = story_dir / "overrides"
    overrides_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        overrides_dir / f"{_safe_component(record.override_id)}.json",
        _serialize_dataclass(record),
    )


def load_override_records(story_dir: Path) -> tuple[OverrideRecord, ...]:
    """Load all persisted override records in append-only order."""

    overrides_dir = story_dir / "overrides"
    if not overrides_dir.exists():
        return ()

    records: list[OverrideRecord] = []
    for path in sorted(overrides_dir.glob("*.json")):
        data = load_json_safe(path)
        if data is None:
            continue
        try:
            records.append(
                OverrideRecord(
                    override_id=str(data["override_id"]),
                    project_key=str(data["project_key"]),
                    story_id=str(data["story_id"]),
                    run_id=str(data["run_id"]),
                    flow_id=str(data["flow_id"]),
                    target_node_id=(
                        str(data["target_node_id"])
                        if data.get("target_node_id")
                        else None
                    ),
                    override_type=str(data["override_type"]),
                    actor_type=str(data["actor_type"]),
                    actor_id=str(data["actor_id"]),
                    reason=str(data["reason"]),
                    created_at=_parse_datetime(data["created_at"]) or _EPOCH,
                    consumed_at=_parse_datetime(data.get("consumed_at")),
                ),
            )
        except (KeyError, TypeError, ValueError):
            continue

    records.sort(key=lambda record: record.created_at)
    return tuple(records)
