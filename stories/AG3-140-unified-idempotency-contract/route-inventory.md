# AG3-140 — Mutating-Route Idempotency Inventory (mandatory cross-cutting artifact)

Story: **AG3-140 — Einheitlicher Idempotenz-Vertrag (BC-weit)**. The ZERO-DEBT
completeness ledger required by Scope item 5 / AC5. Regenerated from the ACTUAL
route regexes + the `ControlPlaneApplication` dispatch table (Codex r1 finding 6):
every route below is transcribed from its handler, and each mutating route's
evidence test PROVES the contract (replay + mismatch + in-flight + — where a
deterministic 4xx exists — replay-after-failure), not merely op_id validation.

## The one unified contract (FK-91 §91.1a Regel 5)

`op_id` is **client-supplied and required**. Every mutating route:
- **Missing `op_id`** → fail-closed `422` (op_id-specific, via `op_id_validation_error()`).
- **Replay** of the same `op_id` → the **stored result**, no second mutation.
- Same `op_id`, **different body** (URL path keys folded into the body-hash) → `409 idempotency_mismatch`.
- **Parallel** same `op_id` (a live claim) → `409 operation_in_flight`.
- **Every** deterministic domain **4xx is finalized** so a replay returns it
  verbatim exactly once (AC8) — including the story-field `ForbiddenFieldError`
  (422), which is validated INSIDE the claimed mutation path (Codex r2 #3). Only
  an unexpected pre-commit **≥500** or a pre-outcome exception releases the claim.

**The shared finalize/release window invariant** (Codex r2 #1/#2), centralized in
`run_route_idempotent` (guard module) for the generic BC routes and mirrored by the
control-plane runtime: the `claimed` placeholder is written BEFORE the mutation; a
mutation exception BEFORE any committed side effect RELEASES the claim (a retry
re-executes cleanly); a committed side effect followed by a crash before finalize
leaves the `claimed` row (fail-closed in-flight on retry, AC3, never released); and
a `finalize` CAS loss (the claim was taken over, e.g. an admin abort) NEVER returns
the success response — the row is re-classified and a fail-closed replay/mismatch/
conflict is returned.

Wire strings: only `idempotency_mismatch` (409) is named verbatim in FK-91
§91.1a. `missing_op_id`/`operation_in_flight` (and the per-BC `invalid_*_payload`
422 codes) are AGENTKIT strings (English, ARCH-55) — the concept fixes behavior.

## One record truth, one mechanism

All claim→mutate→finalize idempotency resolves against the single physical
`control_plane_operations` record (the materialization of the formal
`state-storage.entity.inflight-operation-record`, `identity_key: op_id`).
`request_body_hash` is the replay-vs-mismatch discriminator; `status='claimed'`
is the in-flight fence written **before** the mutation (crash window closed). The
generic port (`state_backend/store/inflight_idempotency_guard.py`) is consumed by
`story_context_manager`, `task_management`, `project_management`, `execution_planning`
and `auth`; the guard-counter writes a terminal record co-transactionally with its
counter; the `control_plane` phase/closure path owns its richer story-scoped
claim/finalize on the same record and (AG3-140 r1) now ALSO stamps + compares
`request_body_hash`.

## Mutating-route inventory (every mutating HTTP route)

| # | Route (verbatim) | Method | Handler | Mechanism | Evidence test proving the contract |
|---|---|---|---|---|---|
| 1 | `/v1/stories` | POST | story_context_manager `create_story` | guard claim/finalize; project_key in body | `test_service.py::test_create_replay_after_success_returns_snapshot_without_second_mutation`, `::test_parallel_in_flight_op_id_raises_operation_in_flight`, `::test_create_story_replay_after_forbidden_reraises_and_runs_once` (AC8) |
| 2 | `/v1/stories/{id}` | PATCH | story_context_manager `update_story_fields` | guard | `test_service.py::test_update_fields_body_mismatch_raises_idempotency_mismatch`, `::test_replay_after_failure_is_not_reexecutable_and_not_mismatch` (AC8); missing-op_id 422 in `test_http_routes.py` |
| 3 | `/v1/stories/{id}/fields/{field_key}` | PUT | story_context_manager `set_story_field` → delegates to `update_story_fields` (guarded); pre-claim `ForbiddenFieldError` only | guard (via delegation) | `test_http_routes.py` (set_field op_id required) + row 2 guard tests |
| 4 | `/v1/stories/{id}/approve` | POST | story_context_manager `_status_transition` | guard | `test_service.py::test_status_transition_replay_after_failure_reraises_and_runs_once` (AC8), replay/mismatch/in-flight tests |
| 5 | `/v1/stories/{id}/reject` | POST | story_context_manager `_status_transition` | guard | `tests/unit/story_context_manager/test_service.py` |
| 6 | `/v1/stories/{id}/cancel` | POST | story_context_manager `cancel_story` | guard | `tests/unit/story_context_manager/test_service.py` |
| 7 | story-exit viability handoff | (internal) | story_context_manager `administratively_cancel_for_story_exit` | guard (op_id = exit_id) | `tests/unit/story_context_manager/test_service.py` (exit idempotent + finalize) |
| 8 | story-split scope_split | (internal) | story_context_manager `administratively_cancel_for_story_split` | guard (op_id = split_id) | `tests/unit/story_context_manager/test_service.py` (split idempotent + finalize) |
| 9 | `/v1/projects/{key}/tasks` | POST | task_management `_handle_create_task` | guard | `test_routes.py::TestCreateIdempotency` (missing_op_id / replay-no-realloc / mismatch / in_flight) |
| 10 | `/v1/projects/{key}/tasks/{task_id}/resolve` | POST | task_management `_handle_resolve_task` | guard + path-task_id in body-hash | `test_routes.py::TestResolveIdempotency` incl. `::test_resolve_replay_after_failure_returns_stored_404_once`, `::test_resolve_same_op_id_different_task_returns_409_mismatch` |
| 11 | `/v1/projects/{key}/tasks/{task_id}/dismiss` | POST | task_management `_handle_dismiss_task` | guard | `test_routes.py::TestDismissIdempotency` |
| 12 | `/v1/projects/{key}/tasks/{task_id}/links` | POST | task_management `_handle_link_task` | guard | `test_routes.py::TestLinkIdempotency` |
| 13 | `/v1/projects/{key}/tasks/{task_id}/links/delete` | POST | task_management `_handle_unlink_task` | guard | `test_routes.py::TestUnlinkIdempotency` |
| 14 | `/v1/projects` | POST | project_management `_handle_create` | guard; project key in body | `test_routes.py::TestCreateIdempotency` (replay-runs-once / mismatch / in_flight / replay-after-409) |
| 15 | `/v1/projects/{key}/archive` | POST | project_management `_handle_archive` | guard + `target_project_key` in body-hash | `test_routes.py::TestArchiveIdempotency::*` (incl. different_project_409) |
| 16 | `/v1/projects/{key}` | PATCH | project_management `_handle_patch_detail` | guard + `target_project_key` | `test_routes.py::TestPatchDetailIdempotency::*` (incl. different_project_409) |
| 17 | `/v1/projects/{key}/configuration` | PATCH | project_management `_handle_patch_configuration` | guard + `target_project_key` | `test_routes.py::TestPatchConfigurationIdempotency::*` |
| 18 | `/v1/projects/{key}/planning/dependencies` | POST | execution_planning `_handle_create_dependency` | guard + `target_project_key` | `test_execution_planning_routes.py::test_create_dependency_replay_returns_stored_result`, `::test_create_dependency_same_op_id_different_body_returns_409_mismatch`, `::test_create_dependency_in_flight_returns_409` |
| 19 | `/v1/projects/{key}/planning/config` | PUT | execution_planning `_handle_put_config` | guard + `target_project_key` | `test_execution_planning_routes.py::test_put_config_replay_returns_stored_result`, `::test_put_config_same_op_id_different_body_returns_409_mismatch` |
| 20 | `/v1/projects/{key}/planning/dependencies/{story_id}/{depends_on}/{kind}` | DELETE | execution_planning `handle_delete` (op_id in DELETE body; dispatcher threads the body) | guard + full path tuple in body-hash | `test_execution_planning_routes.py::test_delete_dependency_missing_op_id_returns_422`, `::test_delete_dependency_replay_returns_stored_result_without_second_remove`, `::test_delete_dependency_same_op_id_different_target_returns_409_mismatch`, `::test_delete_dependency_in_flight_returns_409`, `::test_delete_dependency_replay_after_not_found_returns_stored_404` (AC8) |
| 21 | `/v1/governance/guard-counters` | POST | control_plane_http `_handle_post_guard_counter` | atomic single-TX (increment + record) on the inflight-record; op_id-PK unique-gate = in-flight protection; body-hash-409 | `test_hook_rest_mediation.py::test_guard_counter_concurrent_duplicate_op_id_counts_once_via_unique_gate` (AC4), `::test_guard_counter_op_id_mismatch_conflicts_via_rest`, `::test_guard_counter_replayed_op_id_counts_once_via_rest` |
| 22 | `…/phases/{phase}/start` | POST | control_plane runtime `start_phase` (`_acquire_claim`) | owner-scoped claim/finalize + in-flight reject + **request_body_hash** replay-vs-mismatch (AG3-140 r1) | control_plane phase body-hash mismatch/replay tests (`tests/unit/control_plane/`, `tests/contract/state_backend/`) |
| 23 | `…/phases/{phase}/complete` | POST | control_plane runtime `complete_phase` (`_mutate_phase`/`_load_existing_operation`) | body-hash on terminal record + replay-vs-mismatch | control_plane complete/replay + mismatch tests |
| 24 | `…/phases/{phase}/fail` | POST | control_plane runtime `fail_phase` | same | control_plane tests |
| 25 | `…/phases/{phase}/resume` | POST | control_plane runtime `resume_phase` | same; **formal.story-workflow resume** (replay returns stored; parallel same op_id in-flight) | `tests/integration/pipeline_engine/…::test_resume_replays_same_op_id_without_second_dispatch`, `::test_resume_loses_live_foreign_claim_and_never_dispatches` |
| 26 | `…/closure/complete` | POST | control_plane runtime `complete_closure` | claim/finalize + **request_body_hash** replay-vs-mismatch; app.py maps mismatch → 409 | `tests/unit/control_plane/test_http.py::test_missing_op_id_closure_payload_returns_422` + control_plane closure body-hash tests |
| 27 | `/v1/project-edge/operations/{op_id}/admin-abort` | POST | control_plane runtime `admin_abort` | op_id is the URL-path target (idempotent by construction; a second abort of a resolved op → 409) — AG3-138 owned | `tests/unit/control_plane/test_runtime.py` (admin-abort) |
| 28 | `/v1/projects/{key}/api-tokens` | POST | auth `_handle_create_token` | guard + `target_project_key` in body-hash | `test_auth_routes.py::test_create_token_replay_returns_same_token_and_issues_once`, `::test_create_token_body_mismatch_returns_409`, `::test_create_token_cross_project_mismatch_returns_409`, `::test_create_token_in_flight_returns_409` |
| 29 | `/v1/projects/{key}/api-tokens/{token_id}` | DELETE | auth `_handle_revoke_token` (op_id in DELETE body) | guard + `target_project_key` + `target_token_id` | `test_auth_routes.py::test_revoke_token_replay_returns_same_success_and_revokes_once`, `::test_revoke_token_replay_after_not_found_returns_same_404` (AC8), `::test_revoke_token_cross_token_mismatch_returns_409`, `::test_revoke_token_in_flight_returns_409` |

## Documented exceptions & non-mutating surfaces (Scope item 5, cited not skipped)

| Route | Method | Status | Justification |
|---|---|---|---|
| `POST /v1/project-edge/sync` | POST | **Read-only observation — NOT a mutation** (Codex r1 finding 4) | `sync_project_edge` (runtime.py) only calls `load_binding`/`load_lock` (reads) and builds an `EdgeBundle` from CURRENT state; it writes NO `control_plane_operations` row. A replay MUST return the current bundle, not a stale stored one, so claim/finalize would be WRONG. The `op_id` it carries is the FK-91 §91.1a Regel 17 reconcile-correlation key (`GET /v1/project-edge/operations/{op_id}`), not a mutation-idempotency claim. It is therefore NOT in the mutating-idempotency table (the earlier draft's claim/finalize entry was inaccurate and is removed). |
| `POST /v1/governance/worker-health` | POST | **No op_id — documented exception** | FK-91 §91.1a endpoint table + Regel 12: an idempotent upsert on `(story_id, worker_id)` — a retry overwrites the same state (harmless), so no op_id fence is needed. |
| `POST /v1/auth/login` | POST | No op_id | Session mint: each login legitimately creates a NEW session (not an idempotent keyed mutation); authenticated, not op_id-deduped. |
| `POST /v1/auth/logout` | POST | No op_id | Idempotent revoke of the presented token; a retry revokes the same (already-revoked) token harmlessly. |
| `kpi_analytics` (`/v1/...kpi...`) | — | **Read-only (proven)** | `kpi_analytics/http/routes.py` `handle_post` returns `None` unconditionally ("KPI surface is read-only"). No PUT/PATCH/DELETE handler. |
| `concept_catalog` | — | **Read-only (proven)** | `concept_catalog/http/routes.py` exposes only `handle_get`. No `handle_post`/`put`/`patch`/`delete`. |

### Concept-defined but NOT HTTP-wired (transparency)

FK-91's endpoint table lists `…/ownership/takeover-request`, `takeover-confirm`,
`takeover-reconcile-worktree` and `repair-resolve`. These have **no route pattern
in `control_plane_http` and no HTTP handler** today (the strings live only in the
domain layer); their ownership/epoch fencing is owned by AG3-142 / AG3-148 when wired.

## Known deferrals (WARNING dispositions — explicitly tracked)

- **Generic-guard orphan reconcile → AG3-142 (Codex r1 WARNING a).** The generic
  guard's claim rows carry `NULL backend_instance_id` (its fence is the op_id-PK
  + `claimed` status, not an instance epoch), so AG3-138's instance-scoped startup
  reconciliation does not auto-sweep a crash-orphaned generic-guard claim — it
  stays in-flight until `admin_abort`. This is **fail-closed** (never a double
  execution) and consistent with **FK-91 §91.1a Regel 16** (claims never end by
  wall clock). Auto-reconcile of generic-guard orphans is deferred to **AG3-142**
  (ownership/epoch fencing of the regime paths), where the guard claim can carry
  the instance identity + operation_epoch so the AG3-138 reconciliation sweeps it.
  Surfaced (not swallowed) per SEVERITY-SEMANTIK / ZERO-DEBT.
- **Guard-counter `correlation_id` (Codex r1 WARNING b).** The consolidated
  `control_plane_operations` record has no `correlation_id` column. The now-inert
  parameter was REMOVED from `record_invocation_idempotent` (its sole caller never
  supplied it) — no dead param remains.
- **task_management control_plane_http integration test (Codex r1 WARNING c).**
  `tests/integration/control_plane_http/test_task_management_routes.py` uses the
  in-memory guard because that subtree is deliberately SQLite/docker-free
  (AG3-051 allow-list). It is unit-level route coverage, NOT real-store coverage;
  the real-Postgres record semantics are covered by
  `tests/contract/state_backend/test_inflight_idempotency_guard_postgres.py` and
  the guard-counter concurrency test.

## Client conformance (Scope items 6/7)

All mutating client callers client-mint `op_id`: the bundle asset
`bundles/target_project/tools/agentkit/projectedge.py` (`_client_op_id`),
`harness_client/projectedge/`, the operator CLI `run-phase`/`resume`, and the
frontend `frontend/app/api.ts` (`makeOpId()`). Verified in the scope-6/7 commit.
