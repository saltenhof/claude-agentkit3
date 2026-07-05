# AG3-144 FENCE-HALF Remediation Review r3

Reviewed remediation delta `0cf2644d..9ed59291` and the relevant production paths. I did not edit production code.

## CRITICAL-2 closure confirmation

The five explicitly remediated paths are now threaded from attempt-start capture to the fence call and are declared in the registry, but CRITICAL-2 is **not fully closed** because other production `ArtifactManager.write()` paths still reach `artifact_envelope_upsert` without the required snapshots.

| Path | Resolved for threading? | Evidence |
|---|---:|---|
| `record_layer_artifacts` -> `persist_layer_artifact_rows` / `qa_layer_artifact_upsert` | Yes | `ImplementationPhaseHandler.on_enter` captures `capture_fence_context` before QA (`src/agentkit/backend/implementation/phase.py:243`) and passes ownership/compaction/digest into `record_qa_layer_artifacts` (`implementation/phase.py:339`, `:350`). The accessor/facade/driver preserve them (`telemetry/projection_accessor.py:670`, `:734`; `state_backend/store/facade.py:2276`; `state_backend/postgres_store.py:5390`). Registry declares all three (`control_plane/result_kinds.py:126`). |
| `record_verify_decision` -> `persist_verify_decision_row` / `verify_decision` | Yes | Same attempt-start snapshot is passed into `record_verify_decision` (`implementation/phase.py:374`, `:379`), through facade (`state_backend/store/facade.py:2298`, `:2360`) into the driver fence call (`state_backend/postgres_store.py:5489`). Registry now includes ownership plus compaction/digest (`control_plane/result_kinds.py:139`). |
| `record_closure_report` -> `persist_closure_report_row` / `closure_report` | Yes | Closure captures at sequence start (`closure/phase.py:385`) and threads ownership into `_write_report` -> `write_execution_report` -> facade -> driver (`closure/phase.py:1135`; `closure/execution_report/writer.py:60`; `state_backend/store/facade.py:2570`; `state_backend/postgres_store.py:5754`). Registry declares ownership/compaction/digest (`control_plane/result_kinds.py:151`). |
| `StateBackendArtifactRepository.write_envelope` / `_pg_write` / `artifact_envelope_upsert` for VerifySystem envelope sites | Partly | The hot VerifySystem envelope sites now pass `ctx.expected_*` (`verify_system/system.py:831`, `:885`, `:957`; `verify_system/adversarial_orchestrator/spawn.py:316`), and `_pg_write` passes them into `apply_completion_fence` (`state_backend/store/artifact_repository.py:593`). Registry declares artifact target version plus ownership/compaction/digest (`control_plane/result_kinds.py:114`). This does **not** cover all production `ArtifactManager.write()` callers; see residual finding below. |
| Single-row QA repos (`FacadeQAStageResultsRepository`, `FacadeQAFindingsRepository`) | Yes for the repository API | The write APIs now accept/pass ownership/compaction/digest to `apply_completion_fence` (`state_backend/store/projection_repositories.py:597`, `:659`, `:869`, `:932`). |

The exact r2 exploit is now covered by a real `ImplementationPhaseHandler.on_enter` test: same `run_id`, ownership epoch advances `1 -> 2` during QA, stale row recorded, and no QA read model/projection/check outcome/decision/story-context side effect is written (`tests/integration/verify_system/test_stale_fence_business_boundary.py:355`). Driver-level sibling tests cover QA-layer ownership, compaction, and digest (`tests/integration/state_backend/test_completion_fence_postgres.py:942`, `:975`, `:1007`) and artifact-envelope ownership, compaction, and digest (`:1085`, `:1112`, `:1141`). Verify and closure ownership epoch tests exist (`:1177`, `:1205`).

Transaction shape caveat: the guarded writes still call `apply_completion_fence` before the projection/upsert in the same transaction. Ownership rows are read with `FOR UPDATE` (`state_backend/postgres_store.py:3963`, `:4004`). However, compaction and digest predicate reads are plain `SELECT`s (`state_backend/postgres_store.py:4034`, `:4047`), and artifact target version is also a plain aggregate read (`:4124`). That is not a full `SELECT ... FOR UPDATE` serialization guarantee for all supplied predicates.

## Residual ArtifactManager-write adjudication

| Caller | Result kind reached | Can it clobber a fenced projection? | Verdict |
|---|---|---:|---|
| `verify_system/llm_evaluator/dialogue_runner.py` prompt-audit transcript | `ArtifactManager.write()` -> `StateBackendArtifactRepository._pg_write()` -> `completion_kind="artifact_envelope_upsert"`, `result_kind="projection_upsert"` (`dialogue_runner.py:408`; `artifact_repository.py:559`, `:593`, `:594`; registry `result_kinds.py:114`) | Yes. It writes `ArtifactClass.PROMPT_AUDIT` (`dialogue_runner.py:400`) to `artifact_envelopes` with `ON CONFLICT ... DO UPDATE` (`artifact_repository.py:625`). The call passes no ownership/compaction/digest snapshot, so same-run epoch/compaction/digest divergence is skipped. | **CRITICAL** |
| `verify_system/llm_evaluator/structured_evaluator.py` prompt-audit response | Same `artifact_envelope_upsert` / `projection_upsert` path (`structured_evaluator.py:753`; `artifact_repository.py:593`, `:594`) | Yes. It writes `ArtifactClass.PROMPT_AUDIT` (`structured_evaluator.py:743`) into the same upsert table/key family and passes no expected predicates. This is production-reachable from the default Layer-2 runner wiring (`verify_system/system.py:2525`, `:2537`). | **CRITICAL** |
| `verify_system/adversarial_orchestrator/runtime/artifact.py::materialize_adversarial_artifact` | Same `artifact_envelope_upsert` / `projection_upsert` path (`runtime/artifact.py:193`; `artifact_repository.py:593`, `:594`) | Yes. It writes `ArtifactClass.QA` at `ADVERSARIAL_STAGE` (`runtime/artifact.py:180`, `:190`) through `ON CONFLICT ... DO UPDATE`, with no expected predicates. It is reachable from `run_adversarial_runtime` (`runtime/runner.py:221`). | **CRITICAL** |

These writes are not `append_only_observation`. `PROMPT_AUDIT` is deliberately not a Verify target, but that does not make its storage append-only: the repository maps every envelope write to the `artifact_envelope_upsert` projection-upsert fence path and updates `artifact_envelopes` on conflict. Therefore the worker's deferral is not acceptable.

## Other regression checks

No evidence of test weakening in the inspected delta; the new tests exercise the stale cases rather than loosening assertions. I did not run the test suite.

No new second source of truth was introduced for the reviewed paths. `result_kinds.py` and `fence_context.py` remain A-core: no `state_backend` or HTTP imports. SQLite remains signature-parity/no-mirror for this fence surface. The added comments are English in the inspected delta, so ARCH-55 is clean here. `append_only_observation` remains legitimately exempt: it short-circuits the fence and is not routed through these projection-upsert paths.

## Findings

### CRITICAL: Production ArtifactManager audit/adversarial writes still skip required attempt-start predicates

The remediation threaded the main VerifySystem envelope sites but left production-reachable `ArtifactManager.write()` callers unthreaded in Layer 2 prompt audit and Layer 3 adversarial runtime. All three reach `artifact_envelope_upsert`, declared as `projection_upsert`, and can execute `ON CONFLICT ... DO UPDATE` on `artifact_envelopes` with `expected_ownership_epoch=None`, `expected_compaction_epoch=None`, and `expected_execution_contract_digest=None`.

Reachable stale path: implementation captures epoch/digest/compaction at attempt start, the QA subflow runs Layer 2 or Layer 3, ownership/compaction/digest changes mid-subflow while `run_id` remains the same, then an unthreaded prompt-audit/adversarial envelope write commits because baseline active ownership still passes and the divergent predicates are skipped. That is the same fail-open class as r2, just on remaining envelope writers.

### CRITICAL: Supplied compaction/digest predicates are not locked with `SELECT ... FOR UPDATE`

`apply_completion_fence` evaluates ownership under row locks, but compaction and execution-contract digest predicates are plain reads. The compaction writer increments via an independent `INSERT ... ON CONFLICT DO UPDATE` path and does not lock the same ownership row. A concurrent compaction/digest change can therefore land after the fence read and before the guarded projection/upsert in the same transaction. This does not satisfy the requested no-TOCTOU property for all supplied predicates.

VERDICT: REJECT
