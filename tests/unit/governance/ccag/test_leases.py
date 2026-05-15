"""Tests for agentkit.governance.ccag.leases — consume-once Permission-Lease."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.governance.ccag.leases import (
    LeaseExhaustedError,
    LeaseExpiredError,
    LeaseNotFoundError,
    PermissionLease,
    PermissionLeaseStore,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_store(tmp_path: Path) -> PermissionLeaseStore:
    return PermissionLeaseStore(tmp_path / "leases.db")


def _future_iso(seconds: int = 3600) -> str:
    return (datetime.now(tz=UTC) + timedelta(seconds=seconds)).isoformat()


def _past_iso(seconds: int = 3600) -> str:
    return (datetime.now(tz=UTC) - timedelta(seconds=seconds)).isoformat()


# ---------------------------------------------------------------------------
# Save / Load
# ---------------------------------------------------------------------------


class TestPermissionLeaseStore:
    def test_save_and_load(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        lease = PermissionLease(
            lease_id="lease-001",
            tool_name="Bash",
            tool_input_fingerprint="command:git push",
            granted_at=datetime.now(tz=UTC).isoformat(),
            expires_at=_future_iso(),
            story_id="AK3-001",
        )
        store.save(lease)
        loaded = store.load("lease-001")
        assert loaded.lease_id == "lease-001"
        assert loaded.tool_name == "Bash"
        assert loaded.consumed is False

    def test_load_not_found_raises(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        with pytest.raises(LeaseNotFoundError):
            store.load("nonexistent-id")

    def test_overwrite_on_same_id(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        lease = PermissionLease(
            lease_id="dup",
            tool_name="Bash",
            granted_at=datetime.now(tz=UTC).isoformat(),
        )
        store.save(lease)
        lease2 = PermissionLease(
            lease_id="dup",
            tool_name="Write",
            granted_at=datetime.now(tz=UTC).isoformat(),
        )
        store.save(lease2)
        loaded = store.load("dup")
        assert loaded.tool_name == "Write"


# ---------------------------------------------------------------------------
# Consume-once semantics
# ---------------------------------------------------------------------------


class TestConsumeOnce:
    def test_consume_first_call_succeeds(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        lease = PermissionLease(
            lease_id="consume-1",
            tool_name="Bash",
            granted_at=datetime.now(tz=UTC).isoformat(),
        )
        store.save(lease)
        consumed = store.consume("consume-1")
        assert consumed.consumed is True

    def test_consume_second_call_raises_exhausted(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        lease = PermissionLease(
            lease_id="consume-2",
            tool_name="Bash",
            granted_at=datetime.now(tz=UTC).isoformat(),
        )
        store.save(lease)
        store.consume("consume-2")
        with pytest.raises(LeaseExhaustedError):
            store.consume("consume-2")

    def test_consume_nonexistent_raises_not_found(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        with pytest.raises(LeaseNotFoundError):
            store.consume("ghost-lease")

    def test_consume_expired_lease_raises(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        lease = PermissionLease(
            lease_id="expired-1",
            tool_name="Bash",
            granted_at=datetime.now(tz=UTC).isoformat(),
            expires_at=_past_iso(100),  # already expired
        )
        store.save(lease)
        with pytest.raises(LeaseExpiredError):
            store.consume("expired-1")

    def test_is_valid_true_for_fresh_lease(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        lease = PermissionLease(
            lease_id="valid-1",
            tool_name="Bash",
            granted_at=datetime.now(tz=UTC).isoformat(),
            expires_at=_future_iso(),
        )
        store.save(lease)
        assert store.is_valid("valid-1") is True

    def test_is_valid_false_after_consume(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        lease = PermissionLease(
            lease_id="valid-2",
            tool_name="Bash",
            granted_at=datetime.now(tz=UTC).isoformat(),
        )
        store.save(lease)
        store.consume("valid-2")
        assert store.is_valid("valid-2") is False

    def test_is_valid_false_for_expired_lease(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        lease = PermissionLease(
            lease_id="expired-2",
            tool_name="Bash",
            granted_at=datetime.now(tz=UTC).isoformat(),
            expires_at=_past_iso(100),
        )
        store.save(lease)
        assert store.is_valid("expired-2") is False

    def test_is_valid_false_for_nonexistent(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.is_valid("ghost") is False

    def test_no_expiry_lease_can_be_consumed(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        lease = PermissionLease(
            lease_id="no-expiry",
            tool_name="Bash",
            granted_at=datetime.now(tz=UTC).isoformat(),
            expires_at=None,
        )
        store.save(lease)
        consumed = store.consume("no-expiry")
        assert consumed.consumed is True

    def test_persisted_consumed_state_survives_reload(self, tmp_path: Path) -> None:
        """Consume-once must persist across store re-instantiation."""
        db_path = tmp_path / "leases.db"
        store1 = PermissionLeaseStore(db_path)
        lease = PermissionLease(
            lease_id="persist-1",
            tool_name="Bash",
            granted_at=datetime.now(tz=UTC).isoformat(),
        )
        store1.save(lease)
        store1.consume("persist-1")

        # New store instance pointing to same DB
        store2 = PermissionLeaseStore(db_path)
        assert store2.is_valid("persist-1") is False
        with pytest.raises(LeaseExhaustedError):
            store2.consume("persist-1")
