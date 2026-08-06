"""Real-Postgres proofs for the control-plane writer lease session."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Thread

import psycopg
import pytest

from agentkit.backend.control_plane.records import ControlPlaneOperationRecord
from agentkit.backend.state_backend.config import load_state_backend_config
from agentkit.backend.state_backend.operation_ledger import (
    claim_control_plane_operation_global,
    save_control_plane_operation_global,
)
from agentkit.backend.state_backend.postgres_store._connection import _connect_global
from agentkit.backend.state_backend.state_backend_connection_manager import (
    boot_backend_instance_identity_global,
)
from agentkit.backend.state_backend.store.control_plane_writer_lease import (
    StateBackendControlPlaneWriterAlreadyActiveError,
    StateBackendControlPlaneWriterLeaseLostError,
    _writer_lock_key,
    acquire_control_plane_writer_lease,
)

pytestmark = pytest.mark.integration


def test_writer_state_operations_use_the_advisory_lock_session(
    postgres_isolated_schema: str,
) -> None:
    del postgres_isolated_schema
    lease = acquire_control_plane_writer_lease()
    try:
        lease_pid = lease.connection.execute("SELECT pg_backend_pid() AS pid").fetchone()
        assert lease_pid is not None
        with _connect_global() as connection:
            state_pid = connection.execute("SELECT pg_backend_pid() AS pid").fetchone()
        assert state_pid is not None
        assert state_pid["pid"] == lease_pid["pid"]
    finally:
        lease.release()


def test_lost_lease_session_rejects_state_work(
    postgres_isolated_schema: str,
) -> None:
    del postgres_isolated_schema
    lease = acquire_control_plane_writer_lease()
    identity = boot_backend_instance_identity_global("lost-session-writer", _test_now())
    lease.bind_identity(identity)
    lease.connection.close()
    try:
        with pytest.raises(
            StateBackendControlPlaneWriterLeaseLostError,
            match="database session is not usable",
        ):
            boot_backend_instance_identity_global("must-not-write", _test_now())
    finally:
        lease.release()


def test_request_scope_detects_session_loss_before_handler_returns(
    postgres_isolated_schema: str,
) -> None:
    del postgres_isolated_schema
    lease = acquire_control_plane_writer_lease()
    try:
        with pytest.raises(
            StateBackendControlPlaneWriterLeaseLostError,
            match="session holding the control-plane writer lease was lost",
        ), lease.request_scope():
            lease.connection.close()
    finally:
        lease.release()


def test_orderly_release_waits_for_accepted_request_scope(
    postgres_isolated_schema: str,
) -> None:
    del postgres_isolated_schema
    lease = acquire_control_plane_writer_lease()
    request_entered = Event()
    allow_request_return = Event()
    request_returned = Event()
    release_returned = Event()

    def run_request() -> None:
        with lease.request_scope():
            request_entered.set()
            assert allow_request_return.wait(timeout=5)
        request_returned.set()

    def release_lease() -> None:
        lease.release()
        release_returned.set()

    request_thread = Thread(target=run_request)
    release_thread = Thread(target=release_lease)
    request_thread.start()
    assert request_entered.wait(timeout=5)
    release_thread.start()
    release_was_blocked = not release_returned.wait(timeout=0.1)
    allow_request_return.set()
    request_thread.join(timeout=5)
    release_thread.join(timeout=5)

    assert release_was_blocked
    assert request_returned.is_set()
    assert release_returned.is_set()
    assert not request_thread.is_alive()
    assert not release_thread.is_alive()


def test_process_local_second_acquire_never_increments_advisory_lock_count(
    postgres_isolated_schema: str,
) -> None:
    del postgres_isolated_schema
    lease = acquire_control_plane_writer_lease()
    try:
        with pytest.raises(
            StateBackendControlPlaneWriterAlreadyActiveError,
            match="this process already owns",
        ):
            acquire_control_plane_writer_lease()
    finally:
        lease.release()

    database_url = load_state_backend_config().database_url
    assert database_url is not None
    with psycopg.connect(database_url) as independent:
        row = independent.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired",
            (_writer_lock_key(),),
        ).fetchone()
        assert row is not None and row[0] is True
        independent.execute(
            "SELECT pg_advisory_unlock(hashtext(%s))",
            (_writer_lock_key(),),
        )


def test_claim_write_rejects_missing_sender_identity_fields(
    postgres_isolated_schema: str,
) -> None:
    """L3: no claim writer can persist an epoch-less or sender-less row."""

    del postgres_isolated_schema
    now = _test_now()
    incomplete = ControlPlaneOperationRecord(
        op_id="missing-claim-sender",
        project_key="tenant-a",
        story_id="AG3-214",
        run_id="run-1",
        session_id=None,
        operation_kind="story_reset",
        phase=None,
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by="reset-owner",
        claimed_at=now,
    )

    for write_claim in (
        claim_control_plane_operation_global,
        save_control_plane_operation_global,
    ):
        with pytest.raises(ValueError, match="operation_epoch"):
            write_claim(incomplete)


def _test_now() -> datetime:
    return datetime(2026, 8, 4, tzinfo=UTC)
