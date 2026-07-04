# Codex Review R3 - AG3-140

## 1. Summary

REJECT. The round-2 remediation is materially improved: the four generic BC
route wrappers now delegate to the centralized `run_route_idempotent`, the helper
does not return the mutation success when `finalize()` returns `False`, the
pre-outcome release / post-commit in-flight window is tested, and the
ForbiddenFieldError PATCH/PUT gap is genuinely fixed.

I still found two contract defects. First, story_context_manager did not adopt
the new finalize-CAS-loss invariant and still ignores `finalize(False)`, so a
lost/taken-over claim can return a successful committed story mutation. Second,
the generic helper classifies every non-`claimed` same-hash row as a replay; a
real admin-abort writes an `aborted` control-plane payload, so the route replay
builder turns the fail-closed takeover into a bogus `500 corrupt_idempotency_*`
instead of the intended stable conflict/replay outcome.

Focused verification run:

`.\\.venv\\Scripts\\python -m pytest -q -p no:cacheprovider tests/unit/state_backend/test_inflight_idempotency_guard.py tests/contract/state_backend/test_inflight_idempotency_guard_postgres.py tests/unit/project_management/http/test_routes.py::TestCreateWindowInvariants tests/unit/story_context_manager/test_service.py::test_update_fields_replay_after_forbidden_field_reraises_and_runs_once tests/unit/story_context_manager/test_service.py::test_set_field_replay_after_forbidden_field_reraises_and_runs_once`

Result: `23 passed`.

Additional check: `git diff --check d8a7da41 c32a47ff` reports
`src/agentkit/backend/state_backend/store/story_repository.py:1055: new blank line at EOF`.

## 2. Part-A Verification

1. FIXED for the four generic call sites, but see Part-B finding 2 for the real
   admin-abort terminal shape. `run_route_idempotent` handles `finalize(False)`
   at `src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:521`
   to `:540` by re-classifying instead of returning success. The four generic
   route wrappers all go through it:
   `src/agentkit/backend/task_management/http/routes.py:459`,
   `src/agentkit/backend/project_management/http/routes.py:311`,
   `src/agentkit/backend/execution_planning/http/routes.py:198`,
   `src/agentkit/backend/auth/http/routes.py:256`. There is both a helper-level
   test at `tests/unit/state_backend/test_inflight_idempotency_guard.py:193` and
   a route-level test at `tests/unit/project_management/http/test_routes.py:1019`
   proving a finalize-false create does not return `201`.

2. FIXED for the centralized generic helper. Pre-outcome exceptions release at
   `src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:511`
   to `:517`; `>=500` responses release at `:518` to `:520`; the post-commit
   crash/no-finalize state is pinned at
   `tests/unit/state_backend/test_inflight_idempotency_guard.py:242` and the
   real Postgres store path at
   `tests/contract/state_backend/test_inflight_idempotency_guard_postgres.py:116`.
   I did not find a generic route mutate that performs a durable external side
   effect before its durable write: project routes read/validate then `save`,
   execution-planning reads/validates then `add/remove/upsert`, task routes
   allocate/read/validate then record, and auth token creation only generates
   in-memory token material before `repository.save`.

3. FIXED. `ForbiddenFieldError` is in `_FINALIZABLE_DOMAIN_ERRORS` at
   `src/agentkit/backend/story_context_manager/service.py:173` to `:179`.
   PATCH now runs `check_forbidden_fields(updates)` inside the claimed mutation
   at `service.py:656` to `:663`, and PUT delegates unconditionally to
   `update_story_fields` at `service.py:874` to `:885`. The tests at
   `tests/unit/story_context_manager/test_service.py:1427` and `:1467` prove the
   forbidden PATCH/PUT path is entered exactly once and replay re-raises the
   stored 422.

4. NOT-FIXED. The round-2 source comments in `service.py` were changed to
   English, but new code comments/docstrings still contain German review terms:
   `tests/unit/story_context_manager/test_service.py:1243`,
   `:1428`, and `:1468` use `Befund`. This is not the main rejection reason,
   but it violates the requested ARCH-55 check. There is also a new
   `diff --check` whitespace defect at
   `src/agentkit/backend/state_backend/store/story_repository.py:1055`.

## 3. Part-B Findings

1. `src/agentkit/backend/story_context_manager/service.py:594`,
   `:692`, `:836`, `:1002`, `:1030`, `:1122`, `:1150`, `:1249` - MAJOR -
   story_context_manager still ignores `guard.finalize(...)` returning `False`.
   The new centralized `run_route_idempotent` fixes this for the generic HTTP
   wrappers, but story_context_manager uses its own claim/finalize flow and never
   checks the boolean. Concrete scenario: `update_story_fields` wins a claim,
   saves the story at `service.py:687`, an admin abort/takeover resolves the
   `control_plane_operations` row before `service.py:692`, `finalize()` returns
   `False`, and the service still emits and returns the updated Story as success.
   The idempotency record now contains the abort/takeover result, not the stored
   story response, so the first caller was told a success that is not durably
   recorded under its `op_id`. Fix: factor story_context_manager through the same
   finalize-false re-classification invariant or add a local equivalent that
   refuses to return success after a lost claim; add a StoryService test with a
   finalize-false guard.

2. `src/agentkit/backend/state_backend/store/inflight_idempotency_guard.py:273`
   to `:279`, `src/agentkit/backend/control_plane/runtime.py:1423` to `:1438`,
   `src/agentkit/backend/state_backend/postgres_store.py:3716` to `:3724` -
   MAJOR - the generic helper misclassifies a real admin-aborted generic claim as
   a replay. `_resolve_loser()` treats every non-`claimed` row with the same
   body hash as `ReplayOutcome`, regardless of terminal status or payload shape.
   A real admin abort updates the row to `status='aborted'`, clears
   `claimed_by/claimed_at`, and stores a `ControlPlaneMutationResult` payload,
   not the route replay shape `{"status_code": ..., "body": ...}`. On a late
   `finalize(False)` or a retry of the same request, `run_route_idempotent`
   routes that payload through the BC replay builder; for example project
   management fails closed as `500 corrupt idempotency replay record` at
   `src/agentkit/backend/project_management/http/routes.py:336` to `:346`.
   That is not the promised replay/mismatch/in-flight conflict outcome and it
   labels a valid admin-abort row as corrupt data. Fix: include terminal status
   in generic classification and only replay records finalized by the route
   contract (`status='committed'` with route-shaped payload); classify
   admin-aborted/repair/failed rows as a stable conflict outcome and cover it
   with a real-store or faithful route-level admin-abort test, not the current
   always-false fake that leaves the row `claimed`.

## 4. Final Assessment

The R2 fixes for the four generic call sites and forbidden-field AC8 are real,
and the new Postgres guard tests cover the normal record path. AG3-140 is still
not approvable because the unified contract is not actually uniform: the
story-context service can still return success after losing its claim, and the
generic helper's real admin-abort path returns a malformed replay/500 instead of
a stable fail-closed contract response.

VERDICT: REJECT
