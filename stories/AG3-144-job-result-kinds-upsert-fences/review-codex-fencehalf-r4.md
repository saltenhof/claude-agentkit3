# AG3-144 FENCE-HALF Remediation Review r4

Reviewed delta `9ed59291..57eb5956` (whole fence-half context `6446aa8f..57eb5956`) against the production code. I did not edit production code.

## Structural-Enforcement Confirmation

The remediation tightens the immediate artifact boundary, but it does **not** make a `projection_upsert` envelope write impossible without a real attempt-start fence snapshot.

Confirmed improvements:

- `ArtifactManager.write(...)` now requires keyword-only `expected_ownership_epoch`, `expected_compaction_epoch`, and `expected_execution_contract_digest` with no defaults (`src/agentkit/backend/artifacts/manager.py:53`).
- `ArtifactRepository.write_envelope(...)` and `StateBackendArtifactRepository.write_envelope(...)` also require those keyword-only arguments with no defaults (`src/agentkit/backend/artifacts/repository.py:42`, `src/agentkit/backend/state_backend/store/artifact_repository.py:430`).
- Postgres artifact-envelope writes resolve `artifact_envelope_upsert`, apply `apply_completion_fence(...)`, and only then execute the `artifact_envelopes ON CONFLICT ... DO UPDATE` (`src/agentkit/backend/state_backend/store/artifact_repository.py:562`, `:591`, `:628`).
- Missing `story_contexts`/project-key resolution fails closed with `StaleCompletionFencedError`, not a permissive bypass (`src/agentkit/backend/state_backend/store/artifact_repository.py:572`).

But the boundary still accepts explicit `None` and many wrapper APIs still default these predicates to `None` (`PromptRuntime.materialize_prompt`, `persist_prompt_audit`, `VerifyContextBundle`, evaluator/materializer constructors). Explicit `None` is still a predicate skip in `apply_completion_fence`; it is not a hard runtime failure and not a real snapshot. Therefore the structural property requested in r4 is not met.

### Independent `ArtifactManager.write(...)` Caller Enumeration

Repo grep found these production `ArtifactManager.write(...)` call sites under `src/agentkit/backend`:

| Caller | Reaches `artifact_envelope_upsert` / `projection_upsert`? | Fence context assessment |
|---|---:|---|
| `verify_system/system.py:847` (`_write_layer_envelope`) | Yes | PASS for the normal implementation QA path. `ImplementationPhaseHandler.on_enter` captures `attempt_start_fence = capture_fence_context(...)` before `run_qa_subflow` and threads it through `VerifyContextBundle`; the write uses `ctx.expected_*`. |
| `verify_system/system.py:901` (`_write_policy_artifact`) | Yes | PASS for the normal implementation QA path; same `VerifyContextBundle` attempt-start snapshot. |
| `verify_system/system.py:973` (`_run_context_sufficiency_pre_step`) | Yes | PASS for the normal implementation QA path; same `VerifyContextBundle` attempt-start snapshot. |
| `verify_system/adversarial_orchestrator/spawn.py:314` | Yes | PASS for the normal implementation QA path. `VerifySystem` passes `ctx.expected_*` into the adversarial spawner. |
| `verify_system/adversarial_orchestrator/runtime/artifact.py:209` | Yes | PASS only when reached through `AdversarialChallenger.evaluate(...)`, because `VerifySystem._execute_layer` narrows to `AdversarialChallenger` and passes `ctx.expected_*`; the runtime helper itself still defaults to `None`, but the current src production caller threads the QA attempt snapshot. |
| `verify_system/llm_evaluator/structured_evaluator.py:776` | Yes | PASS for the default `VerifySystem`-built Layer-2 runner: `_resolve_layer2_runner` constructs a fresh `PromptRuntimeMaterializer` and `StructuredEvaluator` with `ctx.expected_*`. Not structurally guaranteed for injected `system.layer2_runner`, which bypasses `_resolve_layer2_runner`. |
| `verify_system/llm_evaluator/dialogue_runner.py:436` | Yes when called with an `ArtifactManager`, `story_id`, and `run_id` | No src caller found, but the method defaults all predicates to `None`; if used productively with an artifact manager it still reaches the projection upsert without a real snapshot. This is no longer an r3 hot path in current grep, but the boundary remains fail-open by construction. |
| `prompt_runtime/audit.py:214` (`persist_prompt_audit`) | Yes | **CRITICAL**. This wrapper defaults all expected predicates to `None`, and multiple production paths call through it without a snapshot. |
| `exploration/drafting/persistence.py:124` | Yes | **CRITICAL**. Production-wired by `build_exploration_phase_handler` / `_build_exploration_drafting`; it writes the ENTWURF envelope with explicit `None` predicates and comments that the exploration phase has no fence capture. That is a reachable projection upsert, not an append-only/exempt write. |
| `exploration/review/persistence.py:144` | Yes | **CRITICAL**. Production-wired by `build_exploration_review`; it writes exploration review QA artifacts with explicit `None` predicates and comments that the gap is an open PO question. Not append-only/exempt. |
| `requirements_coverage/top.py:353` | Yes | **CRITICAL**. Production-wired by setup and the Layer-1 ARE provider. `load_context(...)` writes with the real `run_id` and explicit `None` predicates; `check_gate(...)` writes with a synthetic run id. Neither path carries a genuine attempt-start snapshot or is classified `append_only_observation`. |
| `implementation/handover/packager.py:219` | Yes if invoked | No src production caller found; the method itself explicitly passes `None` and documents the missing capture point. If wired later as-is, it is a projection-upsert hole. |
| `verify_system/artifacts.py:155` (`write_layer_artifacts`) | Yes if invoked | No src production caller found; legacy helper explicitly passes `None`, while the real VerifySystem path uses `_write_layer_envelope` + state-backend batch. |
| `verify_system/artifacts.py:203` (`write_verify_decision_artifact`) | Yes if invoked | No src production caller found; legacy helper explicitly passes `None`, while the real VerifySystem path uses `_write_policy_artifact` + `record_verify_decision`. |

Additional transitive production gaps through `prompt_runtime/audit.py:214`:

- `implementation/worker_session/session.py:208` calls `PromptRuntime.materialize_prompt(...)` without any expected predicates. This is the worker-spawn prompt-audit path and can write a `PROMPT_AUDIT` envelope with `None` predicates.
- `state_backend/store/exploration_worker_runner.py:110` drives that worker-session prompt materialization during exploration drafting.
- `bootstrap/composition_root.py:699` builds exploration `PromptRuntimeMaterializer` without expected predicates, so exploration review prompt-audit envelopes can also write with `None`.
- `closure/runtime_ports.py:324` builds feedback-fidelity prompt materialization without expected predicates.

These are not fabricated `FenceContext` instances; they are worse: no real attempt-start context is captured or threaded. The code explicitly documents several of them as “open PO question” / “documents the gap” (`exploration/drafting/persistence.py:118-123`, `exploration/review/persistence.py:139-143`, `requirements_coverage/top.py:343-352`, `implementation/handover/packager.py:211-218`). That is not convergence under ZERO DEBT.

## CRITICAL-B Confirmation

Partially improved, not closed.

Confirmed:

- The compaction predicate read now uses `SELECT epoch FROM compaction_epochs ... FOR UPDATE` (`src/agentkit/backend/state_backend/postgres_store.py:4062`).
- The incrementer touches the same `(project_key, story_id)` row via `INSERT INTO compaction_epochs ... ON CONFLICT (project_key, story_id) DO UPDATE SET epoch = compaction_epochs.epoch + 1 RETURNING epoch` (`src/agentkit/backend/state_backend/store/compaction_epoch_repository.py:130`).
- For an existing `compaction_epochs` row, the predicate read and incrementer serialize.
- The digest predicate is acceptably lock-free: `execution_contract_digests` is inserted with a plain primary-key `INSERT` and no `ON CONFLICT`; repo grep found no production `UPDATE` or `DELETE` against that table (`src/agentkit/backend/state_backend/postgres_store.py:2784`, `:2800`). That supports AG3-143 read-only-after-insert semantics.

Remaining CRITICAL:

- The compaction serialization still has the genesis-row TOCTOU. `capture_fence_context(...)` reads absent compaction rows as epoch `0` (`src/agentkit/backend/state_backend/store/facade.py:2140` via `StateBackendCompactionEpochRepository.read_epoch`, which defaults absence to `0`). Later, `apply_completion_fence(...)` checks `expected_compaction_epoch=0` with `SELECT ... FOR UPDATE`, but if no row exists yet, it locks nothing. A concurrent first-ever compaction `INSERT ... ON CONFLICT` can still land after the fence read and before the guarded projection write commits. The code itself documents this as residual and open (`src/agentkit/backend/state_backend/postgres_store.py:4049-4059`).

The r4 criterion says “NO remaining TOCTOU for any SUPPLIED predicate.” A supplied compaction predicate with value `0` still has a TOCTOU window. CRITICAL-B is therefore not closed.

## Regression Checks

Previously fixed paths remain improved, subject to the residual gaps above:

- QA-layer batch: `ImplementationPhaseHandler.on_enter` captures attempt-start fence context before QA and passes it to `ProjectionAccessor.record_qa_layer_artifacts(...)`; the facade raises `StaleCompletionFencedError` on a stale batch, which stops follow-on side effects.
- Verify decision: same captured snapshot is passed to `record_verify_decision(...)` before check-outcome emission and before `save_story_context`.
- Closure report: `ClosurePhaseHandler` captures `capture_fence_context(...)` at closure sequence start and passes it through `write_execution_report(...)` / `record_closure_report(...)`.
- VerifySystem artifact-envelope sites: the three main QA envelopes and adversarial spawner/runtime path now thread the QA attempt snapshot on the normal implementation path.
- Single-row QA stage/finding repositories apply the completion fence before their Postgres upserts.
- Business-boundary stale behavior remains fail-closed: `record_layer_artifacts`, `record_verify_decision`, and `record_closure_report` raise `StaleCompletionFencedError`, and implementation comments/order show no check-outcome, verify-decision continuation, or story-context save after a stale batch/decision.
- Missing active ownership still fails closed in `_evaluate_fence_predicates(...)`.
- `append_only_observation` remains legitimately exempt: `apply_completion_fence(...)` short-circuits it before baseline predicates.
- SQLite remains no-mirror for this fence behavior; the SQLite backend deletes the expected predicate arguments and does not attempt to emulate the Postgres fence.
- `result_kinds.py` and `fence_context.py` remain A-core in substance: no operational state-backend/HTTP imports were introduced in those files.
- I did not find test weakening in the reviewed delta; new tests appear to add stale-path coverage rather than loosen assertions. I did not run the full test suite or remote gates for this review-only task.

Regression caveats:

- The delta introduces reachable “open PO question” comments on the exact fence surface. That is a ZERO DEBT violation and a direct indication of incomplete remediation.
- The `FenceContext` model still defaults expected predicates to `None`; production implementation/closure code compensates by capturing and threading real values, but the type alone does not prevent an empty/default context.
- `VerifyContextBundle` also defaults the expected predicates to `None`. The current implementation-phase caller populates it, but the public VerifySystem API is still not impossible-by-construction for other callers.

## Completeness Grep

Relevant upsert sweep:

- `artifact_envelopes`: Postgres `ON CONFLICT ... DO UPDATE` is fenced in `StateBackendArtifactRepository._pg_write`, but production callers still reach it with explicit/default `None` predicates as listed above. This is the main completeness failure.
- `qa_stage_results`: batch path is fenced by `persist_layer_artifact_rows(...)`; single-row repository path calls `apply_completion_fence(...)` before `pg_execute_stage_upsert(...)`.
- `qa_findings`: batch path is fenced with the QA-layer batch; single-row repository path calls `apply_completion_fence(...)` before `pg_execute_finding_upsert(...)`.
- `decision_records`: `persist_verify_decision_row(...)` applies the steering fence before the `decision_records ON CONFLICT ... DO UPDATE`.
- `closure_report`: closure writes are steering-fenced before the projection file is written. I found no closure-table `ON CONFLICT ... DO UPDATE` in the reviewed production code; the closure report is a fenced projection-file write.
- `qa_check_outcomes` still has an unfenced `ON CONFLICT ... DO UPDATE`, but it is deliberately ordered after fenced QA-layer and verify-decision commits in the implementation path and is outside the table list requested for completeness. It remains a side-effect-ordering dependency, not an independent approval basis here.

## Findings

### CRITICAL: Production artifact-envelope projection upserts still commit without genuine attempt-start snapshots

The structural change prevents accidental omission at the immediate `ArtifactManager.write(...)` boundary, but it does not prevent explicit/default `None` predicate skips. Several production-reachable paths now merely document the absence of a fence context and still write through `artifact_envelope_upsert`:

- Exploration drafting ENTWURF envelope (`exploration/drafting/persistence.py:124`), production-wired by `build_exploration_phase_handler`.
- Exploration review QA envelopes (`exploration/review/persistence.py:144`), production-wired by `build_exploration_review`.
- Requirements coverage audit envelopes (`requirements_coverage/top.py:353`), production-wired by setup and Layer-1 ARE provider.
- Prompt-runtime audit envelopes (`prompt_runtime/audit.py:214`) reached by worker-session prompt materialization (`implementation/worker_session/session.py:208`) and exploration/closure prompt materializers built without snapshots.

All of these reach the same Postgres `artifact_envelopes ON CONFLICT ... DO UPDATE` guarded by `artifact_envelope_upsert`, declared as `projection_upsert`. Passing `expected_ownership_epoch=None`, `expected_compaction_epoch=None`, and `expected_execution_contract_digest=None` skips the required attempt-start predicates. These writes are not reclassified as `append_only_observation` and are not explicitly exempt at the result-kind registry level. This is still fail-open for same-run ownership epoch, compaction epoch, and digest divergence.

### CRITICAL: Compaction predicate serialization still fails for the first compaction row

The new `FOR UPDATE` locks an existing `compaction_epochs` row, but the common initial state is “no row means epoch 0.” In that state, the predicate read locks no row, while the incrementer can concurrently insert the first row and advance the epoch before the guarded projection upsert commits. A supplied `expected_compaction_epoch=0` can therefore be invalidated after the predicate read. This is a remaining TOCTOU for a supplied predicate.

### ERROR: The remediation leaves documented open gaps on reachable safety-critical paths

The code comments explicitly state “open PO question” / “documents the gap” on exploration, requirements coverage, handover, and compaction genesis-row handling. For this fence-half convergence review, those comments are not harmless documentation; they identify reachable or soon-to-be-reachable fail-closed gaps in the safety boundary.

VERDICT: REJECT
