"""Operation-record serialization, replay, and response payload helpers."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import (
    object_claims,
    runtime_constants,
)
from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    OwnershipTransferredDetail,
    PhaseDispatchResult,
    PhaseMutationRequest,
)
from agentkit.backend.control_plane.ownership import (
    INITIAL_OPERATION_EPOCH,
)
from agentkit.backend.control_plane.ownership_fence import (
    ERROR_CODE_OWNERSHIP_TRANSFERRED,
)
from agentkit.backend.control_plane.records import (
    ControlPlaneOperationRecord,
)
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

from ._models import _RECONCILE_PRESERVED_STATUSES

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.backend.control_plane.push_sync import (
        BarrierVerdict,
    )
    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord
    from agentkit.backend.telemetry.events import EventType

logger = logging.getLogger(__name__)

def _control_plane_request_body_hash(
    request: PhaseMutationRequest | ClosureCompleteRequest,
    *,
    operation_kind: str,
    phase: str | None,
) -> str:
    """Canonical body-hash of a phase/closure request (AG3-140, FK-91 §91.1a Rule 5).

    SHA-256 of the canonical request body (``op_id`` excluded by
    :func:`compute_body_hash`). ``operation_kind`` and ``phase`` are folded in so a
    reused ``op_id`` that carries the SAME :class:`PhaseMutationRequest` for a
    DIFFERENT action (start vs complete vs fail vs resume) or a DIFFERENT phase
    hashes differently -- a claim/terminal write stamps this and a claim-loser /
    replay compares it (hash match -> replay; hash differs -> ``409
    idempotency_mismatch``).

    The ``operation_kind`` + ``phase`` fed here on the CLAIM / terminal WRITE for a
    given entrypoint MUST equal the ones fed on its REPLAY check, otherwise a
    legitimate replay would false-mismatch (see the per-entrypoint call sites).

    Args:
        request: The phase or closure mutation request.
        operation_kind: The operation kind of THIS entrypoint (``phase_start`` /
            ``phase_complete`` / ``phase_fail`` / ``phase_resume`` /
            ``closure_complete``).
        phase: The requested phase (``None``/``""`` for a closure carries the same
            ``"closure"`` value at every site).

    Returns:
        A lowercase hex SHA-256 digest string.
    """
    from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
        compute_body_hash,
    )

    payload = dict(request.model_dump(mode="json"))
    #: Distinguish start/complete/fail/resume reusing the SAME PhaseMutationRequest,
    #: and setup vs closure vs any other phase, under one op_id.
    payload["__operation_kind"] = operation_kind
    payload["__phase"] = phase or ""
    #: ``compute_body_hash`` excludes the ``op_id`` key -> a pure function of the
    #: mutation data (a replay of the same mutation hashes equal).
    return compute_body_hash(payload)


def _replay_or_mismatch(
    request: PhaseMutationRequest | ClosureCompleteRequest,
    stored: ControlPlaneOperationRecord,
    *,
    operation_kind: str,
    phase: str | None,
    mutating_retry: bool = True,
) -> ControlPlaneMutationResult:
    """Replay a terminal row, or fail closed with ``409 idempotency_mismatch`` (AG3-140).

    A claim-loser / replay classifies a stored TERMINAL row by comparing the
    incoming request's body-hash against the one stamped on the row, THEN by the
    stored terminal status:

    * hash DIFFERS -> the ``op_id`` is being reused for a DIFFERENT phase/action/
      body: fail closed with :class:`IdempotencyMismatchError` (mapped to HTTP
      ``409 idempotency_mismatch`` at the adapter, FK-91 §91.1a Rule 5).
    * hash MATCHES + a NON-COMMITTED terminal (``aborted`` / ``repair`` /
      ``failed``) -> fail closed with a ``rejected`` result (mapped to HTTP
      ``409 conflict``): a mutating retry against a terminal this mutation did not
      commit is NEVER replayed as a 201 success (AG3-140 Codex r6).
    * hash MATCHES + a committed-success terminal -> a legitimate replay of the
      SAME mutation: return the stored result (``_replayed_result``).

    Fail-closed note: a ``None`` stored hash is a legacy / pre-AG3-140 row that was
    written before the body-hash was populated on this path -- it falls back to
    op_id-only replay (NEVER raises on a null stored hash), so an in-flight rollout
    can never turn an honest replay into a spurious mismatch.

    Args:
        request: The incoming phase or closure mutation request.
        stored: The stored TERMINAL operation record.
        operation_kind: This entrypoint's operation kind (MUST match the write).
        phase: This entrypoint's phase (MUST match the write).

    Returns:
        The stored result as a ``replayed`` (or verbatim reconcile-preserved)
        result on a hash match / legacy null hash.

    Raises:
        IdempotencyMismatchError: When the stored row carries a body-hash that
            differs from the incoming request's (409 idempotency_mismatch).
    """
    stored_hash = stored.request_body_hash
    if stored_hash is not None:
        incoming = _control_plane_request_body_hash(request, operation_kind=operation_kind, phase=phase)
        if incoming != stored_hash:
            from agentkit.backend.story_context_manager.errors import (
                IdempotencyMismatchError,
            )

            raise IdempotencyMismatchError(
                f"op_id {request.op_id!r} was previously used with a different "
                "request body; use a new op_id for a different mutation",
                detail={"op_id": request.op_id, "conflict": "body_hash_mismatch"},
            )
    #: AG3-140 (Codex r6): terminal-status discrimination on the MUTATING retry
    #: path. A non-committed terminal row (``aborted`` / ``repair`` / ``failed``)
    #: must fail closed as a STABLE 409 conflict -- it is NEVER replayed as a 201
    #: success, even when the body-hash matches (e.g. a phase-start whose claim was
    #: admin-aborted, retried with the same op_id). Only a committed-success
    #: terminal replays its stored result. This applies the SAME status rule as the
    #: shared ``classify_terminal_row`` (non-committed terminal -> conflict). It is
    #: keyed on control-plane's own ``_RECONCILE_PRESERVED_STATUSES`` rather than
    #: reusing ``classify_terminal_row`` directly, because control-plane's terminal
    #: vocabulary has MULTIPLE success statuses (``committed`` / ``synced`` /
    #: ``replayed`` / ``resolved``) that all legitimately replay, whereas the
    #: generic classifier treats every status other than the single ``committed``
    #: as a conflict -- feeding control-plane status into it verbatim would
    #: false-conflict ``synced`` / ``resolved`` replays. ``_RECONCILE_PRESERVED_STATUSES``
    #: is the ONE control-plane definition of "non-committed terminal" and is
    #: already the set ``_replayed_result`` special-cases, so this is not a second
    #: source of truth. The verbatim ``aborted`` / ``repair`` / ``failed`` payload
    #: is preserved ONLY on the reconcile READ surface (``get_operation`` /
    #: ``GET /operations/{op_id}``, FK-91 Rule 17) and on the ``mutating_retry=False``
    #: LATE-OWNER finalize path (the original owner whose ownership CAS lost to a
    #: concurrent admin-abort surfaces its own aborted row verbatim -- legitimate
    #: late-owner visibility, NOT a duplicate retry), neither of which sets
    #: ``mutating_retry=True``.
    if mutating_retry and stored.status in _RECONCILE_PRESERVED_STATUSES:
        return _rejection_result(
            op_id=request.op_id,
            operation_kind=stored.operation_kind,
            run_id=stored.run_id,
            phase=stored.phase,
            reason=(
                f"op_id {request.op_id!r} resolved to a non-committed terminal "
                f"state ({stored.status!r}, e.g. an administrative abort or an "
                "unrepaired partial write) that this mutation did not commit; a "
                "retry cannot replay it as success. Reconcile via the operations "
                "read endpoint for this op_id and use a new op_id for a new mutation."
            ),
        )
    return _replayed_result(stored.response_payload)


def _operation_record(
    *,
    op_id: str,
    project_key: str,
    story_id: str,
    run_id: str | None,
    session_id: str | None,
    operation_kind: str,
    phase: str | None,
    result: ControlPlaneMutationResult,
    now: datetime,
    request_body_hash: str | None = None,
) -> ControlPlaneOperationRecord:
    """Build the terminal operation record (no live claim -- a terminal row).

    AG3-140: ``request_body_hash`` is the canonical body-hash of the originating
    request (op_id excluded), stamped so a later replay of the SAME op_id can
    distinguish a legitimate replay (hash match) from a ``409 idempotency_mismatch``
    (hash differs). Fed by :func:`_control_plane_request_body_hash` at every call
    site with THAT site's ``operation_kind`` + ``phase`` (consistent with its
    replay check).
    """
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        session_id=session_id,
        operation_kind=operation_kind,
        phase=phase,
        status=result.status,
        response_payload=result.model_dump(mode="json"),
        created_at=now,
        updated_at=now,
        request_body_hash=request_body_hash,
    )


def _lifecycle_event_record(
    *,
    event_type: EventType,
    project_key: str,
    story_id: str,
    run_id: str,
    source_component: str,
    payload: dict[str, object],
    now: datetime,
    phase: str | None = None,
) -> ExecutionEventRecord:
    """Build (NO write) one canonical control-plane lifecycle execution event (#1)."""
    return ExecutionEventRecord(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        event_id=f"evt-{uuid.uuid4().hex}",
        event_type=event_type.value,
        occurred_at=now,
        source_component=source_component,
        severity="info",
        phase=phase,
        payload=payload,
    )

def _build_claim_placeholder(
    request: PhaseMutationRequest,
    *,
    run_id: str,
    phase: str,
    owner_token: str,
    now: datetime,
    instance_identity: BackendInstanceIdentityRecord,
    operation_kind: str = "phase_start",
) -> ControlPlaneOperationRecord:
    """Build the in-flight ``claimed`` placeholder op record (AG3-054).

    The ``claimed`` status marks an in-flight reservation, distinct from the
    terminal ``committed`` / ``rejected`` the winning caller writes next; its
    ``response_payload`` is empty (not a replayable result). ``claimed_by`` is the
    per-call owner token and ``claimed_at`` is the claim instant -- an audit
    instant only (AG3-139: its age is never interpreted to end the claim); the
    ownership-scoped finalize/release CAS keys off this exact value (WARNING-4).

    AG3-130: ``operation_kind`` parametrizes the claim reservation so ``resume``
    reserves its op_id under ``phase_resume`` through the SAME claim-before-dispatch
    protocol as ``start`` (no double-resume: the side-effecting engine resume runs
    only after the reservation).

    AG3-138 (``inflight-operation-record``, FK-91 §91.1a rules 13/16): every
    freshly-acquired claim is stamped with the CALLING instance's identity
    (``backend_instance_id`` + ``instance_incarnation``), an initial fencing
    ``operation_epoch`` (bumped only by an explicit admin-abort, never by wall
    clock) and its ``declared_serialization_scope`` (the default
    ``(project_key, story_id)`` object-serialization scope, Rule 13).
    """
    return ControlPlaneOperationRecord(
        op_id=request.op_id,
        project_key=request.project_key,
        story_id=request.story_id,
        run_id=run_id,
        session_id=request.session_id,
        operation_kind=operation_kind,
        phase=phase,
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by=owner_token,
        claimed_at=now,
        operation_epoch=INITIAL_OPERATION_EPOCH,
        backend_instance_id=instance_identity.backend_instance_id,
        instance_incarnation=instance_identity.instance_incarnation,
        declared_serialization_scope=object_claims.format_declared_scope(
            object_claims.story_claim_key(request.project_key, request.story_id)
        ),
        #: AG3-140: stamp the canonical body-hash on the claim so a claim-loser
        #: (``_acquire_claim`` terminal-replay branch) can classify a reused op_id
        #: as a legitimate replay (hash match) vs ``409 idempotency_mismatch`` (hash
        #: differs). Fed with THIS claim's operation_kind + phase, identical to the
        #: terminal-write/replay pair of the same entrypoint (no false-mismatch).
        request_body_hash=_control_plane_request_body_hash(request, operation_kind=operation_kind, phase=phase),
    )


def _rejection_result(
    *,
    op_id: str,
    operation_kind: str,
    run_id: str | None,
    phase: str | None,
    reason: str,
    dispatch_phase: str = "setup",
) -> ControlPlaneMutationResult:
    """Build a fail-closed REJECTED mutation result (no bundle, no committed op).

    The single shared shape for every control-plane rejection (fresh-setup
    unresolvable ctx / pre-start-guard / unadmitted complete-fail / in-flight
    claim loss): ``status='rejected'``, no ``edge_bundle`` (it materialized none),
    and the reason carried on a ``rejected`` :class:`PhaseDispatchResult`.

    Args:
        op_id: The operation id.
        operation_kind: ``phase_start`` / ``phase_complete`` / ``phase_fail``.
        run_id: The run id (``None`` when unknown, e.g. a claim-loss replay).
        phase: The requested phase (``None`` when unknown).
        reason: The human-readable rejection reason.
        dispatch_phase: The phase name carried on the inner ``PhaseDispatchResult``
            (defaults to ``setup``; the outer ``phase`` may be ``None``).

    Returns:
        The fail-closed ``rejected`` :class:`ControlPlaneMutationResult`.
    """
    return ControlPlaneMutationResult(
        status="rejected",
        op_id=op_id,
        operation_kind=operation_kind,
        run_id=run_id,
        phase=phase,
        edge_bundle=None,
        phase_dispatch=PhaseDispatchResult(
            phase=phase or dispatch_phase,
            status="rejected",
            reaction="rejected",
            dispatched=False,
            rejection_reason=reason,
        ),
    )


def _push_barrier_rejection(
    verdict: BarrierVerdict,
    *,
    op_id: str,
    operation_kind: str,
    run_id: str,
    phase: str,
) -> ControlPlaneMutationResult:
    """Build a fail-closed REJECTED result for a blocked push barrier (AG3-147).

    FK-10 §10.2.4b: a boundary transition without a server-verified push is
    deterministically blocked -- no commit, no bundle. The stable
    ``push_barrier_unverified`` code plus the blocking repos + named A-core block
    codes ride the reason (Rule-8 error contract, ARCH-55) so a consumer
    recognises "unverified push" and escalates (FK-10 §10.6.1), never a bypass.
    """
    return _rejection_result(
        op_id=op_id,
        operation_kind=operation_kind,
        run_id=run_id,
        phase=phase,
        reason=(
            f"{runtime_constants.PUSH_BARRIER_BLOCKED_CODE}: "
            f"{operation_kind} blocked -- the "
            f"{verdict.barrier_type.value} push barrier is not satisfied "
            f"(FK-10 §10.2.4b, fail-closed; the Edge report alone is never "
            f"sufficient). Unverified repos: {verdict.blocking_summary()}"
        ),
        dispatch_phase=phase,
    )


def _ownership_transferred_rejection(
    *,
    op_id: str,
    operation_kind: str,
    run_id: str | None,
    phase: str | None,
    new_owner_session_id: str,
    new_ownership_epoch: int,
    transferred_at: datetime,
) -> ControlPlaneMutationResult:
    """Build the ex-owner ``ownership_transferred`` rejection (AG3-142).

    FK-91 §91.1a Rule 18 / FK-56 §56.13c: a mutating call whose run-ownership no
    longer matches the active record is deterministically rejected with the
    structured ``ownership_transferred`` payload -- reason, new owner, transfer
    instant -- embedded in the FK-91 Rule 8 error contract
    (``error_code`` / ``error`` / ``correlation_id``, added by the HTTP layer).
    No silent fallback to ``ai_augmented``: ``edge_bundle`` stays ``None``, like
    every other ``rejected`` result.
    """
    return ControlPlaneMutationResult(
        status="rejected",
        op_id=op_id,
        operation_kind=operation_kind,
        run_id=run_id,
        phase=phase,
        edge_bundle=None,
        phase_dispatch=PhaseDispatchResult(
            phase=phase or "setup",
            status="rejected",
            reaction="rejected",
            dispatched=False,
            rejection_reason=(
                f"{operation_kind} rejected: run-ownership was transferred to "
                f"session {new_owner_session_id!r} at {transferred_at.isoformat()!r}; "
                "this session is no longer the owner and this mutation is "
                "fail-closed rejected (FK-56 §56.13c, FK-91 §91.1a Rule 18)."
            ),
        ),
        error_code=ERROR_CODE_OWNERSHIP_TRANSFERRED,
        ownership_conflict=OwnershipTransferredDetail(
            reason=ERROR_CODE_OWNERSHIP_TRANSFERRED,
            new_owner_session_id=new_owner_session_id,
            new_ownership_epoch=new_ownership_epoch,
            transferred_at=transferred_at,
        ),
    )


def _object_claim_busy_rejection(
    *,
    op_id: str,
    operation_kind: str,
    run_id: str | None,
    phase: str | None,
    conflict: object_claims.ObjectClaimConflict,
) -> ControlPlaneMutationResult:
    """Build the K4 deterministic ``409 + Retry-After`` busy-object rejection.

    SOLL-054/IMPL-016: the declared serialization object (default per-story,
    FK-91 §91.1a Rule 13) is currently claimed by another in-flight mutation.
    NO operation is stored for this attempt (unlike a terminal rejection, this
    is never persisted) -- a retry with the SAME op_id re-evaluates from
    scratch once the object is free.
    """
    return ControlPlaneMutationResult(
        status="rejected",
        op_id=op_id,
        operation_kind=operation_kind,
        run_id=run_id,
        phase=phase,
        edge_bundle=None,
        phase_dispatch=PhaseDispatchResult(
            phase=phase or "setup",
            status="rejected",
            reaction="rejected",
            dispatched=False,
            rejection_reason=(
                f"{operation_kind} rejected: the story object "
                f"{conflict.key.scope_key!r} is currently claimed by another "
                "in-flight mutation (SOLL-054 durable object-mutation-claim, "
                "FK-91 §91.1a Rule 13: serialization per mutated object, "
                "bound to the object not the caller); retry after "
                f"{conflict.retry_after_seconds}s (K4/IMPL-016: deterministic "
                "409 + Retry-After, never a blocking wait)."
            ),
        ),
        error_code=conflict.error_code,
        retry_after_seconds=conflict.retry_after_seconds,
    )


def _replayed_result(
    stored_payload: dict[str, object],
) -> ControlPlaneMutationResult:
    """Rebuild a stored result as a ``replayed`` result, RE-RUNNING validators (E6).

    The status rewrite to ``replayed`` is done by re-constructing the model via
    ``model_validate`` over the stored payload with ``status`` overridden -- NOT
    via ``model_copy(update=...)`` (which pydantic does NOT re-validate). So the
    model's ``edge_bundle``-optionality invariant (``edge_bundle`` may be ``None``
    only for a non-materializing status) is re-enforced on every replay: a
    tampered stored payload that violates it raises at the boundary instead of
    silently passing.

    AG3-138: an ``aborted`` / ``repair`` / ``failed`` terminal result (which
    carries NO ``edge_bundle``) is surfaced VERBATIM -- rewriting its status to
    ``replayed`` would both hide the true terminal state from an idempotent
    retry AND violate the model invariant (``replayed`` requires an
    ``edge_bundle``). Only the ordinary success statuses are echoed as
    ``replayed``.

    Args:
        stored_payload: The JSON payload of the persisted operation.

    Returns:
        A validated :class:`ControlPlaneMutationResult`: verbatim for a
        preserved terminal status, else a ``replayed`` echo.
    """
    stored_status = stored_payload.get("status")
    if stored_status in _RECONCILE_PRESERVED_STATUSES or stored_status in {
        "offered",
        "pending_human_approval",
        "approved",
        "denied",
        "expired",
    }:
        return ControlPlaneMutationResult.model_validate(stored_payload)
    return ControlPlaneMutationResult.model_validate(
        {**stored_payload, "status": "replayed"},
    )
