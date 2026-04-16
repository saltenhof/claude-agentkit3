"""Persistence helpers for flow-oriented runtime records."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import re
from typing import TYPE_CHECKING, cast

from agentkit.phase_state_store.models import (
    FlowExecution,
    NodeExecutionLedger,
    OverrideRecord,
)
from agentkit.pipeline.state import atomic_write_json, load_json_safe

if TYPE_CHECKING:
    from pathlib import Path


def _serialize_dataclass(obj: object) -> dict[str, object]:
    data = cast("dict[str, object]", asdict(obj))
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


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
            attempt_no=int(data.get("attempt_no", 1)),
            started_at=_parse_datetime(data.get("started_at")) or datetime.fromisoformat(
                "1970-01-01T00:00:00+00:00",
            ),
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
            execution_count=int(data.get("execution_count", 0)),
            success_count=int(data.get("success_count", 0)),
            last_outcome=(
                str(data["last_outcome"]) if data.get("last_outcome") else None
            ),
            last_attempt_no=(
                int(data["last_attempt_no"]) if data.get("last_attempt_no") else None
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

