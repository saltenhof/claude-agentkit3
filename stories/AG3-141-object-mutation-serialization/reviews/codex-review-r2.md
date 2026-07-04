# Codex Review R2 - AG3-141 Object-Mutation Serialization

## Summary

Verdict: reject. The round-1 release-lifecycle blocker is fixed in the runtime control flow, and the durable queue-position algorithm is fixed on a fresh/current schema. I found one new MAJOR defect in the queue-counter bootstrap/migration path and one MAJOR ARCH-55 violation in newly added source comments/docstrings.

Focused checks run:

- `.venv\Scripts\python -m pytest tests/unit/control_plane/test_object_claim_wiring.py tests/unit/control_plane/test_object_claims.py tests/unit/control_plane/test_startup_reconcile.py` - 42 passed.
- `.venv\Scripts\python -m pytest tests/integration/control_plane/test_object_mutation_serialization_pg.py::test_queue_position_is_strictly_increasing_across_release_and_reacquire` - 1 passed.

## Part A - Round-1 Findings

1. **FIXED** - BLOCKER: release lifecycle fail-closed on success/handled paths.

   `_mutate_phase` loads a replay before acquiring the object claim at `src/agentkit/backend/control_plane/runtime.py:2490`, acquires the object claim at `src/agentkit/backend/control_plane/runtime.py:2501`, uses a non-best-effort release after successful commit at `src/agentkit/backend/control_plane/runtime.py:2579`, and also uses a non-best-effort release for handled claim/binding collision paths at `src/agentkit/backend/control_plane/runtime.py:2591`. Best-effort release is limited to the pre-commit exception path at `src/agentkit/backend/control_plane/runtime.py:2603`.

   `complete_closure` follows the same shape: replay before claim at `src/agentkit/backend/control_plane/runtime.py:1718`, claim acquisition at `src/agentkit/backend/control_plane/runtime.py:1761`, non-best-effort release on committed success at `src/agentkit/backend/control_plane/runtime.py:1794`, non-best-effort releases on handled rejection paths at `src/agentkit/backend/control_plane/runtime.py:1807` and `src/agentkit/backend/control_plane/runtime.py:1832`, and best-effort only on the pre-commit exception path at `src/agentkit/backend/control_plane/runtime.py:1851`.

   The injected release-failure tests assert that the operation committed and the service raised instead of returning `committed`: `tests/unit/control_plane/test_object_claim_wiring.py:359` plus `tests/unit/control_plane/test_object_claim_wiring.py:372`, and closure at `tests/unit/control_plane/test_object_claim_wiring.py:435` plus `tests/unit/control_plane/test_object_claim_wiring.py:449`. Caveat: the fake port records release attempts but does not expose an explicit "held rows" collection, so the "claim still held" part is implicit from release always raising, not directly asserted.

   AC1 is preserved. Startup reconciliation directly scans `object_mutation_claims` by same backend identity and earlier incarnation at `src/agentkit/backend/control_plane/startup_reconcile.py:184`, releasing them at `src/agentkit/backend/control_plane/startup_reconcile.py:200`. The integration crash test covers a real held claim and same-instance restart release at `tests/integration/control_plane/test_object_mutation_serialization_pg.py:529` and `tests/integration/control_plane/test_object_mutation_serialization_pg.py:581`. I found no wall-clock expiry path.

   On the surfaced-5xx commit-then-release-failure path, same-`op_id` replay is claim-free because `_load_existing_operation` runs before object-claim acquisition for both `_mutate_phase` and `complete_closure`; replay classification returns from `_replay_or_mismatch` at `src/agentkit/backend/control_plane/runtime.py:2927`. It therefore does not deadlock on its own held claim. The residual same-incarnation stuck claim after a surfaced release failure/crash is documented at `src/agentkit/backend/control_plane/runtime.py:2571` and `src/agentkit/backend/control_plane/runtime.py:1789`; recovery is same-instance later-incarnation startup reconciliation, not wall-clock cleanup.

2. **FIXED for fresh/current schema; new bootstrap defect below** - MAJOR: `queue_position` strict monotonicity.

   The allocator now uses durable per-project `object_claim_queue_positions` state inside the same per-project `pg_advisory_xact_lock`: lock at `src/agentkit/backend/state_backend/postgres_store.py:2843`, counter UPSERT/RETURNING at `src/agentkit/backend/state_backend/postgres_store.py:2901`, claim insert with assigned position at `src/agentkit/backend/state_backend/postgres_store.py:2916`. The integration test proves release/reacquire monotonicity at `tests/integration/control_plane/test_object_mutation_serialization_pg.py:614`, including a different object in the same project at `tests/integration/control_plane/test_object_mutation_serialization_pg.py:662`.

   The counter table has no wall-clock/expiry column at `src/agentkit/backend/state_backend/postgres_schema.sql:364`. The table is one row per project, so there is no per-claim row growth. Reconcile/admin-abort only scan/delete `object_mutation_claims`, not the counter table, which is correct.

## Part B - New Findings

1. `src/agentkit/backend/state_backend/postgres_store.py:493` - **MAJOR** - Existing bootstrapped Postgres schemas can skip creation of `object_claim_queue_positions`.

   Concrete failure scenario: a database bootstrapped by the round-1 remediation commit `e9b14601` already has the required canary tables, including `object_mutation_claims`, but it does not have the new `object_claim_queue_positions` table introduced at `src/agentkit/backend/state_backend/postgres_schema.sql:364`. After upgrading to `f963d6cd`, `_schema_is_bootstrapped` checks `required_tables` at `src/agentkit/backend/state_backend/postgres_store.py:493`, but that tuple omits `object_claim_queue_positions`. If the other canaries pass, `_ensure_schema_once` returns without executing the canonical `CREATE TABLE IF NOT EXISTS` script. The first object-claim acquisition then executes `INSERT INTO object_claim_queue_positions` at `src/agentkit/backend/state_backend/postgres_store.py:2903` and fails with a missing relation/table, turning mutating control-plane calls into 5xx before any claim can be acquired.

   Fix: add `object_claim_queue_positions` to the bootstrap canary, or add an explicit idempotent ensure path that runs even when the old canary says the schema is bootstrapped. Add a migration regression test that simulates a schema with `object_mutation_claims` present and `object_claim_queue_positions` absent, then verifies bootstrap creates the counter before acquire.

2. `src/agentkit/backend/control_plane/object_claims.py:23` - **MAJOR** - Newly added source violates ARCH-55 English-only.

   Concrete failure scenario: the new source file contains German terms in comments/docstrings: `Pflicht-Auflage` at `src/agentkit/backend/control_plane/object_claims.py:23`, `Fehler-Vertrag` at `src/agentkit/backend/control_plane/object_claims.py:69`, and `projektweite Mutationen` at `src/agentkit/backend/control_plane/object_claims.py:106`. CLAUDE.md makes ARCH-55 binding for source code, identifiers, schema, contracts, and code comments; this is not a prose concept file exception. A gate or strict review of ARCH-55 must fail this change.

   Fix: translate the new source comments/docstrings to English, e.g. "mandatory condition", "error contract", and "project-wide mutations".

No additional runtime release/double-release, lock-order, read-locking, wall-clock-expiry, or counter sweep defect was found beyond the bootstrap issue above.

## Part C - Finding 3 Assessment

The tension report is real and correctly characterized. A non-blocking `409 + Retry-After` busy response stores no live pending operation row. Persisting a cross-request "waiting project claim" anyway would need a durable owner and a deterministic end-way. With no wall-clock expiry and no abortable `claimed` operation, an abandoned waiting client could leave an unrecoverable project-wide reservation that younger story claims must honor forever, which recreates the stuck-reservation failure mode AG3-138/139/141 are trying to remove.

Deferring the cross-request pending-project-overtaking guarantee to the first productive project-claim caller is sound, provided AG3-144/148 either define a recoverable persisted reservation lifecycle or revise the invariant/interaction model. For AG3-141, treating held cross-scope exclusion plus within-lock-set ordering as the bar is acceptable, and the monotonic `queue_position` counter is the right ordering primitive to carry forward. The concept invariant remains unresolved, but it is correctly documented as a PO/orchestrator decision rather than a code fix to force into this story.

VERDICT: REJECT
