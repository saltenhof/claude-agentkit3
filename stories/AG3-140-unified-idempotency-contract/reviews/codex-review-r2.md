# Codex Review R2 - AG3-140

## 1. Summary

REJECT. Most round-1 remediation is real: dependency DELETE now receives the
DELETE body, the auth/project/planning routes are under the shared guard, the
control-plane body-hash path is materially fixed, and project-edge sync is
correctly reclassified as read-only. I found no remaining server-side wire-model
`op_id` default.

However, the story-context replay-after-failure fix is still incomplete for a
deterministic domain 422, and the newly wrapped generic BC routes have two
cross-cutting race/error-boundary defects around finalize/release. These are
contract defects, not cosmetic review gaps.

Focused verification run:

`.\.venv\Scripts\python -m pytest -q -p no:cacheprovider tests/unit/state_backend/test_inflight_idempotency_guard.py tests/unit/project_management/http/test_routes.py tests/unit/auth/http/test_auth_routes.py tests/unit/execution_planning/http/test_execution_planning_routes.py tests/unit/story_context_manager/test_service.py::test_status_transition_replay_after_failure_reraises_and_runs_once tests/unit/story_context_manager/test_service.py::test_replay_after_failure_is_not_reexecutable_and_not_mismatch tests/unit/story_context_manager/test_service.py::test_create_story_replay_after_forbidden_reraises_and_runs_once`

Result: `74 passed`.

## 2. Part-A Verification

1. FIXED - dependency DELETE now has the full contract. `control_plane_http/app.py:1306-1320` decodes the DELETE body and passes it to planning; `execution_planning/http/routes.py:344-383` validates required `op_id`, hashes the full URL target tuple, and runs `_run_idempotent`; tests at `tests/unit/execution_planning/http/test_execution_planning_routes.py:340-381` prove missing op_id, replay without second remove, and different-target mismatch. No server-side default is present on `DeleteDependencyRequest`.

2. FIXED - project_management, execution_planning, and auth are now guarded. Examples: project wrappers at `project_management/http/routes.py:297-352`, planning wrappers at `execution_planning/http/routes.py:185-233`, auth wrappers at `auth/http/routes.py:240-295`. The exact api-token scenario is pinned at `tests/unit/auth/http/test_auth_routes.py:243-279`: duplicate POST replays the same plaintext token and different label returns `409 idempotency_mismatch`.

3. FIXED - control_plane phase/closure body-hash handling is materially fixed. Claims stamp `request_body_hash` at `control_plane/runtime.py:2790-2797`; terminal records stamp it at `runtime.py:2236-2249` and `runtime.py:2026-2038`; terminal replay classifies mismatch at `runtime.py:2574-2626`. Real-Postgres tests exist at `tests/contract/state_backend/test_control_plane_operation_store_postgres.py:1131-1226`, and the comments explicitly state the closure test no longer xfails.

4. FIXED - project-edge sync is read-only. `sync_project_edge` only calls `load_binding` / `load_lock` and builds in-memory bundles at `control_plane/runtime.py:2101-2175`; I see no claim, `control_plane_operations` write, save binding/lock, or commit call inside that method. The inventory's read-only classification is correct.

5. NOT-FIXED - story_context_manager finalizes several deterministic 4xx outcomes, but not all. The fixed cases are real: `_run_claimed` finalizes `_FINALIZABLE_DOMAIN_ERRORS` at `story_context_manager/service.py:336-358`, and the replay-after-failure tests at `tests/unit/story_context_manager/test_service.py:1308-1423` prove single execution for status/create/update validation scenarios. But `ForbiddenFieldError` is a deterministic domain 422 for PATCH/PUT fields and is still thrown before any claim at `service.py:632-633` and `service.py:869-875`; it is also absent from `_FINALIZABLE_DOMAIN_ERRORS` at `service.py:173-178`. Replay of the same `op_id` therefore re-enters the route and re-runs the domain check instead of replaying a stored error. AC8 is still incomplete.

6. FIXED with one caveat - route-inventory.md was regenerated and now has the corrected `/api-tokens`, `/planning/config`, story-field PUT, dependency DELETE, project-edge-sync read-only decision, and Known deferrals section for the generic-guard orphan reconcile gap. Caveat: because Part-A #5 remains incomplete, the inventory's top-level claim that deterministic 4xx failures are finalized everywhere overstates the actual PATCH/PUT forbidden-field behavior.

## 3. Part-B New Findings

1. `src/agentkit/backend/project_management/http/routes.py:347`, `src/agentkit/backend/execution_planning/http/routes.py:230`, `src/agentkit/backend/auth/http/routes.py:292`, `src/agentkit/backend/task_management/http/routes.py:499` - MAJOR - The new generic route wrappers ignore `guard.finalize(...)` returning `False`. The guard contract says `False` means the claim was lost, e.g. admin-aborted, and "the caller must then NOT treat the mutation as durably recorded" (`state_backend/store/inflight_idempotency_guard.py:153-164`). Current behavior still returns the successful mutation response. Concrete scenario: an admin abort resolves a claimed generic operation while token creation/project archive is running; the route commits its side effect, finalize CAS returns false, but the client receives `201/200 committed` even though the idempotency record contains the abort result, not the stored route response. Fix: require finalize success before returning success; on false, load/classify the existing row and return a fail-closed conflict/replay outcome, with a test guard whose finalize returns false.

2. `src/agentkit/backend/project_management/http/routes.py:340`, `src/agentkit/backend/execution_planning/http/routes.py:226`, `src/agentkit/backend/auth/http/routes.py:286`, `src/agentkit/backend/control_plane_http/app.py:1697-1705` - MAJOR - Several newly wrapped generic routes do not release a fresh claim when `mutate()` raises before producing a route response. Task-management catches unexpected service exceptions into a 500 response, which `_run_idempotent` releases; project_management/execution_planning/auth do not have that boundary, and the HTTP server wrapper does not catch the exception either. Concrete scenario: after a successful claim, `ProjectRepository.get()` or `ProjectApiTokenRepository.save()` raises a transient database exception before a deterministic outcome exists; the request fails at transport level and the `claimed` row remains, so the retry is permanently `operation_in_flight` until admin intervention. Fix: put an explicit exception boundary around pre-outcome route mutations and release the owner-scoped claim only for exceptions known to occur before a committed side effect; keep post-commit crash windows fail-closed.

3. `src/agentkit/backend/story_context_manager/service.py:632`, `src/agentkit/backend/story_context_manager/service.py:869`, `src/agentkit/backend/story_context_manager/service.py:173` - MAJOR - Deterministic forbidden-field failures are outside the claim/finalize path. `PATCH /stories/{id}` calls `check_forbidden_fields(updates)` before constructing `IdempotencyRequest`, and `PUT /fields/{field_key}` raises `ForbiddenFieldError` before delegating to the guarded update path. The error is not in `_FINALIZABLE_DOMAIN_ERRORS`, so replay-after-failure is not stored. Concrete scenario: a client sends `{"op_id":"op-x","status":"Done"}` to PATCH, gets `422 forbidden_field`, times out, retries with the same op_id, and the service executes the forbidden-field path again rather than replaying one stored error. Fix: either move forbidden-field validation inside the claimed mutation and include `ForbiddenFieldError` in the finalizable registry, or document it as a pre-contract wire validation and remove the overbroad AC8/inventory claim; the story as written requires the former.

4. `src/agentkit/backend/story_context_manager/service.py:165`, `src/agentkit/backend/story_context_manager/service.py:654`, `src/agentkit/backend/story_context_manager/service.py:809`, `src/agentkit/backend/story_context_manager/service.py:1225` - NIT - New source comments use German review terminology (`Befund`) in code comments. ARCH-55 requires English source comments. Fix: rename to `finding` or remove the review-origin wording.

## 4. Final Assessment

The R1 fixes are not paper-only, but AG3-140 is not approvable yet. The remaining story_context_manager AC8 gap is a direct NOT-FIXED item, and the generic guard adoption added two cross-BC correctness holes around finalize CAS loss and pre-outcome exception release. These need tests at the shared wrapper boundary plus at least one route-level proof.

VERDICT: REJECT
