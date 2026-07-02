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

from agentkit.backend.control_plane.ownership import (
    MIN_INSTANCE_INCARNATION,
    MIN_OWNERSHIP_EPOCH,
    MIN_QUEUE_POSITION,
    BindingStatus,
    OwnershipAcquisition,
    OwnershipStatus,
    is_canonical_binding_version,
)

#: Closed set of admissible ``SessionRunBindingRecord.status`` values (the
#: ``BindingStatus`` value space) for fail-closed record-boundary validation.
_VALID_BINDING_STATUS = frozenset(status.value for status in BindingStatus)

if TYPE_CHECKING:
    from datetime import datetime

__all__ = (
    "BackendInstanceIdentityRecord",
    "BindingDeleteScope",
    "ControlPlaneOperationRecord",
    "ObjectMutationClaimRecord",
    "RunOwnershipRecord",
    "SessionRunBindingRecord",
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
    row per participating repo (state-storage entities v5). Replaces the former
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

    def __post_init__(self) -> None:
        if self.ownership_epoch < MIN_OWNERSHIP_EPOCH:
            raise ValueError(
                f"ownership_epoch must be >= {MIN_OWNERSHIP_EPOCH}, "
                f"got {self.ownership_epoch!r}",
            )
        if not self.repo_id.strip():
            raise ValueError("repo_id is part of the identity and must not be empty")


@dataclass(frozen=True)
class BackendInstanceIdentityRecord:
    """Persistent backend instance identity + boot incarnation (IMPL-004).

    Persistence for ``backend_instance_id`` plus a monotone boot incarnation
    counter (FK-91 §91.1a rule 16). AG3-137 provides the schema/record/repository
    so AG3-138 need only create/increment on boot.

    Raises:
        ValueError: On an empty ``backend_instance_id`` or an
            ``instance_incarnation`` below the minimum.
    """

    backend_instance_id: str
    instance_incarnation: int
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.backend_instance_id.strip():
            raise ValueError("backend_instance_id must not be empty")
        if self.instance_incarnation < MIN_INSTANCE_INCARNATION:
            raise ValueError(
                "instance_incarnation must be >= "
                f"{MIN_INSTANCE_INCARNATION}, got {self.instance_incarnation!r}",
            )


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
    #: The EXACT raw ``claimed_at`` column value as read back from the store
    #: (ISO-8601 TEXT, or ``None``). The takeover CAS observes THIS value so it
    #: matches the raw column like-for-like (ERROR-2). ``None`` on a fresh
    #: (not-yet-stored) record.
    claimed_at_raw: str | None = None
    #: AG3-137 additive ``inflight-operation-record`` columns (FK-91 §91.1a
    #: rules 13/16). Populated by AG3-138/AG3-141; ``None`` on legacy/pre-AG3-137
    #: rows and on AG3-137 writes.
    operation_epoch: int | None = None
    backend_instance_id: str | None = None
    instance_incarnation: int | None = None
    declared_serialization_scope: str | None = None
    finalized_at: datetime | None = None
