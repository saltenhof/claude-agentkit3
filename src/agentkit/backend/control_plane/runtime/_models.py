"""Runtime boundary models and small pure helpers."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agentkit.backend.control_plane.models import (
        ControlPlaneMutationResult,
        EdgeBundle,
        PhaseDispatchResult,
    )
    from agentkit.backend.control_plane.records import SessionRunBindingRecord
    from agentkit.backend.exceptions import ControlPlaneBindingCollisionError
    from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

logger = logging.getLogger(__name__)

_RECONCILE_PRESERVED_STATUSES = frozenset({"aborted", "repair", "failed"})


@dataclass(frozen=True)
class MergePrecondition:
    """Closure-entry push precondition projected from the barrier SSOT."""

    satisfied: bool
    blocking_repos: tuple[str, ...]
    detail: str


class OperationNotFoundError(LookupError):
    """Raised when an ``admin_abort`` target ``op_id`` does not exist (HTTP 404)."""

    def __init__(self, op_id: str) -> None:
        super().__init__(op_id)
        self.op_id = op_id


class OperationNotAbortableError(RuntimeError):
    """Raised when an ``admin_abort`` target is not a live claim (HTTP 409).

    The operation exists but is not currently ``claimed`` -- it is already
    terminal (committed / rejected / aborted / repair / failed / replayed) or was
    resolved concurrently between the load and the abort CAS. Fail-closed: an
    already-resolved operation is not re-aborted (no second terminal write).
    """

    def __init__(self, op_id: str, current_status: str) -> None:
        super().__init__(
            f"operation {op_id!r} is not an abortable in-flight claim (current status: {current_status!r})",
        )
        self.op_id = op_id
        self.current_status = current_status


class _ModeResolutionKeys(Protocol):
    """The authoritative ``(project_key, story_id)`` lookup keys for mode resolution.

    Both :class:`PhaseMutationRequest` and :class:`ClosureCompleteRequest` satisfy
    this structurally, so the single sanctioned-surface mode resolution
    (``_story_lock_records_apply``) is shared across setup and closure without
    coupling to a concrete request type.
    """

    @property
    def project_key(self) -> str: ...

    @property
    def story_id(self) -> str: ...


@dataclass(frozen=True)
class _StartPhaseOutcome:
    """Outcome of the post-claim dispatch for a ``start_phase`` (#1, ERROR-2).

    Carries EITHER a fail-closed ``rejection`` (the caller releases the claim and
    returns it) OR the admitted ``dispatch_result`` for the caller to commit in
    ONE place. Exactly one is non-``None``; both ``None`` means "admitted with no
    dispatch outcome" (a non-setup fail-closed-to-standard materialization).

    ``mints_ownership_record`` (AG3-142, SOLL-015): ``True`` ONLY for a
    genuinely fresh setup start (no active ownership record existed for this
    run) -- the caller's finalize then INSERTS the new active record
    atomically in the SAME transaction instead of enforcing the (not-yet-
    existing) fence.

    ``observed_ownership_epoch`` (AG3-142, no TOCTOU): the ``ownership_epoch``
    of the active record observed at THIS early admission check, when one
    exists (``None`` when ``mints_ownership_record`` is ``True`` -- there is
    nothing yet to observe). Threaded verbatim to the finalize's commit-time
    re-check (mirrors ``owner_operation_epoch``): the fence re-verifies the
    active record STILL carries this EXACT epoch, not merely "some" epoch,
    closing the race window between this check and the commit.
    """

    rejection: ControlPlaneMutationResult | None
    dispatch_result: PhaseDispatchResult | None
    mints_ownership_record: bool = False
    observed_ownership_epoch: int | None = None
    #: AG3-143 (FK-44 §44.3a, SOLL-095): the freshly-formed
    #: ``execution_contract_digest`` hex string for a genuinely fresh setup
    #: start (``mints_ownership_record=True``); ``None`` for every other
    #: commit (nothing to mint) and for a ``rejection`` outcome.
    execution_contract_digest: str | None = None


@dataclass(frozen=True)
class _StartPhaseMaterialization:
    """The PLANNED start_phase side effects + edge bundle (no writes) (#1).

    ERROR-1 fix (#1): the start_phase side effects are PLANNED here (pure record
    construction, no store writes) so the ownership-scoped CAS finalize can apply
    them atomically in ONE transaction, gated on still owning the claim. A fast
    story carries an empty ``binding`` / ``locks`` / ``events`` (it materializes no
    story-scoped state) but still a valid ``bundle`` (ai_augmented).
    """

    bundle: EdgeBundle
    binding: SessionRunBindingRecord | None
    locks: tuple[StoryExecutionLockRecord, ...]
    events: tuple[ExecutionEventRecord, ...]


@dataclass(frozen=True)
class _ClaimOutcome:
    """Outcome of the owner-scoped claim acquisition (AG3-054; AG3-139).

    Exactly one shape is valid:

    * ``won=True`` -- this caller holds the claim (a fresh insert) and proceeds
      to dispatch; ``result`` is ``None`` and ``claimed_at_raw`` is the RAW claim
      instant this caller stamped.
    * ``won=False`` -- this caller LOST; ``result`` is the fail-closed outcome to
      return (a terminal REPLAY, or an "operation in flight, retry" rejection for
      a foreign claim of ANY age); ``claimed_at_raw`` is ``None``.

    AG3-139: there is no wall-clock expiry and no CAS takeover of a foreign claim
    -- ownership never ends by wall clock / TTL / lease (FK-91 §91.1a Rule 16).
    An orphaned claim is ended ONLY via the AG3-138 startup reconciliation or an
    explicit ``admin_abort_inflight_operation``.

    WARNING-4 fix (#4): ``claimed_at_raw`` is the EXACT claim instant (raw ISO
    TEXT) this caller wrote. It is threaded to finalize/release so their
    ownership CAS matches BOTH ``claimed_by`` AND ``claimed_at`` -- a stale owner
    whose token is reused (DI/test wiring) cannot match a NEWER claim generation.

    AG3-138: ``operation_epoch`` is the fencing token stamped on the claim at
    acquisition time (``_build_claim_placeholder``), threaded to finalize so its
    CAS additionally requires the stored epoch to be unchanged
    (``operation_finalize_requires_cas_on_operation_epoch``).
    """

    won: bool
    result: ControlPlaneMutationResult | None
    claimed_at_raw: str | None = None
    operation_epoch: int | None = None

    def result_or_raise(self) -> ControlPlaneMutationResult:
        """Return the loser's result; guard the won-but-no-result invariant."""
        if self.result is None:
            msg = "a lost claim must always carry a fail-closed result"
            raise RuntimeError(msg)
        return self.result


def _start_binding_collision_reason(phase: str, exc: ControlPlaneBindingCollisionError) -> str:
    return "".join(
        (
            f"phase_start({phase}) rejected: {exc}. A start for this run ",
            "must not overwrite a foreign run's live binding (AG3-054 ",
            "run-scoping, fail-closed).",
        )
    )


def _claimed_operation_rejection_reason(operation_kind: str, op_id: str, operation_label: str) -> str:
    suffix = (
        "A complete/fail reusing a live start's op_id must not clobber the claim " if operation_label == "complete/fail" else ""
    )
    return "".join(
        (
            f"{operation_kind} rejected: op_id {op_id!r} is held by a LIVE ",
            "'claimed' start claim; only its owner's finalize/release may ",
            f"transition it. {suffix}(AG3-054 ERROR-3, fail-closed).",
        )
    )


def _phase_binding_collision_reason(operation_kind: str, exc: ControlPlaneBindingCollisionError) -> str:
    return "".join(
        (
            f"{operation_kind} rejected: {exc}. A {operation_kind} for an ",
            "old run must not overwrite a foreign run's live binding ",
            "(AG3-054 run-scoping, fail-closed).",
        )
    )


def _closure_binding_collision_reason(exc: ControlPlaneBindingCollisionError) -> str:
    return "".join(
        (
            f"closure_complete rejected: {exc}. A closure for an old run ",
            "must not tear down a foreign run's live binding (AG3-054 ",
            "run-scoping, fail-closed).",
        )
    )

def _is_valid_owner_token(token: object) -> bool:
    """Whether an owner token is non-empty and UUID-shaped (AG3-054, #5).

    Accepts either a bare UUID (``uuid4`` hex or canonical form) or the productive
    ``owner-<uuid4hex>`` shape (the ``owner-`` prefix is stripped before the UUID
    check). An empty / whitespace-only / non-UUID token is rejected so two distinct
    claims can never cross-match. Validation is purely structural -- any unique
    UUID-shaped token (including a test-injected one) is accepted.

    Args:
        token: The candidate owner token (validated structurally).

    Returns:
        ``True`` iff the token carries a parseable UUID.
    """
    if not isinstance(token, str) or not token.strip():
        return False
    candidate = token.strip()
    if candidate.startswith("owner-"):
        candidate = candidate[len("owner-") :]
    try:
        uuid.UUID(candidate)
    except ValueError:
        return False
    return True
