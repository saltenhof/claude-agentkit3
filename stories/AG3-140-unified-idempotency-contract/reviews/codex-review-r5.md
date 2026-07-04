# Codex Review R5 - AG3-140

## 1. Summary

REJECT. The Round-4 remediation fixed the generic route guard defect: terminal
classification now compares stored `operation_kind` before replay, the in-memory
and state-backend guard implementations both stamp and read it, and the
resolve/dismiss, link/unlink, create/delete-dependency, and real-Postgres
route/control-plane collision tests pin the intended 409 behavior. The German
cleanup is also fixed for the AG3-140-touched Python files, with a real
fail-closed regression pin.

The final sweep found one remaining MAJOR contract gap in the guard-counter
idempotency path. Its duplicate-op resolution still classifies by
`request_body_hash` only and ignores the persisted `operation_kind`. A foreign
committed row under the same `op_id` and same hash is treated as a replay (or
becomes a payload-shape 400) instead of the contractual stable
`409 idempotency_mismatch`. That violates the "different operation" arm of the
unified contract for the `POST /v1/governance/guard-counters` mutating route.

Focused checks run:

- `.venv\Scripts\python -m pytest tests/contract/test_op_id_no_server_mint_pin.py tests/unit/state_backend/test_inflight_idempotency_guard.py tests/unit/task_management/http/test_routes.py::TestCrossActionRejection tests/unit/execution_planning/http/test_execution_planning_routes.py::test_create_then_delete_dependency_same_op_id_returns_409_not_replay -q` -> `20 passed`
- `git diff --check d8a7da41 de3fba60` -> clean

## 2. Part-A Verification

1. FIXED for the Round-4 generic-guard finding. `_classify_terminal` now returns
   `MismatchOutcome` when `stored_operation_kind != request.operation_kind`
   before any replay (`src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:264`).
   The Postgres/facade-backed guard stamps `request.operation_kind` into the
   claim row and reads `existing["operation_kind"]` for terminal classification
   (`src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:291`,
   `:329`). The in-memory guard mirrors this by storing `operation_kind` and
   passing it back into `_classify_terminal` on claim/classify
   (`src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:410`,
   `:417`, `:463`). Cross-action tests assert 409 and no second mutation for
   resolve/dismiss and link/unlink
   (`tests/unit/task_management/http/test_routes.py:1045`, `:1060`, `:1063`,
   `:1069`, `:1085`, `:1088`), and create/delete-dependency
   (`tests/unit/execution_planning/http/test_execution_planning_routes.py:487`,
   `:505`, `:507`). The real-Postgres route/control-plane collision test seeds a
   committed `phase_start` row with the same body hash and asserts
   `MismatchOutcome` (`tests/contract/state_backend/test_inflight_idempotency_guard_postgres.py:228`,
   `:239`, `:245`, `:251`). Legit same-action replay remains covered by the
   focused guard tests that passed.

2. FIXED. German was removed from the AG3-140-touched Python diff. The regression
   pin is not a no-op: it enumerates the touched `.py` files
   (`tests/contract/test_op_id_no_server_mint_pin.py:71`) and scans each existing
   file against a concrete German blocklist (`tests/contract/test_op_id_no_server_mint_pin.py:119`,
   `:141`, `:144`). It intentionally skips only itself because it defines the
   blocklist (`tests/contract/test_op_id_no_server_mint_pin.py:138`). The focused
   test run above passed. A raw diff grep now finds German only in removed lines
   and in the blocklist definition itself, not in added source/test prose.

## 3. Part-B Findings

1. `src/agentkit/backend/state_backend/store/guard_counter_repository.py:269`,
   `:272`, `:273`, `:275`, `:354`; `src/agentkit/backend/control_plane/guard_counter.py:164`;
   `src/agentkit/backend/control_plane_http/app.py:397` - MAJOR -
   guard-counter duplicate-op classification ignores `operation_kind`. On a
   duplicate `op_id`, `record_invocation_idempotent()` reads only
   `request_body_hash` and `response_json`; if the hash matches it returns
   `status="replayed"` without checking that the stored row is a
   `guard_counter_record`. Concrete failure scenario: `control_plane_operations`
   already contains a committed foreign operation under `op_id="x"` with the same
   `request_body_hash` (the same worst-case collision AG3-140 now explicitly
   handles for generic routes). A subsequent `POST /v1/governance/guard-counters`
   with `op_id="x"` hits the unique gate, reads the foreign row, treats it as a
   replay, and either tries to validate the foreign payload as
   `GuardCounterMutationAccepted` or returns a replay if the payload happens to
   fit. The HTTP adapter then maps the validation failure to
   `400 invalid_guard_counter_payload`, not `409 idempotency_mismatch`. This is
   the same class of cross-shape replay/corrupt-response risk Round 4 fixed in
   `_classify_terminal`, but the guard-counter path did not adopt the
   discriminator. Fix: include `operation_kind` (and terminal status) in
   `_read_idempotency_key()` and return mismatch unless it is exactly
   `operation_kind == "guard_counter_record"` and the expected terminal status;
   add a real-store regression where a committed foreign row with the same
   `op_id`/hash makes guard-counter return 409 with no counter increment/drain.

## 4. Final Assessment

Round-4's two explicit findings are fixed, and the normal generic-route
idempotency contract is now well pinned. The story is still not approvable
because one mutating route, guard-counter record, does not enforce the
operation-kind discriminator on duplicate-op replay classification. Acceptance
criteria 4 and 8 are therefore not fully met for the "different operation" case
across the unified record table.

VERDICT: REJECT
