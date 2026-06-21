"""Tests for agentkit.backend.governance.ccag.requests — PermissionRequest store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from agentkit.backend.governance.ccag.requests import (
    PermissionRequest,
    PermissionRequestStore,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_store(tmp_path: Path) -> PermissionRequestStore:
    return PermissionRequestStore(tmp_path / "requests.db")


# ---------------------------------------------------------------------------
# Create / Load
# ---------------------------------------------------------------------------


class TestPermissionRequestStore:
    def test_create_returns_pending_request(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        req = store.create(
            request_id="req-001",
            tool_name="Bash",
            tool_input_fingerprint="command:rm -rf /tmp",
            story_id="AK3-001",
        )
        assert req.request_id == "req-001"
        assert req.status == "pending"
        assert req.tool_name == "Bash"

    def test_load_returns_created_request(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create(request_id="req-002", tool_name="Write")
        loaded = store.load("req-002")
        assert loaded is not None
        assert loaded.tool_name == "Write"

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.load("nonexistent") is None

    def test_create_sets_expires_at(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        req = store.create(
            request_id="req-003",
            tool_name="Bash",
            ttl_seconds=60,
        )
        assert req.expires_at is not None
        expiry = datetime.fromisoformat(req.expires_at)
        now = datetime.now(tz=UTC)
        assert expiry > now
        # Within reasonable bounds (< 120s)
        assert (expiry - now).seconds < 120


# ---------------------------------------------------------------------------
# list_pending
# ---------------------------------------------------------------------------


class TestListPending:
    def test_list_pending_all(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create(request_id="r1", tool_name="Bash")
        store.create(request_id="r2", tool_name="Write")
        pending = store.list_pending()
        assert len(pending) == 2

    def test_list_pending_filtered_by_story(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create(request_id="r1", tool_name="Bash", story_id="AK3-001")
        store.create(request_id="r2", tool_name="Bash", story_id="AK3-002")
        pending = store.list_pending(story_id="AK3-001")
        assert len(pending) == 1
        assert pending[0].request_id == "r1"

    def test_decided_requests_not_in_pending(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create(request_id="r1", tool_name="Bash")
        store.decide("r1", approved=True)
        pending = store.list_pending()
        assert len(pending) == 0


# ---------------------------------------------------------------------------
# decide
# ---------------------------------------------------------------------------


class TestDecide:
    def test_approve_changes_status(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create(request_id="r1", tool_name="Bash")
        updated = store.decide("r1", approved=True, note="looks fine")
        assert updated is not None
        assert updated.status == "approved"
        assert updated.decision_note == "looks fine"
        assert updated.decided_at is not None

    def test_deny_changes_status(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create(request_id="r1", tool_name="Bash")
        updated = store.decide("r1", approved=False)
        assert updated is not None
        assert updated.status == "denied"

    def test_decide_nonexistent_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = store.decide("ghost", approved=True)
        # Returns None because WHERE status='pending' matches nothing
        assert result is None


# ---------------------------------------------------------------------------
# PermissionRequest.effective_status
# ---------------------------------------------------------------------------


class TestEffectiveStatus:
    def test_pending_not_expired(self) -> None:
        req = PermissionRequest(
            request_id="r1",
            tool_name="Bash",
            status="pending",
            created_at=datetime.now(tz=UTC).isoformat(),
            expires_at=(
                datetime.now(tz=UTC) + timedelta(seconds=3600)
            ).isoformat(),
        )
        assert req.effective_status() == "pending"

    def test_pending_expired_returns_expired(self) -> None:
        req = PermissionRequest(
            request_id="r1",
            tool_name="Bash",
            status="pending",
            created_at=datetime.now(tz=UTC).isoformat(),
            expires_at=(
                datetime.now(tz=UTC) - timedelta(seconds=1)
            ).isoformat(),
        )
        assert req.effective_status() == "expired"
        assert req.is_expired() is True

    def test_approved_not_affected_by_expiry(self) -> None:
        req = PermissionRequest(
            request_id="r1",
            tool_name="Bash",
            status="approved",
            created_at=datetime.now(tz=UTC).isoformat(),
            expires_at=(
                datetime.now(tz=UTC) - timedelta(seconds=1)
            ).isoformat(),
        )
        # Already decided — expiry doesn't retroactively change it
        assert req.effective_status() == "approved"


# ---------------------------------------------------------------------------
# Story_execution mode: request appears in State-Backend (Akzeptanzkriterium 2)
# ---------------------------------------------------------------------------


class TestRequestInStateBackend:
    """Verify that a PermissionRequest created in story_execution mode
    is durably persisted in the store (Akzeptanzkriterium 2).

    We use a real SQLite memory-backed store to avoid mocking.
    """

    def test_request_persisted_and_retrievable(self, tmp_path: Path) -> None:
        store = PermissionRequestStore(tmp_path / "state.db")
        req = store.create(
            request_id="state-req-001",
            tool_name="Bash",
            tool_input_fingerprint="command:some-blocked-cmd",
            story_id="AK3-013",
            run_id="run-xyz",
            operating_mode="story_execution",
        )
        assert req.operating_mode == "story_execution"

        # Reload from same DB
        loaded = store.load("state-req-001")
        assert loaded is not None
        assert loaded.story_id == "AK3-013"
        assert loaded.operating_mode == "story_execution"
        assert loaded.status == "pending"

    def test_request_survives_store_reinstantiation(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state.db"
        store1 = PermissionRequestStore(db_path)
        store1.create(
            request_id="persist-req",
            tool_name="Write",
            story_id="AK3-013",
        )
        store2 = PermissionRequestStore(db_path)
        loaded = store2.load("persist-req")
        assert loaded is not None
        assert loaded.tool_name == "Write"
