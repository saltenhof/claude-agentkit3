# AG3-140 — Idempotency-Contract Completeness Matrix (path × property)

Story: **AG3-140 — Einheitlicher Idempotenz-Vertrag (BC-weit)**. This artifact is
the Codex-round-5 deliverable (STEP 2d): every idempotency-resolution PATH proved
against every contract PROPERTY, so no sibling path can silently diverge again.
It is the companion to `route-inventory.md` (the per-route ledger); this file is
the per-mechanism proof grid.

## Method change (Codex r5): ONE shared classifier

Rounds r2→r3 and r4→r5 were both "correct on the audited path, missing on a
SIBLING path" findings. The structural fix (STEP 2c) is a **single source of truth
for the duplicate-`op_id` decision**:

`classify_terminal_row(incoming_body_hash, incoming_operation_kind, stored_status,
stored_body_hash, stored_operation_kind) -> {ROW_REPLAY | ROW_MISMATCH |
ROW_CONFLICT | ROW_IN_FLIGHT}`
(in `src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py`).

Fail-closed precedence: `claimed` → in-flight; body-hash differs → mismatch;
operation_kind differs → mismatch (never a cross-action/cross-shape replay);
non-`committed` terminal (aborted/repair/failed) → conflict; else → replay.

**Every** classification path now routes through this one function:

| Mechanism | Routes through the shared classifier? |
|---|---|
| Generic `run_route_idempotent` guard (`StateBackend`/`InMemory`, `claim`+`classify`) | YES — `_resolve_loser` / `_classify_existing` → `classify_terminal_row` |
| `story_context_manager` service | YES — has NO bespoke classifier; calls the guard's `claim`/`classify` |
| Guard-counter co-transactional record | YES — the atomic PK-gate INSERT stays (atomicity), but its duplicate resolution now calls `classify_terminal_row` with `incoming_operation_kind="guard_counter_record"` |
| control-plane phase/closure runtime | **NO — documented divergence.** It folds `operation_kind`+`phase` INTO its request-body-hash (`_control_plane_request_body_hash`) and additionally enforces AG3-137/138 instance-epoch fencing + verbatim aborted/repair/failed reconciliation (E6). Its richer, phase-aware, epoch-fenced semantics are a strict superset of the generic 5-input decision, so it cannot collapse onto the generic classifier without losing the fence. It enforces the SAME observable contract (see PATH 3 below) via its own runtime, proven cell-by-cell. |

## Legend

Properties (columns): P1 missing/empty op_id → **422**; P2 body-hash mismatch →
**409**; P3 operation_kind mismatch → **409, never cross-shape replay/400/500**;
P4 terminal-status discrimination (committed/own-shape → replay; aborted/repair/
failed → **stable 409 conflict**); P5 `finalize()==False` (CAS lost) → **no false
success**; P6 replay-after-success → stored result **once**; P7 replay-after-failure
→ stored error **once**; P8 parallel same op_id → **in-flight/conflict**; P9
pre-outcome exception → **release + clean retry**; P10 post-commit crash → **stays
in-flight** (AC3).

Each cell = the proving test (`file::test`) or a documented **N/A**.

---

## PATH 1 — generic `run_route_idempotent` guard (task / project / execution / auth)

Guard mechanics: `tests/unit/state_backend/test_inflight_idempotency_guard.py`
(`iig`). Real store: `tests/contract/state_backend/test_inflight_idempotency_guard_postgres.py` (`iig_pg`).

| Prop | Proving test |
|---|---|
| P1 | `tests/unit/task_management/http/test_routes.py::TestCreateIdempotency::test_create_missing_op_id_returns_422_missing_op_id` (+ project/execution/auth siblings) |
| P2 | `iig::test_same_op_id_different_body_is_mismatch_after_finalize` (HTTP: `task_management/http/test_routes.py::TestCreateIdempotency::test_create_same_op_id_different_body_returns_409_mismatch`) |
| P3 | `iig::test_run_route_idempotent_same_op_id_different_operation_kind_is_mismatch` (HTTP cross-action: `task_management/http/test_routes.py::TestCrossActionRejection::test_resolve_then_dismiss_same_op_id_returns_409_not_replay`, `::test_link_then_unlink_same_op_id_returns_409_not_replay`) |
| P4 | aborted→conflict `iig::test_run_route_idempotent_admin_aborted_row_is_stable_conflict_not_replay`; committed→replay `iig::test_run_route_idempotent_success_then_replay_returns_stored_result` |
| P5 | `iig::test_run_route_idempotent_finalize_false_does_not_return_success` |
| P6 | `iig::test_run_route_idempotent_success_then_replay_returns_stored_result` (HTTP: `task_management/http/test_routes.py::TestCreateIdempotency::test_create_replay_returns_stored_result_and_runs_once`) |
| P7 | `tests/unit/task_management/http/test_routes.py::TestResolveIdempotency::test_resolve_replay_after_failure_returns_stored_404_once` (+ project/execution/auth siblings) |
| P8 | `iig::test_parallel_same_op_id_before_finalize_is_in_flight_rejected`; real store `iig_pg::test_fresh_claim_wins_and_parallel_same_op_id_is_in_flight_real_store` |
| P9 | `iig::test_run_route_idempotent_pre_outcome_exception_releases_claim_and_retry_succeeds` (HTTP: `project_management/http/test_routes.py::TestCreateWindowInvariants::test_create_pre_outcome_exception_releases_claim_and_retry_succeeds`) |
| P10 | `iig::test_run_route_idempotent_post_commit_crash_stays_in_flight`; real store `iig_pg::test_crash_window_claim_without_finalize_retry_is_in_flight_real_store` |

## PATH 2 — story_context_manager service

`tests/unit/story_context_manager/test_service.py` (`scm`) unless noted. SCM has
**no bespoke classifier** — it calls the shared guard's `claim`/`classify`.

| Prop | Proving test |
|---|---|
| P1 | `tests/unit/story_context_manager/test_http_routes.py::test_post_stories_missing_op_id_returns_422` |
| P2 | `scm::test_update_fields_body_mismatch_raises_idempotency_mismatch` |
| P3 | `scm::test_cross_operation_same_op_id_is_mismatch_not_cross_shape_replay` **(added r5)** — create then status-transition reuse of one op_id → 409, story never transitioned; the operation_kind-with-colliding-hash isolation is proven at the shared-guard level by PATH 1 `iig::test_run_route_idempotent_same_op_id_different_operation_kind_is_mismatch` |
| P4 | committed→replay `scm::test_create_replay_after_success_returns_snapshot_without_second_mutation`; aborted-terminal→fail-closed `scm::test_create_finalize_lost_does_not_return_success` |
| P5 | `scm::test_create_finalize_lost_does_not_return_success` (+ `::test_update_fields_finalize_lost_does_not_return_success`) |
| P6 | `scm::test_create_replay_after_success_returns_snapshot_without_second_mutation` |
| P7 | `scm::test_replay_after_failure_is_not_reexecutable_and_not_mismatch` (+ status-transition / forbidden-field replay siblings) |
| P8 | `scm::test_parallel_in_flight_op_id_raises_operation_in_flight` |
| P9 | `scm::test_pre_outcome_infra_exception_releases_claim_and_retry_succeeds` **(added r5)** — a transient infra fault in the claimed mutation releases the claim; the same-op_id retry re-claims and succeeds |
| P10 | `scm::test_crash_between_mutate_and_finalize_is_not_doubly_executable` |

## PATH 3 — control-plane phase/closure runtime (folds operation_kind+phase into body-hash; epoch-fenced)

`tests/unit/control_plane/test_runtime.py` (`cpr`); HTTP `tests/unit/control_plane/test_http.py` (`cph`); real store `tests/contract/state_backend/test_control_plane_operation_store_postgres.py` (`cp_pg`).

| Prop | Proving test |
|---|---|
| P1 | `cph::test_missing_op_id_phase_payload_returns_422` (+ closure / project-edge-sync siblings) |
| P2 | `cpr::test_phase_start_reused_op_id_with_different_body_raises_mismatch` (+ complete/closure; HTTP `cph::test_phase_mutation_body_hash_mismatch_maps_to_409`) |
| P3 | `cpr::test_complete_phase_reusing_live_claimed_start_op_id_does_not_clobber` (+ atomic `::test_complete_closure_reusing_live_claimed_start_op_id_is_atomic`) — a different operation_kind under a live op_id never clobbers/cross-shape-replays |
| P4 | repair/aborted→409 `cph::test_phase_mutation_repair_lock_rejection_maps_to_409`, `cpr::test_mutating_dispatch_against_story_in_repair_is_rejected`; committed→replay `cpr::test_repeated_op_id_replays_without_second_mutation` |
| P5 | `cpr::test_late_executor_finalize_after_abort_fails_epoch_fence` (+ `::test_late_finalize_after_admin_abort_materializes_no_side_effects`) |
| P6 | `cpr::test_repeated_op_id_replays_without_second_mutation` (+ `::test_replay_returns_same_phase_dispatch_and_dispatches_once`, `::test_get_operation_returns_replayed_result`) |
| P7 | **N/A** — the control-plane runtime does NOT store a deterministic-domain-error snapshot for verbatim replay (that pattern is a REST-route concern, PATH 1/2). A `fail_phase` / aborted / repair terminal is NOT replayed as a stored 4xx; it is a **stable 409 conflict** — which is exactly property **P4** (proven above). There is no fourth "stored-error-replay" outcome to prove for this path. |
| P8 | `cpr::test_same_op_id_concurrent_starts_dispatch_once` (+ `::test_concurrent_claims_one_wins_loser_gets_in_flight_rejection_mid_dispatch`); real store `cp_pg::test_two_concurrent_same_op_id_starts_dispatch_once_real_store` |
| P9 | `cpr::test_exception_after_claim_releases_claim_and_leaves_op_reclaimable`; real store `cp_pg::test_exception_after_claim_releases_real_store_claim` |
| P10 | `cpr::test_stale_claim_placeholder_with_no_claimed_at_is_rejected_not_reclaimed` (+ `::test_foreign_claim_of_any_age_is_never_taken_over`) |

## PATH 4 — guard-counter co-transactional record

REST/real Postgres `tests/integration/governance_hooks/test_hook_rest_mediation.py` (`gc`); unit `tests/unit/control_plane/test_hook_mediation_services.py` (`gcu`).

| Prop | Proving test |
|---|---|
| P1 | **N/A** — the guard-counter mutation is an internal governance-edge co-transactional record; op_id is always minted by the edge client, so there is no missing-op_id → 422 wire surface. |
| P2 | `gc::test_guard_counter_op_id_mismatch_conflicts_via_rest` (unit `gcu::test_guard_counter_same_op_id_different_body_raises_mismatch`; no-side-effect `gc::test_guard_counter_mismatch_has_no_drain_or_count`) |
| P3 | `gc::test_guard_counter_foreign_committed_op_id_is_mismatch_no_side_effect` **(added r5)** — a foreign committed op (`operation_kind=phase_start`) owning the op_id under the SAME body-hash → stable 409 mismatch, zero counter side effect, foreign row untouched; never a cross-shape replay/400 |
| P4 | committed→replay `gc::test_guard_counter_replayed_op_id_counts_once_via_rest`. Aborted/repair/failed variant **N/A** — the guard-counter writes ONE terminal `committed` row and has no aborted/repair/failed terminal of its own (a foreign non-committed terminal resolves via P3 → 409). |
| P5 | **N/A** — a single atomic transaction gated by the op_id PRIMARY KEY; there is no claim→finalize CAS window, hence no `finalize()==False` case. |
| P6 | `gc::test_guard_counter_replayed_op_id_counts_once_via_rest` (+ `::test_guard_counter_replay_has_no_drain_or_recount`; unit `gcu::test_guard_counter_replayed_op_id_does_not_double_count`; PK-gate `gc::test_guard_counter_duplicate_op_id_hits_unique_gate_and_replays`) |
| P7 | **N/A** — a guard-counter record stores no domain-error snapshot (there is no domain-failure outcome to replay). The unreachable/failure path is non-blocking: `gc::test_guard_counter_unreachable_is_non_blocking_no_db_fallback`. |
| P8 | `gc::test_guard_counter_concurrent_duplicate_op_id_counts_once_via_unique_gate` |
| P9 | `gc::test_guard_counter_record_is_atomic_rolls_back_on_key_save_failure` — an exception at key-save rolls back the whole txn (no counted-but-unkeyed row); the clean retry counts exactly once |
| P10 | Same atomic test (`gc::test_guard_counter_record_is_atomic_rolls_back_on_key_save_failure`): the counter increment and idempotency-key commit are ONE transaction, so there is no separate post-commit finalize step that could be lost — all-or-nothing. |

---

## Completeness statement

Every `(path, property)` cell is either a named proving test or a documented N/A
with reason. All four mechanisms enforce the ONE unified contract; three route
their duplicate-`op_id` decision through the single `classify_terminal_row`, and
the fourth (control-plane) enforces the identical observable contract through its
epoch-fenced, phase-aware runtime (documented divergence, superset semantics). The
r5 gaps (SCM P3/P9, guard-counter P3) are closed by three added tests; the r5
NONE-FOUND control-plane P7 is a documented N/A (it collapses into P4 for this
path). No cell required a concept change.
