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
from agentkit.backend.state_backend.governance_runtime_store import save_story_execution_lock_global
from agentkit.backend.state_backend.operation_ledger import (
    insert_object_mutation_claim_global,
    load_control_plane_operation_global,
    load_object_mutation_claim_global,
)
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.state_backend_connection_manager import (
    load_backend_instance_identity_global,
    save_backend_instance_identity_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    insert_run_ownership_record_global,
    load_active_run_ownership_record_global,
    load_run_ownership_record_global,
    load_session_run_binding_global,
    load_takeover_transfer_record_global,
    save_session_run_binding_global,
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
        "reconciled_at",
        "reconcile_ref",
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


# ---------------------------------------------------------------------------
# AK4 / Codex ERROR §4 + WARNING §5a — DB-enforced binding_version / status
# value domain (parity fresh CREATE TABLE and existing-schema ALTER)
# ---------------------------------------------------------------------------


def _raw_insert_binding(
    conn: object,
    *,
    session_id: str,
    binding_version: str,
    status: str = "active",
    story_id: str = "AG3-240",
) -> None:
    """Raw INSERT bypassing the record validation to hit the DB CHECK directly."""
    conn.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO session_run_bindings (
            session_id, project_key, story_id, run_id, principal_type,
            worktree_roots_json, binding_version, updated_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            "tenant-a",
            story_id,
            "run-1",
            "orchestrator",
            "[]",
            binding_version,
            _NOW.isoformat(),
            status,
        ),
    )


def test_schema_check_rejects_non_canonical_binding_version() -> None:
    """Codex ERROR §4: the DB CHECK rejects a non-integer binding_version.

    Even a writer that bypasses the record validation (raw SQL) cannot persist a
    ``bind-*`` correlation token: the ``session_run_bindings_binding_version_check``
    constraint fails closed at the persistence boundary.
    """
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        postgres_store._connect_global() as conn,
    ):
        _raw_insert_binding(
            conn, session_id="sess-badver", binding_version="bind-not-int"
        )


def test_schema_check_rejects_zero_and_leading_zero_binding_version() -> None:
    """Codex ERROR §4: '0' and leading-zero forms are not canonical integers >= 1."""
    for bad in ("0", "01"):
        with (
            pytest.raises(psycopg.errors.CheckViolation),
            postgres_store._connect_global() as conn,
        ):
            _raw_insert_binding(
                conn, session_id=f"sess-{bad}", binding_version=bad
            )


def test_schema_check_rejects_unknown_binding_status() -> None:
    """Codex ERROR §9: the DB CHECK rejects an out-of-vocabulary binding status."""
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        postgres_store._connect_global() as conn,
    ):
        _raw_insert_binding(
            conn, session_id="sess-badstatus", binding_version="1", status="bogus"
        )


def test_insert_session_binding_row_persists_status_and_reason() -> None:
    """Codex WARNING §5b: the atomic binding insert writes status/revocation_reason.

    The internal ``_insert_session_binding_row`` used to write only the legacy
    columns; a revoked binding round-trips its status and machine-readable reason
    instead of silently defaulting to ``active`` / ``NULL``.
    """
    from agentkit.backend.state_backend.persistence_mappers import session_binding_to_row

    revoked = SessionRunBindingRecord(
        session_id="sess-revoked",
        project_key="tenant-a",
        story_id="AG3-243",
        run_id="run-1",
        principal_type="orchestrator",
        worktree_roots=("wt",),
        binding_version="2",
        updated_at=_NOW,
        status="revoked",
        revocation_reason="ownership_transferred",
    )
    with postgres_store._connect_global() as conn:
        postgres_store._insert_session_binding_row(
            conn, session_binding_to_row(revoked)
        )
    loaded = load_session_run_binding_global("sess-revoked")
    assert loaded is not None
    assert loaded.status == "revoked"
    assert loaded.revocation_reason == "ownership_transferred"
    assert loaded.binding_version == "2"


def test_existing_schema_backfill_normalizes_then_reapplies_checks() -> None:
    """Codex WARNING §5a: an existing DB gets the SAME hard binding_version boundary.

    Emulates a pre-check existing schema: the AG3-137 CHECK is dropped and a
    legacy random ``bind-<uuid>`` version row is inserted. The existing-schema
    migration path (backfill normalisation + ``_ensure_session_binding_constraints``)
    lifts the value to the canonical ``'1'`` and re-adds the constraint, so the
    existing DB is NOT left softer than a fresh schema — a subsequent
    non-canonical write is rejected fail-closed.
    """
    with postgres_store._connect_global() as conn:
        conn.execute(
            "ALTER TABLE session_run_bindings "
            "DROP CONSTRAINT IF EXISTS session_run_bindings_binding_version_check"
        )
        _raw_insert_binding(
            conn,
            session_id="sess-legacy",
            binding_version="bind-legacy-uuid",
            story_id="AG3-244",
        )

    with postgres_store._connect_global() as conn:
        postgres_store._ensure_run_ownership_backfill(conn)
        postgres_store._ensure_session_binding_constraints(conn)

    loaded = load_session_run_binding_global("sess-legacy")
    assert loaded is not None
    assert loaded.binding_version == "1", "legacy non-canonical version lifted to '1'"
    assert loaded.status == "active"

    # The re-applied CHECK now rejects a fresh non-canonical write (parity with fresh).
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        postgres_store._connect_global() as conn,
    ):
        _raw_insert_binding(
            conn,
            session_id="sess-legacy-2",
            binding_version="bind-again",
            story_id="AG3-244",
        )


# ---------------------------------------------------------------------------
# AK4-adjacent / Codex WARNING §6 — canary is fail-closed on partial migration
# ---------------------------------------------------------------------------


def test_canary_fails_closed_when_an_ag3_137_table_is_missing() -> None:
    """Codex WARNING §6: a partial migration (one new table missing) is NOT bootstrapped.

    The old canary checked only ``run_ownership_records``; a DB where that table
    exists but another AG3-137 table was lost (failed rollout / manual repair)
    would report bootstrapped and skip the migration. The hardened canary reports
    False, forcing a full bootstrap that recreates the dropped table.
    """
    with postgres_store._connect_global() as conn:
        conn.execute("DROP TABLE IF EXISTS object_mutation_claims CASCADE")
        assert postgres_store._schema_is_bootstrapped(conn) is False

    reset_backend_cache_for_tests()
    with postgres_store._connect_global():
        pass  # reconnect re-runs the full bootstrap (canary False -> recreate)
    assert "object_mutation_claims" in _table_names()


def test_canary_fails_closed_when_an_additive_column_is_missing() -> None:
    """Codex WARNING §6: a missing additive column also forces a full bootstrap.

    The new tables can all exist while an additive ALTER column on an existing
    control-plane table is still missing (a partial rollout). The column-level
    canary catches that and re-runs the additive ALTERs.
    """
    with postgres_store._connect_global() as conn:
        conn.execute(
            "ALTER TABLE control_plane_operations "
            "DROP COLUMN IF EXISTS operation_epoch"
        )
        assert postgres_store._schema_is_bootstrapped(conn) is False

    reset_backend_cache_for_tests()
    with postgres_store._connect_global():
        pass
    assert "operation_epoch" in _column_names("control_plane_operations")


_AG3_137_BINDING_CONSTRAINT_NAMES = {
    "session_run_bindings_status_check",
    "session_run_bindings_binding_version_check",
}


def _present_binding_constraint_names() -> set[str]:
    """Return which AG3-137 session-binding CHECK constraints exist in the schema."""
    with postgres_store._connect_global() as conn:
        rows = conn.execute(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = current_schema()
              AND c.conname = ANY(%s)
            """,
            (sorted(_AG3_137_BINDING_CONSTRAINT_NAMES),),
        ).fetchall()
    return {str(row["conname"]) for row in rows}


def test_bootstrap_reapplies_binding_constraints_on_b2b3d0bd_shaped_db() -> None:
    """Codex ERROR §5a/§4: the REAL connect path re-hardens an r1-shaped existing DB.

    A DB already migrated by r1 (``b2b3d0bd``) has the four AG3-137 tables and the
    additive columns but NOT the two ``session_run_bindings`` CHECK constraints
    (the additive ``status`` ALTER adds its column without a check, and
    ``binding_version`` stayed a bare ``TEXT``), plus a legacy non-canonical
    ``binding_version`` row. The bootstrap short-circuit
    (``_ensure_schema_once`` -> ``_schema_is_bootstrapped``) must NOT declare that
    DB bootstrapped: the ``pg_constraint`` canary makes it re-run
    ``_ensure_schema``, which normalises the legacy row THEN adds the constraints.

    Proven through ``_connect_global`` / ``_ensure_schema_once`` (the REAL path) —
    the sibling ``test_existing_schema_backfill_normalizes_then_reapplies_checks``
    only calls the helpers manually and never exercises this short-circuit.
    Without the ``pg_constraint`` probe in ``_schema_is_bootstrapped`` this test is
    red at step 2 (the canary would return ``True`` on the constraint-less DB) and
    at (a)/(b) (constraints/normalisation would never run on reconnect).
    """
    # 1. Reshape the freshly-bootstrapped fixture schema into the b2b3d0bd state:
    #    drop BOTH remediation CHECK constraints and insert a legacy bind-<...> row
    #    (only possible while the binding_version CHECK is absent). All AG3-137
    #    tables + additive columns stay present — exactly the r1 rollout shape.
    with postgres_store._connect_global() as conn:
        conn.execute(
            "ALTER TABLE session_run_bindings "
            "DROP CONSTRAINT IF EXISTS session_run_bindings_binding_version_check"
        )
        conn.execute(
            "ALTER TABLE session_run_bindings "
            "DROP CONSTRAINT IF EXISTS session_run_bindings_status_check"
        )
        _raw_insert_binding(
            conn,
            session_id="sess-r1",
            binding_version="bind-001",
            story_id="AG3-137",
        )

    # 2. The canary must now report the schema as NOT bootstrapped (constraints
    #    absent) even though every AG3-137 table + additive column is present.
    #    The still-cached bootstrap name keeps _ensure_schema_once from re-adding
    #    them here, so this observes the pure b2b3d0bd state. This is the exact gap
    #    the fix closes.
    with postgres_store._connect_global() as conn:
        assert postgres_store._schema_is_bootstrapped(conn) is False

    # 3. Drive the REAL path: clear the process bootstrap cache and reconnect so
    #    _ensure_schema_once actually re-runs _ensure_schema (NOT the manual
    #    helpers) on the b2b3d0bd-shaped schema.
    reset_backend_cache_for_tests()
    with postgres_store._connect_global():
        pass

    # (a) Both constraints exist again.
    assert _present_binding_constraint_names() == _AG3_137_BINDING_CONSTRAINT_NAMES

    # (b) The legacy non-canonical row was normalised to the canonical '1'.
    loaded = load_session_run_binding_global("sess-r1")
    assert loaded is not None
    assert loaded.binding_version == "1"
    assert loaded.status == "active"

    # (c) The re-added CHECK now rejects a fresh non-canonical raw write (parity
    #     with a fresh schema — the existing DB is no longer softer).
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        postgres_store._connect_global() as conn,
    ):
        _raw_insert_binding(
            conn,
            session_id="sess-r1-2",
            binding_version="bind-again",
            story_id="AG3-137",
        )

    # (d) Idempotency: a second real connect short-circuits cleanly (canary now
    #     True), with no error and no duplicate backfilled ownership record.
    reset_backend_cache_for_tests()
    with postgres_store._connect_global() as conn:
        assert postgres_store._schema_is_bootstrapped(conn) is True
    assert _count_ownership("tenant-a", "AG3-137") == 1


def _table_names() -> set[str]:
    with postgres_store._connect_global() as conn:
        rows = conn.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'
            """,
        ).fetchall()
    return {str(row["table_name"]) for row in rows}
