"""Control-plane records: session-run binding and operation records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = (
    "BindingDeleteScope",
    "ControlPlaneOperationRecord",
    "SessionRunBindingRecord",
)


@dataclass(frozen=True)
class BindingDeleteScope:
    """Run-scoped key set for a control-plane session-binding deletion (AG3-054).

    The session-run-binding is keyed by ``session_id`` (one row per session) but a
    closure must delete ONLY the binding that belongs to the closing run. Carrying
    the full ``(session_id, project_key, story_id, run_id)`` lets the store delete
    run-matched and fail closed if the live binding belongs to a DIFFERENT run that
    has rebound the same session (never tearing down a foreign run's regime).
    """

    session_id: str
    project_key: str
    story_id: str
    run_id: str


@dataclass(frozen=True)
class SessionRunBindingRecord:
    """Central session-to-run binding used for operating mode resolution."""

    session_id: str
    project_key: str
    story_id: str
    run_id: str
    principal_type: str
    worktree_roots: tuple[str, ...]
    binding_version: str
    updated_at: datetime


@dataclass(frozen=True)
class ControlPlaneOperationRecord:
    """Idempotent mutation record for one control-plane operation.

    AG3-054 (leased, owner-scoped claim): ``claimed_by`` / ``claimed_at`` carry
    the lease ownership of an in-flight ``claimed`` row. ``claimed_by`` is the
    per-call owner token minted by the runtime; ``claimed_at`` is the lease start
    instant (ISO-8601 TEXT, matching the table's other instants -- the lease
    expiry compares ``now - claimed_at`` against the lease TTL). Both are ``None``
    on a TERMINAL row (the finalize clears ``claimed_by`` to mark "no owner
    holds it"); a terminal row is identified by ``status != 'claimed'``.

    ERROR-2 fix (AG3-054): ``claimed_at_raw`` preserves the EXACT raw ``claimed_at``
    column value as it was read from the store (before the mapper normalizes a
    naive/malformed instant for the lease-expiry compare). The takeover CAS matches
    the RAW stored column like-for-like, so it must observe the raw value -- NOT the
    normalized ``claimed_at`` (e.g. a row stored as ``'2026-06-07T09:00:00'`` would
    never CAS-match against the normalized ``'...+00:00'``, permanently poisoning the
    op_id). It is populated only on a row read back from the store; a record built
    for a fresh write carries ``None`` (the write stamps a canonical aware value).
    """

    op_id: str
    project_key: str
    story_id: str
    run_id: str | None
    session_id: str | None
    operation_kind: str
    phase: str | None
    status: str
    response_payload: dict[str, object]
    created_at: datetime
    updated_at: datetime
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    #: The EXACT raw ``claimed_at`` column value as read back from the store
    #: (ISO-8601 TEXT, or ``None``). The takeover CAS observes THIS value so it
    #: matches the raw column like-for-like (ERROR-2). ``None`` on a fresh
    #: (not-yet-stored) record.
    claimed_at_raw: str | None = None
