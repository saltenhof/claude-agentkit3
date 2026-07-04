"""Unit tests for the AG3-138 startup reconciliation of orphaned claims.

Blood-type A decision logic over injectable ports (no I/O): only the OWN
instance's earlier-incarnation orphaned claims are finalized; a partial write goes
to ``repair``, a clean orphan to ``failed``; a store failure is fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest

from agentkit.backend.control_plane.records import (
    BackendInstanceIdentityRecord,
    ControlPlaneOperationRecord,
    ObjectMutationClaimRecord,
)
from agentkit.backend.control_plane.startup_reconcile import (
    StartupReconciliationError,
    run_startup_reconciliation,
)

_NOW = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
_CLAIMED_AT = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)


def _identity(instance_id: str, incarnation: int) -> BackendInstanceIdentityRecord:
    return BackendInstanceIdentityRecord(
        backend_instance_id=instance_id,
        instance_incarnation=incarnation,
        updated_at=_NOW,
    )


def _claim(
    *,
    op_id: str,
    backend_instance_id: str,
    incarnation: int,
    story_id: str = "AG3-300",
    run_id: str | None = "run-1",
) -> ControlPlaneOperationRecord:
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id=story_id,
        run_id=run_id,
        session_id="sess-1",
        operation_kind="phase_start",
        phase="implementation",
        status="claimed",
        response_payload={},
        created_at=_CLAIMED_AT,
        updated_at=_CLAIMED_AT,
        claimed_by="owner-x",
        claimed_at=_CLAIMED_AT,
        operation_epoch=1,
        backend_instance_id=backend_instance_id,
        instance_incarnation=incarnation,
        declared_serialization_scope="tenant-a:AG3-300",
    )


@dataclass
class _FakeReconcileRepo:
    """In-memory identity-fenced orphan store for the reconcile logic."""

    operations: dict[str, ControlPlaneOperationRecord] = field(default_factory=dict)
    #: story_id -> earliest persisted engine-write timestamp. The partial-write
    #: detection is claim-window scoped (story + ``since``), never a ``run_id``
    #: column (the engine's ``flow_executions.run_id`` is engine-internal, distinct
    #: from the control-plane operation ``run_id``; AG3-138 P1).
    engine_writes: dict[str, datetime] = field(default_factory=dict)
    #: When set, the scan raises to prove the fail-closed wrap.
    scan_raises: bool = False

    def list_orphaned_claimed_operations(
        self, backend_instance_id: str, before_incarnation: int
    ) -> tuple[ControlPlaneOperationRecord, ...]:
        if self.scan_raises:
            raise RuntimeError("simulated store failure during orphan scan")
        return tuple(
            op
            for op in self.operations.values()
            if op.status == "claimed"
            and op.backend_instance_id == backend_instance_id
            and op.instance_incarnation is not None
            and op.instance_incarnation < before_incarnation
        )

    def finalize_orphaned_operation(
        self,
        *,
        op_id: str,
        backend_instance_id: str,
        status: str,
        response_payload: dict[str, object],
        now: datetime,
        owner_operation_epoch: int,
    ) -> bool:
        existing = self.operations.get(op_id)
        if (
            existing is None
            or existing.status != "claimed"
            or existing.backend_instance_id != backend_instance_id
        ):
            return False
        #: AG3-138 P3/AC4: the identity fence PLUS the MANDATORY ``operation_epoch`` CAS
        #: observed by the orphan scan -- a row whose epoch moved since the scan (or a
        #: NULL-epoch row) is left untouched (fail-closed, no identity-only path).
        if existing.operation_epoch != owner_operation_epoch:
            return False
        self.operations[op_id] = replace(
            existing,
            status=status,
            response_payload=response_payload,
            updated_at=now,
            operation_epoch=(existing.operation_epoch or 0) + 1,
        )
        return True

    def has_engine_writes_since(self, story_id: str, since: datetime) -> bool:
        #: Claim-window scoped partial-write signal: a recorded engine write for the
        #: story at/after ``since`` (the orphan claim's own ``claimed_at``).
        write_at = self.engine_writes.get(story_id)
        return write_at is not None and write_at >= since


@dataclass
class _FakeObjectClaimRepo:
    """In-memory object-mutation-claim port (AG3-141 Scope item 7).

    A DIRECT, identity-fenced scan of the claim table itself -- independent of
    whatever happened to the claim's paired ``control_plane_operations`` row
    (a crashed single-transaction complete/fail/closure mutation holds a
    durable object claim yet leaves NO ``claimed`` operation row at all, so an
    operation-keyed cascade would never reach it).
    """

    claims: dict[tuple[str, str, str], ObjectMutationClaimRecord] = field(
        default_factory=dict
    )
    released: list[tuple[str, str, str, str]] = field(default_factory=list)

    def seed(self, claim: ObjectMutationClaimRecord) -> None:
        self.claims[
            (claim.project_key, claim.serialization_scope, claim.scope_key)
        ] = claim

    def list_orphaned(
        self, backend_instance_id: str, before_incarnation: int
    ) -> tuple[ObjectMutationClaimRecord, ...]:
        return tuple(
            claim
            for claim in self.claims.values()
            if claim.backend_instance_id == backend_instance_id
            and claim.instance_incarnation < before_incarnation
        )

    def release_claim(
        self, project_key: str, serialization_scope: str, scope_key: str, op_id: str
    ) -> bool:
        self.released.append((project_key, serialization_scope, scope_key, op_id))
        self.claims.pop((project_key, serialization_scope, scope_key), None)
        return True


def _object_claim(
    *,
    op_id: str,
    backend_instance_id: str,
    incarnation: int,
    story_id: str = "AG3-300",
) -> ObjectMutationClaimRecord:
    return ObjectMutationClaimRecord(
        project_key="tenant-a",
        serialization_scope="story",
        scope_key=story_id,
        op_id=op_id,
        backend_instance_id=backend_instance_id,
        instance_incarnation=incarnation,
        acquired_at=_CLAIMED_AT,
        queue_position=0,
    )


def test_only_own_earlier_incarnation_claims_finalized_foreign_untouched() -> None:
    """AC1/AC2: own earlier-incarnation orphans -> failed; foreign untouched."""
    repo = _FakeReconcileRepo()
    # Own, earlier incarnation (2 < 3): reconcilable.
    repo.operations["op-own"] = _claim(
        op_id="op-own", backend_instance_id="inst-me", incarnation=2
    )
    # Foreign identity: NEVER touched by this instance's reconciliation.
    repo.operations["op-foreign"] = _claim(
        op_id="op-foreign", backend_instance_id="inst-other", incarnation=1
    )
    # Own, CURRENT incarnation (3): not an orphan (not < 3).
    repo.operations["op-current"] = _claim(
        op_id="op-current", backend_instance_id="inst-me", incarnation=3
    )

    object_claim_repo = _FakeObjectClaimRepo()
    object_claim_repo.seed(
        _object_claim(op_id="op-own", backend_instance_id="inst-me", incarnation=2)
    )
    object_claim_repo.seed(
        _object_claim(
            op_id="op-foreign",
            backend_instance_id="inst-other",
            incarnation=1,
            story_id="AG3-301",
        )
    )
    object_claim_repo.seed(
        _object_claim(
            op_id="op-current",
            backend_instance_id="inst-me",
            incarnation=3,
            story_id="AG3-302",
        )
    )
    outcome = run_startup_reconciliation(
        repo,  # type: ignore[arg-type]
        _identity("inst-me", 3),
        object_claim_repo=object_claim_repo,  # type: ignore[arg-type]
        now_fn=lambda: _NOW,
    )

    assert outcome.finalized_op_ids == ("op-own",)
    assert outcome.repair_op_ids == ()
    assert repo.operations["op-own"].status == "failed"
    assert repo.operations["op-foreign"].status == "claimed"
    assert repo.operations["op-current"].status == "claimed"
    #: Scope item 7: the DIRECT object-claim scan releases only the caller's
    #: own earlier-incarnation orphan -- the foreign identity and the
    #: own-but-current-incarnation claim are left untouched.
    assert object_claim_repo.released == [("tenant-a", "story", "AG3-300", "op-own")]


def test_orphan_with_engine_writes_goes_to_repair_not_failed() -> None:
    """AC5/IMPL-005: a partial-write orphan enters the explicit repair state."""
    repo = _FakeReconcileRepo()
    repo.operations["op-partial"] = _claim(
        op_id="op-partial", backend_instance_id="inst-me", incarnation=1
    )
    #: An engine write persisted AT the claim's own claimed_at (>= since) -> detected.
    repo.engine_writes["AG3-300"] = _CLAIMED_AT

    object_claim_repo = _FakeObjectClaimRepo()
    object_claim_repo.seed(
        _object_claim(op_id="op-partial", backend_instance_id="inst-me", incarnation=1)
    )
    outcome = run_startup_reconciliation(
        repo,  # type: ignore[arg-type]
        _identity("inst-me", 2),
        object_claim_repo=object_claim_repo,  # type: ignore[arg-type]
        now_fn=lambda: _NOW,
    )

    assert outcome.finalized_op_ids == ("op-partial",)
    assert outcome.repair_op_ids == ("op-partial",)
    result = repo.operations["op-partial"]
    assert result.status == "repair"
    assert "reconcile/repair state" in str(result.response_payload["admin_note"])
    #: A repair-routed orphan's object claim is released too (Scope item 7) --
    #: repair mutation-locks NEW mutations at the operations layer, not via a
    #: held object claim.
    assert object_claim_repo.released == [("tenant-a", "story", "AG3-300", "op-partial")]


def test_object_claim_with_no_paired_operation_row_is_still_reconciled() -> None:
    """Scope item 7 crux: a crashed single-transaction mutation (complete/fail/
    closure) holds a durable object claim but leaves NO ``control_plane_operations``
    row at all (it commits atomically, or crashes before it does) -- an
    operation-keyed cascade could never find it. The DIRECT claim-table scan
    reconciles it anyway.
    """
    repo = _FakeReconcileRepo()  # no operations seeded at all
    object_claim_repo = _FakeObjectClaimRepo()
    object_claim_repo.seed(
        _object_claim(
            op_id="op-orphan-claim-only",
            backend_instance_id="inst-me",
            incarnation=1,
            story_id="AG3-400",
        )
    )

    outcome = run_startup_reconciliation(
        repo,  # type: ignore[arg-type]
        _identity("inst-me", 2),
        object_claim_repo=object_claim_repo,  # type: ignore[arg-type]
        now_fn=lambda: _NOW,
    )

    assert outcome.finalized_op_ids == ()
    assert object_claim_repo.released == [
        ("tenant-a", "story", "AG3-400", "op-orphan-claim-only")
    ]


def test_older_foreign_write_before_claim_does_not_trigger_repair() -> None:
    """AG3-138 P1: a partial write from BEFORE this claim's window -> failed, not repair.

    A clean-crashed orphan (claimed at ``_CLAIMED_AT``) whose story carries an engine
    write from an EARLIER operation (persisted strictly before the claim) must NOT be
    routed to ``repair``: the claim-window (``since = claimed_at``) scoping excludes
    writes that predate this operation, so the older/foreign write is not attributed
    to it. This is the operations-scoped guarantee -- an unrelated write of the same
    story never opens a false repair for a cleanly crashed later operation.
    """
    repo = _FakeReconcileRepo()
    repo.operations["op-clean"] = _claim(
        op_id="op-clean", backend_instance_id="inst-me", incarnation=1
    )
    #: A write one hour BEFORE this orphan's claimed_at -> an earlier operation's write.
    repo.engine_writes["AG3-300"] = _CLAIMED_AT - timedelta(hours=1)

    outcome = run_startup_reconciliation(
        repo,  # type: ignore[arg-type]
        _identity("inst-me", 2),
        object_claim_repo=_FakeObjectClaimRepo(),  # type: ignore[arg-type]
        now_fn=lambda: _NOW,
    )

    assert outcome.finalized_op_ids == ("op-clean",)
    assert outcome.repair_op_ids == ()
    assert repo.operations["op-clean"].status == "failed"


def test_store_failure_is_fail_closed_start() -> None:
    """AC9: a failure during reconciliation raises StartupReconciliationError."""
    repo = _FakeReconcileRepo(scan_raises=True)
    with pytest.raises(StartupReconciliationError):
        run_startup_reconciliation(
            repo,  # type: ignore[arg-type]
            _identity("inst-me", 2),
            object_claim_repo=_FakeObjectClaimRepo(),  # type: ignore[arg-type]
            now_fn=lambda: _NOW,
        )


def test_null_epoch_own_orphan_is_fail_closed_not_unfenced_finalize() -> None:
    """AC4/AC9: a scanned own-identity orphan with a NULL operation_epoch fails closed.

    An own-identity claim is always AG3-138-stamped, so a NULL epoch on a scanned
    orphan is a contradiction; reconciliation must refuse an unfenced (identity-only)
    finalize rather than silently finalizing it, and abort the boot (fail-closed).
    """
    repo = _FakeReconcileRepo()
    null_epoch_claim = replace(
        _claim(op_id="op-null-epoch", backend_instance_id="inst-me", incarnation=1),
        operation_epoch=None,
    )
    repo.operations["op-null-epoch"] = null_epoch_claim

    with pytest.raises(StartupReconciliationError):
        run_startup_reconciliation(
            repo,  # type: ignore[arg-type]
            _identity("inst-me", 3),
            object_claim_repo=_FakeObjectClaimRepo(),  # type: ignore[arg-type]
            now_fn=lambda: _NOW,
        )
    #: The row was NEVER finalized without a fence -- it stays claimed.
    assert repo.operations["op-null-epoch"].status == "claimed"
