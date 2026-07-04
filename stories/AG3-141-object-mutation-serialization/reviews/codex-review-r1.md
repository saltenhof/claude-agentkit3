# Codex Review R1 - AG3-141 Object-Mutation Serialization

## Summary

Verdict: reject. The core same-story start/resume serialization path is largely in place: claims are acquired before dispatch, busy objects return deterministic `409`/`Retry-After`, reads do not acquire object claims, startup reconciliation directly scans `object_mutation_claims` with an identity fence, and there is no TTL release path.

However, the release lifecycle is not fail-closed on complete/fail/closure success or handled-return paths. A release failure can be swallowed while the caller receives a normal result, leaving the story durably blocked without an abortable `claimed` operation row. I also found a monotonicity defect in `queue_position`.

## Findings

1. `src/agentkit/backend/control_plane/runtime.py:2526` / `src/agentkit/backend/control_plane/runtime.py:1810` - **BLOCKER** - Complete/fail/closure can return normally while the durable object claim remains held.

   Concrete failure scenario: `_mutate_phase` acquires the story object claim, commits the complete/fail operation at `runtime.py:2518`, returns `result` at `runtime.py:2525`, then the `finally` block calls `_release_object_claim_best_effort` at `runtime.py:2531`. `_release_claim_key_best_effort` catches and only logs any release failure at `runtime.py:511`. If the release transaction fails after the operation commit, the API still returns `committed` while `object_mutation_claims` keeps the row. Subsequent mutations of that story deterministically get the busy-object rejection. For complete/fail/closure there is no `claimed` operation row, so `admin_abort` cannot target the stuck operation; startup reconciliation releases it only after a same-instance restart. The same silent-return problem exists for `complete_closure` via the best-effort release in `runtime.py:1814`.

   Suggested fix: track whether the object claim was acquired and use a non-best-effort release for successful and handled-return paths. Best-effort release is appropriate only while preserving an already-raising original exception. Add tests with an injected `release_claim` failure for complete/fail/closure proving the service never returns `committed` or a normal rejection while the claim remains held.

2. `src/agentkit/backend/state_backend/postgres_store.py:2873` - **MAJOR** - `queue_position` is not strictly increasing.

   Concrete failure scenario: acquire any claim in a project, it receives `queue_position = 0`; release it, so the row disappears; acquire another claim in the same project, `SELECT COALESCE(MAX(queue_position), -1) + 1 FROM object_mutation_claims` again returns `0`. This contradicts the implementation comment at `postgres_store.py:2832` and the review focus/spec requirement that `queue_position` be strictly increasing for FIFO/fairness audit. Reused positions also make administrative ordering ambiguous after releases.

   Suggested fix: allocate positions from durable per-project counter state or a sequence advanced under the same per-project advisory transaction lock. Do not derive the next position from the mutable set of currently-held claim rows. Add a Postgres integration test that acquires, releases, then acquires again and asserts the second position is greater than the first.

## W1/W2/W3 Assessment

W1: Reusing `error_code="conflict"` is acceptable for this story only because the response also carries `retry_after_seconds` and the HTTP adapter emits `Retry-After`. I would not block on a dedicated busy-object code.

W2: The multi-object lock-set has no productive caller yet, but SOLL-049 explicitly requires the mechanism. The A-core and Postgres smoke test make it a valid enabling mechanism, not dead code.

W3: Reconciliation itself looks correctly shaped: it directly scans `object_mutation_claims` by `backend_instance_id` and earlier `instance_incarnation`, and does not rely on an operation-keyed cascade. I found no TTL/wall-clock release path.

## Test-Honesty Spot Check

The same-story concurrency test uses real `ControlPlaneRuntimeService` plus the Postgres fixture and a slow injected dispatcher; it honestly proves that only one `start_phase` reaches dispatch.

The K4 busy-object test is also on the real runtime/Postgres path and asserts no operation row is stored for the rejected attempt.

The read-lock-free coverage is credible: there is a DI spy unit test and an integration read with a held claim; production `get_operation` only loads the operation row.

The fairness tests prove held project/story cross-scope exclusion, but not pending-project overtaking and not `queue_position` monotonicity. The op-row-less orphan release path is proven in a unit fake; the Postgres integration AC1 covers an orphan with both op row and object claim.

VERDICT: REJECT
