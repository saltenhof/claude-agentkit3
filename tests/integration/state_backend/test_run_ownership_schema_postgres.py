"""Integration: AG3-137 session-ownership schema against the REAL Postgres backend.

Exercises the DB-enforced mechanics that only a real Postgres can prove:
the ``at_most_one_active_ownership_per_story`` partial-unique invariant (AK1),
field-exact schemas with no TTL / snapshot columns (AK2), the lossless additive
bootstrap over pre-existing rows (AK3), and the idempotent, fail-closed
run-ownership backfill wired into the schema bootstrap (AK6/IMPL-007).

The ``postgres_isolated_schema`` fixture is auto-attached to every
``/integration/state_backend/`` item (``tests/integration/conftest.py``); it
pins ``AGENTKIT_STATE_BACKEND=postgres`` on a worker-scoped, per-test-isolated
schema (a disposable ``postgres:17-alpine`` container locally). When neither an
explicit Postgres env nor Docker is available the session fixture fails closed,
so these tests genuinely execute the DDL/DML on Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime

import psycopg
import pytest

from agentkit.backend.control_plane.ownership import (
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.records import (
    BackendInstanceIdentityRecord,
    ObjectMutationClaimRecord,
    RunOwnershipRecord,
    SessionRunBindingRecord,
    TakeoverTransferRecord,
)
from agentkit.backend.state_backend import postgres_store
from agentkit.backend.state_backend.store import (
    insert_object_mutation_claim_global,
    insert_run_ownership_record_global,
    load_active_run_ownership_record_global,
    load_backend_instance_identity_global,
    load_control_plane_operation_global,
    load_object_mutation_claim_global,
    load_run_ownership_record_global,
    load_takeover_transfer_record_global,
    reset_backend_cache_for_tests,
    save_backend_instance_identity_global,
    save_session_run_binding_global,
    save_story_execution_lock_global,
    save_takeover_transfer_record_global,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC)


def _ownership(
    *,
    story_id: str,
    run_id: str,
    status: OwnershipStatus = OwnershipStatus.ACTIVE,
    epoch: int = 1,
    project_key: str = "tenant-a",
) -> RunOwnershipRecord:
    return RunOwnershipRecord(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        owner_session_id="sess-1",
        ownership_epoch=epoch,
        status=status,
        acquired_via=OwnershipAcquisition.SETUP,
        acquired_at=_NOW,
        audit_ref="audit:x",
    )


def _binding(
    *,
    session_id: str,
    story_id: str,
    run_id: str,
    project_key: str = "tenant-a",
) -> SessionRunBindingRecord:
    return SessionRunBindingRecord(
        session_id=session_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        principal_type="orchestrator",
        worktree_roots=("wt",),
        binding_version="1",
        updated_at=_NOW,
    )


def _active_lock(*, story_id: str, run_id: str, project_key: str = "tenant-a") -> None:
    from agentkit.backend.governance.guard_system.records import (
        StoryExecutionLockRecord,
    )

    save_story_execution_lock_global(
        StoryExecutionLockRecord(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=("wt",),
            binding_version="1",
            activated_at=_NOW,
            updated_at=_NOW,
        )
    )


def _column_names(table: str) -> set[str]:
    with postgres_store._connect_global() as conn:
        rows = conn.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = ?
            """,
            (table,),
        ).fetchall()
    return {str(row["column_name"]) for row in rows}


def _count_ownership(project_key: str, story_id: str) -> int:
    with postgres_store._connect_global() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM run_ownership_records
            WHERE project_key = ? AND story_id = ?
            """,
            (project_key, story_id),
        ).fetchone()
    return int(row["n"])


# ---------------------------------------------------------------------------
# AK1 — DB-enforced at_most_one_active_ownership_per_story (partial-unique)
# ---------------------------------------------------------------------------


def test_second_active_ownership_for_same_story_is_rejected_by_constraint() -> None:
    """AK1: a second status='active' record for the same story fails deterministically.

    Not an application-side check, not a silent overwrite — the partial-unique
    index raises a constraint violation (fail-closed, FK-56 §56.8a).
    """
    insert_run_ownership_record_global(_ownership(story_id="AG3-201", run_id="run-a"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_run_ownership_record_global(
            _ownership(story_id="AG3-201", run_id="run-b")
        )
    # The first (only) active record is intact — never overwritten.
    active = load_active_run_ownership_record_global("tenant-a", "AG3-201")
    assert active is not None
    assert active.run_id == "run-a"


def test_inactive_records_coexist_with_one_active_record() -> None:
    """AK1: the partial-unique is scoped to active only; historical records coexist."""
    insert_run_ownership_record_global(
        _ownership(story_id="AG3-202", run_id="run-old", status=OwnershipStatus.ENDED)
    )
    insert_run_ownership_record_global(
        _ownership(story_id="AG3-202", run_id="run-new", status=OwnershipStatus.ACTIVE)
    )
    active = load_active_run_ownership_record_global("tenant-a", "AG3-202")
    assert active is not None
    assert active.run_id == "run-new"
    ended = load_run_ownership_record_global("tenant-a", "AG3-202", "run-old")
    assert ended is not None
    assert ended.status is OwnershipStatus.ENDED


# ---------------------------------------------------------------------------
# AK2 — field-exact schemas, no TTL, no snapshot, per-repo transfer identity
# ---------------------------------------------------------------------------


def test_object_mutation_claim_schema_is_field_exact_with_no_ttl() -> None:
    assert _column_names("object_mutation_claims") == {
        "project_key",
        "serialization_scope",
        "scope_key",
        "op_id",
        "backend_instance_id",
        "instance_incarnation",
        "acquired_at",
        "queue_position",
    }
    claim = ObjectMutationClaimRecord(
        project_key="tenant-a",
        serialization_scope="story",
        scope_key="AG3-210",
        op_id="op-1",
        backend_instance_id="inst-1",
        instance_incarnation=1,
        acquired_at=_NOW,
        queue_position=0,
    )
    insert_object_mutation_claim_global(claim)
    assert load_object_mutation_claim_global("tenant-a", "story", "AG3-210") == claim
    # A duplicate claimed-object identity is rejected (the object is exclusive).
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_object_mutation_claim_global(claim)


def test_takeover_transfer_schema_is_field_exact_one_row_per_repo() -> None:
    assert _column_names("takeover_transfer_records") == {
        "project_key",
        "story_id",
        "run_id",
        "ownership_epoch",
        "repo_id",
        "takeover_base_sha",
        "last_push_at",
        "push_lag_hint",
        "base_quality",
        "challenge_ref",
        "confirm_ref",
    }
    repo_a = TakeoverTransferRecord(
        project_key="tenant-a",
        story_id="AG3-211",
        run_id="run-1",
        ownership_epoch=1,
        repo_id="repo-a",
        takeover_base_sha="sha-a",
    )
    repo_b = TakeoverTransferRecord(
        project_key="tenant-a",
        story_id="AG3-211",
        run_id="run-1",
        ownership_epoch=1,
        repo_id="repo-b",
        takeover_base_sha="sha-b",
    )
    save_takeover_transfer_record_global(repo_a)
    save_takeover_transfer_record_global(repo_b)
    # One row per participating repo — both persist independently.
    assert (
        load_takeover_transfer_record_global("tenant-a", "AG3-211", "run-1", 1, "repo-a")
        == repo_a
    )
    assert (
        load_takeover_transfer_record_global("tenant-a", "AG3-211", "run-1", 1, "repo-b")
        == repo_b
    )


def test_run_ownership_schema_is_field_exact() -> None:
    assert _column_names("run_ownership_records") == {
        "project_key",
        "story_id",
        "run_id",
        "owner_session_id",
        "ownership_epoch",
        "status",
        "acquired_via",
        "acquired_at",
        "audit_ref",
    }


def test_backend_instance_identity_roundtrips() -> None:
    record = BackendInstanceIdentityRecord("inst-42", 3, _NOW)
    save_backend_instance_identity_global(record)
    assert load_backend_instance_identity_global("inst-42") == record
    # Upsert increments the incarnation in place (AG3-138 boot semantics).
    save_backend_instance_identity_global(BackendInstanceIdentityRecord("inst-42", 4, _NOW))
    reloaded = load_backend_instance_identity_global("inst-42")
    assert reloaded is not None
    assert reloaded.instance_incarnation == 4


def test_loaders_return_none_when_the_row_is_absent() -> None:
    """The loaders return None (not an error) for an absent identity."""
    assert load_run_ownership_record_global("tenant-a", "missing", "run-x") is None
    assert load_active_run_ownership_record_global("tenant-a", "missing") is None
    assert load_object_mutation_claim_global("tenant-a", "story", "missing") is None
    assert (
        load_takeover_transfer_record_global("tenant-a", "missing", "r", 1, "repo")
        is None
    )
    assert load_backend_instance_identity_global("missing") is None


# ---------------------------------------------------------------------------
# AK3 — additive bootstrap is lossless over pre-existing (legacy) rows
# ---------------------------------------------------------------------------


def _drop_ownership_tables_and_reset_bootstrap() -> None:
    """Simulate a pre-AG3-137 schema: drop the new tables and clear the cache.

    After this, the next connection re-runs the FULL bootstrap because the
    ``run_ownership_records`` canary is missing (``_schema_is_bootstrapped``
    returns False) — proving the migration + backfill are wired into bootstrap,
    not a one-shot fixture side effect.
    """
    with postgres_store._connect_global() as conn:
        conn.execute("DROP TABLE IF EXISTS run_ownership_records CASCADE")
        conn.execute("DROP TABLE IF EXISTS object_mutation_claims CASCADE")
        conn.execute("DROP TABLE IF EXISTS takeover_transfer_records CASCADE")
        conn.execute("DROP TABLE IF EXISTS backend_instance_identity CASCADE")
    reset_backend_cache_for_tests()


def test_bootstrap_is_lossless_over_a_legacy_operation_row() -> None:
    """AK3: a DB with legacy control_plane_operations rows survives the bootstrap.

    A legacy row (only the pre-AG3-137 columns) is inserted, then a full
    re-bootstrap runs. The row's values are intact and the additive columns are
    present-and-NULL (no data loss, no clobber).
    """
    with postgres_store._connect_global() as conn:
        conn.execute(
            """
            INSERT INTO control_plane_operations (
                op_id, project_key, story_id, run_id, session_id,
                operation_kind, phase, status, response_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "op-legacy-1",
                "tenant-a",
                "AG3-220",
                "run-1",
                "sess-1",
                "phase_start",
                "setup",
                "committed",
                "{}",
                _NOW.isoformat(),
                _NOW.isoformat(),
            ),
        )

    _drop_ownership_tables_and_reset_bootstrap()

    # Reconnect -> full bootstrap re-runs (canary missing) -> ALTERs are idempotent.
    stored = load_control_plane_operation_global("op-legacy-1")
    assert stored is not None
    assert stored.status == "committed"
    assert stored.operation_kind == "phase_start"
    # Additive inflight-operation columns exist and default to None (lossless).
    assert stored.operation_epoch is None
    assert stored.backend_instance_id is None
    assert stored.finalized_at is None


# ---------------------------------------------------------------------------
# AK6 / IMPL-007 — idempotent, fail-closed run-ownership backfill
# ---------------------------------------------------------------------------


def test_backfill_via_bootstrap_creates_one_active_ownership_for_a_running_run() -> None:
    """AK6: the bootstrap backfill materialises one active ownership per active binding.

    Proves the backfill is WIRED into the schema bootstrap: an active binding
    without an ownership record is seeded, the new tables are dropped, and a
    reconnect re-runs the full bootstrap (canary missing) — which recreates the
    tables AND runs the backfill, deriving the owner from the binding.
    """
    save_session_run_binding_global(
        _binding(session_id="sess-bf", story_id="AG3-230", run_id="run-1")
    )
    _drop_ownership_tables_and_reset_bootstrap()

    # Reconnect via a control-plane read -> triggers the wired bootstrap + backfill.
    record = load_active_run_ownership_record_global("tenant-a", "AG3-230")
    assert record is not None
    assert record.run_id == "run-1"
    assert record.ownership_epoch == 1
    assert record.status is OwnershipStatus.ACTIVE
    assert record.acquired_via is OwnershipAcquisition.SETUP
    assert record.owner_session_id == "sess-bf"
    assert _count_ownership("tenant-a", "AG3-230") == 1


def test_backfill_is_idempotent_on_repeated_runs() -> None:
    """AK6: a second backfill creates no duplicate (idempotent)."""
    save_session_run_binding_global(
        _binding(session_id="sess-idem", story_id="AG3-231", run_id="run-1")
    )
    with postgres_store._connect_global() as conn:
        postgres_store._ensure_run_ownership_backfill(conn)
    with postgres_store._connect_global() as conn:
        postgres_store._ensure_run_ownership_backfill(conn)
    assert _count_ownership("tenant-a", "AG3-231") == 1
    record = load_active_run_ownership_record_global("tenant-a", "AG3-231")
    assert record is not None
    assert record.ownership_epoch == 1


def test_backfill_fails_closed_on_a_running_run_without_a_derivable_owner() -> None:
    """AK6: a running run (active lock) with NO binding is a fail-closed finding.

    The owner is not guessed (IMPL-007): the backfill raises a deterministic
    ``RunOwnershipBackfillError`` instead of inventing an owner.
    """
    _active_lock(story_id="AG3-232", run_id="run-orphan")
    with (
        pytest.raises(postgres_store.RunOwnershipBackfillError, match="derivable owner"),
        postgres_store._connect_global() as conn,
    ):
        postgres_store._ensure_run_ownership_backfill(conn)
    assert _count_ownership("tenant-a", "AG3-232") == 0


def test_backfill_fails_closed_on_ambiguous_double_active_bindings() -> None:
    """AK6: two active bindings for one story is ambiguous -> fail-closed, never pick."""
    save_session_run_binding_global(
        _binding(session_id="sess-1", story_id="AG3-233", run_id="run-1")
    )
    save_session_run_binding_global(
        _binding(session_id="sess-2", story_id="AG3-233", run_id="run-2")
    )
    with pytest.raises(postgres_store.RunOwnershipBackfillError, match="ambiguous"), postgres_store._connect_global() as conn:
        postgres_store._ensure_run_ownership_backfill(conn)
    assert _count_ownership("tenant-a", "AG3-233") == 0
