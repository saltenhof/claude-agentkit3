"""Unit tests for the AG3-138 startup reconciliation of orphaned claims.

Blood-type A decision logic over injectable ports (no I/O): only the OWN
instance's earlier-incarnation orphaned claims are finalized; a Teil-Write goes
to ``repair``, a clean orphan to ``failed``; a store failure is fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane.records import (
    BackendInstanceIdentityRecord,
    ControlPlaneOperationRecord,
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
    engine_write_runs: set[tuple[str, str]] = field(default_factory=set)
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
    ) -> bool:
        existing = self.operations.get(op_id)
        if (
            existing is None
            or existing.status != "claimed"
            or existing.backend_instance_id != backend_instance_id
        ):
            return False
        self.operations[op_id] = replace(
            existing, status=status, response_payload=response_payload, updated_at=now
        )
        return True

    def has_engine_writes_since(
        self, story_id: str, run_id: str, since: datetime
    ) -> bool:
        del since
        return (story_id, run_id) in self.engine_write_runs


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

    outcome = run_startup_reconciliation(
        repo,  # type: ignore[arg-type]
        _identity("inst-me", 3),
        now_fn=lambda: _NOW,
    )

    assert outcome.finalized_op_ids == ("op-own",)
    assert outcome.repair_op_ids == ()
    assert repo.operations["op-own"].status == "failed"
    assert repo.operations["op-foreign"].status == "claimed"
    assert repo.operations["op-current"].status == "claimed"


def test_orphan_with_engine_writes_goes_to_repair_not_failed() -> None:
    """AC5/IMPL-005: a Teil-Write orphan enters the explicit repair state."""
    repo = _FakeReconcileRepo()
    repo.operations["op-partial"] = _claim(
        op_id="op-partial", backend_instance_id="inst-me", incarnation=1
    )
    repo.engine_write_runs.add(("AG3-300", "run-1"))

    outcome = run_startup_reconciliation(
        repo,  # type: ignore[arg-type]
        _identity("inst-me", 2),
        now_fn=lambda: _NOW,
    )

    assert outcome.finalized_op_ids == ("op-partial",)
    assert outcome.repair_op_ids == ("op-partial",)
    result = repo.operations["op-partial"]
    assert result.status == "repair"
    assert "Reconcile-/Repair-Zustand" in str(result.response_payload["admin_note"])


def test_store_failure_is_fail_closed_start() -> None:
    """AC9: a failure during reconciliation raises StartupReconciliationError."""
    repo = _FakeReconcileRepo(scan_raises=True)
    with pytest.raises(StartupReconciliationError):
        run_startup_reconciliation(
            repo,  # type: ignore[arg-type]
            _identity("inst-me", 2),
            now_fn=lambda: _NOW,
        )
