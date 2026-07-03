# AG3-140 — Mutating-Route Idempotency Inventory (mandatory cross-cutting artifact)

Story: **AG3-140 — Einheitlicher Idempotenz-Vertrag (BC-weit)**. This is the
ZERO-DEBT completeness ledger required by Scope item 5 / Acceptance criterion 5:
every mutating BC route, its idempotency mechanism, and an evidence test name.

## The one unified contract (FK-91 §91.1a Regel 5)

`op_id` is **client-supplied and required** (no server-side mint remains). One
contract for every mutating endpoint:

- **Replay** of the same `op_id` → the **stored result**, no second mutation.
- Same `op_id`, **different body** → `409 idempotency_mismatch` (body-hash check).
- **Parallel** same `op_id` → rejected **in-flight** (`409 operation_in_flight`),
  never executed twice.
- **Missing `op_id`** on a mutating route → fail-closed `422` (`missing_op_id`,
  or the `op_id`-specific validation 422 via `op_id_validation_error()`), distinct
  from an ordinary `400`/`422` payload-shape rejection.

Wire strings mandated by the concept: only `idempotency_mismatch` (409) is named
verbatim in FK-91 §91.1a (Regel 5 + Regel 12). The `422` for missing `op_id` and
`operation_in_flight` (409) for the in-flight loser are AGENTKIT wire strings
(English, ARCH-55) — the concept fixes the behavior, not the string.

## One record truth, one mechanism (decision (a))

All claim→mutate→finalize idempotency now resolves against the **single physical
inflight-operation-record** `control_plane_operations` (the materialization of the
formal `state-storage.entity.inflight-operation-record`, `identity_key: op_id`).
`request_body_hash` is the replay-vs-mismatch discriminator; `status='claimed'`
is the shared in-flight fence written **before** the mutation (crash-window
closed). The legacy `idempotency_keys` table is retired. The generic port
(`state_backend/store/inflight_idempotency_guard.py`, state_backend-owned) is
consumed by `story_context_manager` and `task_management`; `control_plane`'s phase
path keeps its own richer story-scoped claim/finalize on the same record; the
guard-counter keeps its atomic single-transaction record on the same table.

## Mutating-route inventory

| # | Route | Method | Handler / request model | Mechanism | Evidence (test) |
|---|---|---|---|---|---|
| 1 | `/v1/stories` | POST | story_context_manager `create_story` | client op_id (required, 422); claim→mutate→finalize on the inflight-record; replay / mismatch-409 / in-flight-409 | `test_service.py::test_create_replay_after_success_returns_snapshot_without_second_mutation`, `::test_parallel_in_flight_op_id_raises_operation_in_flight`, `::test_crash_between_mutate_and_finalize_is_not_doubly_executable` (AC3) |
| 2 | `/v1/stories/{id}` | PATCH | story_context_manager `update_story_fields` | same | `test_service.py::test_update_fields_body_mismatch_raises_idempotency_mismatch`; missing-op_id 422 in `test_http_routes.py` |
| 3 | `/v1/stories/{id}/approve` | POST | story_context_manager `_status_transition` | same | `tests/unit/story_context_manager/test_service.py` (transition replay/mismatch) |
| 4 | `/v1/stories/{id}/reject` | POST | story_context_manager `_status_transition` | same | `tests/unit/story_context_manager/test_service.py` |
| 5 | `/v1/stories/{id}/cancel` | POST | story_context_manager `cancel_story` | same | `tests/unit/story_context_manager/test_service.py` |
| 6 | story-exit viability handoff | (internal POST) | story_context_manager `administratively_cancel_for_story_exit` | same (op_id = exit_id) | `tests/unit/story_context_manager/test_service.py` (exit idempotent branches) |
| 7 | story-split scope_split | (internal POST) | story_context_manager `administratively_cancel_for_story_split` | same (op_id = split_id) | `tests/unit/story_context_manager/test_service.py` (split idempotent branches) |
| 8 | `…/tasks` | POST (create) | task_management `_handle_create_task` | client op_id (required, 422); guard claim→mutate→finalize; replay / mismatch-409 / in-flight-409 | `test_routes.py::TestCreateIdempotency` (missing_op_id / replay-no-realloc / mismatch / in_flight) |
| 9 | `…/tasks/{id}/resolve` | POST | task_management `_handle_resolve_task` | same + path-task_id folded into body-hash | `test_routes.py::TestResolveIdempotency` incl. `::test_resolve_replay_after_failure_returns_stored_404_once`, `::test_resolve_same_op_id_different_task_returns_409_mismatch` |
| 10 | `…/tasks/{id}/dismiss` | POST | task_management `_handle_dismiss_task` | same | `test_routes.py::TestDismissIdempotency` |
| 11 | `…/tasks/{id}/links` | POST (link) | task_management `_handle_link_task` | same | `test_routes.py::TestLinkIdempotency` |
| 12 | `…/tasks/{id}/links/delete` | POST (unlink) | task_management `_handle_unlink_task` | same | `test_routes.py::TestUnlinkIdempotency` |
| 13 | `/v1/projects/{key}` | PATCH | project_management `_handle_patch_detail` (`ProjectPatchRequest.op_id`) | client op_id (required, 422); server-mint removed | `tests/unit/project_management/http/test_routes.py` |
| 14 | `/v1/projects/{key}/configuration` | PATCH | project_management `_handle_patch_configuration` | client op_id (required, 422); server-mint removed | `tests/unit/project_management/http/test_routes.py` |
| 15 | project create | POST | project_management `_handle_create` | client op_id (required, 422) | `tests/unit/project_management/http/test_routes.py` |
| 16 | project archive | POST | project_management `_handle_archive` | client op_id (required, 422) | `tests/unit/project_management/http/test_routes.py` |
| 17 | dependency create | POST | execution_planning `_handle_create_dependency` | client op_id (required, 422) | `tests/unit/execution_planning/http/test_execution_planning_routes.py` |
| 18 | `…/execution-input/limits` | PUT | execution_planning `_handle_put_config` | client op_id (required, 422) | `tests/unit/execution_planning/http/test_execution_planning_routes.py` |
| 19 | `/v1/governance/guard-counters` | POST | control_plane_http `_handle_post_guard_counter` (`GuardCounterMutationRequest.op_id`) | client op_id (hook-side mint); atomic single-TX (increment + idempotency record) on the inflight-record; body-hash-409; op_id-PK unique-gate = in-flight protection | `test_hook_rest_mediation.py::test_guard_counter_concurrent_duplicate_op_id_counts_once_via_unique_gate` (AC4), `::test_guard_counter_record_is_atomic_rolls_back_on_key_save_failure`, `::test_guard_counter_op_id_mismatch_conflicts_via_rest` |
| 20 | `…/phases/{phase}/start` | POST | control_plane_http `_handle_post_phase_mutation` (`PhaseMutationRequest`) | client op_id (required, 422); control_plane owner-scoped claim/finalize + in-flight rejection on the inflight-record | `tests/unit/control_plane/test_runtime.py`, `tests/contract/state_backend/test_control_plane_operation_store_postgres.py` |
| 21 | `…/phases/{phase}/complete` | POST | control_plane_http (`PhaseMutationRequest`) | same | `tests/unit/control_plane/test_runtime.py` |
| 22 | `…/phases/{phase}/fail` | POST | control_plane_http (`PhaseMutationRequest`) | same | `tests/unit/control_plane/test_runtime.py` |
| 23 | `…/phases/{phase}/resume` | POST | control_plane_http (`PhaseMutationRequest`, `action=resume`) | same; **formal.story-workflow resume**: op_id reserved by the SAME in-flight claim, replay returns the stored result | `tests/integration/pipeline_engine/test_operator_cli_phase_rest.py::test_resume_replays_same_op_id_without_second_dispatch`, `::test_resume_loses_live_foreign_claim_and_never_dispatches` |
| 24 | `…/closure/complete` | POST | control_plane_http `_handle_post_closure_complete` (`ClosureCompleteRequest`) | client op_id (required, 422); claim/finalize on the inflight-record | `tests/unit/control_plane/test_http.py::test_missing_op_id_closure_payload_returns_422`, `tests/unit/control_plane/test_runtime.py` |
| 25 | `/v1/project-edge/sync` | POST | control_plane_http `_handle_post_project_edge_sync` (`ProjectEdgeSyncRequest`) | client op_id (required, 422); claim/finalize on the inflight-record | `tests/unit/control_plane/test_http.py::test_missing_op_id_project_edge_sync_payload_returns_422` |
| 26 | `/v1/project-edge/operations/{op_id}/admin-abort` | POST | control_plane_http `_handle_post_admin_abort` (`AdminAbortRequest`) | op_id is the URL-path target (idempotent by construction; a second abort of a resolved op deterministically 409s) — AG3-138 owned | `tests/unit/control_plane/test_runtime.py` (admin-abort) |
| 27 | `/v1/projects/{key}/tokens` | POST (token create) | auth `_handle_create_token` (`request.op_id`) | client op_id (required, 422); server-mint removed | `tests/unit/auth/http/test_auth_routes.py` |
| 28 | `/v1/projects/{key}/tokens/{id}` | DELETE (revoke) | auth `_handle_revoke_token` (`request.op_id`) | client op_id (required, 422); DELETE decodes an optional JSON body carrying op_id | `tests/unit/auth/http/test_auth_routes.py` |

## Documented exceptions & non-mutating surfaces (Scope item 5, cited not skipped)

| Route | Method | Status | Justification |
|---|---|---|---|
| `/v1/governance/worker-health` | POST | **No op_id — documented exception** | FK-91 §91.1a endpoint table + Regel 12: *"Der Save ist ein idempotenter Upsert auf `(story_id, worker_id)` — ein Retry ueberschreibt denselben State (harmlos), daher kein separates `op_id` noetig."* / *"Der Worker-Health-Write ist ein idempotenter Upsert."* An idempotent upsert needs no op_id fence. |
| `/v1/auth/login` | POST | No op_id | Session mint: each login legitimately creates a NEW session (not an idempotent mutation of a keyed resource); it is authenticated, not op_id-deduped. |
| `/v1/auth/logout` | POST | No op_id | Idempotent revoke of the presented token; a retry revokes the same (already-revoked) token harmlessly. |
| `kpi_analytics` (`/v1/...kpi...`) | — | **Read-only (proven)** | `kpi_analytics/http/routes.py` `handle_post` (≈:177–184) returns `None` unconditionally: *"Handle KPI POST routes or return None (KPI surface is read-only)."* No PUT/PATCH/DELETE handler. |
| `concept_catalog` (`/v1/...concepts...`) | — | **Read-only (proven)** | `concept_catalog/http/routes.py` exposes only `handle_get`. No `handle_post`/`put`/`patch`/`delete` handler exists. |

### Concept-defined but NOT HTTP-wired (transparency, ZERO DEBT)

FK-91's endpoint table lists `…/ownership/takeover-request`, `takeover-confirm`,
`takeover-reconcile-worktree` and `repair-resolve`. These have **no route pattern
in `control_plane_http` and no HTTP handler** today (the strings live only in the
domain layer: `control_plane/{models,runtime,startup_reconcile}.py`). They are
therefore not mutating HTTP routes in scope for AG3-140; their ownership/epoch
fencing is owned by AG3-142 / AG3-148 when wired. Recorded here so the inventory
is complete rather than silently short.

## Client conformance (Scope items 6/7)

All mutating client callers client-mint `op_id` (no reliance on the removed
server defaults): the bundle asset `bundles/target_project/tools/agentkit/
projectedge.py` (phase/closure/sync), `harness_client/projectedge/` (bounded
sync + caller op_id), the operator CLI `run-phase`/`resume`, and the frontend
`frontend/app/api.ts` (`makeOpId()`). Verified in the AG3-140 scope-6/7 commit.
