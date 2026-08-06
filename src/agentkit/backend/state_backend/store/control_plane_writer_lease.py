"""Database-lifetime exclusivity for the single control-plane writer."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Condition, Lock, RLock
from typing import TYPE_CHECKING

from agentkit.backend.state_backend.config import (
    SCHEMA_OVERRIDE_ENV,
    StateBackendKind,
    load_state_backend_config,
    resolve_schema_name,
)
from agentkit.backend.state_backend.postgres_store._writer_lease_runtime import (
    ActiveWriterLeaseRegistrationError,
    StateBackendControlPlaneWriterLeaseLostError,
    assert_writer_lease_acquired,
    exclusive_writer_lease_acquisition,
    load_bound_writer_identity,
    register_active_writer_lease,
    unregister_active_writer_lease,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager
    from typing import Any

    import psycopg

    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord

_WRITER_LOCK_KEY = "agentkit_control_plane_single_writer"


class StateBackendControlPlaneWriterAlreadyActiveError(RuntimeError):
    """State-adapter signal that the database writer lease is unavailable."""


@dataclass
class _PostgresControlPlaneWriterLease:
    connection_context: AbstractContextManager[psycopg.Connection[Any]]
    connection: psycopg.Connection[Any]
    lock_key: str
    released: bool = False
    identity: BackendInstanceIdentityRecord | None = None
    access_lock: RLock = field(default_factory=RLock, repr=False)
    request_condition: Condition = field(
        default_factory=lambda: Condition(Lock()),
        repr=False,
    )
    active_requests: int = 0
    closing: bool = False

    def assert_held(self) -> None:
        with self.access_lock:
            if self.released:
                raise StateBackendControlPlaneWriterLeaseLostError(
                    "the control-plane writer lease has already been released",
                )
            try:
                # A PostgreSQL session advisory lock lives exactly as long as this
                # connection.  A successful round-trip therefore proves the session
                # that owns the lock is still alive; no reacquisition is attempted.
                self.connection.execute("SELECT 1").fetchone()
                self.connection.commit()
            except Exception as exc:
                raise StateBackendControlPlaneWriterLeaseLostError(
                    "the database session holding the control-plane writer lease "
                    "was lost; this process must not accept further requests",
                ) from exc

    def bind_identity(self, identity: BackendInstanceIdentityRecord) -> None:
        """Bind exactly one boot identity to the process-local lease owner."""

        with self.access_lock:
            if self.released:
                raise StateBackendControlPlaneWriterLeaseLostError(
                    "cannot bind an identity to a released writer lease",
                )
            if self.identity is not None and self.identity != identity:
                raise StateBackendControlPlaneWriterLeaseLostError(
                    "the writer lease is already bound to another boot identity",
                )
            self.identity = identity

    @contextmanager
    def request_scope(self) -> Iterator[None]:
        """Keep shutdown behind this request and verify the lease at both edges."""

        with self.request_condition:
            if self.released or self.closing:
                raise StateBackendControlPlaneWriterLeaseLostError(
                    "the control-plane writer is shutting down",
                )
            self.active_requests += 1
        try:
            self.assert_held()
            yield
            self.assert_held()
        finally:
            with self.request_condition:
                self.active_requests -= 1
                if self.active_requests == 0:
                    self.request_condition.notify_all()

    def release(self) -> None:
        self.quiesce_requests()
        with self.access_lock:
            if self.released:
                return
            self.released = True
            try:
                if not self.connection.closed:
                    row = self.connection.execute(
                        "SELECT pg_advisory_unlock(hashtext(%s)) AS released",
                        (self.lock_key,),
                    ).fetchone()
                    if row is None or not bool(row["released"]):
                        raise StateBackendControlPlaneWriterLeaseLostError(
                            "the control-plane writer advisory lock was not owned "
                            "by its reserved database session",
                        )
                    self.connection.commit()
            finally:
                unregister_active_writer_lease(self)
                self.connection_context.__exit__(None, None, None)

    def quiesce_requests(self) -> None:
        """Reject new requests and wait for all accepted requests to finish."""

        with self.request_condition:
            self.closing = True
            while self.active_requests:
                self.request_condition.wait()


def assert_control_plane_writer_lease_acquired() -> None:
    """Reject incarnation changes outside the one lease-owning writer process."""

    assert_writer_lease_acquired()


def load_bound_control_plane_writer_identity() -> BackendInstanceIdentityRecord | None:
    """Return the immutable sender identity bound to the active writer lease."""

    identity = load_bound_writer_identity()
    return identity


def acquire_control_plane_writer_lease() -> _PostgresControlPlaneWriterLease:
    """Acquire the one database-scoped writer lease without waiting.

    Acquisition happens before boot identity mutation and reconciliation.  A
    concurrent writer is rejected with an operator-readable reason; it never
    increments the shared incarnation and can therefore never classify the live
    writer's claims as orphans.
    """

    try:
        with exclusive_writer_lease_acquisition():
            return _acquire_control_plane_writer_lease()
    except ActiveWriterLeaseRegistrationError as exc:
        raise StateBackendControlPlaneWriterAlreadyActiveError(str(exc)) from exc


def _acquire_control_plane_writer_lease() -> _PostgresControlPlaneWriterLease:
    """Acquire and register the DB lease inside the process acquisition slot."""

    config = load_state_backend_config()
    if config.backend is not StateBackendKind.POSTGRES:
        raise StateBackendControlPlaneWriterAlreadyActiveError(
            "the control-plane writer lease requires the canonical Postgres "
            "state backend; no writer may start without database exclusivity",
        )
    from agentkit.backend.state_backend.postgres_store._connection import (
        borrow_control_plane_writer_lease_connection,
    )
    context = borrow_control_plane_writer_lease_connection()
    connection = context.__enter__()
    lock_key = _writer_lock_key()
    try:
        row = connection.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired",
            (lock_key,),
        ).fetchone()
        acquired = row is not None and bool(row["acquired"])
        if not acquired:
            raise StateBackendControlPlaneWriterAlreadyActiveError(
                "another active control-plane writer already holds the "
                "database-scoped lifetime lease; startup was rejected before "
                "boot incarnation and reconciliation",
            )
        connection.commit()
        lease = _PostgresControlPlaneWriterLease(context, connection, lock_key)
        register_active_writer_lease(lease)
        return lease
    except Exception:
        context.__exit__(None, None, None)
        raise


def _writer_lock_key() -> str:
    """Resolve the database lock key, namespaced only in explicit test schemas."""

    if os.environ.get(SCHEMA_OVERRIDE_ENV) is None:
        return _WRITER_LOCK_KEY
    # The resolver validates both the test-only enable gate and reserved schema
    # namespace. Production has no override and therefore always uses the one
    # unqualified database-wide key.
    return f"{_WRITER_LOCK_KEY}:{resolve_schema_name()}"


__all__ = [
    "StateBackendControlPlaneWriterAlreadyActiveError",
    "StateBackendControlPlaneWriterLeaseLostError",
    "assert_control_plane_writer_lease_acquired",
    "acquire_control_plane_writer_lease",
    "load_bound_control_plane_writer_identity",
]
