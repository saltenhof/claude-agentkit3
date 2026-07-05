# Summary

Reviewed `6446aa8f..590b0df5` as the AG3-144 fence-half only. The two commits are coherent single-author work (`saltenhof <saltenhof@users.noreply.github.com>`). I did not reject for the absent 202/client half.

Verdict is reject. The fence gate exists, and the stale store is append-only/idempotent, but the productive implementation path ignores stale sentinels and can still advance steering state after the fence has quarantined the result. In addition, several required predicates are either not threaded by the productive callers or are explicitly treated as optional/permissive.

# Findings

## CRITICAL: Productive implementation phase continues after stale QA/verify fences

Files:
- `src/agentkit/backend/implementation/phase.py:294`
- `src/agentkit/backend/implementation/phase.py:318`
- `src/agentkit/backend/implementation/phase.py:327`
- `src/agentkit/backend/implementation/phase.py:336`
- `src/agentkit/backend/state_backend/postgres_store.py:5237`
- `src/agentkit/backend/state_backend/postgres_store.py:5320`

Failure scenario:
1. Run `run-old` is executing the implementation QA subflow.
2. Before the QA result commit, ownership transfers or reset/exit lands so `apply_completion_fence` rejects the QA batch. `persist_layer_artifact_rows` records a `stale_observations` row and returns `()`.
3. `ProjectionAccessor.record_qa_layer_artifacts(...)` returns that empty tuple to `implementation/phase.py:294`, but the caller does not check it.
4. The handler then emits QA check outcomes at `implementation/phase.py:318`, calls `record_verify_decision(...)` at `implementation/phase.py:327`, ignores its stale `()` return as well, and for a passing decision writes completed story context at `implementation/phase.py:336`.

That violates AC5/AC6/AC10: a stale result can still produce follow-on side effects and steering state even though the fenced write itself was routed to `stale_observations`. The AG3-142 control-plane finalize may later reject the operation, but these phase-handler side effects have already happened.

Fix direction:
Make stale routing fail closed at the business boundary. Either have `record_layer_artifacts` / `ProjectionAccessor.record_qa_layer_artifacts` and `record_verify_decision` raise `StaleCompletionFencedError` like the artifact and single-QA repositories do, or make `implementation/phase.py` check the returned tuple before any check-outcome emission, verify-decision continuation, `save_story_context`, or completed `HandlerResult`.

## CRITICAL: Required fence predicates are skipped in productive callers

Files:
- `src/agentkit/backend/state_backend/store/facade.py:2165`
- `src/agentkit/backend/state_backend/store/facade.py:2181`
- `src/agentkit/backend/state_backend/store/facade.py:2339`
- `src/agentkit/backend/state_backend/postgres_store.py:3830`
- `src/agentkit/backend/state_backend/postgres_store.py:3943`
- `src/agentkit/backend/state_backend/postgres_store.py:3985`
- `src/agentkit/backend/state_backend/postgres_store.py:3997`
- `src/agentkit/backend/state_backend/store/artifact_repository.py:530`

Failure scenario:
1. A verify or closure result starts under ownership epoch `1`, compaction epoch `7`, and digest `D1`.
2. Before commit, the same run's ownership epoch changes, reset advances compaction to `8`, or the expected execution contract digest no longer matches the persisted digest.
3. The productive `record_verify_decision(...)` facade has no fence-context parameters and calls `persist_verify_decision_row(...)` without `expected_ownership_epoch`, `expected_compaction_epoch`, or `expected_execution_contract_digest`.
4. The gate treats `None` as "not applicable", so those predicates are skipped and the projection/upsert can commit.

The same pattern exists for closure, QA batch, artifact envelopes, and artifact target version: the registry declares optional predicates, but the productive converted paths do not pass the admission-time snapshots needed to enforce them. The gate also does not evaluate `binding_version` at all.

Fix direction:
Thread a typed `FenceContext` from the admission/attempt start point through every fenced write. For non-append-only completions, do not let productive facades default required story/run predicates to `None`. Implement or explicitly fail closed for `binding_version` and artifact target version rather than declaring them without enforcement.

## CRITICAL: Missing active ownership/project context is treated as permission to write

Files:
- `src/agentkit/backend/state_backend/postgres_store.py:3919`
- `src/agentkit/backend/state_backend/postgres_store.py:3928`
- `src/agentkit/backend/state_backend/postgres_store.py:3936`
- `src/agentkit/backend/state_backend/store/artifact_repository.py:379`
- `src/agentkit/backend/state_backend/store/artifact_repository.py:522`
- `src/agentkit/backend/state_backend/store/artifact_repository.py:542`

Failure scenario:
1. A stale completion arrives for a story whose active ownership row is absent, deleted, not backfilled, or not resolvable through `story_contexts`.
2. `_evaluate_fence_predicates` explicitly permits `active is None`; it only rejects when an active row exists and names a different run.
3. For artifact envelopes, if `story_contexts` cannot resolve `project_key`, `_pg_write` skips `apply_completion_fence` entirely and proceeds to the `ON CONFLICT ... DO UPDATE`.

This is fail-open against the baseline predicate "active ownership record". A non-append-only completion with no active ownership record should be stale, not allowed to update `artifact_envelopes`, QA read models, decision records, or closure projections.

Fix direction:
For `projection_upsert` and `steering`, absence of the active ownership row or unresolved `project_key` must produce a stale observation or a hard fail before the projection write. Keep legacy SQLite narrow, but do not create a permissive Postgres path.

## MAJOR: Result-kind registry is not on the production write path

Files:
- `src/agentkit/backend/control_plane/result_kinds.py:157`
- `src/agentkit/backend/state_backend/store/artifact_repository.py:530`
- `src/agentkit/backend/state_backend/store/projection_repositories.py:572`
- `src/agentkit/backend/state_backend/store/projection_repositories.py:807`
- `src/agentkit/backend/state_backend/postgres_store.py:5227`
- `src/agentkit/backend/state_backend/postgres_store.py:5307`
- `src/agentkit/backend/state_backend/postgres_store.py:5557`

Failure scenario:
A new or misspelled completion kind can call `apply_completion_fence(..., completion_kind="new_kind", result_kind="projection_upsert")`. The DB gate validates only the result-kind literal, then touches the DB and evaluates predicates. `resolve_result_kind` is only used by tests and never protects the converted production paths before DB access.

This does not satisfy AC3's "completion/job type with no declared result kind is rejected BEFORE any DB access".

Fix direction:
Require production callers to resolve `completion_kind` through `result_kinds.resolve_result_kind` before opening the DB transaction, and pass the resolved declaration into the store. Add a test that an undeclared completion kind on a real converted path performs no SQL.

## MAJOR: `run_fence_status_v` is not consistent with the gate for ended/reset/split and missing-active cases

Files:
- `src/agentkit/backend/state_backend/postgres_schema.sql:401`
- `src/agentkit/backend/state_backend/postgres_schema.sql:411`
- `src/agentkit/backend/state_backend/postgres_schema.sql:428`
- `src/agentkit/backend/state_backend/postgres_store.py:3953`
- `src/agentkit/backend/state_backend/postgres_store.py:3961`

Failure scenario:
If AG3-149 starts marking the run ownership record `ended`, `reset`, or `split`, the gate can still load the run's own record and return an `exit_reset_split_freedom` violation. The view, however, filters `WHERE r.status = 'active'`, so the row disappears instead of reporting `exit_reset_split_free = false`. Conversely, if the active row is missing entirely, the view has no row while the gate currently permits the write.

That makes the view a divergent read surface instead of the same model surface the gate enforces.

Fix direction:
Make the view and gate share the same predicate semantics. For non-active terminal statuses, expose a row with `exit_reset_split_free = false` or make the gate also treat absence as a hard stale state. Keep the AG3-149 replacement seam explicit and test the typed-status branch, not only the committed-exit-op fallback.

## MAJOR: ARCH-55 is violated in new source comments/docstrings

Files:
- `src/agentkit/backend/control_plane/fence_context.py:10`
- `src/agentkit/backend/control_plane/result_kinds.py:77`
- `src/agentkit/backend/state_backend/postgres_store.py:3853`
- `src/agentkit/backend/state_backend/postgres_store.py:5291`

Failure scenario:
The new production code includes German text (`wo einschlaegig`) in comments/docstrings. ARCH-55 requires English-only for code comments/docstrings.

Fix direction:
Replace the German phrase with English wording such as "where applicable".

# Explicit Assessments

AC8 single-connection simulation: not adequate for this increment. The AG3-142-style single-connection simulation is acceptable only if the same commit-time predicate catalog is actually enforced. Here, productive callers skip expected epoch/digest/compaction predicates, the active-row absence case is permissive, and optional predicate reads are not proven to serialize with their writers. The tests prove selected stale routes, not the full no-TOCTOU property required by AC6/AC8.

AC9 synchronous-finalize stopgap: partly sound but insufficient. The current control-plane start/resume/complete/fail/closure finalize paths do pass `expected_ownership_epoch` into AG3-142's `_enforce_ownership_fence_row`, so I did not find a separate unfenced phase-progress operation commit in today's synchronous finalize. However, that stopgap does not cover the QA/verify projection and steering side effects inside the implementation handler, and those are reachable today.

VERDICT: REJECT
