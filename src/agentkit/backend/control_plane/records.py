"""Control-plane records: session-run binding, ownership and operation records.

Blood-type A (technology-free domain records). The new session-ownership
records (:class:`RunOwnershipRecord`, :class:`ObjectMutationClaimRecord`,
:class:`TakeoverTransferRecord`, :class:`BackendInstanceIdentityRecord`) carry
pure ``__post_init__`` value validation (no I/O); the DB-enforced
``at_most_one_active_ownership_per_story`` partial-unique invariant and the
transaction/constraint mechanics live in the ``state_backend`` layer
(blood-type AT/T), not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.edge_commands import ALL_COMMAND_KINDS, ALL_COMMAND_STATUSES
from agentkit.backend.control_plane.ownership import (
    MIN_INSTANCE_INCARNATION,
    MIN_OWNERSHIP_EPOCH,
    MIN_QUEUE_POSITION,
    BindingStatus,
    OwnershipAcquisition,
    OwnershipStatus,
    TakeoverApprovalStatus,
    is_canonical_binding_version,
)
from agentkit.backend.state_backend.backend_instance_identity_types import (
    BackendInstanceIdentityRecord as BackendInstanceIdentityRecord,
)

#: Closed set of admissible ``SessionRunBindingRecord.status`` values (the
#: ``BindingStatus`` value space) for fail-closed record-boundary validation.
_VALID_BINDING_STATUS = frozenset(status.value for status in BindingStatus)
_VALID_TAKEOVER_CHALLENGE_STATUS = frozenset(
    {"pending", "confirmed", "denied", "expired"}
)

if TYPE_CHECKING:
    from datetime import datetime

__all__ = (
    "BackendInstanceIdentityRecord",
    "BindingDeleteScope",
    "ControlPlaneOperationRecord",
    "EdgeCommandRecord",
    "ObjectMutationClaimRecord",
    "RunOwnershipRecord",
    "SessionRunBindingRecord",
    "TakeoverApprovalRecord",
    "TakeoverChallengeRecord",
    "TakeoverChallengeRepoRecord",
    "TakeoverConfirmTerminalRecords",
    "TakeoverTransferRecord",
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
    """Central session-to-run binding used for operating mode resolution.

    Session-side projection of the active :class:`RunOwnershipRecord` (FK-56
    §56.8): it resolves the operating mode and carries the session view
    (principal, worktrees, ``binding_version``) but is subordinate to the
    ownership record.

    AG3-137 (additive, fail-closed value domains): ``status`` (``active`` |
    ``revoked``, FK-56 §56.7a) and a machine-readable ``revocation_reason``
    (vocabulary includes ``ownership_transferred``) are additive with safe
    defaults so pre-existing constructors stay compatible. ``binding_version``
    carries a monotone positive-integer version token (FK-17 §17.3a.16, minted
    DB-monotone by ``control_plane.runtime._next_binding_version``).

    The value stays typed ``str`` (a canonical decimal, e.g. ``"1"``, ``"2"``)
    rather than ``int`` because it flows verbatim into the derived
    ``StoryExecutionLockRecord`` / edge-bundle projections whose column lives in
    ``sqlite_store`` (K5: not migrated to a numeric column here); a literal
    numeric-column migration is the fencing consumer's job (AG3-142). But the
    value DOMAIN is a monotone positive integer and is enforced hard here at the
    record boundary (:func:`is_canonical_binding_version`), so no ``bind-*`` /
    ``exit-*`` correlation token, empty string or leading-zero form can enter a
    binding. The ``exit-<id>`` teardown token legitimately carried by the
    story-exit path lives on the ``StoryExecutionLockRecord`` axis, NOT here.

    No admission/fencing semantics change here (that is AG3-142).

    Raises:
        ValueError: On a non-canonical ``binding_version`` (not a base-10 integer
            ``>= 1``), an unknown ``status`` (outside the ``BindingStatus`` space),
            a ``revocation_reason`` set on an ``active`` binding, or a missing
            ``revocation_reason`` on a ``revoked`` binding.
    """

    session_id: str
    project_key: str
    story_id: str
    run_id: str
    principal_type: str
    worktree_roots: tuple[str, ...]
    binding_version: str
    updated_at: datetime
    status: str = BindingStatus.ACTIVE.value
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        if not is_canonical_binding_version(self.binding_version):
            raise ValueError(
                "binding_version must be a canonical base-10 integer >= 1 "
                "(FK-17 §17.3a.16: monotone, CAS-capable); got "
                f"{self.binding_version!r} (a bind-*/exit-* correlation token, "
                "empty string or leading-zero form is not a valid binding "
                "version).",
            )
        if self.status not in _VALID_BINDING_STATUS:
            raise ValueError(
                "SessionRunBindingRecord.status must be one of "
                f"{sorted(_VALID_BINDING_STATUS)} (FK-56 §56.7a), got "
                f"{self.status!r}",
            )
        if self.status == BindingStatus.ACTIVE.value:
            if self.revocation_reason is not None:
                raise ValueError(
                    "an active binding must not carry a revocation_reason "
                    "(FK-56 §56.7a: the reason is an attribute of a REVOKED "
                    f"binding); got {self.revocation_reason!r}",
                )
        elif self.revocation_reason is None or not self.revocation_reason.strip():
            raise ValueError(
                "a revoked binding requires a machine-readable revocation_reason "
                "(FK-56 §56.7a); got an empty/missing reason",
            )


@dataclass(frozen=True)
class RunOwnershipRecord:
    """Canonical, DB-enforced ownership anchor of a story run (FK-17 §17.3.15).

    Answers which session owns the implementation of a story and is the
    authoritative admission basis for all regime mutations (FK-56 §56.8a). The
    control-plane runtime is the single writer, on behalf of the
    ``story-lifecycle`` BC (FK-17 §17.5). Persistence-model tag:
    ``canonical_runtime_ledger`` (FK-17 §17.7).

    Identity is ``(project_key, story_id, run_id)`` (exactly one row per run).
    At most one record with ``status == ACTIVE`` may exist per
    ``(project_key, story_id)`` — enforced by the persistence layer as a
    partial-unique index (``at_most_one_active_ownership_per_story``), never as
    an application-side check.

    Raises:
        ValueError: On an ``ownership_epoch`` below
            :data:`~agentkit.backend.control_plane.ownership.MIN_OWNERSHIP_EPOCH`,
            an empty ``owner_session_id`` or an empty ``audit_ref``.
    """

    project_key: str
    story_id: str
    run_id: str
    owner_session_id: str
    ownership_epoch: int
    status: OwnershipStatus
    acquired_via: OwnershipAcquisition
    acquired_at: datetime
    audit_ref: str

    def __post_init__(self) -> None:
        if self.ownership_epoch < MIN_OWNERSHIP_EPOCH:
            raise ValueError(
                "ownership_epoch must be >= "
                f"{MIN_OWNERSHIP_EPOCH} (FK-17 §17.3a.15), got "
                f"{self.ownership_epoch!r}",
            )
        if not self.owner_session_id.strip():
            raise ValueError("owner_session_id must be a non-empty session id")
        if not self.audit_ref.strip():
            raise ValueError(
                "audit_ref is mandatory (FK-17 §17.3a.15): the reference to the "
                "triggering audit operation must not be empty",
            )


@dataclass(frozen=True)
class ObjectMutationClaimRecord:
    """Instance-bound object-mutation claim (``state-storage.entity.``\
``object-mutation-claim``).

    Serialises mutations per mutated object (FK-91 §91.1a rules 13/16). The
    claim is bound to ``backend_instance_id`` plus ``instance_incarnation`` and
    **never** expires by wall-clock time, TTL, lease or heartbeat
    (``object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock``)
    — there is deliberately no TTL/expiry attribute.

    Raises:
        ValueError: On a missing instance identity (empty ``backend_instance_id``),
            an ``instance_incarnation`` below the minimum, a ``queue_position``
            below zero, an empty ``op_id`` or empty scope components.
    """

    project_key: str
    serialization_scope: str
    scope_key: str
    op_id: str
    backend_instance_id: str
    instance_incarnation: int
    acquired_at: datetime
    queue_position: int

    def __post_init__(self) -> None:
        if not self.backend_instance_id.strip():
            raise ValueError(
                "object-mutation claim requires an instance identity: "
                "backend_instance_id must not be empty (FK-91 §91.1a rule 16)",
            )
        if self.instance_incarnation < MIN_INSTANCE_INCARNATION:
            raise ValueError(
                "instance_incarnation must be >= "
                f"{MIN_INSTANCE_INCARNATION}, got {self.instance_incarnation!r}",
            )
        if self.queue_position < MIN_QUEUE_POSITION:
            raise ValueError(
                f"queue_position must be >= {MIN_QUEUE_POSITION}, "
                f"got {self.queue_position!r}",
            )
        if not self.op_id.strip():
            raise ValueError("op_id must not be empty")
        if not self.serialization_scope.strip() or not self.scope_key.strip():
            raise ValueError(
                "serialization_scope and scope_key identify the claimed object "
                "and must not be empty",
            )


@dataclass(frozen=True)
class TakeoverTransferRecord:
    """Per-repo takeover transfer record (``state-storage.entity.``\
``takeover-transfer-record``).

    Identity ``(project_key, story_id, run_id, ownership_epoch, repo_id)`` — one
    row per participating repo (state-storage entities v6). Replaces the former
    ``takeover-worktree-snapshot`` (SOLL-147): the handover object is a SHA
    (``takeover_base_sha``), never a file snapshot; no snapshot infrastructure
    exists.

    AG3-137 provides the schema/record/repository only. The productive writer
    (challenge → confirm CAS) is AG3-148, which is why the non-identity
    attributes are optional here: they are materialised across the transfer
    lifecycle (e.g. ``takeover_base_sha`` at confirm, FK-56 §56.13c) rather than
    all at once.

    Raises:
        ValueError: On an ``ownership_epoch`` below the minimum or empty identity
            components.
    """

    project_key: str
    story_id: str
    run_id: str
    ownership_epoch: int
    repo_id: str
    takeover_base_sha: str | None = None
    last_push_at: datetime | None = None
    push_lag_hint: str | None = None
    base_quality: str | None = None
    challenge_ref: str | None = None
    confirm_ref: str | None = None
    reconciled_at: datetime | None = None
    reconcile_ref: str | None = None

    def __post_init__(self) -> None:
        if self.ownership_epoch < MIN_OWNERSHIP_EPOCH:
            raise ValueError(
                f"ownership_epoch must be >= {MIN_OWNERSHIP_EPOCH}, "
                f"got {self.ownership_epoch!r}",
            )
        if not self.repo_id.strip():
            raise ValueError("repo_id is part of the identity and must not be empty")
        if self.reconciled_at is None and self.reconcile_ref is not None:
            raise ValueError("reconcile_ref requires reconciled_at")
        if self.reconciled_at is not None and self.reconcile_ref is None:
            raise ValueError("reconciled_at requires reconcile_ref")
        if self.reconcile_ref is not None and not self.reconcile_ref.strip():
            raise ValueError("reconcile_ref must be non-empty when present")
        if self.reconcile_ref is not None and not self.reconcile_ref.startswith(
            "admin_transition:",
        ):
            raise ValueError(
                "pre-AG3-151 takeover reconcile clear requires "
                "an audited admin_transition reconcile_ref",
            )


@dataclass(frozen=True)
class TakeoverChallengeRepoRecord:
    """Persisted per-repo challenge display/audit block."""

    repo_id: str
    takeover_base_sha: str | None
    last_push_at: datetime | None
    push_lag_hint: str | None
    base_quality: str

    def __post_init__(self) -> None:
        if not self.repo_id.strip():
            raise ValueError("repo_id must not be empty")
        if not self.base_quality.strip():
            raise ValueError("base_quality must not be empty")


@dataclass(frozen=True)
class TakeoverChallengeRecord:
    """Server-authoritative takeover challenge decision basis."""

    challenge_id: str
    request_op_id: str
    project_key: str
    story_id: str
    run_id: str
    requesting_session_id: str
    requesting_principal_type: str
    reason: str
    owner_session_id: str
    ownership_epoch: int
    binding_version: str
    phase_status: str
    issued_at: datetime
    expires_at: datetime
    repos: tuple[TakeoverChallengeRepoRecord, ...]
    open_operation_ids: tuple[str, ...]
    takeover_history_refs: tuple[str, ...]
    status: str = "pending"
    decided_at: datetime | None = None
    terminal_op_id: str | None = None

    def __post_init__(self) -> None:
        for value_name in (
            "challenge_id",
            "request_op_id",
            "project_key",
            "story_id",
            "run_id",
            "requesting_session_id",
            "requesting_principal_type",
            "reason",
            "owner_session_id",
            "binding_version",
            "phase_status",
        ):
            if not str(getattr(self, value_name)).strip():
                raise ValueError(f"{value_name} must not be empty")
        if self.ownership_epoch < MIN_OWNERSHIP_EPOCH:
            raise ValueError(
                f"ownership_epoch must be >= {MIN_OWNERSHIP_EPOCH}, "
                f"got {self.ownership_epoch!r}",
            )
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if self.status not in _VALID_TAKEOVER_CHALLENGE_STATUS:
            raise ValueError(
                "status must be one of "
                f"{sorted(_VALID_TAKEOVER_CHALLENGE_STATUS)}, got {self.status!r}",
            )
        if self.status == "pending":
            if self.decided_at is not None or self.terminal_op_id is not None:
                raise ValueError("a pending challenge must not carry terminal audit")
        elif self.decided_at is None or not (self.terminal_op_id or "").strip():
            raise ValueError("a terminal challenge requires decided_at and terminal_op_id")


@dataclass(frozen=True)
class TakeoverConfirmTerminalRecords:
    """Terminal rows that confirm commits beside the ownership transfer."""

    challenge: TakeoverChallengeRecord
    request_op_record: ControlPlaneOperationRecord
    challenge_to_insert: TakeoverChallengeRecord | None = None
    challenge_to_expire: TakeoverChallengeRecord | None = None
    approved_approval: TakeoverApprovalRecord | None = None


@dataclass(frozen=True)
class TakeoverApprovalRecord:
    """Persistent human approval request for an agent-initiated takeover."""

    approval_id: str
    project_key: str
    story_id: str
    run_id: str
    requested_by_session_id: str
    requested_by_principal_type: str
    reason: str
    challenge_ref: str
    status: TakeoverApprovalStatus
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None
    decided_by_session_id: str | None = None
    decision_reason: str | None = None

    def __post_init__(self) -> None:
        for value_name in (
            "approval_id",
            "project_key",
            "story_id",
            "run_id",
            "requested_by_session_id",
            "requested_by_principal_type",
            "reason",
            "challenge_ref",
        ):
            if not str(getattr(self, value_name)).strip():
                raise ValueError(f"{value_name} must not be empty")
        if self.expires_at <= self.requested_at:
            raise ValueError("expires_at must be after requested_at")
        if self.status is TakeoverApprovalStatus.PENDING:
            if self.decided_at is not None or self.decided_by_session_id is not None:
                raise ValueError("a pending approval must not carry decision metadata")
            return
        if self.decided_at is None:
            raise ValueError("a terminal approval requires decided_at")
        if self.status in {
            TakeoverApprovalStatus.APPROVED,
            TakeoverApprovalStatus.DENIED,
        } and (
            self.decided_by_session_id is None
            or not self.decided_by_session_id.strip()
        ):
            raise ValueError("approved/denied approvals require decided_by_session_id")


@dataclass(frozen=True)
class ControlPlaneOperationRecord:
    """Idempotent mutation record for one control-plane operation.

    AG3-054 (owner-scoped claim): ``claimed_by`` / ``claimed_at`` carry the
    ownership of an in-flight ``claimed`` row. ``claimed_by`` is the per-call
    owner token minted by the runtime; ``claimed_at`` is the claim instant
    (ISO-8601 TEXT, matching the table's other instants). AG3-139: ``claimed_at``
    is a pure AUDIT instant -- no code path compares it against a wall clock or a
    TTL to decide whether the claim has "expired"; ownership never ends by wall
    clock (FK-91 §91.1a Rule 16). It IS still consulted, verbatim, by the
    ownership-scoped finalize/release CAS (WARNING-4, ``owner_claimed_at``) and
    as the ``since`` bound for the AG3-138 admin-abort partial-write probe. Both
    ``claimed_by`` / ``claimed_at`` are ``None`` on a TERMINAL row (the finalize
    clears ``claimed_by`` to mark "no owner holds it"); a terminal row is
    identified by ``status != 'claimed'``.

    AG3-137 (additive, ``inflight-operation-record`` columns): ``operation_epoch``,
    ``backend_instance_id``, ``instance_incarnation``,
    ``declared_serialization_scope`` and ``finalized_at`` are additive and default
    to ``None``. AG3-137 only carries them through schema/record/mapper; their
    population and fencing semantics arrive in AG3-138 / AG3-141.
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
    #: AG3-137 additive ``inflight-operation-record`` columns (FK-91 §91.1a
    #: rules 13/16). Populated by AG3-138/AG3-141; ``None`` on legacy/pre-AG3-137
    #: rows and on AG3-137 writes.
    operation_epoch: int | None = None
    backend_instance_id: str | None = None
    instance_incarnation: int | None = None
    declared_serialization_scope: str | None = None
    finalized_at: datetime | None = None
    #: AG3-140 (unified idempotency contract): SHA-256 of the canonical request
    #: body (op_id excluded). A claim stamps it; a claim-loser compares it to
    #: decide replay (hash match) vs ``409 idempotency_mismatch`` (hash differs).
    #: ``None`` on legacy / pre-AG3-140 rows and on control-plane operations that
    #: do not carry a body-hash (the phase/closure/sync paths dedup on op_id
    #: alone, unchanged).
    request_body_hash: str | None = None


@dataclass(frozen=True)
class EdgeCommandRecord:
    """One Edge-Command-Queue record (``state-storage.entity.edge-command-record``).

    FK-91 §91.1b: identity is ``command_id``; ``(project_key, story_id, run_id,
    session_id)`` scopes the command to the ONE owning session. ``ownership_epoch``
    is stamped at CREATION time (the active record's epoch the commissioning
    mutation observed) -- pure audit accountability, never a second fencing key:
    the Rule-15 fence at result-commit time re-reads the CURRENT active record,
    exactly like every other regime mutation (``_enforce_ownership_fence_row``).

    No wall-clock TTL/expiry field exists by design (SOLL-165, FK-91 §91.1a Rule
    16): an open command (``status`` in ``created``/``delivered``) stays open
    until a result terminates it -- there is no expiry codepath.

    Raises:
        ValueError: On an unknown ``command_kind``/``status``, an
            ``ownership_epoch`` below the minimum, or an empty identity
            component.
    """

    command_id: str
    project_key: str
    story_id: str
    run_id: str
    session_id: str
    command_kind: str
    payload: dict[str, object]
    status: str
    ownership_epoch: int
    created_at: datetime
    delivered_at: datetime | None = None
    completed_at: datetime | None = None
    result_op_id: str | None = None
    result_type: str | None = None
    result_payload: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.command_id.strip():
            raise ValueError("command_id must not be empty")
        if (
            not self.project_key.strip()
            or not self.story_id.strip()
            or not self.run_id.strip()
        ):
            raise ValueError("project_key, story_id and run_id must not be empty")
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty (the owning session)")
        if self.command_kind not in ALL_COMMAND_KINDS:
            raise ValueError(
                f"command_kind must be one of {sorted(ALL_COMMAND_KINDS)}, "
                f"got {self.command_kind!r}",
            )
        if self.status not in ALL_COMMAND_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(ALL_COMMAND_STATUSES)}, "
                f"got {self.status!r}",
            )
        if self.ownership_epoch < MIN_OWNERSHIP_EPOCH:
            raise ValueError(
                f"ownership_epoch must be >= {MIN_OWNERSHIP_EPOCH}, "
                f"got {self.ownership_epoch!r}",
            )
