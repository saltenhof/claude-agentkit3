---
id: formal.architecture-conformance.entities
title: Architecture Conformance Entities
status: active
doc_kind: spec
context: architecture-conformance
spec_kind: entity-set
version: 22
prose_refs:
  - concept/technical-design/01_systemkontext_und_architekturprinzipien.md
  - concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md
---

# Architecture Conformance Entities

Diese Entitaeten beschreiben die maschinell pruefbare Sicht auf
Komponenten, Blutgruppen und stabile Namespace-Grenzen.

Version 2 fuehrt die BC-Hierarchie (Top + Sub) fuer die ersten 4
geschnittenen Bounded Contexts ein. Version 3 ergaenzt BC 5
(exploration-and-design); Version 4 ergaenzt BC 6
(implementation-phase); Version 5 ergaenzt BC 7 (story-closure);
Version 6 ergaenzt BC 8 (artifacts); Version 7 ergaenzt BC 9
(telemetry-and-events).
Version 8 korrigiert BC 9 (telemetry-and-events) — ReadModels umbenannt in ProjectionAccessor.
Version 9 ergaenzt BC 10 (prompt-runtime).
Version 10 ergaenzt BC 11 (agent-skills).
Version 11 ergaenzt BC 12 (installation-and-bootstrap).
Version 12 ergaenzt BC 13 (failure-corpus).
Version 13 ergaenzt BC 14 (execution-planning).
Version 14 ergaenzt BC 15 (requirements-and-scope-coverage).
Version 15 ergaenzt BC 16 (kpi-and-dashboard) -- alle 16 BCs geschnitten.
Version 16 schliesst die Konzeptluecke fuer nicht-fachliche Module:
fuehrt `boundary_modules` und `boundary_module_kinds` als parallele
Top-Level-Konzepte neben `component_groups` ein. Loest die bisherigen
Stub-Eintraege auf — `story`, `hook_runtime`, `phase_state_store`
werden Subs ihrer Owner-BCs (BC 3 / BC 4 / BC 1); `control_plane`,
`projectedge`, `state_backend_drivers` werden boundary_modules. Plus
neuer Sub `verify_system.qa_read_models` (BC 2) und neue
boundary_modules `cli`, `config`, `integrations`, `shared`,
`filesystem`, `state_backend_repository`. Schema_version: 1 -> 2.
Version 17 schliesst Phase E (Mapper-Layer): state_backend_drivers
`may_import_component_groups` von `any` (transitorisch) auf `[]`
gesetzt — Driver importieren keine BC-Records mehr direkt.
Version 18 fuegt BC 17 (project-management) als A-Komponente hinzu —
Owner der Project-Entitaet, des Story-ID-Praefix-Schemas und der
Projekt-Konfiguration. Plus zwei neue Foundation-Boundaries als
adapter_boundary: `concept_catalog` (FK-Doc-Verlinkung,
conceptRefs-Resolver) und `multi_llm_hub` (Adapter zum externen
Multi-LLM-Hub).
Version 19 schneidet die Governance-Hook-Auswertung in einen
harness-neutralen A-Kern (`guard_evaluation`) und eine lokalisierte
Claude-Code-Adapter-Insel (`harness_adapters.claude_code`).
Version 20 erlaubt der Control-Plane-HTTP-Registry, den projektneutralen
Concept-Catalog-Adapter (`/v1/concepts`) zu registrieren.
Version 21 erlaubt der Control-Plane-HTTP-Registry, den projektneutralen
Multi-LLM-Hub-Adapter (`/v1/hub`) zu registrieren.
Version 22 fuegt `boundary.auth` als R-Adapter-Boundary fuer Strategen-
Sessions und projektgebundene Project-API-Tokens hinzu.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.architecture-conformance.entities
schema_version: 2
kind: entity-set
context: architecture-conformance
bloodgroups:
  - id: architecture-conformance.bloodgroup.a_code
    code: A
    meaning: fachliche Komponenten mit Geschaeftsregeln
  - id: architecture-conformance.bloodgroup.r_code
    code: R
    meaning: Repraesentations-Ueberfuehrung zwischen Domaene und Aussen
  - id: architecture-conformance.bloodgroup.t_code
    code: T
    meaning: Bindung an konkrete technische Laufzeit-Umgebung ausserhalb der Kernfachlichkeit
  - id: architecture-conformance.bloodgroup.null_code
    code: "0"
    meaning: Null-Software, domaenen- und projektunabhaengig wiederverwendbar (Volldefinition concept/methodology/software-blutgruppen.md)
boundary_module_kinds:
  - id: architecture-conformance.boundary_kind.entry_boundary
    code: entry_boundary
    meaning: Eingangs-Boundary (CLI, HTTP-Server, Event-Listener) — ruft fachliche Komponenten auf, hat keine Geschaeftslogik. Nichts importiert ein entry_boundary von innen.
  - id: architecture-conformance.boundary_kind.adapter_boundary
    code: adapter_boundary
    meaning: Adapter zu externen Systemen oder Datenquellen (GitHub, ARE, LLM-Pools, VectorDB, MCP, Filesystem-basierte Konzept-Korpora) — uebersetzt zwischen externer Repraesentation und Domaene. Wird von fachlichen BCs genutzt; importiert keine BCs selbst.
  - id: architecture-conformance.boundary_kind.config_foundation
    code: config_foundation
    meaning: Konfigurations-Loader, Schema-Validierung, Defaults. Wird von fachlichen Komponenten gelesen, nie geschrieben. Keine Domain-Logik.
  - id: architecture-conformance.boundary_kind.shared_foundation
    code: shared_foundation
    meaning: Fachneutrale Basistypen, Exceptions, stateless Hilfen. Importiert nichts Fachliches und keine Boundary-Module mit I/O.
  - id: architecture-conformance.boundary_kind.infrastructure_driver
    code: infrastructure_driver
    meaning: Persistenz- und Infrastrukturtreiber (Postgres-/SQLite-Driver, Filesystem-I/O). Wird ausschliesslich von R-Adaptern aufgerufen, nie direkt von A.
  - id: architecture-conformance.boundary_kind.infrastructure_io
    code: infrastructure_io
    meaning: Transport-/Output-Schicht (Filesystem-Writer, Artifact-Exporter). Trennt Builder (A) von Writer (R/T) und verhindert, dass A-BCs Filesystem-I/O direkt importieren.
component_groups:

  # -----------------------------------------------------------------------
  # BC 1: pipeline-framework
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.pipeline_engine
    name: PipelineEngine
    bloodgroup: A
    module_prefixes:
      - agentkit.pipeline_engine
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.phase_state_store
      - architecture-conformance.group.phase_envelope_store
      - architecture-conformance.group.compaction_resilience
      - architecture-conformance.group.flow_orchestrator
      - architecture-conformance.group.pipeline_registry
      - architecture-conformance.group.phase_executor

  - id: architecture-conformance.group.phase_state_store
    name: PhaseStateStore
    bloodgroup: A
    module_prefixes:
      - agentkit.pipeline_engine.phase_state_store
    parent_group_id: architecture-conformance.group.pipeline_engine
    exposure: sub_exposed
    component_kind: domain
    # Schema-Owner laut Phase A Row 33 fuer FlowExecution, PhaseState,
    # OverrideRecord, NodeExecutionLedger und phase_state_projection.
    # Persistenz erfolgt via boundary.state_backend_repository; das
    # Schema selbst lebt hier.

  - id: architecture-conformance.group.flow_orchestrator
    name: FlowOrchestrator
    bloodgroup: A
    module_prefixes:
      - agentkit.pipeline_engine.flow_orchestrator
    parent_group_id: architecture-conformance.group.pipeline_engine
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.phase_executor
    name: PhaseExecutor
    bloodgroup: A
    module_prefixes:
      - agentkit.pipeline_engine.phase_executor
    parent_group_id: architecture-conformance.group.pipeline_engine
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.phase_envelope_store
    name: PhaseEnvelopeStore
    bloodgroup: A
    module_prefixes:
      - agentkit.pipeline_engine.phase_envelope_store
    parent_group_id: architecture-conformance.group.pipeline_engine
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.pipeline_registry
    name: PipelineRegistry
    bloodgroup: A
    module_prefixes:
      - agentkit.pipeline_engine.pipeline_registry
    parent_group_id: architecture-conformance.group.pipeline_engine
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.compaction_resilience
    name: CompactionResilience
    bloodgroup: A
    module_prefixes:
      - agentkit.pipeline_engine.compaction_resilience
    parent_group_id: architecture-conformance.group.pipeline_engine
    exposure: sub_exposed
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 2: verify-system
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.verify_system
    name: VerifySystem
    bloodgroup: A
    module_prefixes:
      - agentkit.verify_system
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.stage_registry
      - architecture-conformance.group.qa_read_models
      - architecture-conformance.group.evidence_assembler
      - architecture-conformance.group.llm_evaluator
      - architecture-conformance.group.conformance_service
      - architecture-conformance.group.adversarial_orchestrator
      - architecture-conformance.group.policy_engine
      - architecture-conformance.group.qa_cycle_coordinator

  - id: architecture-conformance.group.qa_read_models
    name: QaReadModels
    bloodgroup: A
    module_prefixes:
      - agentkit.verify_system.qa_read_models
    parent_group_id: architecture-conformance.group.verify_system
    exposure: sub_exposed
    component_kind: domain
    # Schema-Owner fuer QA-Read-Models (qa_stage_results, qa_findings).
    # Persistenz erfolgt via boundary.state_backend_repository; die
    # Pydantic-Schemas leben hier.

  - id: architecture-conformance.group.stage_registry
    name: StageRegistry
    bloodgroup: A
    module_prefixes:
      - agentkit.verify_system.stage_registry
    parent_group_id: architecture-conformance.group.verify_system
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.llm_evaluator
    name: LlmEvaluator
    bloodgroup: A
    module_prefixes:
      - agentkit.verify_system.llm_evaluator
    parent_group_id: architecture-conformance.group.verify_system
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.conformance_service
    name: ConformanceService
    bloodgroup: A
    module_prefixes:
      - agentkit.verify_system.conformance_service
    parent_group_id: architecture-conformance.group.verify_system
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.evidence_assembler
    name: EvidenceAssembler
    bloodgroup: A
    module_prefixes:
      - agentkit.verify_system.evidence_assembler
    parent_group_id: architecture-conformance.group.verify_system
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.adversarial_orchestrator
    name: AdversarialOrchestrator
    bloodgroup: A
    module_prefixes:
      - agentkit.verify_system.adversarial_orchestrator
    parent_group_id: architecture-conformance.group.verify_system
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.policy_engine
    name: PolicyEngine
    bloodgroup: A
    module_prefixes:
      - agentkit.verify_system.policy_engine
    parent_group_id: architecture-conformance.group.verify_system
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.qa_cycle_coordinator
    name: QaCycleCoordinator
    bloodgroup: A
    module_prefixes:
      - agentkit.verify_system.qa_cycle_coordinator
    parent_group_id: architecture-conformance.group.verify_system
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 3: story-lifecycle
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.story_context_manager
    name: StoryContextManager
    bloodgroup: A
    module_prefixes:
      - agentkit.story_context_manager
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.story_types
      - architecture-conformance.group.story_identity
      - architecture-conformance.group.story_storage_backend
      - architecture-conformance.group.operating_mode_resolver
      - architecture-conformance.group.story_contract_matrix
      - architecture-conformance.group.story_creation_flow
      - architecture-conformance.group.story_administration

  - id: architecture-conformance.group.story_types
    name: StoryTypes
    bloodgroup: A
    module_prefixes:
      - agentkit.story_context_manager.story_types
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: sub_exposed
    component_kind: domain
    # Story-Domaenentypen (frueher unter agentkit.story als Stub-Top
    # gefuehrt). Code-Pfad-Migration nach agentkit.story_context_manager.
    # story_types erfolgt im Code-Refactor-Schritt.

  - id: architecture-conformance.group.story_identity
    name: StoryIdentity
    bloodgroup: A
    module_prefixes:
      - agentkit.story_context_manager.story_identity
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.story_creation_flow
    name: StoryCreationFlow
    bloodgroup: A
    module_prefixes:
      - agentkit.story_context_manager.story_creation_flow
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.story_contract_matrix
    name: StoryContractMatrix
    bloodgroup: A
    module_prefixes:
      - agentkit.story_context_manager.story_contract_matrix
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.story_administration
    name: StoryAdministration
    bloodgroup: A
    module_prefixes:
      - agentkit.story_context_manager.story_administration
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.operating_mode_resolver
    name: OperatingModeResolver
    bloodgroup: A
    module_prefixes:
      - agentkit.story_context_manager.operating_mode_resolver
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.story_storage_backend
    name: StoryStorageBackend
    bloodgroup: A
    module_prefixes:
      - agentkit.story_context_manager.story_storage_backend
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 4: governance-and-guards
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.governance
    name: Governance
    bloodgroup: A
    module_prefixes:
      - agentkit.governance
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.principal_capability
      - architecture-conformance.group.escalation_mechanism
      - architecture-conformance.group.guard_system
      - architecture-conformance.group.hook_runtime
      - architecture-conformance.group.harness_adapters_claude_code
      - architecture-conformance.group.ccag_permission_runtime
      - architecture-conformance.group.integrity_gate
      - architecture-conformance.group.governance_observer
      - architecture-conformance.group.setup_preflight_gate

  - id: architecture-conformance.group.guard_system
    name: GuardSystem
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.guard_system
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.hook_runtime
    name: GuardEvaluation
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.guard_evaluation
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain
    # Harness-neutraler A-Kern fuer GuardSystem. Die historische
    # HookRuntime-ID bleibt stabil, der Python-Kompatibilitaetspfad
    # `agentkit.governance.hookruntime` gehoert zur Adapter-Insel.

  - id: architecture-conformance.group.harness_adapters_claude_code
    name: HarnessAdaptersClaudeCode
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.harness_adapters.claude_code
      - agentkit.governance.hookruntime
    parent_group_id: architecture-conformance.group.governance
    exposure: internal
    component_kind: domain
    # Lokalisierte Claude-Code-Mediation: Tool-Namen, Hook-Payload und
    # Exit-Code-Vertrag bleiben hier und werden auf HookEvent gemappt.

  - id: architecture-conformance.group.ccag_permission_runtime
    name: CcagPermissionRuntime
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.ccag_permission_runtime
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.governance_observer
    name: GovernanceObserver
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.governance_observer
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.integrity_gate
    name: IntegrityGate
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.integrity_gate
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.principal_capability
    name: PrincipalCapability
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.principal_capability
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.setup_preflight_gate
    name: SetupPreflightGate
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.setup_preflight_gate
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.escalation_mechanism
    name: EscalationMechanism
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.escalation_mechanism
    parent_group_id: architecture-conformance.group.governance
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 5: exploration-and-design
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.exploration
    name: Exploration
    bloodgroup: A
    module_prefixes:
      - agentkit.exploration
    parent_group_id: null
    exposure: top
    top_surface_modules: []   # leer initial; wird mit konkreten Module-FQN gefuellt sobald Code-Refactor laeuft
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.exploration_mode_router
      - architecture-conformance.group.exploration_drafting
      - architecture-conformance.group.exploration_mandate_classification
      - architecture-conformance.group.exploration_review

  - id: architecture-conformance.group.exploration_mode_router
    name: ModeRouter
    bloodgroup: A
    module_prefixes:
      - agentkit.exploration.mode_router
    parent_group_id: architecture-conformance.group.exploration
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.exploration_drafting
    name: ExplorationDrafting
    bloodgroup: A
    module_prefixes:
      - agentkit.exploration.drafting
    parent_group_id: architecture-conformance.group.exploration
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.exploration_review
    name: ExplorationReview
    bloodgroup: A
    module_prefixes:
      - agentkit.exploration.review
    parent_group_id: architecture-conformance.group.exploration
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.exploration_mandate_classification
    name: MandateClassification
    bloodgroup: A
    module_prefixes:
      - agentkit.exploration.mandate_classification
    parent_group_id: architecture-conformance.group.exploration
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 6: implementation-phase
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.implementation
    name: Implementation
    bloodgroup: A
    module_prefixes:
      - agentkit.implementation
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.implementation_handover_packager
      - architecture-conformance.group.implementation_worker_session
      - architecture-conformance.group.implementation_worker_health
      - architecture-conformance.group.implementation_worker_loop

  - id: architecture-conformance.group.implementation_worker_session
    name: WorkerSession
    bloodgroup: A
    module_prefixes:
      - agentkit.implementation.worker_session
    parent_group_id: architecture-conformance.group.implementation
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.implementation_worker_loop
    name: WorkerLoop
    bloodgroup: A
    module_prefixes:
      - agentkit.implementation.worker_loop
    parent_group_id: architecture-conformance.group.implementation
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.implementation_handover_packager
    name: HandoverPackager
    bloodgroup: A
    module_prefixes:
      - agentkit.implementation.handover_packager
    parent_group_id: architecture-conformance.group.implementation
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.implementation_worker_health
    name: WorkerHealthMonitor
    bloodgroup: A
    module_prefixes:
      - agentkit.implementation.worker_health
    parent_group_id: architecture-conformance.group.implementation
    exposure: sub_exposed
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 7: story-closure
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.closure
    name: Closure
    bloodgroup: A
    module_prefixes:
      - agentkit.closure
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.closure_gates
      - architecture-conformance.group.closure_merge_sequence
      - architecture-conformance.group.closure_post_merge_finalization
      - architecture-conformance.group.closure_execution_report

  - id: architecture-conformance.group.closure_gates
    name: ClosureGates
    bloodgroup: A
    module_prefixes:
      - agentkit.closure.gates
    parent_group_id: architecture-conformance.group.closure
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.closure_merge_sequence
    name: MergeSequence
    bloodgroup: A
    module_prefixes:
      - agentkit.closure.merge_sequence
    parent_group_id: architecture-conformance.group.closure
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.closure_post_merge_finalization
    name: PostMergeFinalization
    bloodgroup: A
    module_prefixes:
      - agentkit.closure.post_merge_finalization
    parent_group_id: architecture-conformance.group.closure
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.closure_execution_report
    name: ExecutionReport
    bloodgroup: A
    module_prefixes:
      - agentkit.closure.execution_report
    parent_group_id: architecture-conformance.group.closure
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 8: artifacts
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.artifacts
    name: Artifacts
    bloodgroup: A
    module_prefixes:
      - agentkit.artifacts
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.artifacts_producer_registry

  - id: architecture-conformance.group.artifacts_producer_registry
    name: ProducerRegistry
    bloodgroup: A
    module_prefixes:
      - agentkit.artifacts.producer_registry
    parent_group_id: architecture-conformance.group.artifacts
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 9: telemetry-and-events
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.telemetry
    name: Telemetry
    bloodgroup: A
    module_prefixes:
      - agentkit.telemetry
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.telemetry_hooks
      - architecture-conformance.group.telemetry_projection_accessor
      - architecture-conformance.group.telemetry_contract

  - id: architecture-conformance.group.telemetry_hooks
    name: TelemetryHooks
    bloodgroup: A
    module_prefixes:
      - agentkit.telemetry.hooks
    parent_group_id: architecture-conformance.group.telemetry
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.telemetry_projection_accessor
    name: ProjectionAccessor
    bloodgroup: A
    module_prefixes:
      - agentkit.telemetry.projection_accessor
    parent_group_id: architecture-conformance.group.telemetry
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.telemetry_contract
    name: TelemetryContract
    bloodgroup: A
    module_prefixes:
      - agentkit.telemetry.contract
    parent_group_id: architecture-conformance.group.telemetry
    exposure: sub_exposed
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 10: prompt-runtime
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.prompt_runtime
    name: PromptRuntime
    bloodgroup: A
    module_prefixes:
      - agentkit.prompt_runtime
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.prompt_runtime_bundle_store
      - architecture-conformance.group.prompt_runtime_bundle_pinning
      - architecture-conformance.group.prompt_runtime_materialization

  - id: architecture-conformance.group.prompt_runtime_bundle_store
    name: BundleStore
    bloodgroup: A
    module_prefixes:
      - agentkit.prompt_runtime.bundle_store
    parent_group_id: architecture-conformance.group.prompt_runtime
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.prompt_runtime_bundle_pinning
    name: BundlePinning
    bloodgroup: A
    module_prefixes:
      - agentkit.prompt_runtime.bundle_pinning
    parent_group_id: architecture-conformance.group.prompt_runtime
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.prompt_runtime_materialization
    name: Materialization
    bloodgroup: A
    module_prefixes:
      - agentkit.prompt_runtime.materialization
    parent_group_id: architecture-conformance.group.prompt_runtime
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 11: agent-skills
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.skills
    name: Skills
    bloodgroup: A
    module_prefixes:
      - agentkit.skills
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.skills_bundle_store
      - architecture-conformance.group.skills_binding
      - architecture-conformance.group.skills_quality_metric

  - id: architecture-conformance.group.skills_bundle_store
    name: SkillBundleStore
    bloodgroup: A
    module_prefixes:
      - agentkit.skills.bundle_store
    parent_group_id: architecture-conformance.group.skills
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.skills_binding
    name: SkillBinding
    bloodgroup: A
    module_prefixes:
      - agentkit.skills.binding
    parent_group_id: architecture-conformance.group.skills
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.skills_quality_metric
    name: SkillQualityMetric
    bloodgroup: A
    module_prefixes:
      - agentkit.skills.quality_metric
    parent_group_id: architecture-conformance.group.skills
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 12: installation-and-bootstrap
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.installer
    name: Installer
    bloodgroup: A
    module_prefixes:
      - agentkit.installer
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.installer_checkpoint_engine
      - architecture-conformance.group.installer_bootstrap_checkpoints
      - architecture-conformance.group.installer_integration_checkpoints
      - architecture-conformance.group.installer_upgrade

  - id: architecture-conformance.group.installer_checkpoint_engine
    name: CheckpointEngine
    bloodgroup: A
    module_prefixes:
      - agentkit.installer.checkpoint_engine
    parent_group_id: architecture-conformance.group.installer
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.installer_bootstrap_checkpoints
    name: BootstrapCheckpoints
    bloodgroup: A
    module_prefixes:
      - agentkit.installer.bootstrap_checkpoints
    parent_group_id: architecture-conformance.group.installer
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.installer_integration_checkpoints
    name: IntegrationCheckpoints
    bloodgroup: A
    module_prefixes:
      - agentkit.installer.integration_checkpoints
    parent_group_id: architecture-conformance.group.installer
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.installer_upgrade
    name: Upgrade
    bloodgroup: A
    module_prefixes:
      - agentkit.installer.upgrade
    parent_group_id: architecture-conformance.group.installer
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 13: failure-corpus
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.failure_corpus
    name: FailureCorpus
    bloodgroup: A
    module_prefixes:
      - agentkit.failure_corpus
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.failure_corpus_incident_triage
      - architecture-conformance.group.failure_corpus_pattern_promotion
      - architecture-conformance.group.failure_corpus_check_factory

  - id: architecture-conformance.group.failure_corpus_incident_triage
    name: IncidentTriage
    bloodgroup: A
    module_prefixes:
      - agentkit.failure_corpus.incident_triage
    parent_group_id: architecture-conformance.group.failure_corpus
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.failure_corpus_pattern_promotion
    name: PatternPromotion
    bloodgroup: A
    module_prefixes:
      - agentkit.failure_corpus.pattern_promotion
    parent_group_id: architecture-conformance.group.failure_corpus
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.failure_corpus_check_factory
    name: CheckFactory
    bloodgroup: A
    module_prefixes:
      - agentkit.failure_corpus.check_factory
    parent_group_id: architecture-conformance.group.failure_corpus
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 14: execution-planning
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.execution_planning
    name: ExecutionPlanning
    bloodgroup: A
    module_prefixes:
      - agentkit.execution_planning
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.execution_planning_planning_model
      - architecture-conformance.group.execution_planning_proposal_ingest
      - architecture-conformance.group.execution_planning_readiness_assessment
      - architecture-conformance.group.execution_planning_scheduling_policy
      - architecture-conformance.group.execution_planning_plan_derivation

  - id: architecture-conformance.group.execution_planning_planning_model
    name: PlanningModel
    bloodgroup: A
    module_prefixes:
      - agentkit.execution_planning.planning_model
    parent_group_id: architecture-conformance.group.execution_planning
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.execution_planning_proposal_ingest
    name: ProposalIngest
    bloodgroup: A
    module_prefixes:
      - agentkit.execution_planning.proposal_ingest
    parent_group_id: architecture-conformance.group.execution_planning
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.execution_planning_readiness_assessment
    name: ReadinessAssessment
    bloodgroup: A
    module_prefixes:
      - agentkit.execution_planning.readiness_assessment
    parent_group_id: architecture-conformance.group.execution_planning
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.execution_planning_scheduling_policy
    name: SchedulingPolicy
    bloodgroup: A
    module_prefixes:
      - agentkit.execution_planning.scheduling_policy
    parent_group_id: architecture-conformance.group.execution_planning
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.execution_planning_plan_derivation
    name: PlanDerivation
    bloodgroup: A
    module_prefixes:
      - agentkit.execution_planning.plan_derivation
    parent_group_id: architecture-conformance.group.execution_planning
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 15: requirements-and-scope-coverage
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.requirements_coverage
    name: RequirementsCoverage
    bloodgroup: A
    module_prefixes:
      - agentkit.requirements_coverage
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.requirements_coverage_are_client
      - architecture-conformance.group.requirements_coverage_scope_mapping
      - architecture-conformance.group.requirements_coverage_are_integration

  - id: architecture-conformance.group.requirements_coverage_are_client
    name: AreClient
    bloodgroup: R
    module_prefixes:
      - agentkit.requirements_coverage.are_client
    parent_group_id: architecture-conformance.group.requirements_coverage
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.requirements_coverage_scope_mapping
    name: ScopeMapping
    bloodgroup: A
    module_prefixes:
      - agentkit.requirements_coverage.scope_mapping
    parent_group_id: architecture-conformance.group.requirements_coverage
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.requirements_coverage_are_integration
    name: AreIntegration
    bloodgroup: A
    module_prefixes:
      - agentkit.requirements_coverage.are_integration
    parent_group_id: architecture-conformance.group.requirements_coverage
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 16: kpi-and-dashboard
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.kpi_analytics
    name: KpiAnalytics
    bloodgroup: A
    module_prefixes:
      - agentkit.kpi_analytics
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.kpi_analytics_catalog
      - architecture-conformance.group.kpi_analytics_fact_store
      - architecture-conformance.group.kpi_analytics_aggregation
      - architecture-conformance.group.kpi_analytics_dashboard
      - architecture-conformance.group.kpi_analytics_design_system

  - id: architecture-conformance.group.kpi_analytics_catalog
    name: KpiCatalog
    bloodgroup: A
    module_prefixes:
      - agentkit.kpi_analytics.catalog
    parent_group_id: architecture-conformance.group.kpi_analytics
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.kpi_analytics_fact_store
    name: FactStore
    bloodgroup: A
    module_prefixes:
      - agentkit.kpi_analytics.fact_store
    parent_group_id: architecture-conformance.group.kpi_analytics
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.kpi_analytics_aggregation
    name: Aggregation
    bloodgroup: A
    module_prefixes:
      - agentkit.kpi_analytics.aggregation
    parent_group_id: architecture-conformance.group.kpi_analytics
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.kpi_analytics_dashboard
    name: Dashboard
    bloodgroup: A
    module_prefixes:
      - agentkit.kpi_analytics.dashboard
    parent_group_id: architecture-conformance.group.kpi_analytics
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.kpi_analytics_design_system
    name: DesignSystem
    bloodgroup: A
    module_prefixes:
      - agentkit.kpi_analytics.design_system
    parent_group_id: architecture-conformance.group.kpi_analytics
    exposure: internal
    component_kind: domain

  # -----------------------------------------------------------------------
  # BC 17: project-management
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.project_management
    name: ProjectManagement
    bloodgroup: A
    module_prefixes:
      - agentkit.project_management
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    # Owner der Project-Entitaet, des Story-ID-Praefix-Schemas und der
    # projektbezogenen Konfiguration. Wird von allen anderen BCs als
    # Quelle des Projekt-Kontextes konsumiert (project_key bleibt
    # Cross-Cutting-Filter im control_plane_http; project_management
    # besitzt das Konzept). Story-Counter pro Projekt liegt nicht hier,
    # sondern im story_context_manager.

  # -----------------------------------------------------------------------
  # Shared: WorktreeManager (owner: story-lifecycle, cross-BC)
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.worktree_manager
    name: WorktreeManager
    bloodgroup: A
    module_prefixes:
      - agentkit.worktree_manager
    parent_group_id: null
    exposure: top
    component_kind: shared
    owner_group_id: architecture-conformance.group.story_context_manager
    allowed_importers:
      - architecture-conformance.group.pipeline_engine
      - architecture-conformance.group.story_context_manager
    exported_symbols:
      - agentkit.worktree_manager.WorktreeManager.create
      - agentkit.worktree_manager.WorktreeManager.merge
      - agentkit.worktree_manager.WorktreeManager.cleanup
      - agentkit.worktree_manager.WorktreeManager.exists
    allowed_imported_symbols:
      - pathlib.Path
      - os.PathLike

boundary_modules:

  # -----------------------------------------------------------------------
  # Eingangs-Boundaries (entry_boundary): rufen fachliche BCs auf,
  # haben keine Geschaeftslogik. Nichts importiert sie von innen.
  # -----------------------------------------------------------------------

  - id: architecture-conformance.boundary.cli
    name: CommandLineInterface
    bloodgroup: R
    boundary_kind: entry_boundary
    module_prefixes:
      - agentkit.cli
    importable_by: []
    may_import_component_groups: any
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.integrations
      - architecture-conformance.boundary.control_plane_http
      - architecture-conformance.boundary.control_plane_records
      - architecture-conformance.boundary.control_plane_runtime

  - id: architecture-conformance.boundary.control_plane_http
    name: ControlPlaneHttp
    bloodgroup: R
    boundary_kind: entry_boundary
    module_prefixes:
      - agentkit.control_plane.http
    importable_by:
      - architecture-conformance.boundary.cli
    may_import_component_groups: any
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.control_plane_records
      - architecture-conformance.boundary.control_plane_runtime
      - architecture-conformance.boundary.state_backend_repository
      - architecture-conformance.boundary.filesystem
      - architecture-conformance.boundary.concept_catalog
      - architecture-conformance.boundary.multi_llm_hub
      - architecture-conformance.boundary.auth
    # HTTP-Transport-Schicht. Nimmt Requests entgegen, ruft fachliche
    # Komponenten und Runtime-Service. Boot-Punkt durch CLI.

  - id: architecture-conformance.boundary.control_plane_records
    name: ControlPlaneRecords
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.control_plane.models
      - agentkit.control_plane.records
    importable_by: any
    may_import_component_groups:
      - architecture-conformance.group.telemetry
      - architecture-conformance.group.telemetry_contract
    may_import_boundary_modules:
      - architecture-conformance.boundary.shared
    # Pydantic-Modelle und Persistenz-Records der Control-Plane.
    # Datentypen mit Cross-BC-Refs (z.B. Telemetry-Event-Typen). Da
    # nicht "rein-fachneutral", als adapter_boundary modelliert
    # statt shared_foundation.

  - id: architecture-conformance.boundary.control_plane_runtime
    name: ControlPlaneRuntime
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.control_plane.runtime
      - agentkit.control_plane.repository
      - agentkit.control_plane.telemetry
    importable_by: any
    may_import_component_groups: any
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.control_plane_records
      - architecture-conformance.boundary.state_backend_repository
      - architecture-conformance.boundary.filesystem
    # Runtime-Service, Repository und Telemetrie der Control-Plane.
    # Adapter-Schicht zwischen HTTP und fachlichen Komponenten.

  # -----------------------------------------------------------------------
  # Adapter-Boundaries (adapter_boundary): duenne Wrapper ueber externe
  # APIs. Werden von BCs aufgerufen; importieren keine BCs.
  # -----------------------------------------------------------------------

  - id: architecture-conformance.boundary.integrations
    name: Integrations
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.integrations
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.shared

  - id: architecture-conformance.boundary.projectedge
    name: ProjectEdge
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.projectedge
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.control_plane_records

  - id: architecture-conformance.boundary.concept_catalog
    name: ConceptCatalog
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.concept_catalog
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.filesystem
    # Foundation-Bereich parallel zu BCs. Adaptiert das Filesystem
    # (concept/-Markdown-Korpus) zu fachlichen Lese-Repraesentationen:
    # ConceptRef-Resolver, Markdown-Index, Cross-Reference-Graph,
    # Backlinks. Wird von governance, requirements_coverage,
    # story_context_manager und vom Frontend (Concept-Browser)
    # konsumiert. Kein A-BC, weil keine fachlichen Invarianten -
    # reine Resolver-/Index-Logik.

  - id: architecture-conformance.boundary.multi_llm_hub
    name: MultiLlmHub
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.multi_llm_hub
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.integrations
    # Adapter zum externen Multi-LLM-Hub (Pflicht-Dependency, nicht
    # AK3-Code). Liefert Sessions, Backend-Metriken und proxy-iert
    # Send-Operationen ans Hub-Frontend. Kein A-BC, weil AK3 das
    # Hub-Konzept nicht fachlich besitzt - Routing-Policies, falls
    # noetig, leben in prompt_runtime, nicht hier.

  - id: architecture-conformance.boundary.auth
    name: Auth
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.auth
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.state_backend_repository
    # Aeussere API-Auth-Schicht fuer UI-BFF und Project-API:
    # Strategen-Cookie-Sessions, CSRF und projektgebundene Thin-Client-
    # Tokens. Kein A-BC, keine Rollen-/Quota- oder fachliche Policy-Logik.

  - id: architecture-conformance.boundary.state_backend_repository
    name: StateBackendRepository
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.state_backend.store
    importable_by: any
    may_import_component_groups: any
    may_import_boundary_modules:
      - architecture-conformance.boundary.state_backend_drivers
      - architecture-conformance.boundary.state_persistence_scope
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.control_plane_records
      - architecture-conformance.boundary.filesystem
      - architecture-conformance.boundary.auth
    # Anti-Korruptions-Schicht zwischen BCs und Drivers. Implementiert
    # die fachlichen Repository-Schnittstellen, die in den jeweiligen
    # BCs definiert sind. Darf BC-Records lesen, um sie auf Driver-DTOs
    # zu mappen. Mappers leben hier, nicht in den BC-Records selbst.
    # Nutzt Filesystem-Pfad-Konstanten (LAYER_ARTIFACT_FILES) um
    # Artefakt-Dateinamen pro Layer zu bestimmen.

  - id: architecture-conformance.boundary.state_persistence_scope
    name: StatePersistenceScope
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.state_backend.scope
    importable_by: any
    may_import_component_groups: any
    may_import_boundary_modules:
      - architecture-conformance.boundary.shared
    # Cross-BC-Persistenz-Identitaet (StateScope, RuntimeStateScope).
    # Aggregiert IDs aus mehreren BCs (project_key, story_id, run_id,
    # flow_id, attempt_no). Wird von Drivers, Repository und fachlichen
    # BCs konsumiert.

  # -----------------------------------------------------------------------
  # Konfigurations-Foundation (config_foundation): wird gelesen, nie
  # geschrieben. Keine Domain-Logik.
  # -----------------------------------------------------------------------

  - id: architecture-conformance.boundary.config
    name: Config
    bloodgroup: R
    boundary_kind: config_foundation
    module_prefixes:
      - agentkit.config
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.shared

  # -----------------------------------------------------------------------
  # Shared-Foundation (shared_foundation): fachneutrale Basistypen,
  # Exceptions, stateless Hilfen. Importiert nichts.
  # -----------------------------------------------------------------------

  - id: architecture-conformance.boundary.shared
    name: Shared
    bloodgroup: "0"
    boundary_kind: shared_foundation
    module_prefixes:
      - agentkit.shared
      - agentkit.exceptions
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules: []
    # Bluttyp 0 (Null-Software): fachneutrale Basistypen, Exceptions,
    # stateless Helfer. Importiert nichts AK3-Spezifisches; kann in
    # jedes andere Python-Projekt kopiert werden, ohne Domaenenwissen
    # mitzunehmen. Volldefinition concept/methodology/software-blutgruppen.md.

  # -----------------------------------------------------------------------
  # Infrastructure-IO (infrastructure_io): Filesystem-Writer und
  # Artifact-Exporter. Trennt Builder (A) von Writer (R/T).
  # -----------------------------------------------------------------------

  - id: architecture-conformance.boundary.filesystem
    name: Filesystem
    bloodgroup: R
    boundary_kind: infrastructure_io
    module_prefixes:
      - agentkit.boundary.filesystem
      - agentkit.state_backend.paths
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.shared
    # Atomic-Write-Helpers (atomic_write_json) und Artifact-Writer.
    # BC-Builder produzieren JSON-serialisierbare Strukturen; das
    # Schreiben passiert hier. Verhindert, dass A-BCs Filesystem-I/O
    # direkt importieren.
    #
    # `agentkit.state_backend.paths` haelt Filesystem-Pfad-Konstanten
    # (STATE_DB_DIR/STATE_DB_FILE/LAYER_ARTIFACT_FILES/...) und
    # gehoert konzeptionell hierher; physisch unter state_backend/
    # bis Phase E den Pfad konsolidiert.

  # -----------------------------------------------------------------------
  # Infrastructure-Driver (infrastructure_driver): T-Bluttyp.
  # Persistenz-Treiber. Werden ausschliesslich von R-Adaptern
  # aufgerufen, nie direkt von A.
  # -----------------------------------------------------------------------

  - id: architecture-conformance.boundary.state_backend_drivers
    name: StateBackendDrivers
    bloodgroup: T
    boundary_kind: infrastructure_driver
    module_prefixes:
      - agentkit.state_backend.postgres_store
      - agentkit.state_backend.sqlite_store
      - agentkit.state_backend.config
    importable_by:
      - architecture-conformance.boundary.state_backend_repository
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.filesystem
      - architecture-conformance.boundary.control_plane_records
      - architecture-conformance.boundary.state_persistence_scope
    # Postgres- und SQLite-Driver. config.py haelt StateBackendKind +
    # load_state_backend_config (Driver-Schicht-Konfig). paths.py
    # haelt Filesystem-Pfade (STATE_DB_DIR/STATE_DB_FILE).
    #
    # Driver importieren keine BC-Records mehr direkt; Mapping erfolgt
    # in store.mappers (boundary.state_backend_repository). Die Driver
    # erhalten und liefern ausschliesslich dict[str, Any]-Zeilen.
```
<!-- FORMAL-SPEC:END -->
