## Summary

Verdict is reject. The re-cut correctly reuses `_enforce_ownership_fence_row`
for `qa_stage_results`, `qa_findings`, and `decision_records`, and the central
fence itself rejects missing-active and mismatched owner/epoch under
`SELECT ... FOR UPDATE`. However, the implementation still leaves reachable
projection writes outside the lease fence:

- the requested `artifact_envelopes` Postgres upsert is still completely
  unfenced and is executed by the real implementation QA subflow before the
  later fenced FK-69 read-model write;
- the closure report file write is gated by a separate fence transaction, then
  written after the row lock has been released, leaving a TOCTOU window;
- an additional production QA projection, `qa_check_outcomes`, is written by
  the same implementation phase after the fenced QA batch but with no ownership
  fence at all.

The old deleted async/stale/result-kind machinery was not reintroduced by this
commit, and the reconnect test exercises the real `ControlPlaneRuntimeService`
operation store path. Those positives do not compensate for the fail-open
projection writes.

## Per-Projection-Write Completeness Map

| Surface | Status | Evidence |
|---|---|---|
| `artifact_envelopes` upsert | **UNFENCED** | `StateBackendArtifactRepository._pg_write()` performs `INSERT INTO artifact_envelopes ... ON CONFLICT ... DO UPDATE` without any `_enforce_ownership_fence_row` call (`src/agentkit/backend/state_backend/store/artifact_repository.py:469-501`). The real implementation phase calls `verify_system.run_qa_subflow(...)` before any fenced AG3-144 write (`src/agentkit/backend/implementation/phase.py:270-315`), and the subflow persists envelopes through `ArtifactManager.write()` (`src/agentkit/backend/verify_system/system.py:807-826`, `src/agentkit/backend/verify_system/system.py:853-873`). |
| `qa_stage_results` | Fenced here | `persist_layer_artifact_rows()` calls `_enforce_ownership_fence_row()` before any projection file or row write (`src/agentkit/backend/state_backend/postgres_store.py:5062-5078`), then performs `pg_execute_stage_upsert()` inside the same connection/transaction (`src/agentkit/backend/state_backend/postgres_store.py:5093-5096`). |
| `qa_findings` batch delete+rebuild | Fenced here | Same fenced batch as above; the delete starts only after the fence (`src/agentkit/backend/state_backend/postgres_store.py:5062-5087`), and finding upserts follow in the same transaction (`src/agentkit/backend/state_backend/postgres_store.py:5097-5100`). |
| `decision_records` | Fenced here | `persist_verify_decision_row()` fences first (`src/agentkit/backend/state_backend/postgres_store.py:5145-5155`) and then writes `decision.json` plus the `decision_records` upsert in the same connection scope (`src/agentkit/backend/state_backend/postgres_store.py:5156-5165`). |
| `closure_report` projection | **TOCTOU, not same transaction as write** | `persist_closure_report_row()` opens a transaction and fences (`src/agentkit/backend/state_backend/postgres_store.py:5402-5413`), exits it, then writes `closure.json` (`src/agentkit/backend/state_backend/postgres_store.py:5414-5417`). The active ownership row lock is gone before the actual projection write. |
| `qa_check_outcomes` | **UNFENCED additional projection write** | The implementation phase emits rows after the fenced QA batch (`src/agentkit/backend/implementation/phase.py:334-342`). `CheckOutcomeEmitter` calls `ProjectionAccessor.write_projection(QA_CHECK_OUTCOMES, ...)` (`src/agentkit/backend/verify_system/check_outcome_emitter.py:252-256`), which delegates to `_pg_write()` without owner/epoch inputs (`src/agentkit/backend/telemetry/projection_accessor.py:332-334`, `src/agentkit/backend/state_backend/store/projection_repositories.py:1319-1338`). |

## Transactional, Missing-Active, And Business-Boundary Checks

`_enforce_ownership_fence_row()` itself is fail-closed: it reads the active
`run_ownership_records` row with `FOR UPDATE` and raises on no active row,
wrong run, wrong owner, or moved epoch (`src/agentkit/backend/state_backend/postgres_store.py:3882-3907`).
For the surfaces that call it inside the write transaction, missing-active and
lease drift reject before the row write.

Business-boundary propagation is sound for the fenced `record_layer_artifacts`
and `record_verify_decision` calls: `ImplementationPhaseHandler.on_enter()` does
not catch `OwnershipFenceViolationError` around those calls, so later phase
side effects do not proceed after a rejected fenced write. Closure also does
not swallow the exception from `_write_report()`. The problem is earlier or
out-of-transaction writes that never hit that rejection path.

## Reconnect Assessment

The reconnect test uses real Postgres and the public
`ControlPlaneRuntimeService.start_phase()` / `get_operation()` path. It verifies
that a committed `start_phase` result is read back by client-supplied `op_id`,
and that retrying the same `op_id` does not dispatch a second time
(`tests/integration/control_plane/test_reconnect_reconciliation_pg.py:117-203`).
This is acceptable as a runtime-store reconciliation pin, though it is not an
HTTP-route test of `GET /v1/project-edge/operations/{op_id}`.

## AC6 No-Stale-Machinery Proof

Diff grep over `src` and `tests` did not show new `stale_observation`,
`stale_observations`, result-kind registry, materialized fence view, compaction
predicate, digest predicate, or artifact-version predicate additions. The added
`execution_contract_digest` references are not part of this commit's new fence
logic. SQLite only accepts and deletes the new owner/epoch parameters for
signature parity (`src/agentkit/backend/state_backend/sqlite_store.py:3056-3082`,
`src/agentkit/backend/state_backend/sqlite_store.py:3098-3118`,
`src/agentkit/backend/state_backend/sqlite_store.py:3238-3256`).

## Findings

### CRITICAL: `artifact_envelopes` remains a production unfenced projection upsert

Evidence:

- `src/agentkit/backend/state_backend/store/artifact_repository.py:469-501`
- `src/agentkit/backend/verify_system/system.py:807-826`
- `src/agentkit/backend/verify_system/system.py:853-873`
- `src/agentkit/backend/implementation/phase.py:270-315`

Scenario:

1. Implementation starts under active `(run_id=R, owner=sess-A, epoch=1)` and
   captures that snapshot at `implementation/phase.py:183-186`.
2. During `verify_system.run_qa_subflow(...)`, ownership transfers to
   `(owner=sess-B, epoch=2)`.
3. The QA subflow calls `ArtifactManager.write()` for layer and policy
   envelopes. The Postgres repository performs the `artifact_envelopes` upsert
   without `_enforce_ownership_fence_row`.
4. The ex-owner's `artifact_envelopes` rows commit. A later fenced
   `record_qa_layer_artifacts()` or `record_verify_decision()` may reject, but
   the canonical artifact projection has already been mutated.

Fix: Thread the same owner/epoch snapshot into the `ArtifactManager` /
`StateBackendArtifactRepository` Postgres write path, or move these envelope
writes into the already fenced projection commit so the fence runs first in the
same transaction as the `artifact_envelopes` upsert.

### CRITICAL: closure report fence is TOCTOU because the file write happens after the fence transaction

Evidence:

- `src/agentkit/backend/state_backend/postgres_store.py:5402-5417`

Scenario:

1. Closure report write starts while `(owner=sess-A, epoch=1)` is still active.
2. `persist_closure_report_row()` locks and validates the active ownership row,
   then exits the `_connect()` context at line 5413, committing the transaction
   and releasing the lock.
3. Before line 5417 writes `closure.json`, a takeover updates the active row to
   `(owner=sess-B, epoch=2)`.
4. The old owner still writes the closure projection after losing the lease.

Fix: Keep the ownership row lock held until after the closure projection write
is complete, or persist the closure report through a DB-backed fenced row in the
same transaction and derive/export the file only from the accepted durable row.

### CRITICAL: `qa_check_outcomes` is an unfenced production QA projection write

Evidence:

- `src/agentkit/backend/implementation/phase.py:334-342`
- `src/agentkit/backend/verify_system/check_outcome_emitter.py:252-256`
- `src/agentkit/backend/telemetry/projection_accessor.py:332-334`
- `src/agentkit/backend/state_backend/store/projection_repositories.py:1319-1338`

Scenario:

1. Implementation captures `(owner=sess-A, epoch=1)`.
2. `record_qa_layer_artifacts()` fences and writes the QA batch.
3. Ownership transfers before the `CheckOutcomeEmitter` loop.
4. `ProjectionAccessor.write_projection(QA_CHECK_OUTCOMES, ...)` commits
   `qa_check_outcomes` rows with no owner/epoch context and no
   `_enforce_ownership_fence_row`.

Fix: Either include `qa_check_outcomes` in the fenced QA-layer batch transaction
or give its productive write path the same mandatory owner/epoch parameters and
enforce `_enforce_ownership_fence_row` before the upsert.

VERDICT: REJECT
