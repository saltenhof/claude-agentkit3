"""Unit tests for :class:`EdgeCommandRecord` (FK-91 §91.1b, AG3-145).

Blood-type A: pure ``__post_init__`` value validation, no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane.records import EdgeCommandRecord

_NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


def _record(**overrides: object) -> EdgeCommandRecord:
    defaults: dict[str, object] = {
        "command_id": "cmd-1",
        "project_key": "tenant-a",
        "story_id": "AG3-100",
        "run_id": "run-1",
        "session_id": "sess-1",
        "command_kind": "provision_worktree",
        "payload": {},
        "status": "created",
        "ownership_epoch": 1,
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return EdgeCommandRecord(**defaults)  # type: ignore[arg-type]


def test_valid_record_round_trips_every_field() -> None:
    record = _record(
        delivered_at=_NOW,
        completed_at=_NOW,
        result_op_id="op-1",
        result_type="worktree_report",
        result_payload={"repo_id": "repo-a"},
    )
    assert record.command_id == "cmd-1"
    assert record.result_payload == {"repo_id": "repo-a"}


def test_no_ttl_or_expiry_attribute_exists() -> None:
    """SOLL-165: an open command never ends by wall clock -- no such field exists."""
    field_names = {f for f in EdgeCommandRecord.__dataclass_fields__}
    assert not (field_names & {"ttl", "expiry", "expires_at", "lease_ttl", "expired_at"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("command_id", ""),
        ("project_key", ""),
        ("story_id", ""),
        ("run_id", ""),
        ("session_id", ""),
    ],
)
def test_rejects_empty_identity_components(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        _record(**{field: value})


def test_rejects_unknown_command_kind() -> None:
    with pytest.raises(ValueError, match="command_kind must be one of"):
        _record(command_kind="bogus_kind")


def test_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="status must be one of"):
        _record(status="expired")


def test_rejects_ownership_epoch_below_minimum() -> None:
    with pytest.raises(ValueError, match="ownership_epoch must be >="):
        _record(ownership_epoch=0)
