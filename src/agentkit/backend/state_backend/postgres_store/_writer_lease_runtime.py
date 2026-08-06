"""Process-local runtime binding for the PostgreSQL writer lease session."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator
    from threading import RLock

    import psycopg


class StateBackendControlPlaneWriterLeaseLostError(RuntimeError):
    """Raised when the active writer session is absent or unusable."""


class _WriterLeaseSession(Protocol):
    connection: psycopg.Connection[Any]
    released: bool
    identity: Any | None
    access_lock: RLock


_ACTIVE_LEASE_LOCK = Lock()
_ACTIVE_LEASE: _WriterLeaseSession | None = None
_LEASE_ACQUISITION_LOCK = Lock()
_ATOMIC_WRITER_MUTATION_DEPTH: ContextVar[int] = ContextVar(
    "atomic_writer_mutation_depth",
    default=0,
)


class ActiveWriterLeaseRegistrationError(RuntimeError):
    """Raised before DB acquisition when this process already owns the lease."""


class _CommitDeferringWriterConnection:
    """Delegate to the reserved session while deferring nested commits."""

    def __init__(self, connection: psycopg.Connection[Any]) -> None:
        self._connection = connection

    def commit(self) -> None:
        """Leave the transaction boundary to ``atomic_writer_mutation``."""

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


@contextmanager
def exclusive_writer_lease_acquisition() -> Iterator[None]:
    """Serialize acquisition and reject process-local reentry before SQL."""

    with _LEASE_ACQUISITION_LOCK:
        with _ACTIVE_LEASE_LOCK:
            if _ACTIVE_LEASE is not None:
                raise ActiveWriterLeaseRegistrationError(
                    "this process already owns a control-plane writer lease",
                )
        yield


def register_active_writer_lease(lease: _WriterLeaseSession) -> None:
    """Register exactly one lease owner in this process."""

    global _ACTIVE_LEASE
    with _ACTIVE_LEASE_LOCK:
        if _ACTIVE_LEASE is not None:
            raise ActiveWriterLeaseRegistrationError(
                "this process already owns a control-plane writer lease",
            )
        _ACTIVE_LEASE = lease


def unregister_active_writer_lease(lease: _WriterLeaseSession) -> None:
    """Clear the process binding only when *lease* is still its owner."""

    global _ACTIVE_LEASE
    with _ACTIVE_LEASE_LOCK:
        if _ACTIVE_LEASE is lease:
            _ACTIVE_LEASE = None


def assert_writer_lease_acquired() -> None:
    """Reject incarnation changes outside the lease-owning process."""

    with _ACTIVE_LEASE_LOCK:
        lease = _ACTIVE_LEASE
    if lease is None or lease.released:
        raise StateBackendControlPlaneWriterLeaseLostError(
            "boot identity mutation requires the active database writer lease",
        )


def load_bound_writer_identity() -> Any | None:
    """Return the immutable identity bound to the active writer lease."""

    with _ACTIVE_LEASE_LOCK:
        lease = _ACTIVE_LEASE
    if lease is None:
        return None
    with lease.access_lock:
        if lease.released:
            return None
        return lease.identity


@contextmanager
def atomic_writer_mutation() -> Iterator[None]:
    """Commit one domain mutation and its outer claim finalization atomically.

    The in-flight placeholder is committed before this scope. Every nested
    state-backend borrow then receives the same reserved PostgreSQL session,
    with intermediate ``commit()`` calls deferred until this outer boundary.
    A failure therefore rolls back every domain write together with the claim
    finalization; a success commits both as one database transaction.
    """

    with _ACTIVE_LEASE_LOCK:
        lease = _ACTIVE_LEASE
    if lease is None:
        raise StateBackendControlPlaneWriterLeaseLostError(
            "an atomic control-plane mutation requires the active writer lease",
        )
    with lease.access_lock:
        if lease.released or lease.connection.closed:
            raise StateBackendControlPlaneWriterLeaseLostError(
                "the control-plane writer database session is not usable",
            )
        depth = _ATOMIC_WRITER_MUTATION_DEPTH.get()
        token = _ATOMIC_WRITER_MUTATION_DEPTH.set(depth + 1)
        try:
            yield
            if depth == 0:
                lease.connection.commit()
        except BaseException:
            if not lease.connection.closed:
                lease.connection.rollback()
            raise
        finally:
            _ATOMIC_WRITER_MUTATION_DEPTH.reset(token)


@contextmanager
def borrow_active_writer_connection() -> Iterator[psycopg.Connection[Any] | None]:
    """Yield the lease session so all writer DB work shares its lock fate."""

    with _ACTIVE_LEASE_LOCK:
        lease = _ACTIVE_LEASE
    if lease is None:
        yield None
        return
    with lease.access_lock:
        if lease.released or lease.connection.closed:
            raise StateBackendControlPlaneWriterLeaseLostError(
                "the control-plane writer database session is not usable",
            )
        try:
            connection: Any = lease.connection
            if _ATOMIC_WRITER_MUTATION_DEPTH.get() > 0:
                connection = _CommitDeferringWriterConnection(lease.connection)
            yield connection
        except Exception:
            if not lease.connection.closed:
                lease.connection.rollback()
            raise


__all__ = [
    "ActiveWriterLeaseRegistrationError",
    "StateBackendControlPlaneWriterLeaseLostError",
    "atomic_writer_mutation",
    "assert_writer_lease_acquired",
    "borrow_active_writer_connection",
    "exclusive_writer_lease_acquisition",
    "load_bound_writer_identity",
    "register_active_writer_lease",
    "unregister_active_writer_lease",
]
