---
id: formal.architecture-conformance.entities
title: Architecture Conformance Entities
status: active
doc_kind: spec
context: architecture-conformance
spec_kind: entity-set
version: 29
prose_refs:
  - concept/technical-design/01_systemkontext_und_architekturprinzipien.md
  - concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md
---

# Architecture Conformance Entities

Diese Entitaeten beschreiben die maschinell pruefbare Sicht auf
Komponenten, Blutgruppen und stabile Namespace-Grenzen.

Komponenten sind zweistufig modelliert: fachliche Top-Bounded-Contexts
mit ihren Sub-Komponenten (`component_groups`). Nicht-fachliche Module —
Entry-Boundaries, Adapter, Foundations und Infrastruktur-Treiber — werden
als `boundary_modules` parallel zu den `component_groups` gefuehrt und
ueber `boundary_module_kinds` klassifiziert.

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
  - id: architecture-conformance.boundary_kind.domain_core_foundation
    code: domain_core_foundation
    meaning: Domaenen-Kern-Foundation (Bluttyp A) — fachliche Kerntypen (Story, Severity, ArtifactClass, QaContext, OperatingMode), die mehrere Bounded Contexts gleichzeitig brauchen. Anders als shared_foundation NICHT fachneutral (Bluttyp 0), sondern traegt Domaenenwissen; aber wie shared_foundation ein importierbares Blattmodul ohne I/O, das nichts AK3-Spezifisches importiert (nur stdlib/pydantic). Von jedem importierbar.
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
      - agentkit.backend.pipeline_engine
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
      - agentkit.backend.pipeline_engine.phase_state_store
    parent_group_id: architecture-conformance.group.pipeline_engine
    exposure: sub_exposed
    component_kind: domain
    # Schema-Owner fuer FlowExecution, PhaseState,
    # OverrideRecord, NodeExecutionLedger und phase_state_projection.
    # Persistenz erfolgt via boundary.state_backend_repository; das
    # Schema selbst lebt hier.

  - id: architecture-conformance.group.flow_orchestrator
    name: FlowOrchestrator
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.pipeline_engine.flow_orchestrator
    parent_group_id: architecture-conformance.group.pipeline_engine
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.phase_executor
    name: PhaseExecutor
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.pipeline_engine.phase_executor
    parent_group_id: architecture-conformance.group.pipeline_engine
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.phase_envelope_store
    name: PhaseEnvelopeStore
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.pipeline_engine.phase_envelope_store
    parent_group_id: architecture-conformance.group.pipeline_engine
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.pipeline_registry
    name: PipelineRegistry
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.pipeline_engine.pipeline_registry
    parent_group_id: architecture-conformance.group.pipeline_engine
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.compaction_resilience
    name: CompactionResilience
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.pipeline_engine.compaction_resilience
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
      - agentkit.backend.verify_system
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
      - architecture-conformance.group.sonarqube_gate
      - architecture-conformance.group.pre_merge_runner
      - architecture-conformance.group.policy_engine
      - architecture-conformance.group.qa_cycle_coordinator

  - id: architecture-conformance.group.qa_read_models
    name: QaReadModels
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.verify_system.qa_read_models
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
      - agentkit.backend.verify_system.stage_registry
    parent_group_id: architecture-conformance.group.verify_system
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.sonarqube_gate
    name: SonarqubeGate
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.verify_system.sonarqube_gate
    parent_group_id: architecture-conformance.group.verify_system
    exposure: sub_exposed
    component_kind: domain
    # SonarQube-Green-Gate capability (FK-33 §33.6). sub_exposed
    # so the three lifecycle gate points (QA-subflow here; Setup-green-main
    # FK-22 / Closure Dim 9 FK-29/FK-35 as consumers) can call the
    # capability API. Sequenced after adversarial_orchestrator and before
    # policy_engine in intra_bc_layer_order (FK-33 §33.8.3). The external
    # SonarQube HTTP boundary lives in the integrations adapter, not here.

  - id: architecture-conformance.group.pre_merge_runner
    name: PreMergeRunner
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.verify_system.pre_merge_runner
    parent_group_id: architecture-conformance.group.verify_system
    exposure: sub_exposed
    component_kind: domain
    # Pre-Merge-Verification-Runner capability (FK-29 §29.1a.3 /
    # FK-33 §33.6.3). Owns the PreMergeScanPort/BuildTestPort contract the
    # Closure pre-merge barrier consumes; sub_exposed so the
    # cross-BC closure consumer can call it (dependency direction
    # closure -> verify_system.pre_merge_runner, never the reverse).
    # Sequenced AFTER sonarqube_gate (it consumes the sonarqube_gate attestation /
    # green definition) and before policy_engine. The external Jenkins/Sonar
    # HTTP boundary lives in the integrations adapters, not here.

  - id: architecture-conformance.group.llm_evaluator
    name: LlmEvaluator
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.verify_system.llm_evaluator
    parent_group_id: architecture-conformance.group.verify_system
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.conformance_service
    name: ConformanceService
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.verify_system.conformance_service
    parent_group_id: architecture-conformance.group.verify_system
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.evidence_assembler
    name: EvidenceAssembler
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.verify_system.evidence_assembler
    parent_group_id: architecture-conformance.group.verify_system
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.adversarial_orchestrator
    name: AdversarialOrchestrator
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.verify_system.adversarial_orchestrator
    parent_group_id: architecture-conformance.group.verify_system
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.policy_engine
    name: PolicyEngine
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.verify_system.policy_engine
    parent_group_id: architecture-conformance.group.verify_system
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.qa_cycle_coordinator
    name: QaCycleCoordinator
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.verify_system.qa_cycle_coordinator
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
      - agentkit.backend.story_context_manager
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
      - agentkit.backend.story_context_manager.story_types
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: sub_exposed
    component_kind: domain
    # Story-Domaenentypen (Kerntypen des Bounded Context story-lifecycle).

  - id: architecture-conformance.group.story_identity
    name: StoryIdentity
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.story_context_manager.story_identity
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.story_creation_flow
    name: StoryCreationFlow
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.story_context_manager.story_creation_flow
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.story_contract_matrix
    name: StoryContractMatrix
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.story_context_manager.story_contract_matrix
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.story_administration
    name: StoryAdministration
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.story_context_manager.story_administration
    parent_group_id: architecture-conformance.group.story_context_manager
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.operating_mode_resolver
    name: OperatingModeResolver
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.story_context_manager.operating_mode_resolver
    parent_group_id: architecture-conformance.group.story_context_manager
    # sub_exposed: the named operating-mode resolution owner is
    # consumed cross-BC by governance-and-guards (guard_evaluation + the
    # integrity-gate mode guard, FK-56 §56.7a/§56.10). It carries the SSOT mode
    # seam, so it is exposed as a sub-surface like the other consumed
    # story_context_manager sub-components (StoryTypes/StoryIdentity/...).
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.story_storage_backend
    name: StoryStorageBackend
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.story_context_manager.story_storage_backend
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
      - agentkit.backend.governance
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    intra_bc_layer_order:
      - architecture-conformance.group.escalation_mechanism
      - architecture-conformance.group.guard_system
      - architecture-conformance.group.hook_runtime
      - architecture-conformance.group.principal_capability
      - architecture-conformance.group.harness_adapters_claude_code
      - architecture-conformance.group.harness_adapters_codex
      - architecture-conformance.group.ccag_permission_runtime
      - architecture-conformance.group.integrity_gate
      - architecture-conformance.group.governance_observer
      - architecture-conformance.group.setup_preflight_gate

  - id: architecture-conformance.group.guard_system
    name: GuardSystem
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.governance.guard_system
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.hook_runtime
    name: GuardEvaluation
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.governance.guard_evaluation
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain
    # Harness-neutraler A-Kern fuer GuardSystem. Die Gruppen-ID
    # `hook_runtime` adressiert diesen A-Kern; der Python-Kompatibilitaetspfad
    # `agentkit.backend.governance.hookruntime` gehoert zur Adapter-Insel.

  - id: architecture-conformance.group.harness_adapters_claude_code
    name: HarnessAdaptersClaudeCode
    bloodgroup: A
    module_prefixes:
      - agentkit.harness_client.harness_adapters.claude_code
      - agentkit.backend.governance.hookruntime
    parent_group_id: architecture-conformance.group.governance
    exposure: internal
    component_kind: domain
    # Lokalisierte Claude-Code-Mediation: Tool-Namen, Hook-Payload und
    # Exit-Code-Vertrag bleiben hier und werden auf HookEvent gemappt.
    # BC ownership: harness-integration (FK-76) — nicht governance-and-guards.
    # Die hier gelisteten physischen Modulpfade gehoeren fachlich zu
    # harness-integration; der physische Paketpfad bestimmt NICHT die
    # BC-Ownership und darf nicht zur Ableitung von Governance-Ownership
    # herangezogen werden.

  - id: architecture-conformance.group.harness_adapters_codex
    name: HarnessAdaptersCodex
    bloodgroup: A
    module_prefixes:
      - agentkit.harness_client.harness_adapters.codex
    parent_group_id: architecture-conformance.group.governance
    exposure: internal
    component_kind: domain
    # Lokalisierte Codex-Mediation: Tool-Namen, Hook-Payload und
    # Exit-Code-Vertrag bleiben hier und werden auf HookEvent gemappt.
    # BC ownership: harness-integration (FK-76) — nicht governance-and-guards.
    # Die hier gelisteten physischen Modulpfade gehoeren fachlich zu
    # harness-integration; der physische Paketpfad bestimmt NICHT die
    # BC-Ownership und darf nicht zur Ableitung von Governance-Ownership
    # herangezogen werden.

  - id: architecture-conformance.group.ccag_permission_runtime
    name: CcagPermissionRuntime
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.governance.ccag_permission_runtime
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.governance_observer
    name: GovernanceObserver
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.governance.governance_observer
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.integrity_gate
    name: IntegrityGate
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.governance.integrity_gate
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.principal_capability
    name: PrincipalCapability
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.governance.principal_capabilities
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.setup_preflight_gate
    name: SetupPreflightGate
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.governance.setup_preflight_gate
    parent_group_id: architecture-conformance.group.governance
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.escalation_mechanism
    name: EscalationMechanism
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.governance.escalation_mechanism
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
      - agentkit.backend.exploration
    parent_group_id: null
    exposure: top
    top_surface_modules: []
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
      - agentkit.backend.exploration.mode_router
    parent_group_id: architecture-conformance.group.exploration
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.exploration_drafting
    name: ExplorationDrafting
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.exploration.drafting
    parent_group_id: architecture-conformance.group.exploration
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.exploration_review
    name: ExplorationReview
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.exploration.review
    parent_group_id: architecture-conformance.group.exploration
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.exploration_mandate_classification
    name: MandateClassification
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.exploration.mandate_classification
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
      - agentkit.backend.implementation
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
      - agentkit.backend.implementation.worker_session
    parent_group_id: architecture-conformance.group.implementation
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.implementation_worker_loop
    name: WorkerLoop
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.implementation.worker_loop
    parent_group_id: architecture-conformance.group.implementation
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.implementation_handover_packager
    name: HandoverPackager
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.implementation.handover_packager
    parent_group_id: architecture-conformance.group.implementation
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.implementation_worker_health
    name: WorkerHealthMonitor
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.implementation.worker_health
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
      - agentkit.backend.closure
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
      - agentkit.backend.closure.gates
    parent_group_id: architecture-conformance.group.closure
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.closure_merge_sequence
    name: MergeSequence
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.closure.merge_sequence
    parent_group_id: architecture-conformance.group.closure
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.closure_post_merge_finalization
    name: PostMergeFinalization
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.closure.post_merge_finalization
    parent_group_id: architecture-conformance.group.closure
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.closure_execution_report
    name: ExecutionReport
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.closure.execution_report
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
      - agentkit.backend.artifacts
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
      - agentkit.backend.artifacts.producer_registry
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
      - agentkit.backend.telemetry
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
      - agentkit.backend.telemetry.hooks
    parent_group_id: architecture-conformance.group.telemetry
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.telemetry_projection_accessor
    name: ProjectionAccessor
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.telemetry.projection_accessor
    parent_group_id: architecture-conformance.group.telemetry
    exposure: sub_exposed
    component_kind: domain

  - id: architecture-conformance.group.telemetry_contract
    name: TelemetryContract
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.telemetry.contract
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
      - agentkit.backend.prompt_runtime
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
      - agentkit.backend.prompt_runtime.bundle_store
    parent_group_id: architecture-conformance.group.prompt_runtime
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.prompt_runtime_bundle_pinning
    name: BundlePinning
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.prompt_runtime.bundle_pinning
    parent_group_id: architecture-conformance.group.prompt_runtime
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.prompt_runtime_materialization
    name: Materialization
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.prompt_runtime.materialization
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
      - agentkit.backend.skills
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
      - agentkit.backend.skills.bundle_store
    parent_group_id: architecture-conformance.group.skills
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.skills_binding
    name: SkillBinding
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.skills.binding
    parent_group_id: architecture-conformance.group.skills
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.skills_quality_metric
    name: SkillQualityMetric
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.skills.quality_metric
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
      - agentkit.backend.installer
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
      - agentkit.backend.installer.checkpoint_engine
    parent_group_id: architecture-conformance.group.installer
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.installer_bootstrap_checkpoints
    name: BootstrapCheckpoints
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.installer.bootstrap_checkpoints
    parent_group_id: architecture-conformance.group.installer
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.installer_integration_checkpoints
    name: IntegrationCheckpoints
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.installer.integration_checkpoints
    parent_group_id: architecture-conformance.group.installer
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.installer_upgrade
    name: Upgrade
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.installer.upgrade
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
      - agentkit.backend.failure_corpus
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
      - agentkit.backend.failure_corpus.incident_triage
    parent_group_id: architecture-conformance.group.failure_corpus
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.failure_corpus_pattern_promotion
    name: PatternPromotion
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.failure_corpus.pattern_promotion
    parent_group_id: architecture-conformance.group.failure_corpus
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.failure_corpus_check_factory
    name: CheckFactory
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.failure_corpus.check_factory
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
      - agentkit.backend.execution_planning
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
      - agentkit.backend.execution_planning.planning_model
    parent_group_id: architecture-conformance.group.execution_planning
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.execution_planning_proposal_ingest
    name: ProposalIngest
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.execution_planning.proposal_ingest
    parent_group_id: architecture-conformance.group.execution_planning
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.execution_planning_readiness_assessment
    name: ReadinessAssessment
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.execution_planning.readiness_assessment
    parent_group_id: architecture-conformance.group.execution_planning
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.execution_planning_scheduling_policy
    name: SchedulingPolicy
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.execution_planning.scheduling_policy
    parent_group_id: architecture-conformance.group.execution_planning
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.execution_planning_plan_derivation
    name: PlanDerivation
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.execution_planning.plan_derivation
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
      - agentkit.backend.requirements_coverage
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
      - agentkit.backend.requirements_coverage.are_client
    parent_group_id: architecture-conformance.group.requirements_coverage
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.requirements_coverage_scope_mapping
    name: ScopeMapping
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.requirements_coverage.scope_mapping
    parent_group_id: architecture-conformance.group.requirements_coverage
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.requirements_coverage_are_integration
    name: AreIntegration
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.requirements_coverage.are_integration
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
      - agentkit.backend.kpi_analytics
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
      - agentkit.backend.kpi_analytics.catalog
    parent_group_id: architecture-conformance.group.kpi_analytics
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.kpi_analytics_fact_store
    name: FactStore
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.kpi_analytics.fact_store
    parent_group_id: architecture-conformance.group.kpi_analytics
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.kpi_analytics_aggregation
    name: Aggregation
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.kpi_analytics.aggregation
    parent_group_id: architecture-conformance.group.kpi_analytics
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.kpi_analytics_dashboard
    name: Dashboard
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.kpi_analytics.dashboard
    parent_group_id: architecture-conformance.group.kpi_analytics
    exposure: internal
    component_kind: domain

  - id: architecture-conformance.group.kpi_analytics_design_system
    name: DesignSystem
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.kpi_analytics.design_system
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
      - agentkit.backend.project_management
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
  # BC 18: task-management
  # -----------------------------------------------------------------------

  - id: architecture-conformance.group.task_management
    name: TaskManagement
    bloodgroup: A
    module_prefixes:
      - agentkit.backend.task_management
    parent_group_id: null
    exposure: top
    top_surface_modules: []
    component_kind: domain
    # Owner von Task/TaskLink-Zustand und -Verlinkung (FK-77).
    # Reine Zustands-/Verlinkungs-Verwaltung: KEINE Pipeline-/Phasen-/
    # Gate-/Worktree-Kopplung (FK-77 §77.6) — importiert weder
    # pipeline_engine noch Phase-/Gate-Orchestrierung; ein Task wird nie
    # an die PipelineEngine uebergeben. Persistenz (tm_tasks/tm_task_links)
    # via boundary.state_backend_repository; dedizierter Task-Persistenz-
    # Port analog record_fc_incident, ohne Aufweitung des FK-69-
    # ProjectionKind.

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
      - agentkit.backend.cli
    importable_by: []
    may_import_component_groups: any
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.integrations
      - architecture-conformance.boundary.control_plane_http
      - architecture-conformance.boundary.control_plane_records
      - architecture-conformance.boundary.control_plane_runtime
      # The CLI holds no state_backend_repository grant. The operator/recovery
      # CLI routes ALL state-backend
      # reads through agentkit.backend.bootstrap.composition_root wrapper functions
      # (cli_load_story_context, cli_read_phase_state_record,
      # cli_load_execution_events_for_project_global) so the CLI never imports
      # agentkit.backend.state_backend.store directly. The agentkit.backend.bootstrap module is
      # not a classified boundary module (it is a wiring layer accessible to
      # entry boundaries under may_import_component_groups: any); no additional
      # boundary grant is required for the CLI to use composition_root.

  - id: architecture-conformance.boundary.control_plane_http
    name: ControlPlaneHttp
    bloodgroup: R
    boundary_kind: entry_boundary
    module_prefixes:
      - agentkit.backend.control_plane_http
      - agentkit.backend.control_plane.http
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
      - agentkit.backend.control_plane.models
      - agentkit.backend.control_plane.records
    importable_by: any
    may_import_component_groups:
      - architecture-conformance.group.telemetry
      - architecture-conformance.group.telemetry_contract
    may_import_boundary_modules:
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.core_types
    # Pydantic-Modelle und Persistenz-Records der Control-Plane.
    # Datentypen mit Cross-BC-Refs (z.B. Telemetry-Event-Typen). Da
    # nicht "rein-fachneutral", als adapter_boundary modelliert
    # statt shared_foundation.

  - id: architecture-conformance.boundary.control_plane_runtime
    name: ControlPlaneRuntime
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.backend.control_plane.runtime
      - agentkit.backend.control_plane.repository
      - agentkit.backend.control_plane.telemetry
    importable_by: any
    may_import_component_groups: any
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.core_types
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
      - agentkit.integration_clients
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
      - agentkit.harness_client.projectedge
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.core_types
      - architecture-conformance.boundary.control_plane_records

  - id: architecture-conformance.boundary.concept_catalog
    name: ConceptCatalog
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.backend.concept_catalog
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
      - agentkit.integration_clients.multi_llm_hub
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
      - agentkit.backend.auth
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
      - agentkit.backend.state_backend.store
    importable_by: any
    may_import_component_groups: any
    may_import_boundary_modules:
      - architecture-conformance.boundary.state_backend_drivers
      - architecture-conformance.boundary.state_persistence_scope
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.core_types
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
      - agentkit.backend.state_backend.scope
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
      - agentkit.backend.config
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
      - agentkit.backend.exceptions
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules: []
    # Bluttyp 0 (Null-Software): fachneutrale Basistypen, Exceptions,
    # stateless Helfer. Importiert nichts AK3-Spezifisches; kann in
    # jedes andere Python-Projekt kopiert werden, ohne Domaenenwissen
    # mitzunehmen. Volldefinition concept/methodology/software-blutgruppen.md.

  # -----------------------------------------------------------------------
  # Domain-Core-Foundation (domain_core_foundation): fachliche Kerntypen,
  # die mehrere BCs gleichzeitig brauchen. Bluttyp A (traegt Domaenen-
  # wissen), aber importierbares Blattmodul ohne I/O.
  # -----------------------------------------------------------------------

  - id: architecture-conformance.boundary.core_types
    name: CoreTypes
    bloodgroup: A
    boundary_kind: domain_core_foundation
    module_prefixes:
      - agentkit.backend.core_types
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules: []
    # Domaenen-Kern-Foundation (FK-56 §56.5/§56.7a):
    # Single Source of Truth fuer fachliche Kerntypen, die mehrere BCs
    # gleichzeitig brauchen — ArtifactClass, Severity, Story(Mode/Size),
    # QaContext, AttemptOutcome, PolicyVerdict, ClosureVerdict,
    # PauseReason, die FailureCorpus-Enums sowie der lokale OperatingMode
    # (ai_augmented / story_execution / binding_invalid).
    #
    # Bluttyp A statt 0: anders als boundary.shared (fachneutral, Bluttyp
    # 0, in jedes Projekt kopierbar) traegt core_types Domaenenwissen und
    # ist deshalb KEINE Null-Software. Aber wie shared ein importierbares
    # Blattmodul ohne I/O: es importiert NUR stdlib/pydantic und sich
    # selbst (agentkit.backend.core_types.*), nichts anderes AK3-Spezifisches
    # (may_import_component_groups: [] und may_import_boundary_modules:
    # []). Damit kann JEDER Konsument — A-BCs ebenso wie die R-Adapter-
    # Boundaries control_plane.models / control_plane.runtime /
    # projectedge.runtime und die state_backend-Driver/Repository —
    # exakt dasselbe Objekt cycle-free re-importieren. OperatingMode lebt
    # hier (nicht in projectedge.runtime), damit control_plane.models
    # (R-Adapter) die Annotation aufloesen kann, ohne eine andere
    # Boundary zu importieren (kein Import-Zyklus).

  # -----------------------------------------------------------------------
  # Infrastructure-IO (infrastructure_io): Filesystem-Writer und
  # Artifact-Exporter. Trennt Builder (A) von Writer (R/T).
  # -----------------------------------------------------------------------

  - id: architecture-conformance.boundary.filesystem
    name: Filesystem
    bloodgroup: R
    boundary_kind: infrastructure_io
    module_prefixes:
      - agentkit.backend.boundary.filesystem
      - agentkit.backend.state_backend.paths
    importable_by: any
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.shared
    # Atomic-Write-Helpers (atomic_write_json) und Artifact-Writer.
    # BC-Builder produzieren JSON-serialisierbare Strukturen; das
    # Schreiben passiert hier. Verhindert, dass A-BCs Filesystem-I/O
    # direkt importieren.
    #
    # `agentkit.backend.state_backend.paths` haelt Filesystem-Pfad-Konstanten
    # (STATE_DB_DIR/STATE_DB_FILE/LAYER_ARTIFACT_FILES/...) und
    # gehoert konzeptionell zu dieser Boundary, auch wenn der physische
    # Pfad unter state_backend/ liegt.

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
      - agentkit.backend.state_backend.postgres_store
      - agentkit.backend.state_backend.sqlite_store
      - agentkit.backend.state_backend.config
      - agentkit.backend.state_backend.schema_bootstrap
      - agentkit.backend.state_backend.migration
    importable_by:
      - architecture-conformance.boundary.state_backend_repository
    may_import_component_groups: []
    may_import_boundary_modules:
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.core_types
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.filesystem
      - architecture-conformance.boundary.control_plane_records
      - architecture-conformance.boundary.state_persistence_scope
    # Postgres- und SQLite-Driver. config.py haelt StateBackendKind +
    # load_state_backend_config (Driver-Schicht-Konfig). paths.py
    # haelt Filesystem-Pfade (STATE_DB_DIR/STATE_DB_FILE).
    # schema_bootstrap.py ist der gemeinsame Driver-Helper
    # (ensure_versioned_schema) — loest den Schema-Namen via
    # config.resolve_schema_name (Same-Boundary-Import) und ist von
    # state_backend_repository (den Repos) sowie postgres_store nutzbar.
    #
    # Driver importieren keine BC-Records direkt; Mapping erfolgt
    # in store.mappers (boundary.state_backend_repository). Die Driver
    # erhalten und liefern ausschliesslich dict[str, Any]-Zeilen.
```
<!-- FORMAL-SPEC:END -->
