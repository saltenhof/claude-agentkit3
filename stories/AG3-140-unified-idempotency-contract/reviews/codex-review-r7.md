# Codex Review R7 - AG3-140

## 1. Summary

REJECT. The round-6 control-plane defect is genuinely fixed: a mutating retry
against an existing `aborted` / `repair` / `failed` terminal operation now returns
a `rejected` mutation result that the HTTP adapter maps to 409, while reconcile
reads and late-owner finalize-CAS-loss fallbacks still surface the terminal row
verbatim. The worker/control-plane mirror keyed on
`_RECONCILE_PRESERVED_STATUSES = {aborted, repair, failed}` is sound for this
path because control-plane has multiple legitimate success statuses
(`committed`, `synced`, `replayed`, `resolved`) that must replay and would be
false-conflicted by a verbatim call to the generic classifier.

The final completeness gate is still not approvable. The matrix is not fully
honest for two required cells: control-plane PATH 3 P3 cites live-claim collision
tests instead of a terminal operation-kind/action mismatch, and guard-counter
PATH 4 P1 incorrectly marks missing `op_id` as N/A despite
`/v1/governance/guard-counters` being a mutating HTTP route with required
`op_id`. These are acceptance/test-backedness defects, not round-6 runtime
defects.

Focused checks run:

- `.venv\Scripts\python -m pytest tests/unit/control_plane/test_runtime.py::test_start_phase_retry_against_admin_aborted_terminal_is_conflict_not_replay tests/unit/control_plane/test_runtime.py::test_start_phase_retry_against_noncommitted_terminal_is_conflict tests/unit/control_plane/test_runtime.py::test_get_operation_reconcile_returns_noncommitted_terminal_verbatim tests/unit/control_plane/test_http.py::test_phase_start_retry_against_aborted_terminal_row_maps_to_409 tests/unit/state_backend/test_inflight_idempotency_guard.py::test_run_route_idempotent_same_op_id_different_operation_kind_is_mismatch tests/unit/story_context_manager/test_service.py::test_cross_operation_same_op_id_is_mismatch_not_cross_shape_replay -q` -> `10 passed`
- `.venv\Scripts\python -m pytest tests/contract/test_op_id_no_server_mint_pin.py -q` -> `2 passed`
- `git -C T:\codebase\claude-agentkit3 diff --check d8a7da41 58b2ed47` -> clean

## 2. Part-A Verification

FIXED. Fresh control-plane retry entrypoints call `_load_existing_operation(...)`
with the default `mutating_retry=True`: `start_phase`
(`src/agentkit/backend/control_plane/runtime.py:623`), complete/fail via
`_mutate_admitted_phase` (`:1149`), closure (`:1544`), resume (`:1666`), and the
claim-loser branch (`:365`, `:377`, `:385`). `_load_existing_operation` threads
that flag into `_replay_or_mismatch` (`:2329`, `:2351`, `:2356`). The new branch
rejects matching-hash non-committed terminal rows when `mutating_retry=True`
(`:2672`) by returning `_rejection_result(...)` (`:2673`), and
`_mutation_result_response` maps `status == "rejected"` to HTTP 409
(`src/agentkit/backend/control_plane_http/app.py:1762`, `:1776`).

The late-owner finalize-CAS-lost fallbacks deliberately pass
`mutating_retry=False`: start finalize loss (`runtime.py:923`, `:927`) and resume
finalize loss (`:1890`, `:1894`). That preserves the original owner's visibility
of its now-aborted row while preventing a fresh duplicate retry from replaying it
as success.

Committed and other control-plane success statuses still replay: `_replay_or_mismatch`
only conflicts the preserved non-committed set (`runtime.py:78`, `:2672`) and
otherwise delegates to `_replayed_result` (`:2686`), which returns
`aborted`/`repair`/`failed` verbatim only for read/late-owner surfaces and rewrites
all other stored success statuses to `replayed` (`:2933`, `:2936`). This is not a
hidden divergence from the shared contract; it is the same observable status rule
adapted to control-plane's broader success vocabulary.

The new tests prove the claimed scenario:

- `test_start_phase_retry_against_admin_aborted_terminal_is_conflict_not_replay`
  seeds a live claimed row with the same request hash, runs the real
  `admin_abort_inflight_operation`, then retries the same `op_id` and asserts
  `status == "rejected"` with no binding/event side effect
  (`tests/unit/control_plane/test_runtime.py:750`, `:762`, `:780`, `:786`,
  `:792`, `:794`, `:800`).
- `test_start_phase_retry_against_noncommitted_terminal_is_conflict` is
  parametrized over `aborted`, `repair`, and `failed`; its helper stamps a
  matching `request_body_hash`, then the same-op retry asserts `rejected` and the
  terminal row untouched (`test_runtime.py:709`, `:744`, `:805`, `:816`, `:821`,
  `:823`, `:826`).
- `test_phase_start_retry_against_aborted_terminal_row_maps_to_409` drives the
  real HTTP `/start` route over the real runtime classification and asserts HTTP
  409 plus `status == "rejected"` (`tests/unit/control_plane/test_http.py:1597`,
  `:1617`, `:1622`, `:1637`, `:1639`).
- `test_get_operation_reconcile_returns_noncommitted_terminal_verbatim` guards the
  reconcile/read surface for all three non-committed statuses
  (`test_runtime.py:831`, `:841`, `:846`, `:849`).

## 3. Part-B Findings

1. `stories/AG3-140-unified-idempotency-contract/idempotency-contract-matrix.md:102`; `tests/unit/control_plane/test_runtime.py:1755`; `tests/unit/control_plane/test_runtime.py:1822` - MAJOR - PATH 3 P3 is still not an honest operation_kind/action-mismatch proof. The matrix property is "operation_kind mismatch -> 409, never cross-shape replay/400/500", and the control-plane implementation intentionally folds `__operation_kind` and `__phase` into the body hash (`src/agentkit/backend/control_plane/runtime.py:2546`, `:2584`). But the cited tests cover a different precondition: a complete/closure attempt reusing a LIVE `claimed` phase-start `op_id`, which fails as in-flight/collision before any terminal operation-kind mismatch can be classified. They do not seed or produce a terminal committed `phase_start` row and then retry the same `op_id` through `complete_phase`, `fail_phase`, `resume_phase`, or `closure_complete` to prove a 409 mismatch instead of a cross-operation replay. Concrete failure scenario the matrix would miss: `_control_plane_request_body_hash` stops folding `operation_kind` (or a call site passes the wrong operation kind), and a terminal committed start row is reused by a later complete/closure action; the cited live-claim tests would still pass. Fix: add a control-plane test that commits one operation_kind under an `op_id`, retries a different mutating operation with the same `op_id` and otherwise identical request body, asserts `IdempotencyMismatchError` / HTTP 409, and update PATH 3 P3 to cite that test.

2. `stories/AG3-140-unified-idempotency-contract/idempotency-contract-matrix.md:117`; `stories/AG3-140-unified-idempotency-contract/route-inventory.md:85`; `src/agentkit/backend/control_plane_http/app.py:384`; `src/agentkit/backend/control_plane/models.py:68`, `:86` - MAJOR - PATH 4 P1 is falsely marked N/A. The matrix says guard-counter has "no missing-op_id -> 422 wire surface", but the route inventory explicitly lists `POST /v1/governance/guard-counters` as a mutating HTTP route, `_handle_post_guard_counter` validates the wire payload, and `GuardCounterMutationRequest.op_id` is a required `Field(min_length=1)`. The code maps op-id validation errors to HTTP 422 (`app.py:397`, `:401`, `:402`), but there is no cited test and `rg` finds no guard-counter missing-`op_id` 422 test. Concrete failure scenario the matrix would miss: a future change weakens `_handle_post_guard_counter` validation or returns a generic 400 for missing `op_id`; all cited guard-counter replay/mismatch/concurrency tests would still pass. Fix: add an HTTP/route test for `POST /v1/governance/guard-counters` without `op_id` (and preferably empty `op_id`) asserting 422, then replace the PATH 4 P1 N/A with that test.

No additional code defect found in `classify_terminal_row`: it is total for the
generic/SCM/guard-counter contract (`claimed` -> in-flight, hash mismatch ->
mismatch, operation-kind mismatch -> mismatch, non-`committed` terminal ->
conflict, otherwise replay) at
`src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:258`,
`:286`, `:288`, `:290`, `:292`, `:294`. Grep shows the generic guard, SCM
reclassification, and guard-counter duplicate path route through it; the only
remaining bespoke resolution path is the now-fixed control-plane runtime mirror.

ZERO DEBT / ARCH-55 / determinism checks did not reveal another blocker:
`idempotency_keys` has no live reader/writer outside retirement comments/tests,
the body hash excludes `op_id` and serializes deterministically with
`sort_keys=True` (`inflight_idempotency_guard.py:68`, `:69`), and the AG3-140
static pin for server-side `op_id` defaults and German source/test regressions
passes.

## 4. Final Assessment

Round 6's specific defect is fixed and the core runtime behavior is now correct
for non-committed terminal duplicate retries. However, this is the final decision
round and approval requires a fully honest completeness matrix plus test-backed
acceptance criteria. The matrix still overstates control-plane P3 coverage and
incorrectly exempts the guard-counter HTTP route from missing-`op_id` coverage.
Those MAJOR completeness defects block approval even though the r6 code fix is
sound.

VERDICT: REJECT
