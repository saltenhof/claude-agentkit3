"""Unified in-flight idempotency guard (AG3-140, FK-91 §91.1a Rule 5).

This is the SINGLE idempotency mechanism for every mutating BC operation that
follows the ``claim -> mutate -> finalize`` lifecycle -- today
``story_context_manager`` and ``task_management`` (the ``control_plane`` runtime
carries its own richer, story-scoped claim/finalize path for phase operations,
and the guard-counter keeps its atomic single-transaction record; all three now
share the ONE physical record truth: ``control_plane_operations``, the physical
materialization of the formal ``inflight-operation-record`` entity).

FK-91 §91.1a Rule 5 (the one unified contract):
  * ``op_id`` is client-supplied and required (server minting is removed).
  * A replay of the same ``op_id`` returns the STORED result without a second
    mutation.
  * The same ``op_id`` with a DIFFERENT request body is fail-closed
    ``409 idempotency_mismatch`` (body-hash check).
  * A parallel same ``op_id`` is rejected in-flight (the atomic
    ``INSERT ... ON CONFLICT DO NOTHING`` claim means exactly one caller wins
    and dispatches; a loser never runs the mutation twice).

Crash-window closure (the reason this guard replaces the legacy
check-then-record path): the ``claimed`` placeholder row is written BEFORE the
mutation. A crash between the mutation and ``finalize`` leaves the row
``claimed`` (never a silently-missing record), so a retry gets an in-flight
rejection instead of re-executing -- there is no doubly-executable state. An
orphaned claim is ended only by the AG3-138 startup reconciliation or an
explicit ``admin_abort_inflight_operation`` (never by wall clock).

BC ownership: this port is owned by ``state_backend`` and speaks state-backend
vocabulary (primitives only). Consumers depend ONLY on this module and never
reach across into ``control_plane`` internals; the guard builds the
``ControlPlaneOperationRecord`` and routes it through the state-backend
persistence facade on their behalf (clean BC boundary).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from agentkit.backend.state_backend.store import facade

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Body-hash computation (canonical, op_id-excluded)
# ---------------------------------------------------------------------------


def compute_body_hash(body: dict[str, object]) -> str:
    """Compute a deterministic SHA-256 of a canonical request body.

    The ``op_id`` key is excluded so the hash is a pure function of the mutation
    data (a replay of the same mutation with the same ``op_id`` hashes equal; a
    different body under the same ``op_id`` hashes differently -> mismatch).

    Args:
        body: The request body as a dict.

    Returns:
        A lowercase hex SHA-256 digest string.
    """
    canonical = {k: v for k, v in body.items() if k != "op_id"}
    serialized = json.dumps(canonical, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdempotencyRequest:
    """The scope + idempotency key of one mutating operation.

    ``story_id`` is optional (AG3-140): the formal inflight-operation-record is
    op_id-keyed and NOT story-scoped, so a project-scoped operation (a
    task-management mutation, or a ``create_story`` before its id is allocated)
    carries no ``story_id``. ``project_key`` is always present (NOT NULL on the
    record).
    """

    op_id: str
    operation_kind: str
    body_hash: str
    project_key: str
    story_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    phase: str | None = None
    correlation_id: str = ""


@dataclass(frozen=True)
class FreshClaim:
    """This caller WON the claim: proceed to mutate, then ``finalize``/``release``.

    ``owner_token`` and ``claimed_at_iso`` scope the ownership CAS of the later
    ``finalize`` / ``release`` to THIS claim generation.
    """

    owner_token: str
    claimed_at_iso: str


@dataclass(frozen=True)
class ReplayOutcome:
    """A TERMINAL record with a MATCHING body-hash already exists (replay)."""

    result_payload: dict[str, object]


@dataclass(frozen=True)
class MismatchOutcome:
    """The ``op_id`` exists with a DIFFERENT body-hash (409 idempotency_mismatch)."""

    op_id: str


@dataclass(frozen=True)
class InFlightOutcome:
    """A LIVE ``claimed`` row is held by a concurrent caller (409 operation_in_flight)."""

    op_id: str


@dataclass(frozen=True)
class AbortedOutcome:
    """A terminal row that was NOT committed by the ROUTE contract.

    The op_id resolved to a terminal state that the guard contract did not commit
    -- e.g. an ``admin_abort`` set ``status='aborted'`` (or ``repair`` /
    ``failed``) and stored a control-plane payload. It is a STABLE fail-closed
    conflict (409 ``operation_conflict``): NEVER a replay of that foreign result,
    and never a corrupt-500 through the route replay builder.
    """

    op_id: str


#: The result of :meth:`InflightIdempotencyGuard.claim`. Exactly one variant.
ClaimOutcome = (
    FreshClaim | ReplayOutcome | MismatchOutcome | InFlightOutcome | AbortedOutcome
)


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------


class InflightIdempotencyGuard(Protocol):
    """The unified idempotency port (FK-91 §91.1a Rule 5)."""

    def claim(self, request: IdempotencyRequest) -> ClaimOutcome:
        """Atomically claim ``op_id`` before the mutation.

        Returns a :class:`FreshClaim` iff this caller won the claim (proceed to
        mutate). Otherwise returns the fail-closed loser outcome:
        :class:`ReplayOutcome` (terminal record, body-hash match),
        :class:`MismatchOutcome` (terminal record, body-hash differs) or
        :class:`InFlightOutcome` (a live claim is still held).
        """
        ...

    def finalize(
        self,
        request: IdempotencyRequest,
        claim: FreshClaim,
        result_payload: dict[str, object],
    ) -> bool:
        """Ownership-scoped terminal write of the stored result.

        Returns ``True`` iff this owner's terminal write applied. ``False`` when
        the claim was lost in between (e.g. an ``admin_abort``) -- the caller
        must then NOT treat the mutation as durably recorded.
        """
        ...

    def release(self, request: IdempotencyRequest, claim: FreshClaim) -> None:
        """Ownership-scoped release of the claim (idempotent).

        Called when the mutation raised cleanly BEFORE committing any side
        effect, so a retry may re-run. Deletes the row ONLY when it is still
        ``claimed`` by this owner; a terminal or foreign row is left intact.
        """
        ...

    def classify(self, request: IdempotencyRequest) -> ClaimOutcome:
        """Classify the EXISTING row for ``op_id`` WITHOUT attempting a claim.

        Loads the current row and returns the same loser classification as a
        claim-loser (:class:`ReplayOutcome` / :class:`MismatchOutcome` /
        :class:`InFlightOutcome`). Used on a ``finalize`` CAS loss to decide the
        fail-closed outcome (the caller must NOT return its success response when
        the claim was lost/taken-over). Never returns :class:`FreshClaim`.
        """
        ...


# ---------------------------------------------------------------------------
# Production implementation (state-backend facade)
# ---------------------------------------------------------------------------


_CLAIM_STATUS = "claimed"
_TERMINAL_STATUS = "committed"
#: The placeholder body stored on the ``claimed`` row (``response_json`` is NOT
#: NULL). It is overwritten by :meth:`finalize` with the real result payload and
#: is never surfaced to a caller (a claimed row is an in-flight rejection, never
#: a replay).
_CLAIM_PLACEHOLDER: dict[str, object] = {"_inflight": True}


def _load_result_payload(raw: object) -> dict[str, object]:
    """Parse a stored ``response_json`` column value into a result payload dict.

    ``response_json`` is stored as JSON TEXT (K5 Postgres-only truth). A row
    loader may hand back either the raw JSON string or an already-parsed dict;
    both are normalized here. A non-object payload fails closed to an empty dict
    (never a partial replay of a malformed record).
    """
    if isinstance(raw, str):
        parsed: object = json.loads(raw)
    else:
        parsed = raw
    if isinstance(parsed, dict):
        return {str(k): v for k, v in parsed.items()}
    return {}


# ---------------------------------------------------------------------------
# The ONE idempotency classification (SINGLE SOURCE OF TRUTH, Codex r5 method
# change). EVERY idempotency-resolution path in the AG3-140 surface -- the
# generic guard, story_context_manager (via guard.claim/guard.classify) and the
# guard-counter's co-transactional path -- resolves a duplicate/terminal
# ``control_plane_operations`` row through THIS one decision, so no path can
# diverge on the contract again.
# ---------------------------------------------------------------------------

#: ``op_id`` committed by THIS operation -> return the stored result.
ROW_REPLAY = "replay"
#: same ``op_id``, different body OR different operation -> 409 idempotency_mismatch.
ROW_MISMATCH = "mismatch"
#: a terminal state this contract did not commit (aborted/repair/failed) ->
#: 409 operation_conflict, never a replay of the foreign payload.
ROW_CONFLICT = "conflict"
#: a live concurrent ``claimed`` row -> 409 operation_in_flight.
ROW_IN_FLIGHT = "in_flight"


def classify_terminal_row(
    *,
    incoming_body_hash: str,
    incoming_operation_kind: str,
    stored_status: str,
    stored_body_hash: str | None,
    stored_operation_kind: str,
) -> str:
    """Classify a duplicate ``op_id`` row against the unified contract.

    Fail-closed precedence, returning one of :data:`ROW_REPLAY` /
    :data:`ROW_MISMATCH` / :data:`ROW_CONFLICT` / :data:`ROW_IN_FLIGHT`:

    1. ``stored_status == 'claimed'`` -> ``ROW_IN_FLIGHT`` (a live concurrent claim).
    2. ``stored_body_hash != incoming_body_hash`` -> ``ROW_MISMATCH`` (same op_id,
       different body).
    3. ``stored_operation_kind != incoming_operation_kind`` -> ``ROW_MISMATCH`` (the
       op_id is bound to a DIFFERENT operation -- a different action whose body
       hashes equal, e.g. ``task_resolve`` vs ``task_dismiss``, OR a foreign
       ``control_plane`` / guard-counter operation under a colliding op_id). NEVER
       a cross-action / cross-shape replay.
    4. ``stored_status != 'committed'`` -> ``ROW_CONFLICT`` (a terminal the contract
       did not commit: admin-aborted / repair / failed).
    5. otherwise -> ``ROW_REPLAY`` (committed by THIS operation; the consumer
       reconstructs its own payload shape -- an HTTP ``{status_code, body}`` for the
       generic routes, a story snapshot for ``story_context_manager``, a
       ``GuardCounterMutationAccepted`` for the guard-counter).
    """
    if stored_status == _CLAIM_STATUS:
        return ROW_IN_FLIGHT
    if stored_body_hash != incoming_body_hash:
        return ROW_MISMATCH
    if stored_operation_kind != incoming_operation_kind:
        return ROW_MISMATCH
    if stored_status != _TERMINAL_STATUS:
        return ROW_CONFLICT
    return ROW_REPLAY


def _outcome_for_decision(
    op_id: str, decision: str, replay_payload: dict[str, object]
) -> ClaimOutcome:
    """Map a :func:`classify_terminal_row` decision to a guard ``ClaimOutcome``."""
    if decision == ROW_REPLAY:
        return ReplayOutcome(result_payload=replay_payload)
    if decision == ROW_MISMATCH:
        return MismatchOutcome(op_id=op_id)
    if decision == ROW_CONFLICT:
        return AbortedOutcome(op_id=op_id)
    return InFlightOutcome(op_id=op_id)  # ROW_IN_FLIGHT


class StateBackendInflightIdempotencyGuard:
    """Postgres-backed unified idempotency guard (K5 Postgres-only truth).

    Routes the claim/replay/mismatch/in-flight decision through the state-backend
    control-plane-operation persistence facade (the physical
    ``control_plane_operations`` record). Unit tests use
    :class:`InMemoryInflightIdempotencyGuard`; integration/contract tests use
    this against the Postgres fixture.
    """

    def claim(self, request: IdempotencyRequest) -> ClaimOutcome:
        """See :meth:`InflightIdempotencyGuard.claim`."""
        owner_token = uuid.uuid4().hex
        now_iso = datetime.now(UTC).isoformat()
        row: dict[str, Any] = {
            "op_id": request.op_id,
            "project_key": request.project_key,
            "story_id": request.story_id,
            "run_id": request.run_id,
            "session_id": request.session_id,
            "operation_kind": request.operation_kind,
            "phase": request.phase,
            "status": _CLAIM_STATUS,
            "response_json": json.dumps(_CLAIM_PLACEHOLDER),
            "created_at": now_iso,
            "updated_at": now_iso,
            "claimed_by": owner_token,
            "claimed_at": now_iso,
            "request_body_hash": request.body_hash,
            # The AG3-137/AG3-138 instance-fencing columns are populated only by
            # the control-plane runtime's own operations; the generic guard
            # leaves them NULL (its fence is the op_id PK + the ``claimed``
            # status, not an instance epoch).
            "operation_epoch": None,
            "backend_instance_id": None,
            "instance_incarnation": None,
            "declared_serialization_scope": None,
        }
        won = facade.claim_inflight_operation_row_global(row)
        if won:
            return FreshClaim(owner_token=owner_token, claimed_at_iso=now_iso)
        return self._resolve_loser(request)

    def _resolve_loser(self, request: IdempotencyRequest) -> ClaimOutcome:
        """Classify a claim-loser through the shared :func:`classify_terminal_row`."""
        existing = facade.load_inflight_operation_row_global(request.op_id)
        if existing is None:
            # The row vanished between the failed claim and the load (a
            # concurrent release/abort). Fail-closed to in-flight: a retry
            # re-claims cleanly. Never silently re-run under a lost claim.
            return InFlightOutcome(op_id=request.op_id)
        stored_hash = existing.get("request_body_hash")
        decision = classify_terminal_row(
            incoming_body_hash=request.body_hash,
            incoming_operation_kind=request.operation_kind,
            stored_status=str(existing["status"]),
            stored_body_hash=None if stored_hash is None else str(stored_hash),
            stored_operation_kind=str(existing["operation_kind"]),
        )
        replay_payload = (
            _load_result_payload(existing["response_json"])
            if decision == ROW_REPLAY
            else {}
        )
        return _outcome_for_decision(request.op_id, decision, replay_payload)

    def finalize(
        self,
        request: IdempotencyRequest,
        claim: FreshClaim,
        result_payload: dict[str, object],
    ) -> bool:
        """See :meth:`InflightIdempotencyGuard.finalize`."""
        now_iso = datetime.now(UTC).isoformat()
        row: dict[str, Any] = {
            "op_id": request.op_id,
            "status": _TERMINAL_STATUS,
            "response_json": json.dumps(result_payload),
            "updated_at": now_iso,
            "run_id": request.run_id,
            "session_id": request.session_id,
            "phase": request.phase,
        }
        return facade.finalize_inflight_operation_row_global(
            row,
            owner_token=claim.owner_token,
            owner_claimed_at=claim.claimed_at_iso,
        )

    def release(self, request: IdempotencyRequest, claim: FreshClaim) -> None:
        """See :meth:`InflightIdempotencyGuard.release`."""
        facade.release_control_plane_operation_global(
            request.op_id,
            owner_token=claim.owner_token,
            owner_claimed_at=claim.claimed_at_iso,
        )

    def classify(self, request: IdempotencyRequest) -> ClaimOutcome:
        """See :meth:`InflightIdempotencyGuard.classify`."""
        return self._resolve_loser(request)


# ---------------------------------------------------------------------------
# In-memory implementation (first-class unit-test impl -- NOT a mock)
# ---------------------------------------------------------------------------


@dataclass
class _MemRow:
    status: str
    body_hash: str
    result_payload: dict[str, object]
    owner_token: str
    claimed_at_iso: str
    operation_kind: str


@dataclass
class InMemoryInflightIdempotencyGuard:
    """In-process unified idempotency guard for unit tests.

    A first-class implementation (NOT a mock): it reproduces the exact
    claim/replay/mismatch/in-flight semantics of the Postgres guard so a unit
    test exercises the real contract without a database. The atomic
    ``INSERT ... ON CONFLICT DO NOTHING`` is modelled by the single-threaded
    presence check on ``_rows`` (a concurrency test drives the sequence
    explicitly: claim, then a second claim before finalize -> in-flight).
    """

    _rows: dict[str, _MemRow] = field(default_factory=dict)

    def claim(self, request: IdempotencyRequest) -> ClaimOutcome:
        """See :meth:`InflightIdempotencyGuard.claim`."""
        existing = self._rows.get(request.op_id)
        if existing is None:
            owner_token = uuid.uuid4().hex
            claimed_at_iso = datetime.now(UTC).isoformat()
            self._rows[request.op_id] = _MemRow(
                status=_CLAIM_STATUS,
                body_hash=request.body_hash,
                result_payload=dict(_CLAIM_PLACEHOLDER),
                owner_token=owner_token,
                claimed_at_iso=claimed_at_iso,
                operation_kind=request.operation_kind,
            )
            return FreshClaim(owner_token=owner_token, claimed_at_iso=claimed_at_iso)
        return self._classify_existing(request, existing)

    def _classify_existing(
        self, request: IdempotencyRequest, existing: _MemRow
    ) -> ClaimOutcome:
        """Classify an existing row through the shared :func:`classify_terminal_row`."""
        decision = classify_terminal_row(
            incoming_body_hash=request.body_hash,
            incoming_operation_kind=request.operation_kind,
            stored_status=existing.status,
            stored_body_hash=existing.body_hash,
            stored_operation_kind=existing.operation_kind,
        )
        return _outcome_for_decision(
            request.op_id, decision, dict(existing.result_payload)
        )

    def finalize(
        self,
        request: IdempotencyRequest,
        claim: FreshClaim,
        result_payload: dict[str, object],
    ) -> bool:
        """See :meth:`InflightIdempotencyGuard.finalize`."""
        existing = self._rows.get(request.op_id)
        if (
            existing is None
            or existing.status != _CLAIM_STATUS
            or existing.owner_token != claim.owner_token
            or existing.claimed_at_iso != claim.claimed_at_iso
        ):
            return False
        existing.status = _TERMINAL_STATUS
        existing.result_payload = dict(result_payload)
        return True

    def release(self, request: IdempotencyRequest, claim: FreshClaim) -> None:
        """See :meth:`InflightIdempotencyGuard.release`."""
        existing = self._rows.get(request.op_id)
        if (
            existing is not None
            and existing.status == _CLAIM_STATUS
            and existing.owner_token == claim.owner_token
            and existing.claimed_at_iso == claim.claimed_at_iso
        ):
            del self._rows[request.op_id]

    def classify(self, request: IdempotencyRequest) -> ClaimOutcome:
        """See :meth:`InflightIdempotencyGuard.classify`."""
        existing = self._rows.get(request.op_id)
        if existing is None:
            return InFlightOutcome(op_id=request.op_id)
        return self._classify_existing(request, existing)


# ---------------------------------------------------------------------------
# Shared route window-logic (FK-91 §91.1a Rule 5; the claim/mutate/finalize
# invariant, centralized so every BC HTTP wrapper enforces it identically).
# ---------------------------------------------------------------------------


class _RouteResponseLike(Protocol):
    """A BC HTTP route response: an int status code + a JSON body (bytes)."""

    @property
    def status_code(self) -> int: ...

    @property
    def body(self) -> bytes: ...


_SERVER_ERROR = 500


def _idempotency_mismatch_message(op_id: str) -> str:
    return (
        f"op_id {op_id!r} was previously used with a different request body; "
        "use a new op_id for a different mutation"
    )


def _operation_in_flight_message(op_id: str) -> str:
    return (
        f"op_id {op_id!r} is already in flight; retry after the concurrent "
        "operation settles"
    )


def _operation_conflict_message(op_id: str) -> str:
    return (
        f"op_id {op_id!r} resolved to a terminal state that this route did not "
        "commit (e.g. an administrative abort); it cannot be replayed as this "
        "operation's result"
    )


def _route_loser_response[R: _RouteResponseLike](
    outcome: ClaimOutcome,
    request: IdempotencyRequest,
    *,
    replay: Callable[[dict[str, object]], R],
    conflict: Callable[[str, str, dict[str, object]], R],
) -> R | None:
    """Map a non-winning claim outcome to a fail-closed route response (else None)."""
    if isinstance(outcome, ReplayOutcome):
        return replay(outcome.result_payload)
    if isinstance(outcome, MismatchOutcome):
        return conflict(
            "idempotency_mismatch",
            _idempotency_mismatch_message(outcome.op_id),
            {"op_id": outcome.op_id, "conflict": "body_hash_mismatch"},
        )
    if isinstance(outcome, InFlightOutcome):
        return conflict(
            "operation_in_flight",
            _operation_in_flight_message(outcome.op_id),
            {"op_id": outcome.op_id},
        )
    if isinstance(outcome, AbortedOutcome):
        return conflict(
            "operation_conflict",
            _operation_conflict_message(outcome.op_id),
            {"op_id": outcome.op_id},
        )
    return None  # FreshClaim -> this caller must run the mutation


def run_route_idempotent[R: _RouteResponseLike](
    guard: InflightIdempotencyGuard,
    request: IdempotencyRequest,
    *,
    mutate: Callable[[], R],
    replay: Callable[[dict[str, object]], R],
    conflict: Callable[[str, str, dict[str, object]], R],
) -> R:
    """Run one mutating HTTP route under the unified idempotency contract.

    The single, centralized window invariant (FK-91 §91.1a Rule 5) every BC
    wrapper shares:

    * The ``claimed`` placeholder is written by ``claim`` BEFORE ``mutate``.
    * A loser (replay / mismatch / in-flight) short-circuits before mutating.
    * If ``mutate`` RAISES, the durable side effect is atomic-and-last, so the
      raise means NO committed side effect: the owner-scoped claim is RELEASED
      and the exception re-raised (a retry re-executes cleanly). A post-commit
      failure is a PROCESS crash, not a catchable exception here, and leaves the
      ``claimed`` row -> fail-closed in-flight on retry (AC3), never released.
    * A ``>= 500`` route response (the BC mapped an unexpected fault to 500) also
      releases the claim (pre-commit, retry-able).
    * If ``finalize`` returns ``False`` the claim was lost/taken-over (e.g. an
      admin abort) between claim and finalize: the mutation is NOT durably
      recorded under this op_id, so the SUCCESS response is NOT returned;
      ``classify`` re-reads the row and the fail-closed outcome is returned.

    Args:
        guard: The idempotency guard.
        request: The idempotency request (op_id + scope + body-hash).
        mutate: Runs the mutation; returns the BC route response.
        replay: Builds a replay response from a stored result payload (the BC
            validates ``{status_code, body}`` and fails closed on a malformed
            record).
        conflict: Builds a ``409`` response from ``(error_code, message, detail)``.

    Returns:
        The BC route response (the mutation's, a replay, or a fail-closed 409).
    """
    outcome = guard.claim(request)
    loser = _route_loser_response(outcome, request, replay=replay, conflict=conflict)
    if loser is not None:
        return loser
    if not isinstance(outcome, FreshClaim):  # pragma: no cover - exhaustive union
        raise TypeError(f"unexpected claim outcome: {outcome!r}")
    claim = outcome
    try:
        response = mutate()
    except Exception:
        # Pre-outcome exception (durable write is atomic-and-last -> nothing
        # committed): release the claim so a retry re-executes cleanly.
        guard.release(request, claim)
        raise
    if response.status_code >= _SERVER_ERROR:
        guard.release(request, claim)
        return response
    finalized = guard.finalize(
        request,
        claim,
        {"status_code": response.status_code, "body": json.loads(response.body)},
    )
    if not finalized:
        # The claim was lost/taken-over between claim and finalize: do NOT return
        # the success response. Classify the existing row and return the
        # fail-closed outcome (a concurrent identical finalize -> replay; a
        # divergent body -> mismatch; otherwise an in-flight/lost conflict).
        lost = _route_loser_response(
            guard.classify(request), request, replay=replay, conflict=conflict
        )
        if lost is not None:
            return lost
        return conflict(
            "operation_in_flight",
            _operation_in_flight_message(request.op_id),
            {"op_id": request.op_id},
        )
    return response


__all__ = [
    "AbortedOutcome",
    "ClaimOutcome",
    "FreshClaim",
    "IdempotencyRequest",
    "InFlightOutcome",
    "InMemoryInflightIdempotencyGuard",
    "InflightIdempotencyGuard",
    "MismatchOutcome",
    "ReplayOutcome",
    "StateBackendInflightIdempotencyGuard",
    "classify_terminal_row",
    "compute_body_hash",
    "run_route_idempotent",
]
