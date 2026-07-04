# Codex Review R3 - AG3-141 Object-Mutation Serialization

## Summary

Verdict: approve. I re-read `CLAUDE.md`, the R1/R2 reviews, the full `caef6c94..31c7ad28` diff, and the changed files in context. The round-2 MAJOR bootstrap and ARCH-55 findings are fixed, the minor release-failure proof is strengthened, and I found no new blocking defect. Approval is modulo the explicitly deferred Finding 3 pending-project fairness item.

Focused checks run:

- `.venv\Scripts\python -m pytest tests/contract/control_plane/test_object_serialization_contract.py::test_no_german_in_ag3141_new_source_and_tests tests/unit/control_plane/test_object_claim_wiring.py::test_complete_or_fail_release_failure_surfaces_never_returns_committed tests/unit/control_plane/test_object_claim_wiring.py::test_closure_release_failure_surfaces_never_returns_committed` - 4 passed.
- `.venv\Scripts\python -m pytest tests/integration/control_plane/test_object_mutation_serialization_pg.py::test_pre_ag3_141_schema_upgrade_recreates_the_queue_position_counter tests/integration/control_plane/test_object_mutation_serialization_pg.py::test_queue_position_is_strictly_increasing_across_release_and_reacquire` - 2 passed.
- `.venv\Scripts\python -m pytest tests/unit/control_plane/test_object_claims.py tests/unit/control_plane/test_startup_reconcile.py` - 35 passed.
- `git diff --check caef6c94 31c7ad28` - clean.

## Part A - Round-2 Findings

1. **FIXED** - MAJOR bootstrap canary omission.

   `object_claim_queue_positions` is now part of `_schema_is_bootstrapped`'s `required_tables` at `src/agentkit/backend/state_backend/postgres_store.py:515` and `src/agentkit/backend/state_backend/postgres_store.py:523`, so a pre-AG3-141 schema with `object_mutation_claims` but without the counter is no longer reported as fully bootstrapped. The canonical DDL creates `object_mutation_claims` first at `src/agentkit/backend/state_backend/postgres_schema.sql:343`, then creates the counter with `CREATE TABLE IF NOT EXISTS` at `src/agentkit/backend/state_backend/postgres_schema.sql:364`, so rerunning bootstrap is additive and ordered correctly.

   The regression test is honest: it drops only `object_claim_queue_positions` at `tests/integration/control_plane/test_object_mutation_serialization_pg.py:701`, asserts `not _schema_is_bootstrapped(conn)` at `tests/integration/control_plane/test_object_mutation_serialization_pg.py:707`, resets the bootstrap cache and reconnects at `tests/integration/control_plane/test_object_mutation_serialization_pg.py:711`, proves the counter table exists at `tests/integration/control_plane/test_object_mutation_serialization_pg.py:715`, and proves the first acquire succeeds at `tests/integration/control_plane/test_object_mutation_serialization_pg.py:725`.

   All AG3-137..AG3-141 state tables are covered by the canary: `run_ownership_records`, `object_mutation_claims`, `takeover_transfer_records`, `backend_instance_identity`, and `object_claim_queue_positions` at `src/agentkit/backend/state_backend/postgres_store.py:511`.

2. **FIXED** - MAJOR ARCH-55 English-only violation.

   The three German terms in `object_claims.py` are translated; the relevant comments/docstrings are now English around `src/agentkit/backend/control_plane/object_claims.py:23`, `src/agentkit/backend/control_plane/object_claims.py:68`, and `src/agentkit/backend/control_plane/object_claims.py:106`.

   The regression pin scans the AG3-141 new Python files listed at `tests/contract/control_plane/test_object_serialization_contract.py:152`, uses a real German/umlaut blocklist at `tests/contract/control_plane/test_object_serialization_contract.py:162`, and fails with collected offenders at `tests/contract/control_plane/test_object_serialization_contract.py:185`. It self-excludes only the pin file itself at `tests/contract/control_plane/test_object_serialization_contract.py:176`, which is necessary because that file defines the blocklist.

   Independent `git diff caef6c94 31c7ad28 -- src tests` grep for German terms and umlauts only hit the blocklist definition itself. I found no remaining German in the AG3-141 source/test diff.

3. **FIXED** - minor release-failure proof weakness.

   `_ReleaseRaisesPort` now tracks held claims at `tests/unit/control_plane/test_object_claim_wiring.py:301`, records release attempts, and raises without deleting the held entry at `tests/unit/control_plane/test_object_claim_wiring.py:319`. The complete/fail test asserts the commit happened, release was attempted, and the claim is still held at `tests/unit/control_plane/test_object_claim_wiring.py:390`; the closure test asserts the same at `tests/unit/control_plane/test_object_claim_wiring.py:469`.

## Part B - New Findings

No new defects found.

The bootstrap-canary change does not introduce a false "not bootstrapped" for complete current schemas: a complete schema has all required tables including the counter, so `_schema_is_bootstrapped` still returns true. It only fails closed for incomplete/partial schemas. The counter DDL is idempotent and additive.

The release-failure fake models the production failure case accurately enough for the asserted behavior: production release is an op_id-scoped delete at `src/agentkit/backend/state_backend/postgres_store.py:2966`; if that DB operation raises, the row remains held. The fake also raises without deleting, so `port.held` proves the same failure mode rather than a fake-only artifact.

I re-confirmed the round-0/round-1 guarantees: start and resume acquire object claims before dispatch at `src/agentkit/backend/control_plane/runtime.py:778` and `src/agentkit/backend/control_plane/runtime.py:1950`; success and handled-return paths use non-best-effort object release at `src/agentkit/backend/control_plane/runtime.py:828`, `src/agentkit/backend/control_plane/runtime.py:850`, `src/agentkit/backend/control_plane/runtime.py:1987`, `src/agentkit/backend/control_plane/runtime.py:2006`, `src/agentkit/backend/control_plane/runtime.py:2023`, `src/agentkit/backend/control_plane/runtime.py:1794`, `src/agentkit/backend/control_plane/runtime.py:1807`, `src/agentkit/backend/control_plane/runtime.py:1832`, `src/agentkit/backend/control_plane/runtime.py:2579`, and `src/agentkit/backend/control_plane/runtime.py:2591`; reads are covered by the no-use spy at `tests/unit/control_plane/test_object_claim_wiring.py:26`; same-story serialization, cross-scope held-claim exclusion, and no wall-clock expiry are covered in the Postgres integration suite; queue positions come from the durable per-project counter at `src/agentkit/backend/state_backend/postgres_store.py:2910`; and the single-transaction exception boundary remains pinned in `tests/contract/control_plane/test_object_serialization_contract.py:123`.

## Part C - Deferred Finding 3

Finding 3 remains correctly documented as deferred, not a blocker for AG3-141. The implementation note at `src/agentkit/backend/state_backend/postgres_store.py:2860` explicitly distinguishes held cross-scope exclusion from a persisted pending-project reservation, explains the conflict with non-blocking `409 + Retry-After` and no wall-clock expiry at `src/agentkit/backend/state_backend/postgres_store.py:2868`, and records that resolution is a concept-level prerequisite for the first productive project-claim caller at `src/agentkit/backend/state_backend/postgres_store.py:2878`.

VERDICT: APPROVE
