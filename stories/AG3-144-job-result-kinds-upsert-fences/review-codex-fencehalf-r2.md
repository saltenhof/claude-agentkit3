# AG3-144 FENCE-HALF Remediation Review r2

Reviewed remediation delta `590b0df5..0cf2644d` as a confirmation round against the six r1 findings. I read the production paths, not only the hunks.

## 1. CRITICAL-1: productive implementation phase continued after stale fence

Resolved: **yes for owner-mismatch stale fences; not sufficient for the full stale predicate surface because CRITICAL-2 remains open.**

Evidence:

- `state_backend/store/facade.py` now converts stale driver sentinels to `StaleCompletionFencedError` at the business boundary:
  - `record_layer_artifacts` raises when `persist_layer_artifact_rows` returns `None`.
  - `record_verify_decision` raises when `persist_verify_decision_row` returns `None`.
  - `record_closure_report` raises when `persist_closure_report_row` returns `None`.
- `implementation/phase.py` now lets those exceptions propagate before follow-on work. The ordering is now:
  1. `accessor.record_qa_layer_artifacts(...)`
  2. `record_verify_decision(...)`
  3. check-outcome emission
  4. `save_story_context(...)`
  5. completed `HandlerResult`
- That closes the r1 side-effect window for a stale QA-layer batch or stale verify decision that the fence actually detects. A stale exception now stops check-outcome emission, verify-decision continuation, completed story context, and completed handler return.
- `closure/phase.py` removed the dead `None` handling and relies on `record_closure_report` / `write_execution_report` raising, so a stale closure report does not return a normal completed closure result.
- `tests/integration/verify_system/test_stale_fence_business_boundary.py` drives the real `ImplementationPhaseHandler.on_enter` against real Postgres with an active owner mismatch. It asserts the stale row exists and `qa_stage_results`, `qa_findings`, `qa_check_outcomes`, `decision_records`, and story context remain unchanged.

Residual caveat:

- The ordering does **not** close stale projection writes for predicates that are still not threaded into the QA-layer batch. If `compaction_epoch`, `execution_contract_digest`, or `ownership_epoch` changes during the QA attempt while the active run id remains the same, `record_layer_artifacts` still writes QA projections before `record_verify_decision` can catch only the subset of predicates it receives. That is the unresolved CRITICAL-2 path below.

## 2. CRITICAL-2: required fence predicates skipped by productive callers

Resolved: **no.**

Evidence:

- `FenceContext` exists and `capture_fence_context(...)` captures `expected_ownership_epoch`, `expected_compaction_epoch`, and `expected_execution_contract_digest` at attempt start.
- `implementation/phase.py` captures that context before the QA subflow, and `closure/phase.py` captures it before closure finalization.
- But the captured context is only partially threaded:
  - `record_verify_decision(...)` accepts and passes only `expected_compaction_epoch` and `expected_execution_contract_digest`; it has no `expected_ownership_epoch` parameter.
  - `record_closure_report(...)` accepts and passes only `expected_compaction_epoch` and `expected_execution_contract_digest`; it has no `expected_ownership_epoch` parameter.
  - `record_layer_artifacts(...)` accepts no `FenceContext` and no expected predicates at all. The production `persist_layer_artifact_rows(...)` call passes none of `expected_ownership_epoch`, `expected_compaction_epoch`, or `expected_execution_contract_digest`.
  - `StateBackendArtifactRepository._pg_write(...)` now passes `expected_artifact_target_version`, but still passes no ownership/compaction/digest snapshot.
  - The single-row QA projection repositories also call `apply_completion_fence(...)` without ownership/compaction/digest snapshots.
- The registry reflects this incompleteness:
  - `qa_layer_artifact_upsert` declares no optional predicates.
  - `verify_decision` declares compaction, digest, and operation epoch only, not ownership epoch.
  - `closure_report` declares compaction and digest only, not ownership epoch.
  - `artifact_envelope_upsert` declares only artifact target version.
- `postgres_store._evaluate_fence_predicates(...)` still treats `None` expected values as "not applicable", so those productive paths still skip the predicates.

Reachable stale side-effect path:

1. Implementation attempt starts under active run `R`, ownership epoch `1`, compaction epoch `7`, digest `D1`.
2. During the QA subflow, ownership epoch advances to `2` while the active run id remains `R`, or compaction/digest changes.
3. `record_layer_artifacts(...)` calls the gate with no expected ownership/compaction/digest values. Baseline active ownership passes because the run id is still `R`; skipped predicates cannot reject.
4. QA projection files / `qa_stage_results` / `qa_findings` are written for a stale attempt.
5. `record_verify_decision(...)` may catch compaction/digest later, but it is too late for the QA projection write; it still cannot catch ownership epoch because that value is never passed.

This violates the confirmation requirement that non-append-only completions can no longer skip `ownership_epoch`, `compaction_epoch`, `execution_contract_digest`, and artifact target predicates by passing `None`.

Transaction check:

- For predicates that are actually supplied, the evaluation remains in the same transaction as the guarded write and still uses `SELECT ... FOR UPDATE` for the active/current ownership rows. I did not find a regression in the transaction shape.
- This does not compensate for the missing predicate threading.

`binding_version` assessment:

- `binding_version` is implemented in the gate and directly tested, but deliberately not declared on any registry entry because the session-binding snapshot belongs to the blocked 202/job-pattern half.
- As a scoped deferral, that is acceptable: it is explicitly documented and not silently declared-then-ignored.
- It does not resolve the unrelated missing productive threading for ownership/compaction/digest above.

## 3. CRITICAL-3: missing active ownership / unresolved project_key fail-open

Resolved: **yes.**

Evidence:

- `_evaluate_fence_predicates(...)` now returns `active_ownership_record` as a violation when no active ownership row exists for a non-append-only completion.
- The artifact Postgres write path now hard-fails with `StaleCompletionFencedError` when `_resolve_project_key_for_story(...)` returns `None`; it no longer skips the fence and proceeds to `artifact_envelopes`.
- Missing-active is tested for both projection-upsert (`record_layer_artifacts`) and steering (`record_verify_decision`).
- Append-only observation still legitimately bypasses all fence predicates and remains attributed to `started_by_ownership_epoch`, without touching projections or stale observations.

## 4. MAJOR-4: result-kind registry not on production path

Resolved: **yes for the reviewed production facades and repository paths.**

Evidence:

- `record_layer_artifacts`, `record_verify_decision`, and `record_closure_report` call `resolve_result_kind(...)` before touching `_backend_module()`.
- `StateBackendArtifactRepository._pg_write`, `FacadeQAStageResultsRepository._pg_write`, and `FacadeQAFindingsRepository._pg_write` also resolve before opening or using Postgres.
- `tests/unit/state_backend/store/test_result_kind_registry_gate.py` uses a poison backend and undeclared registry entries to prove no DB/backend access occurs for undeclared facade completion kinds.
- `result_kinds.py` remains A-core: no `state_backend` or HTTP imports.

## 5. MAJOR-5: `run_fence_status_v` diverged from gate semantics

Resolved: **yes.**

Evidence:

- `run_fence_status_v` is now per-run grain from `run_ownership_records`; the old `WHERE r.status = 'active'` filter is gone.
- The view now reports ended/reset/split statuses with `exit_reset_split_free = false` instead of making the row disappear.
- The transitional committed-exit-op derivation remains explicit as the AG3-149 seam.
- Tests cover both the committed-exit-op branch and the typed-status branch. Missing-active is consistent with the gate's new fail-closed behavior: no row means no ownership record exists, and the gate rejects non-append-only writes.

## 6. MAJOR-6: ARCH-55 German in new source comments/docstrings

Resolved: **yes for this delta.**

Evidence:

- The previously cited `wo einschlaegig` text was replaced with English.
- I swept added lines in `590b0df5..0cf2644d` for the obvious German terms from r1; the only hits were removed lines or pre-existing unrelated repository text, not new AG3-144 production additions.

## SQLite / K5 Regression Checks

Passed.

- `sqlite_store.persist_verify_decision_row(...)` and `sqlite_store.persist_closure_report_row(...)` gained `expected_compaction_epoch` / `expected_execution_contract_digest` for signature parity and immediately discard them with `del`.
- There is no SQLite fence, no SQLite `stale_observations` path, and no mirror table introduced.
- The public stale-observation facade remains Postgres-only and fail-closed on non-Postgres backends.

## Other Regression / Integrity Checks

Passed except for CRITICAL-2.

- The in-transaction gate shape is preserved for supplied predicates: `apply_completion_fence(...)` is called inside the same `with _connect(...)` / `_postgres_connect()` transaction as the guarded write, and the ownership rows are read under `FOR UPDATE`.
- I did not find a new second source of truth for stale observations. The public API exposes only `load_stale_observations_global`; inserts are internal to the Postgres fence gate.
- `result_kinds.py` and `fence_context.py` remain free of `state_backend` and HTTP imports.
- No new production TODO/stub path was introduced in the remediation delta. The added verify-system stub is test-only.
- The remediation did not weaken tests to pass the r1 owner-mismatch case; it added a real-handler integration test.

## `run_pipeline` / Ownership WARNING Assessment

Assessment: **test-plumbing warning, not a production regression.**

Evidence:

- `rg "run_pipeline\(" src tests` finds no production caller in `src/` other than the definition in `src/agentkit/backend/pipeline_engine/runner.py`.
- All call sites are tests (`tests/e2e`, `tests/integration`, `tests/unit`).
- The remediation seeds active ownership in E2E/handler harnesses rather than weakening the fence.
- On the available evidence, productive runs go through control-plane admission/finalization paths that mint ownership; the bare engine path is not a production entry point.

## New / Residual Findings

### CRITICAL: Productive non-append-only completions still skip required attempt-start predicates

The remediation does not fully resolve r1 CRITICAL-2 and leaves a reachable stale projection/steering path:

- QA-layer batch writes are non-append-only projection upserts but receive no attempt-start predicate snapshot.
- Verify and closure steering writes receive compaction/digest only, not ownership epoch.
- Artifact envelope upserts receive artifact target version only.
- Because the gate still treats `None` as skipped, a stale same-run ownership-epoch move, and for QA/artifact also a compaction/digest move, can pass the gate and produce projection writes. In the implementation phase, the QA-layer projection write happens before the verify-decision fence, so even a later verify-decision stale exception cannot restore byte-identical projections.

This is scope-breaking for a fail-closed fence.

VERDICT: REJECT
