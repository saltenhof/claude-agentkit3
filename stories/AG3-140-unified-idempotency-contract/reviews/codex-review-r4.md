# Codex Review R4 - AG3-140

## 1. Summary

REJECT. The two round-3 behavioral fixes are substantially implemented: the
story service no longer returns a success after `finalize()` loses ownership,
and admin-aborted generic guard rows classify as a stable conflict instead of a
route replay. `git diff --check d8a7da41 HEAD` is clean.

The final sweep found one remaining MAJOR contract defect. The unified
classification compares only `request_body_hash` and terminal `status`; several
different mutating actions can produce the same canonical hash because the route
operation kind is not part of the hash/comparison. Reusing one `op_id` across two
different endpoints with the same body/target can replay the first endpoint's
stored result instead of returning `409 idempotency_mismatch`.

There is also an ARCH-55 violation in the AG3-140 diff: newly added source/test
comments and docstrings repeatedly use the German concept word `Regel`.

## 2. Part-A Verification

1. FIXED. `story_context_manager` now routes deterministic domain-error
   finalization and success finalization through the lost-claim reclassification
   path. `_run_claimed` finalizes stored domain errors and calls
   `_reclassify_lost_claim` when `finalize()` returns `False`
   (`src/agentkit/backend/story_context_manager/service.py:341`,
   `:356`, `:363`). Successful mutations call `_finalize_success`, which returns
   a reclassified result or raises instead of allowing emit/return on a lost
   claim (`service.py:402`, `:416`). The success sites I found all check the
   helper before emitting: create `:651-657`, update `:751-757`, cancel
   `:897-903`, exit no-op `:1063-1068`, exit mutation `:1093-1099`, split no-op
   `:1185-1190`, split mutation `:1215-1221`, and status transition
   `:1316-1323`. The R3 tests prove no false success; the create test also
   counts the single attempted create (`tests/unit/story_context_manager/test_service.py:1540`,
   `:1552`, `:1557`). The update test proves no success but does not independently
   count the save path (`test_service.py:1560`, `:1573`).

2. FIXED for behavior. `_classify_terminal` now replays only
   `status == "committed"` and maps other terminal states to `AbortedOutcome`
   (`src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:238`,
   `:254`). `run_route_idempotent` maps `AbortedOutcome` to `409
   operation_conflict` (`inflight_idempotency_guard.py:490`, `:512`). The real
   Postgres test uses the real
   `admin_abort_control_plane_operation_global` path and asserts
   `AbortedOutcome` (`tests/contract/state_backend/test_inflight_idempotency_guard_postgres.py:162`,
   `:189`, `:204`). The explicit `409 operation_conflict` assertion is in the
   in-memory route-helper test, not the real-Postgres test
   (`tests/unit/state_backend/test_inflight_idempotency_guard.py:260`, `:294`,
   `:296`). Normal committed replay remains covered by the real-store test at
   `tests/contract/state_backend/test_inflight_idempotency_guard_postgres.py:148`,
   `:154`, `:156`.

3. NOT-FIXED. `git diff --check d8a7da41 HEAD` is clean, but ARCH-55
   English-only is not. New source/test comments and docstrings still contain
   German, for example `Regel` in
   `src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:1`,
   `:11`, `src/agentkit/backend/task_management/http/routes.py:152`,
   `:169`, and `src/agentkit/backend/control_plane/runtime.py:326`.

## 3. Part-B Findings

1. `src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:302`,
   `:313`, `:317`; `src/agentkit/backend/task_management/http/routes.py:779`,
   `:785`, `:850`, `:855`, `:920`, `:925`, `:996`, `:1001`;
   `src/agentkit/backend/execution_planning/http/routes.py:341`, `:346`,
   `:434`, `:437` - MAJOR - terminal classification ignores the stored
   `operation_kind`, and several different mutating routes hash the same
   canonical body for the same target. Concrete scenario: a client resolves task
   `TM-2026-0001` with `op_id="x"` and body `{"op_id":"x",
   "resolved_by":"human"}`; the guard stores a committed `task_resolve` result.
   The client then mistakenly calls `/dismiss` for the same task with the same
   `op_id` and body. `_handle_dismiss_task` computes the same body hash as
   `_handle_resolve_task` because both use `_ResolveRequest` plus
   `target_task_id`, and `_resolve_loser` sees same hash + committed status and
   returns `ReplayOutcome`. The dismiss route returns the stored resolve response
   instead of `409 idempotency_mismatch`, and the dismiss mutation never runs.
   The same defect exists for task link/unlink, and execution-planning
   create/delete dependency can hash the same dependency tuple. This also
   invalidates the comment that committed rows are necessarily this consumer's
   shape: control-plane and guard-counter code also write `status="committed"`
   (`src/agentkit/backend/control_plane/runtime.py:878`, `:1846`, `:2019`,
   `:2225`; `src/agentkit/backend/state_backend/store/guard_counter_repository.py:488`).
   Fix: include operation identity in the canonical discriminator and/or compare
   the stored `operation_kind` against `IdempotencyRequest.operation_kind` before
   replay; mismatched operation kind must be a stable `409 idempotency_mismatch`
   or `operation_conflict`, never a replay. Add cross-action tests for
   resolve-vs-dismiss, link-vs-unlink, and create-vs-delete dependency.

2. `src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:1`,
   `:11`; `src/agentkit/backend/task_management/http/routes.py:152`, `:169`;
   `src/agentkit/backend/control_plane/runtime.py:326`, `:391` - ERROR -
   ARCH-55 English-only is still violated in newly added code/comments/tests by
   German source prose such as `Regel`. Concrete failure scenario: the story's
   mandatory ARCH-55 check cannot truthfully pass, and new code normalizes German
   terminology in source despite the repository rule that code, comments, tests,
   wire keys, and schemas are English-only. Fix: replace these references with
   English wording such as `Rule 5` / `Rule 16` throughout added source and tests.

## 4. Final Assessment

Round-3 remediation fixed the two previously rejected behavioral paths, but
AG3-140 is not yet approvable. The remaining operation-kind/hash gap can return
a stored result for the wrong mutation action, which violates the unified
idempotency contract. ARCH-55 is also still not clean in the AG3-140 diff.

VERDICT: REJECT
