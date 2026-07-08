# Persistence BC Rearchitecture Design

Status: FROZEN target design. This document is the implementation contract for the phased migration of `agentkit.backend.state_backend.store` into BC-aligned persistence components plus shared infrastructure.

Authority inputs: `CLAUDE.md`, component-architecture skill, `domain-registry.yaml` with 19 BCs, `META-DEC-2026-07-08-OPERATION-LEDGER`, `META-DEC-2026-07-02-SESSION-OWNERSHIP`, `bc-cut-decisions.md`, FK-69 §69.4, FK-91 §91.1a, FK-17, FK-15, FK-56, FK-30, DK-00 §1a, FK-01 §1.1a, and the current store facade and sqlite/postgres drivers.

The current facade inventory is 148 exported symbols: 135 names from `PUBLIC_API_NAMES` plus 13 facade-only exports. Every symbol below is assigned to exactly one target component.

## Part 1 - Component List

- StoryLifecycleStore - persists story context, session/run binding, run-ownership records, and ownership-transfer handoff records for the story-lifecycle BC.
  - Provided interface: `save_story_context`, `save_story_context_global`, `load_story_context`, `load_story_context_global`, `load_story_context_by_story_number_global`, `load_story_context_by_uuid_global`, `load_story_contexts_global`, `read_story_context_record`, `save_session_run_binding_global`, `load_session_run_binding_global`, `delete_session_run_binding_global`, `insert_run_ownership_record_global`, `load_run_ownership_record_global`, `load_active_run_ownership_record_global`, `save_takeover_transfer_record_global`, `load_takeover_transfer_record_global`, `backend_has_valid_context`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: story-context local paths keep SQLite parity for tests; global session/run ownership and takeover records are Postgres-only and fail closed off Postgres. D1 is baked in: run-ownership record storage is here, not governance and not ledger.

- PipelineRuntimeStore - persists canonical pipeline runtime records: phase state, phase snapshots, attempts, flow executions, node ledgers, override records, runtime scope, and runtime residue cleanup.
  - Provided interface: `save_phase_state`, `load_phase_state`, `load_phase_state_global`, `read_phase_state_record`, `save_phase_snapshot`, `load_phase_snapshot`, `read_phase_snapshot_record`, `save_attempt`, `load_attempts`, `save_flow_execution`, `load_flow_execution`, `load_flow_execution_global`, `save_node_execution_ledger`, `load_node_execution_ledger`, `save_override_record`, `load_override_records`, `resolve_runtime_scope`, `backend_has_valid_phase_state`, `backend_has_completed_snapshot`, `purge_flow_executions`, `purge_node_execution_ledgers`, `purge_attempts`, `purge_override_records`, `purge_phase_states`, `purge_phase_snapshots`, `count_runtime_execution_residue`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: canonical runtime records keep existing SQLite local support and Postgres global support. `phase_state_projection` table access is explicitly not here; see the Runtime-Record vs Projection-Table table below.

- GovernanceRuntimeStore - persists governance runtime locks and owns ownership-fence enforcement/evaluation helpers, without operation-ledger, object-claim, or backend-instance identity storage.
  - Provided interface: `save_story_execution_lock_global`, `load_story_execution_lock_global`, `purge_guard_decisions`, `resolve_ownership_fence_snapshot`, `OwnershipFenceScope`, `bind_ownership_fence_scope`, `require_ownership_fence_scope`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: lock and guard-decision persistence follows existing backend support; ownership-fence enforcement is fail-closed on Postgres and inert only where the existing SQLite test path deliberately lacks fences. D1 is baked in: fence helpers are here; run-ownership record storage is not.

- HarnessEdgeCommandStore - persists Project Edge command queue records and delivery/ack state for the harness-integration BC.
  - Provided interface: `insert_edge_command_record_global`, `commission_edge_command_record_global`, `load_edge_command_record_global`, `list_and_ack_open_edge_command_records_global`, `supersede_open_edge_command_global`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: edge command queue remains Postgres-only and fail-closed off Postgres.

- StoryClosureStore - persists closure reports and code-backend push freshness/barrier/degradation state for story-closure.
  - Provided interface: `record_closure_report`, `upsert_push_freshness_record_global`, `load_push_freshness_record_global`, `list_push_freshness_records_global`, `upsert_push_barrier_verdict_global`, `load_push_barrier_verdict_global`, `list_push_barrier_verdicts_global`, `upsert_ref_protection_degradation_finding_global`, `list_ref_protection_degradation_findings_global`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: closure report keeps existing backend behavior; push freshness/barrier/degradation records are Postgres-only. D5 is baked in: `story_metrics` table access is not here, only its schema/writer semantics remain with story-closure.

- VerifyArtifactStore - persists verify decisions and QA/layer artifact write surfaces, and provides verify/structural predicates for verify-system.
  - Provided interface: `record_layer_artifacts`, `record_verify_decision`, `load_latest_verify_decision`, `load_latest_verify_decision_for_scope`, `read_latest_verify_decision_record`, `find_latest_qa_envelope`, `backend_has_structural_artifact`, `backend_has_structural_artifact_for_scope`, `backend_verify_decision_passed`, `backend_verify_decision_passed_for_scope`, `purge_decision_records`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: verify decisions and QA artifacts keep existing dual-backend behavior where present; Postgres writes must honor ownership-fence checks. D5 is baked in: `qa_stage_results` and `qa_findings` table access is not here. FK-69 projection writes are coordinated above the store through `Telemetry.write_projection`, not through a VerifyArtifactStore -> TelemetryEventStore import.

- ArtifactCatalogStore - persists and reads generic artifact envelope/catalog records for the artifacts BC.
  - Provided interface: `load_artifact_record`, `load_artifact_record_for_scope`, `read_artifact_record`, `purge_run_bound_artifact_envelopes`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: artifact envelopes retain existing SQLite/Postgres parity, with Postgres write paths using the bound governance ownership fence.

- TelemetryEventStore - persists execution events and owns the ProjectionAccessor DB access layer for FK-69 analytics projection tables.
  - Provided interface: `append_execution_event`, `append_execution_event_global`, `load_execution_events`, `load_execution_events_global`, `load_execution_events_for_project_global`, `load_last_adjudication_ts`, `purge_execution_events`, `upsert_story_metrics`, `load_story_metrics`, `load_story_metrics_for_scope`, `load_latest_story_metrics_global`, `load_qa_stage_results`, `load_qa_stage_results_for_scope`, `load_qa_findings`, `load_qa_findings_for_scope`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: execution events retain existing dual-backend support; analytics projections are exposed through `Telemetry.write_projection` / `Telemetry.read_projection` and the ProjectionAccessor layer. D5 is baked in: `qa_stage_results`, `qa_findings`, `story_metrics`, and `phase_state_projection` DB access lives here.

- ProjectStore - persists project-management entities and Project-API auth tokens.
  - Provided interface: `save_project`, `load_project`, `load_projects`, `load_project_by_story_id_prefix`, `save_project_api_token`, `load_project_api_token`, `load_project_api_token_by_hash`, `load_project_api_tokens_for_project`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: project records keep existing backend behavior. D4 is baked in: all four facade-only auth-token helpers are here and must preserve FK-15 bearer-token opacity, hash lookup, revocation semantics, and project scope.

- ExecutionPlanningStore - persists execution-planning dependencies and parallelization configuration.
  - Provided interface: `save_story_dependency`, `load_story_dependencies`, `load_story_dependency_rows_for_story`, `delete_story_dependency`, `load_parallelization_config`, `save_parallelization_config`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: keep existing local/global behavior; no dependency on pipeline runtime storage.

- RequirementsCoverageStore - persists story-to-ARE requirement coverage links.
  - Provided interface: `save_story_are_link`, `load_story_are_links`, `update_story_are_link_kind`, `delete_story_are_link`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: keep existing backend behavior and fail closed on malformed link transitions.

- PromptRuntimeStore - persists prompt-runtime execution contract digests and prompt-audit lookup state.
  - Provided interface: `insert_execution_contract_digest_global`, `load_execution_contract_digest_global`, `find_prompt_audit_output_hashes`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`.
  - sqlite/postgres note: execution contract digest is Postgres-only and fail-closed off Postgres; prompt-audit reads retain existing envelope backend support without a PromptRuntimeStore -> ArtifactCatalogStore import. D4 is baked in: `find_prompt_audit_output_hashes` is prompt-runtime, not verify or generic artifact catalog.

- StateBackendConnectionManager - owns backend selection, backend capability checks, connection lifecycle, and Core-singleton backend instance identity.
  - Provided interface: `active_backend_is_sqlite`, `control_plane_backend_available`, `save_backend_instance_identity_global`, `load_backend_instance_identity_global`, `boot_backend_instance_identity_global`.
  - Required interfaces: none.
  - sqlite/postgres note: backend identity is Postgres-only and fail-closed off Postgres. D3 is baked in: backend instance identity is Core-singleton topology infrastructure, not a BC and not the ledger.

- PersistenceJsonCodec - owns JSON-safe persistence record typing and JSON load/dump boundary helpers.
  - Provided interface: `JsonRecord`, `load_json_safe`, `dump_json`, `load_json`, `cast_json_record`.
  - Required interfaces: `StateBackendConnectionManager` only for file/backend selection where needed.
  - sqlite/postgres note: backend-neutral utility; no domain ownership.

- PersistenceTestSupport - owns test-only backend cache/schema reset support.
  - Provided interface: `reset_backend_cache_for_tests`.
  - Required interfaces: `StateBackendConnectionManager`.
  - sqlite/postgres note: test-only support for switching active backends and clearing schema bootstrap caches.

- ControlPlaneOperationLedger - shared T-infrastructure for FK-91 §91.1a control-plane operation idempotency, operation ledger state, repair/admin-abort transactions, and object-mutation claims.
  - Provided interface: `save_control_plane_operation_global`, `claim_control_plane_operation_global`, `finalize_control_plane_operation_global`, `claim_inflight_operation_row_global`, `load_inflight_operation_row_global`, `finalize_inflight_operation_row_global`, `finalize_control_plane_start_phase_global`, `commit_control_plane_operation_with_side_effects_global`, `commit_edge_command_result_global`, `release_control_plane_operation_global`, `list_orphaned_claimed_control_plane_operations_global`, `finalize_orphaned_control_plane_operation_global`, `admin_abort_control_plane_operation_global`, `resolve_repair_control_plane_operation_global`, `has_engine_writes_since_control_plane_claim_global`, `has_open_repair_control_plane_operation_for_story_global`, `has_committed_control_plane_operation_for_run_global`, `has_committed_story_exit_operation_for_run_global`, `delete_control_plane_operation_global`, `load_control_plane_operation_global`, `insert_object_mutation_claim_global`, `load_object_mutation_claim_global`, `acquire_object_mutation_claim_global`, `delete_object_mutation_claim_global`, `list_orphaned_object_mutation_claims_global`.
  - Required interfaces: `StateBackendConnectionManager`, `PersistenceJsonCodec`, backend instance identity from `StateBackendConnectionManager`, read-only run-ownership fence data from the state backend without importing `StoryLifecycleStore`.
  - sqlite/postgres note: ledger and object-mutation claims are Postgres-only and fail-closed off Postgres. D2 is baked in: this is the fourth shared-infrastructure component, module prefix `agentkit.backend.state_backend.operation_ledger`, blood group T, not a BC and not governance. Its only consumer is control-plane dispatch; domain BC stores do not import it. Governance decides who may admin-abort; the ledger owns how the abort transacts.

### Facade-Only Export Audit

These 13 exports exist in `facade.py` but not in `PUBLIC_API_NAMES`; they are in scope and assigned above:

| Facade-only export | Target component |
|---|---|
| `JsonRecord` | `PersistenceJsonCodec` |
| `active_backend_is_sqlite` | `StateBackendConnectionManager` |
| `claim_inflight_operation_row_global` | `ControlPlaneOperationLedger` |
| `load_inflight_operation_row_global` | `ControlPlaneOperationLedger` |
| `finalize_inflight_operation_row_global` | `ControlPlaneOperationLedger` |
| `OwnershipFenceScope` | `GovernanceRuntimeStore` |
| `find_latest_qa_envelope` | `VerifyArtifactStore` |
| `find_prompt_audit_output_hashes` | `PromptRuntimeStore` |
| `load_last_adjudication_ts` | `TelemetryEventStore` |
| `save_project_api_token` | `ProjectStore` |
| `load_project_api_token` | `ProjectStore` |
| `load_project_api_token_by_hash` | `ProjectStore` |
| `load_project_api_tokens_for_project` | `ProjectStore` |

### Runtime-Record vs Projection-Table Cut

| Table / record family | Runtime record owner | Projection table DB-access owner | Schema owner | Facade functions in this contract | Corrected distinction |
|---|---|---|---|---|---|
| `qa_stage_results` | none; analytics projection, not canonical QA runtime state | `TelemetryEventStore` / ProjectionAccessor | verify-system `StageRegistry` / `QAStageResultRecord` | `load_qa_stage_results`, `load_qa_stage_results_for_scope` | Verify writes QA artifacts and schema-typed records via `Telemetry.write_projection`; it does not own table access. |
| `qa_findings` | none; analytics projection, not canonical QA runtime state | `TelemetryEventStore` / ProjectionAccessor | verify-system `StageRegistry` / `QAFindingRecord` | `load_qa_findings`, `load_qa_findings_for_scope` | Verify owns finding schemas and producers; Telemetry owns DB reads/writes. |
| `story_metrics` | none; analytics projection, not closure report runtime state | `TelemetryEventStore` / ProjectionAccessor | story-closure `PostMergeFinalization` / `StoryMetricsRecord` | `upsert_story_metrics`, `load_story_metrics`, `load_story_metrics_for_scope`, `load_latest_story_metrics_global` | StoryClosure owns metric semantics and schema, but loses table access; persistence goes through Telemetry. |
| `phase_state_projection` | `PipelineRuntimeStore` owns canonical `phase_states`, `phase_snapshots`, `attempts`, `flow_executions`, `node_execution_ledgers`, `override_records` | `TelemetryEventStore` / ProjectionAccessor | pipeline-framework `PhaseExecutor` | no public facade function today; existing projection repository access moves under Telemetry | Runtime records stay with PipelineRuntimeStore; analytics projection table access is Telemetry. |

## Part 2 - Dependency Summary

Top-level dependency rule: per-BC stores depend only on shared infrastructure; there are no store-to-store imports. Cross-BC reads required by concepts are implemented either through the owning BC's domain surface above the persistence layer or by neutral read-only row access at composition time, never by importing another store.

```
StoryLifecycleStore        -> StateBackendConnectionManager, PersistenceJsonCodec
PipelineRuntimeStore       -> StateBackendConnectionManager, PersistenceJsonCodec
GovernanceRuntimeStore     -> StateBackendConnectionManager, PersistenceJsonCodec
HarnessEdgeCommandStore    -> StateBackendConnectionManager, PersistenceJsonCodec
StoryClosureStore          -> StateBackendConnectionManager, PersistenceJsonCodec
VerifyArtifactStore        -> StateBackendConnectionManager, PersistenceJsonCodec
ArtifactCatalogStore       -> StateBackendConnectionManager, PersistenceJsonCodec
TelemetryEventStore        -> StateBackendConnectionManager, PersistenceJsonCodec
ProjectStore               -> StateBackendConnectionManager, PersistenceJsonCodec
ExecutionPlanningStore     -> StateBackendConnectionManager, PersistenceJsonCodec
RequirementsCoverageStore  -> StateBackendConnectionManager, PersistenceJsonCodec
PromptRuntimeStore         -> StateBackendConnectionManager, PersistenceJsonCodec
ControlPlaneOperationLedger -> StateBackendConnectionManager, PersistenceJsonCodec
PersistenceTestSupport     -> StateBackendConnectionManager
PersistenceJsonCodec       -> StateBackendConnectionManager
StateBackendConnectionManager -> none
```

ARCH-03 acyclicity constraints:

- No per-BC store imports another per-BC store.
- No per-BC store imports `ControlPlaneOperationLedger`.
- `ControlPlaneOperationLedger` is consumed only by control-plane dispatch, an R-facade. It may perform FK-91 transaction mechanics and FK-17 read-only checks against the state backend, but it is not a domain store dependency.
- `StateBackendConnectionManager`, `PersistenceJsonCodec`, and `PersistenceTestSupport` remain shared infrastructure. `ControlPlaneOperationLedger` is the fourth shared-infrastructure component from `META-DEC-2026-07-08-OPERATION-LEDGER`.
- Domain BCs keep schema and semantic ownership where FK-69 requires it, while Telemetry owns projection table access.

## Part 3 - Red Flags and Open Questions

- PASS: D1, D2, D3, D4, and D5 remove the previous ambiguous ownership. The target cut has no intentional deferred facade export.
- PASS: `GovernanceRuntimeStore` now excludes operation-ledger functions, object-mutation claims, and backend-instance identity.
- PASS: `ControlPlaneOperationLedger` is not a BC, not governance, and not imported by domain stores.
- PASS: `StateBackendConnectionManager` owns backend instance identity as Core-singleton topology infrastructure.
- PASS: FK-69 §69.4 is corrected: projection DB access for `qa_stage_results`, `qa_findings`, `story_metrics`, and `phase_state_projection` is Telemetry-owned.
- WARNING: `commit_edge_command_result_global` is a cross-table transaction. The target owner is `ControlPlaneOperationLedger` because it commits a claimed operation ledger row and must preserve FK-91 CAS/idempotency semantics; `HarnessEdgeCommandStore` still owns command CRUD and delivery state. During implementation, keep this as one ledger transaction and do not introduce a Harness->Ledger store import.

## Phased Migration Plan

1. Small shared-infra extraction:
   - Extract `StateBackendConnectionManager`, `PersistenceJsonCodec`, and `PersistenceTestSupport`.
   - Move `active_backend_is_sqlite`, `control_plane_backend_available`, backend selection, JSON load helpers, test reset support, and backend instance identity.
   - Keep a thin static compat shim in `state_backend.store` that re-exports exact symbols only.

2. Small/medium low-coupling BC stores:
   - Extract `ProjectStore`, `RequirementsCoverageStore`, `ExecutionPlanningStore`, and `PromptRuntimeStore`.
   - Repoint project/auth-token consumers first because FK-15 token semantics must remain opaque and hash-based.
   - Repoint ARE link and planning dependency callers next.

3. Artifact and Telemetry split:
   - Extract `ArtifactCatalogStore`, `VerifyArtifactStore`, and `TelemetryEventStore`.
   - Move FK-69 projection repositories and ProjectionAccessor under Telemetry.
   - Change Verify and Closure writers to call `Telemetry.write_projection` for QA rows and story metrics; keep schema classes in their owner BCs.
   - Preserve `find_prompt_audit_output_hashes` under PromptRuntimeStore.

4. Closure and harness edge:
   - Extract `StoryClosureStore` for closure report and push freshness/barrier/degradation state.
   - Extract `HarnessEdgeCommandStore` for edge command queue CRUD/delivery.
   - Leave `commit_edge_command_result_global` with the ledger transaction owner.

5. Runtime and story lifecycle:
   - Extract `PipelineRuntimeStore` for canonical runtime records and residue purges.
   - Extract `StoryLifecycleStore` for story contexts, session-run bindings, run-ownership records, and takeover transfer records.
   - Ensure runtime record code never owns `phase_state_projection` table access.

6. Governance and ledger last:
   - Extract `GovernanceRuntimeStore` fence helpers and lock/guard persistence after lifecycle storage exists.
   - Extract `ControlPlaneOperationLedger` last under `agentkit.backend.state_backend.operation_ledger`.
   - Repoint control-plane dispatch as the only ledger consumer.
   - Delete old mixed `_facade_control_plane_*` ownership from the compat layer once all callers are repointed.

Compat-shim policy:

- The shim is temporary, static, and transparent: explicit imports and explicit `__all__`, no dynamic reflection.
- The shim may re-export from the new components only; it may not contain persistence logic.
- The shim is deleted at the end of migration. No `.pyi` shadowing is allowed; type surfaces live in implementation modules or honest static re-export modules.

Consumer repoint groups:

- Facade-call files: treat the roughly 50 current facade-call files as the first repoint group, ordered by component extraction above.
- Direct store imports: treat the roughly 183 direct `state_backend.store.*` imports as the second group, split by owner component and moved after the target module exists.
- Tests are migrated with their owning production consumers; test-only imports of `reset_backend_cache_for_tests` move to `PersistenceTestSupport`.

Scanner and size compliance:

- Every new module must stay at or below 1200 file lines.
- Every module must stay at or below 100 module-top-level lines through honest static re-exports only.
- Every class must stay at or below 800 lines.
- No metric gaming: no dynamic export installation, no reflection-based facade, no artificial `.pyi` shadow interfaces, no dead wrapper layers, no module split that hides one responsibility under many names.

Gate policy:

- Each phase must keep Jenkins and Sonar green.
- Concept-changing implementation phases must also keep `scripts/ci/check_concept_frontmatter.py` and `scripts/ci/compile_formal_specs.py` green.
- The repository must never be left with a red gate.
