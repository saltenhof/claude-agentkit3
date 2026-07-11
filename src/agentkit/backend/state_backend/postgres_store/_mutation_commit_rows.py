"""Shared mutation-commit row gates for PostgreSQL transactions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agentkit.backend.core_types.freeze import (
    ERROR_CODE_STORY_FROZEN,
    ActiveFreezeState,
    FreezeKind,
    command_resolves_freeze,
    is_canonical_freeze_epoch,
)
from agentkit.backend.exceptions import (
    ControlPlaneClaimCollisionError,
    OwnershipFenceViolationError,
)

if TYPE_CHECKING:
    from ._compat import _CompatConnection


def _enforce_ownership_fence_row(
    conn: _CompatConnection,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    session_id: str,
    expected_ownership_epoch: int,
    command_id: str = "executor_commit",
    enforce_freeze: bool = True,
) -> None:
    """Re-verify the ownership fence AT COMMIT TIME, in THIS transaction (AG3-142).

    FK-56 §56.8a (no TOCTOU): ``SELECT ... FOR UPDATE`` row-locks the story's
    active ``run_ownership_records`` row on the SAME connection as the
    caller's claim-CAS finalize / collision-gated commit -- serializing this
    check against any concurrent CAS on that SAME row (a future AG3-148
    takeover-confirm's ``UPDATE`` blocks until this transaction commits or
    rolls back, and vice versa: two callers can never both observe a
    since-superseded snapshot as current) -- and raises
    :class:`OwnershipFenceViolationError` when the locked row no longer admits
    THIS exact ``(run_id, owner_session_id, ownership_epoch)`` snapshot -- a
    takeover (or the record ending/never having existed) landed between the
    caller's early admission check and this commit. The whole enclosing
    transaction then rolls back (mirrors :class:`ControlPlaneClaimCollisionError`):
    no side effect, no stored op. System-principal executors go through this
    SAME predicate -- there is no bypass (SOLL-016, NO ERROR BYPASSING).

    Args:
        expected_ownership_epoch: The ``ownership_epoch`` the caller observed
            at its early admission check. Fences on BOTH ``owner_session_id``
            AND ``ownership_epoch`` (FK-56 §56.8a,
            ``story_execution_mutations_require_current_ownership_epoch``): a
            recovery/takeover CAS that bumps the epoch WITHOUT necessarily
            changing ``owner_session_id`` still fences a late executor whose
            snapshot predates it.

    Raises:
        OwnershipFenceViolationError: When no active record exists for
            ``(project_key, story_id)``, or the active record's ``run_id`` /
            ``owner_session_id`` / ``ownership_epoch`` no longer matches this
            exact snapshot. ``detail`` carries the freshly-read (under the
            SAME row lock) ``current_owner_session_id`` /
            ``current_ownership_epoch`` / ``transferred_at`` -- all ``None``
            when no active record exists at all for the story.
    """
    # T-bloodtype boundary (module docstring): this driver MUST NOT import
    # BC-Records / A-core modules (``control_plane.records``,
    # ``control_plane.ownership_fence``). The admission PREDICATE is therefore
    # re-localized here as a raw-row comparison (sanctioned duplication --
    # "transaktionale Fence-/Record-Row-Funktionen im state_backend = AT/T,
    # dort lokalisiert"); the ONE domain-level admission decision
    # (``control_plane.ownership_fence.evaluate_ownership_admission``) stays
    # the A-core truth consulted by the runtime's early admission check. Both
    # encodings apply the SAME four predicates in lock-step: an active row
    # exists, its ``run_id`` matches, its ``owner_session_id`` matches, its
    # ``ownership_epoch`` matches.
    if enforce_freeze:
        _enforce_blocking_freeze_row(conn, story_id=story_id, command_id=command_id)
    active = conn.execute(
        """
        SELECT run_id, owner_session_id, ownership_epoch, acquired_at
        FROM run_ownership_records
        WHERE project_key = ? AND story_id = ? AND status = 'active'
        FOR UPDATE
        """,
        (project_key, story_id),
    ).fetchone()
    if (
        active is not None
        and str(active["run_id"]) == run_id
        and str(active["owner_session_id"]) == session_id
        and int(active["ownership_epoch"]) == expected_ownership_epoch
    ):
        return
    if active is None:
        reason = "no active run-ownership record for this story"
    elif str(active["run_id"]) != run_id:
        reason = "active record belongs to a different run"
    elif str(active["owner_session_id"]) != session_id:
        reason = "active record's owner_session_id does not match the caller"
    else:
        reason = "active record's ownership_epoch has moved since admission"
    raise OwnershipFenceViolationError(
        f"ownership fence violated for run {run_id!r} "
        f"(project={project_key!r}, story={story_id!r}, session={session_id!r}, "
        f"expected_ownership_epoch={expected_ownership_epoch!r}): " + reason,
        detail={
            "current_owner_session_id": (str(active["owner_session_id"]) if active is not None else None),
            "current_ownership_epoch": (int(active["ownership_epoch"]) if active is not None else None),
            "transferred_at": (str(active["acquired_at"]) if active is not None else None),
        },
    )


def _enforce_start_phase_fence_row(
    conn: _CompatConnection,
    *,
    op_row: dict[str, Any],
    expected_ownership_epoch: int | None,
) -> None:
    """Fence both fresh ownership minting and already-owned phase starts.

    The terminal payload belongs to the exact ``op_id`` whose claim is being
    finalized. Its dispatch identity is only a correlation key: the canonical
    phase-state and attempt rows are re-read below on this finalize connection.
    When that exact dispatch is durable, a later freeze cannot retroactively turn
    its actual outcome into ``story_frozen``; the ownership fence remains in force
    and the freeze blocks the next admission instead (INV-FRZ-2). No outcome/status
    allowlist is involved.
    """

    dispatch_identity = _dispatch_identity_for_operation(op_row)
    productive_commit_is_durable = (
        dispatch_identity is not None
        and _has_durable_dispatch_commit(
            conn,
            story_id=str(op_row["story_id"]),
            run_id=dispatch_identity[0],
            phase=str(op_row["phase"]),
            attempt_id=dispatch_identity[1],
        )
    )

    if expected_ownership_epoch is None:
        if not productive_commit_is_durable:
            _enforce_blocking_freeze_row(
                conn,
                story_id=str(op_row["story_id"]),
                command_id=str(op_row["operation_kind"]),
            )
        return
    _enforce_ownership_fence_row(
        conn,
        project_key=str(op_row["project_key"]),
        story_id=str(op_row["story_id"]),
        run_id=str(op_row["run_id"]),
        session_id=str(op_row["session_id"]),
        expected_ownership_epoch=expected_ownership_epoch,
        command_id=str(op_row["operation_kind"]),
        enforce_freeze=not productive_commit_is_durable,
    )


def _dispatch_identity_for_operation(op_row: dict[str, Any]) -> tuple[str, str] | None:
    """Return this operation's executor-run/attempt identity, if productive."""

    payload = json.loads(str(op_row["response_json"]))
    phase_dispatch = payload.get("phase_dispatch")
    if not isinstance(phase_dispatch, dict) or phase_dispatch.get("dispatched") is not True:
        return None
    executor_run_id = phase_dispatch.get("executor_run_id")
    attempt_id = phase_dispatch.get("attempt_id")
    if not isinstance(executor_run_id, str) or not executor_run_id:
        return None
    if not isinstance(attempt_id, str) or not attempt_id:
        return None
    return executor_run_id, attempt_id


def _has_durable_dispatch_commit(
    conn: _CompatConnection,
    *,
    story_id: str,
    run_id: str,
    phase: str,
    attempt_id: str,
) -> bool:
    """Return canonical proof that this exact dispatch commit stands."""

    attempt_prefix = f"{phase}-"
    if not attempt_id.startswith(attempt_prefix):
        return False
    try:
        attempt_number = int(attempt_id.removeprefix(attempt_prefix))
    except ValueError:
        return False
    if attempt_number < 1:
        return False

    row = conn.execute(
        """
        SELECT 1
        FROM phase_states AS state
        JOIN attempts AS attempt
          ON attempt.story_id = state.story_id
         AND attempt.run_id = ?
         AND attempt.phase = state.phase
         AND attempt.attempt = ?
        WHERE state.story_id = ?
          AND state.phase = ?
          AND state.attempt_id = ?
          AND CAST(state.payload_json AS JSONB) ->> 'run_id' = ?
        """,
        (run_id, attempt_number, story_id, phase, attempt_id, run_id),
    ).fetchone()
    return row is not None


def _enforce_blocking_freeze_row(
    conn: _CompatConnection,
    *,
    story_id: str,
    command_id: str,
) -> None:
    """Serialize with freeze entry and reject any unresolved active family row."""

    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(?, 0))", (story_id,))
    rows = conn.execute(
        """
        SELECT kind, freeze_reason, freeze_epoch
        FROM governance_freeze_records
        WHERE story_id = ?
        FOR UPDATE
        """,
        (story_id,),
    ).fetchall()
    for row in rows:
        raw_kind = row["kind"]
        try:
            kind = FreezeKind(str(raw_kind))
        except ValueError:
            kind = None
        raw_reason = row["freeze_reason"]
        reason = raw_reason if isinstance(raw_reason, str) and raw_reason.strip() else None
        raw_epoch = row["freeze_epoch"]
        epoch = (
            raw_epoch
            if isinstance(raw_epoch, str) and is_canonical_freeze_epoch(raw_epoch)
            else None
        )
        freeze = ActiveFreezeState(kind=kind, freeze_reason=reason, freeze_epoch=epoch)
        if command_resolves_freeze(command_id, freeze):
            continue
        raise OwnershipFenceViolationError(
            f"story freeze blocks command {command_id!r} for story {story_id!r}",
            detail={
                "error_code": ERROR_CODE_STORY_FROZEN,
                "freeze_kind": kind.value if kind is not None else None,
                "freeze_reason": reason,
                "freeze_epoch": epoch,
                "freeze_state_readable": (
                    kind is not None and reason is not None and epoch is not None
                ),
            },
        )


def _conditional_upsert_control_plane_op_row(conn: _CompatConnection, row: dict[str, Any]) -> None:
    """Conditionally upsert a terminal op row on an EXISTING connection (ERROR-2).

    Shares the conditional-upsert semantics of
    :func:`save_control_plane_operation_global_row` (it REFUSES to overwrite a row
    that is still ``status='claimed'`` -- a live, owned claim) but runs on a
    CALLER-supplied connection so the op-row write and the mutation's side effects
    commit (or roll back) in ONE transaction. The collision is surfaced via
    :class:`ControlPlaneClaimCollisionError` raised INSIDE the transaction, so the
    enclosing ``with _connect_global()`` block re-raises before ``commit`` and the
    already-issued side-effect statements are rolled back -- no orphan binding /
    lock / event survives a collision (AG3-054 ERROR-2, fail-closed atomicity).

    Raises:
        ControlPlaneClaimCollisionError: When the conflicting row is still
            ``claimed`` (the upsert would have clobbered a live claim).
    """
    cursor = conn.execute(
        """
        INSERT INTO control_plane_operations (
            op_id, project_key, story_id, run_id, session_id,
            operation_kind, phase, status, response_json,
            created_at, updated_at, claimed_by, claimed_at,
            request_body_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (op_id) DO UPDATE SET
            project_key = EXCLUDED.project_key,
            story_id = EXCLUDED.story_id,
            run_id = EXCLUDED.run_id,
            session_id = EXCLUDED.session_id,
            operation_kind = EXCLUDED.operation_kind,
            phase = EXCLUDED.phase,
            status = EXCLUDED.status,
            response_json = EXCLUDED.response_json,
            updated_at = EXCLUDED.updated_at,
            claimed_by = EXCLUDED.claimed_by,
            claimed_at = EXCLUDED.claimed_at,
            request_body_hash = EXCLUDED.request_body_hash
        WHERE control_plane_operations.status <> 'claimed'
        """,
        (
            row["op_id"],
            row["project_key"],
            row["story_id"],
            row["run_id"],
            row["session_id"],
            row["operation_kind"],
            row["phase"],
            row["status"],
            row["response_json"],
            row["created_at"],
            row["updated_at"],
            row.get("claimed_by"),
            row.get("claimed_at"),
            # AG3-140 finding 3: the complete/fail/closure terminal upsert (no
            # prior claim placeholder) must persist the body-hash so a later
            # replay can classify replay vs 409 idempotency_mismatch on the real
            # store (mirrors save_control_plane_operation_global_row).
            row.get("request_body_hash"),
        ),
    )
    if int(cursor.rowcount) == 0:
        raise ControlPlaneClaimCollisionError(
            "control-plane operation save refused: op_id "
            f"{row['op_id']!r} is held by a LIVE 'claimed' row; only the "
            "owner's finalize/release may transition it. A non-owner save "
            "(e.g. complete/fail/closure reusing a live start's op_id) must not "
            "clobber the claim (AG3-054 ERROR-3, fail-closed).",
        )
