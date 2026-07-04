# Codex Review R6 - AG3-140

## 1. Summary

REJECT. The Round-5 guard-counter remediation is genuinely fixed: duplicate
`op_id` resolution now reads `request_body_hash`, `status` and
`operation_kind`, routes the loser through `classify_terminal_row(...)`, and the
real-store regression proves that a committed foreign row under the same
`op_id`/hash returns mismatch with no counter increment, no bucket drain and no
foreign-row overwrite.

The convergence method is still incomplete because the documented control-plane
exception is not a strict observable-contract superset. Control-plane phase /
closure duplicate resolution compares the folded body hash, but then replays any
matching terminal payload through `_replayed_result(...)`. For an
`aborted`/`repair`/`failed` terminal row, that returns the terminal result
verbatim, and the HTTP converter maps it to `201 Created` because only
`status == "rejected"` becomes 409. That violates the required
non-committed-terminal cell (`aborted`/`repair`/`failed` -> stable 409 conflict)
and the delivered matrix incorrectly claims the cell is proven.

Focused checks run:

- `.venv\Scripts\python -m pytest tests/integration/governance_hooks/test_hook_rest_mediation.py::test_guard_counter_foreign_committed_op_id_is_mismatch_no_side_effect -q` -> `1 passed`
- Ad hoc read-only runtime check: a seeded matching-hash `status="aborted"` control-plane row makes `start_phase(...)` return `status="aborted"`; `_mutation_result_response(...)` maps such a result to HTTP `201`.
- `git diff --check d8a7da41 99ef1cb1` -> clean

## 2. Part-A Verification

FIXED. `StateBackendGuardCounterRepository.record_invocation_idempotent()` now
loads `request_body_hash`, `status`, `operation_kind` and `response_json` from
the consolidated `control_plane_operations` row
(`src/agentkit/backend/state_backend/store/guard_counter_repository.py:279`,
`:282`, `:367`, `:382`). The duplicate branch calls the shared
`classify_terminal_row(...)` with
`incoming_operation_kind="guard_counter_record"` and returns replay only on
`ROW_REPLAY`; every other classifier outcome becomes mismatch before any counter
side effect (`src/agentkit/backend/state_backend/store/guard_counter_repository.py:289`,
`:296`, `:300`).

The regression is real-store and proves the R5 scenario. It seeds a committed
foreign `phase_start` row with the same `op_id` and hash
(`tests/integration/governance_hooks/test_hook_rest_mediation.py:669`,
`:683`, `:693`, `:694`, `:696`), executes guard-counter recording with that same
`op_id`/hash (`:735`), and asserts mismatch, zero current-week invocations, no
older-week drain, and the foreign row still being `phase_start`/`committed`
(`:739`, `:740`, `:741`, `:745`, `:746`). The focused test passed.

## 3. Part-B Findings

1. `src/agentkit/backend/control_plane/runtime.py:2327`, `:2338`, `:2611`, `:2626`, `:2873`; `src/agentkit/backend/control_plane_http/app.py:1762`, `:1776` - MAJOR - the documented control-plane exception is not a superset for non-committed terminal rows. `_load_existing_operation()` treats any existing non-`claimed` row as replayable after `_replay_or_mismatch(...)`; `_replay_or_mismatch(...)` only checks the folded request-body hash and then calls `_replayed_result(...)`; `_replayed_result(...)` returns `aborted`/`repair`/`failed` payloads verbatim. `_mutation_result_response(...)` maps only `status == "rejected"` to 409, so a matching-hash retry against an `aborted` terminal row surfaces as HTTP 201 with body `{"status": "aborted", ...}` instead of stable 409 conflict. Concrete failure scenario: a phase-start claim is admin-aborted, leaving a `control_plane_operations` row with `status="aborted"` and the original `request_body_hash`; the client retries the same start request with the same `op_id`; the runtime returns the aborted payload and the HTTP adapter returns 201. Fix: terminal duplicate classification on the control-plane path must reject non-committed terminal statuses as conflict for mutating retry/replay, while preserving verbatim `aborted`/`repair`/`failed` only for reconcile/read surfaces such as `GET /operations/{op_id}` and late-owner visibility where that behavior is explicitly required. Add a phase/closure HTTP regression for `aborted` (and preferably `repair`/`failed`) terminal duplicate retry -> 409.

2. `stories/AG3-140-unified-idempotency-contract/idempotency-contract-matrix.md:93`, `:96`; `tests/unit/control_plane/test_http.py:1542`; `tests/unit/control_plane/test_runtime.py:3432` - MAJOR - the matrix is not honest for control-plane P4/P7. It claims `repair/aborted -> 409` is proven by `test_phase_mutation_repair_lock_rejection_maps_to_409` and `test_mutating_dispatch_against_story_in_repair_is_rejected`, but those tests cover a fresh mutation blocked by an open story-level repair lock, not duplicate-`op_id` classification of an existing `aborted`/`repair`/`failed` `control_plane_operations` terminal row. The claimed cell is both unproven and contradicted by the code path above. Fix the code first, then replace the matrix citations with tests that seed or produce the terminal op row and retry the same `op_id` through the phase/closure HTTP route.

No new defects found in the shared classifier itself. `classify_terminal_row(...)`
is total for the intended generic/guard-counter contract: `claimed` ->
in-flight, body hash mismatch -> mismatch, operation-kind mismatch -> mismatch,
non-`committed` terminal -> conflict, and only committed same-hash/same-kind ->
replay (`src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:258`,
`:286`, `:288`, `:290`, `:292`, `:294`). Grep shows the generic guard
(`_resolve_loser`, in-memory `_classify_existing`) and guard-counter duplicate
resolution route through it; the remaining bespoke duplicate-resolution path is
the documented control-plane exception, which is the failing path above.

## 4. Final Assessment

Round 5's specific guard-counter finding is fixed, but AG3-140 is still not
approvable. The control-plane exception does not enforce the same observable
contract for non-committed terminal duplicate rows, and the completeness matrix
overstates coverage for that cell. This leaves a MAJOR contract gap in the
convergence round.

VERDICT: REJECT
