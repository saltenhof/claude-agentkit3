## Summary

The r2 CRITICAL is closed. The real closure Step 5 path now binds an
`OwnershipFenceScope` around the `story_metrics` write, and
`ProjectionAccessor.write_projection(ProjectionKind.STORY_METRICS, ...)` routes
to `FacadeStoryMetricsRepository.write` and then to its fenced `_pg_write`, not
to the retained unfenced `facade.upsert_story_metrics` helper.

I found no reachable production mutating story-projection write in the AG3-144
phase-run surface that can commit on Postgres without the AG3-142
`run_ownership_records` fence. I also found no TOCTOU window in the remediated
paths, no production caller of the retained `upsert_story_metrics` helper, no
new ContextVar thread/executor boundary from the round-3 delta, and no new
ARCH-55 non-English source text.

Review method: static source and diff inspection only. I did not run Postgres
integration tests per instruction. I used grep/AST checks against the source
tree; no production/test files were modified.

## Final Per-Story-Projection-Table Completeness Map

| Table / surface | Fenced? | Evidence file:line | Sole writer / routing |
|---|---:|---|---|
| `artifact_envelopes` | Yes | `ArtifactManager.write` delegates to the repository at `src/agentkit/backend/artifacts/manager.py:77` and `src/agentkit/backend/artifacts/manager.py:80`. The Postgres repository requires a bound scope at `src/agentkit/backend/state_backend/store/artifact_repository.py:492`, fences at `src/agentkit/backend/state_backend/store/artifact_repository.py:500`, and only then executes the upsert at `src/agentkit/backend/state_backend/store/artifact_repository.py:508`. | `StateBackendArtifactRepository.write_envelope`; phase handlers bind the ContextVar around production artifact writes. |
| `qa_stage_results` | Yes on the real production path | Implementation calls the batch boundary at `src/agentkit/backend/implementation/phase.py:325`. The accessor documents this as the productive QA write boundary at `src/agentkit/backend/telemetry/projection_accessor.py:680` and `src/agentkit/backend/telemetry/projection_accessor.py:684`. The driver opens one transaction at `src/agentkit/backend/state_backend/postgres_store.py:5062`, fences first at `src/agentkit/backend/state_backend/postgres_store.py:5065`, and upserts at `src/agentkit/backend/state_backend/postgres_store.py:5096`. | `ProjectionAccessor.record_qa_layer_artifacts` -> `FacadeQALayerBatchWriter` -> `persist_layer_artifact_rows`. The direct single-row repo method exists, but I found no production `src` caller of `ProjectionKind.QA_STAGE_RESULTS` outside the accessor dispatch. |
| `qa_findings` | Yes on the real production path | Same batch as `qa_stage_results`: fence first at `src/agentkit/backend/state_backend/postgres_store.py:5065`, delete old findings at `src/agentkit/backend/state_backend/postgres_store.py:5081`, and rebuild findings at `src/agentkit/backend/state_backend/postgres_store.py:5100`. | Same sole production writer: `ProjectionAccessor.record_qa_layer_artifacts` -> batch driver. |
| `qa_check_outcomes` | Yes | Implementation emits outcomes while the ownership scope is still bound at `src/agentkit/backend/implementation/phase.py:280` through `src/agentkit/backend/implementation/phase.py:359`. The emitter calls `write_projection` at `src/agentkit/backend/verify_system/check_outcome_emitter.py:252` and `src/agentkit/backend/verify_system/check_outcome_emitter.py:254`. The repository requires scope at `src/agentkit/backend/state_backend/store/projection_repositories.py:1426`, fences at `src/agentkit/backend/state_backend/store/projection_repositories.py:1431`, and upserts only after that at `src/agentkit/backend/state_backend/store/projection_repositories.py:1439`. | `CheckOutcomeEmitter.emit` via `ProjectionAccessor.write_projection(QA_CHECK_OUTCOMES, ...)`. |
| `decision_records` | Yes | Implementation passes the captured snapshot at `src/agentkit/backend/implementation/phase.py:360` through `src/agentkit/backend/implementation/phase.py:366`. Facade forwards it at `src/agentkit/backend/state_backend/store/facade.py:2421` through `src/agentkit/backend/state_backend/store/facade.py:2433`. The driver fences first at `src/agentkit/backend/state_backend/postgres_store.py:5148`, writes the projection file at `src/agentkit/backend/state_backend/postgres_store.py:5156`, and upserts `decision_records` at `src/agentkit/backend/state_backend/postgres_store.py:5160`. | `record_verify_decision`. |
| `closure_report` / `closure.json` | Yes | Closure resolves the active snapshot at `src/agentkit/backend/closure/phase.py:1121` and passes it through `write_execution_report` at `src/agentkit/backend/closure/phase.py:1125`. The writer calls `record_closure_report` with that snapshot at `src/agentkit/backend/closure/execution_report/writer.py:48` through `src/agentkit/backend/closure/execution_report/writer.py:53`. The driver opens one transaction at `src/agentkit/backend/state_backend/postgres_store.py:5417`, fences at `src/agentkit/backend/state_backend/postgres_store.py:5421`, and writes the file inside that same transaction at `src/agentkit/backend/state_backend/postgres_store.py:5432`. | `write_execution_report` -> `record_closure_report` -> `persist_closure_report_row`. |
| `story_metrics` | Yes | Closure Step 5 binds a scope at `src/agentkit/backend/closure/phase.py:441` through `src/agentkit/backend/closure/phase.py:448`. `_resolve_metrics` writes via `ProjectionAccessor.write_projection(ProjectionKind.STORY_METRICS, metrics)` at `src/agentkit/backend/closure/phase.py:1201` and `src/agentkit/backend/closure/phase.py:1202`. The accessor routes to `self._repos.story_metrics.write(record)` at `src/agentkit/backend/telemetry/projection_accessor.py:335` and `src/agentkit/backend/telemetry/projection_accessor.py:339`. The repository requires the scope at `src/agentkit/backend/state_backend/store/projection_repositories.py:1016`, fences at `src/agentkit/backend/state_backend/store/projection_repositories.py:1021`, and upserts at `src/agentkit/backend/state_backend/store/projection_repositories.py:1029` and `src/agentkit/backend/state_backend/store/projection_repositories.py:1031`. | Closure/PostMergeFinalization via `ProjectionAccessor.write_projection(STORY_METRICS, ...)`. |
| `phase_state_projection` | Not a live AG3-144 mutating projection write | `ProjectionAccessor` marks it externally owned at `src/agentkit/backend/telemetry/projection_accessor.py:111` and `src/agentkit/backend/telemetry/projection_accessor.py:112`, and `write_projection` rejects non-accessor-owned kinds at `src/agentkit/backend/telemetry/projection_accessor.py:303` through `src/agentkit/backend/telemetry/projection_accessor.py:307`. The state-backend repository exposes purge only at `src/agentkit/backend/state_backend/store/projection_repositories.py:1228` through `src/agentkit/backend/state_backend/store/projection_repositories.py:1243`. | No production write through `ProjectionAccessor`; pipeline engine owns phase state, not this AG3-144 story-projection fence surface. |
| `fc_incidents` | Not a live AG3-144 phase-run projection write | The generic `write_projection(FC_INCIDENTS, ...)` path is fail-closed at `src/agentkit/backend/telemetry/projection_accessor.py:313` and `src/agentkit/backend/telemetry/projection_accessor.py:314`; the dedicated writer is `record_fc_incident` at `src/agentkit/backend/telemetry/projection_accessor.py:354` through `src/agentkit/backend/telemetry/projection_accessor.py:368`. The repository inserts without AG3-142 fencing at `src/agentkit/backend/state_backend/store/fc_incident_repository.py:253` through `src/agentkit/backend/state_backend/store/fc_incident_repository.py:258`, but source grep found no phase-handler or pipeline real-run caller. The visible production handoff is optional GovernanceObserver failure-corpus handoff at `src/agentkit/backend/governance/governance_observer/observer.py:353` through `src/agentkit/backend/governance/governance_observer/observer.py:358`, and I found no production construction/call path for `GovernanceObserver.handle_signal` under `src`. | Failure-corpus/governance observer surface; not a reachable AG3-144 phase-run story projection commit in this review. |
| `risk_window` | Not a live AG3-144 phase-run projection write | The accessor has a dedicated risk-window method at `src/agentkit/backend/telemetry/projection_accessor.py:726` through `src/agentkit/backend/telemetry/projection_accessor.py:739`. The repository insert is unfenced at `src/agentkit/backend/state_backend/store/projection_repositories.py:1181` through `src/agentkit/backend/state_backend/store/projection_repositories.py:1194`, but source grep found only the normalizer call at `src/agentkit/backend/telemetry/risk_window/normalizer.py:139` and no production phase-run caller of `normalize_and_record`. | FK-68 telemetry rolling-window surface; not a reachable AG3-144 phase-run story projection commit in this review. |
| `fc_patterns` / `fc_check_proposals` | Not story-run scoped | They are accessor-owned projection kinds at `src/agentkit/backend/telemetry/projection_accessor.py:101` through `src/agentkit/backend/telemetry/projection_accessor.py:105`, but their writers are pattern/check-factory surfaces, not `(story_id, run_id)` story-run projections. | Out of the AG3-142 ownership-lease fence surface. |

## r2 Critical Closure

`ProjectionAccessor.write_projection(STORY_METRICS, ...)` now reaches
`FacadeStoryMetricsRepository.write`, not the retained helper. The routing is
visible at `src/agentkit/backend/telemetry/projection_accessor.py:335` through
`src/agentkit/backend/telemetry/projection_accessor.py:339`; the repository
branches to `_pg_write` for Postgres at
`src/agentkit/backend/state_backend/store/projection_repositories.py:981` through
`src/agentkit/backend/state_backend/store/projection_repositories.py:984`.

The Postgres write is fence-first and same-transaction: `_pg_write` requires the
ContextVar scope at `src/agentkit/backend/state_backend/store/projection_repositories.py:1016`,
opens `_postgres_connect()` at `src/agentkit/backend/state_backend/store/projection_repositories.py:1017`,
calls `_enforce_ownership_fence_row` at
`src/agentkit/backend/state_backend/store/projection_repositories.py:1021`, and
only then executes `INSERT INTO story_metrics ... ON CONFLICT` at
`src/agentkit/backend/state_backend/store/projection_repositories.py:1029` through
`src/agentkit/backend/state_backend/store/projection_repositories.py:1045`.
`borrow_repository_connection` documents clean-exit commit / exception rollback
for this transaction at `src/agentkit/backend/state_backend/postgres_store.py:417`
through `src/agentkit/backend/state_backend/postgres_store.py:430`.

Closure Step 5 binds the scope around the metrics write at
`src/agentkit/backend/closure/phase.py:441` through
`src/agentkit/backend/closure/phase.py:448`, and `_resolve_metrics` performs the
actual `write_projection` call at `src/agentkit/backend/closure/phase.py:1201`
and `src/agentkit/backend/closure/phase.py:1202`.

## Retained Helper Sweep

The retained `facade.upsert_story_metrics` is still an unfenced low-level helper
at `src/agentkit/backend/state_backend/store/facade.py:2242` through
`src/agentkit/backend/state_backend/store/facade.py:2244`, and the raw Postgres
helper still upserts without a fence at
`src/agentkit/backend/state_backend/postgres_store.py:4654` through
`src/agentkit/backend/state_backend/postgres_store.py:4667`.

I found no production caller. The non-definition callers are tests/seeding:
`tests/integration/installer/test_decommission.py:102`,
`tests/contract/state_backend/test_postgres_backend.py:568`, and
`tests/integration/state_backend/test_story_read_repository_roundtrip.py:85`.
The repository's SQLite branch calls `sqlite_store.upsert_story_metrics_row` at
`src/agentkit/backend/state_backend/store/projection_repositories.py:990`, which
is not the Postgres deployment path.

## Setup DI Fix

`setup_preflight_gate.phase` has no non-`TYPE_CHECKING` import from
`agentkit.backend.state_backend.store`. The only remaining store import in that
module is type-only for mode-lock protocols at
`src/agentkit/backend/governance/setup_preflight_gate/phase.py:52` through
`src/agentkit/backend/governance/setup_preflight_gate/phase.py:65`; the runtime
imports at `src/agentkit/backend/governance/setup_preflight_gate/phase.py:31`
through `src/agentkit/backend/governance/setup_preflight_gate/phase.py:50` do
not import `state_backend.store`. I also ran the same AST-style exclusion used
by `tests/unit/governance/test_architecture_conformance_imports.py:93` through
`tests/unit/governance/test_architecture_conformance_imports.py:141`; it returned
no violations.

The unwired default is fail-closed on Postgres: `_default_fence_scope_binder`
returns `contextlib.nullcontext()` at
`src/agentkit/backend/governance/setup_preflight_gate/phase.py:72` through
`src/agentkit/backend/governance/setup_preflight_gate/phase.py:100`; if an ARE
artifact write is reached, `StateBackendArtifactRepository._pg_write` requires
a bound scope and raises before SQL at
`src/agentkit/backend/state_backend/store/artifact_repository.py:492`.

The real binder is in the composition root. It resolves the snapshot and binds
it at `src/agentkit/backend/bootstrap/composition_root.py:1964` through
`src/agentkit/backend/bootstrap/composition_root.py:1985`, and
`build_setup_phase_handler` injects it at
`src/agentkit/backend/bootstrap/composition_root.py:2040` through
`src/agentkit/backend/bootstrap/composition_root.py:2050`. Setup uses the
injected binder around the ARE bundle load at
`src/agentkit/backend/governance/setup_preflight_gate/phase.py:258` through
`src/agentkit/backend/governance/setup_preflight_gate/phase.py:263`.

## ContextVar Regression Probe

No fail-open empty-run-id path found. Closure Step 5 uses
`metrics_run_id = _resolve_run_id_fail_closed(s_dir) or ""` at
`src/agentkit/backend/closure/phase.py:436`, then binds that value at
`src/agentkit/backend/closure/phase.py:441` through
`src/agentkit/backend/closure/phase.py:448`. `_resolve_run_id_fail_closed`
returns `None` on absent/corrupt runtime scope at
`src/agentkit/backend/closure/phase.py:1018` through
`src/agentkit/backend/closure/phase.py:1033`. If the runtime scope is truly
missing, `build_story_metrics_record` raises before any projection write at
`src/agentkit/backend/closure/post_merge_finalization/metrics.py:32` through
`src/agentkit/backend/closure/post_merge_finalization/metrics.py:50`. If the
record has a canonical run id but the bound scope run id is wrong or empty,
`_enforce_ownership_fence_row` compares the active `run_ownership_records.run_id`
and raises before the upsert at `src/agentkit/backend/state_backend/postgres_store.py:3882`
through `src/agentkit/backend/state_backend/postgres_store.py:3907`.

No new closure/setup thread or executor boundary was introduced. The new
closure/setup bindings are straight-line context managers at
`src/agentkit/backend/closure/phase.py:441` and
`src/agentkit/backend/governance/setup_preflight_gate/phase.py:258`. The only
`ThreadPoolExecutor` hit in the nearby phase tree is the pre-existing worker
health sidecar at `src/agentkit/backend/implementation/worker_health/sidecar.py:235`,
not a new closure/setup projection write boundary.

## ARCH-55

The round-3 diff removes the prior German `ENTWURF` comment and replaces it
with English text at `src/agentkit/backend/exploration/phase.py:281` through
`src/agentkit/backend/exploration/phase.py:288`. I found no newly introduced
non-English identifiers, comments, or docstrings in the round-3 delta. The
pre-existing `SOLL-015` reference remains a concept tag and was already present
in the touched setup comment context.

## Findings

No CRITICAL findings.

No MAJOR findings.

No MINOR findings.

VERDICT: APPROVE
