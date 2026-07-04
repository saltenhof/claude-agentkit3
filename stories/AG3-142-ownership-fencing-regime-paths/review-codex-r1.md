## Summary

Reviewed exact diff `8b113136..3c0f4293` and surrounding implementation. The crux fence design is materially sound: `_enforce_ownership_fence_row` performs `SELECT run_id, owner_session_id, ownership_epoch, acquired_at FROM run_ownership_records WHERE project_key = ? AND story_id = ? AND status = 'active' FOR UPDATE` and compares the locked row against `run_id`, `session_id`, and the observed epoch. The call happens inside the same transaction as the subsequent start finalize or operation commit.

Fence call-site map:

- `start_phase`: early admission at `src/agentkit/backend/control_plane/runtime.py:974`, dispatch/finalize path at `runtime.py:845`, epoch/record passed at `runtime.py:1215`.
- `complete_phase`: entry `runtime.py:1499`, admission `runtime.py:1570`, commit fence epoch passed at `runtime.py:1603` and `runtime.py:2926`.
- `fail_phase`: entry `runtime.py:1513`, same `_mutate_admitted_phase` path as complete.
- `complete_closure`: admission `runtime.py:1996`, epoch captured at `runtime.py:2051`, standard/fast closure pass it at `runtime.py:2060`/`runtime.py:2067`, commit calls at `runtime.py:2687` and `runtime.py:3116`.
- `resume_phase`: admission `runtime.py:2209`, dispatch at `runtime.py:2280`, epoch passed into finalize at `runtime.py:2317` and `runtime.py:2498`.
- Server-side executor dispatch: runtime passes record-based `run_admitted` into `PhaseDispatcher.dispatch` at `runtime.py:1483`; dispatcher uses only that admission input before engine entry at `src/agentkit/backend/control_plane/dispatch.py:326`, then calls `engine.run_phase`/`engine.resume_phase` at `dispatch.py:423`/`dispatch.py:432`. The later commit is still fenced by the runtime/store epoch paths above.

Setup ownership minting is atomic with the start CAS: `_finalize_start_phase` builds the `RunOwnershipRecord` only for fresh setup at `runtime.py:1200`, passes either `ownership_record_to_insert` or `expected_ownership_epoch` at `runtime.py:1225`, and the store inserts only after the claim CAS wins in the same transaction at `src/agentkit/backend/state_backend/postgres_store.py:3801` and `postgres_store.py:3837`. A CAS loser returns before the insert.

Admission replacement is correct: `_evaluate_run_admission` keeps the exit-fence negative check at `runtime.py:1719` and then uses only `load_active_ownership` at `runtime.py:1727`; there is no remaining `has_committed_operation_for_run` positive path in control-plane runtime. `RUN_MISMATCH` is fail-closed by `ownership_fence.py:100` and rejected before dispatch at `runtime.py:987`, which matches the current AG3-149 forward dependency rather than a current-scope deadlock.

Ex-owner image is wired: `ownership_transferred` builds `OwnershipTransferredDetail` with `new_ownership_epoch` at `runtime.py:3715`, HTTP maps that error code to 403 and other rejections to 409 at `src/agentkit/backend/control_plane_http/app.py:1795`, and Edge `resolve()` preserves revoked `block_reason="ownership_transferred"` at `src/agentkit/harness_client/projectedge/runtime.py:211`.

## Findings

### MAJOR - ARCH-55 is violated by new test source prose

File: `tests/integration/state_backend/test_ownership_fence_postgres.py:136`

Failure scenario: AC12 explicitly includes ARCH-55, and CLAUDE.md makes English mandatory for source code comments. The new `_raw_update_ownership_row` docstring contains German prose: `"der Zustand transferred entsteht nur in Tests ueber die sanktionierte AG3-137-Schreibflaeche"`. A review or language gate enforcing ARCH-55 must reject the diff even though the functional fence behavior is otherwise sound.

File: `tests/unit/control_plane/test_runtime.py:4447`

Failure scenario: the new `test_get_operation_still_readable_for_ex_owner` docstring uses `entmuendigten`. This is also source prose in the changed test suite and violates the same AC12/ARCH-55 rule.

Fix direction: translate the affected docstrings/comments to English only. Do not weaken ARCH-55 or exclude tests; tests are source code in this repo.

## Single-Connection-Fence-Test Adequacy Verdict

Adequate for AG3-142. The PG tests do not prove a literal two-connection blocking race, but they do prove the load-bearing behavior for this story: the commit path reads the current active row at commit time, rejects stale owner/epoch snapshots, and rolls back the op and side effects. The remaining mutual-exclusion property is standard PostgreSQL `SELECT ... FOR UPDATE` semantics on the exact row selected in `postgres_store.py:3635`; requiring a two-connection harness despite the documented one-connection worker budget is not justified for this scope. A future AG3-148 transfer-confirm race test can cover the real takeover writer when that writer exists.

VERDICT: REJECT
