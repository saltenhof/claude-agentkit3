---
id: formal.architecture-conformance.entities
title: Architecture Conformance Entities
status: active
doc_kind: spec
context: architecture-conformance
spec_kind: entity-set
version: 32
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
    meaning: Adapter zu externen Systemen oder Datenquellen (GitHub, ARE, LLM-Hub, VectorDB, MCP, Filesystem-basierte Konzept-Korpora) — uebersetzt zwischen externer Repraesentation und Domaene. Wird von fachlichen BCs genutzt; importiert keine BCs selbst.
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
      - architecture-conformance.boundary.projectedge
      - architecture-conformance.boundary.auth
      # AG3-130 (FK-10 §10.1.0 I3): the operator-recovery verbs run-phase/resume are
      # thin REST requesters at the core. They call the official Dev-Edge client
      # (agentkit.harness_client.projectedge.client.ProjectEdgeClient / HttpsJsonTransport)
      # instead of building a ControlPlaneRuntimeService in-process, so the CLI
      # holds a ProjectEdge boundary grant. It remains a duenne client seam (no
      # second HTTP stack, no phase logic on the dev side).
      #
      # The ``control_plane_runtime`` grant was REMOVED (Codex m1): after AG3-130 no
      # CLI module imports the in-process runtime service/repository/telemetry, and
      # dropping the grant makes the architecture guard fail-closed if runtime and
      # ProjectEdge are ever re-coupled here (a future in-process ControlPlaneRuntimeService
      # in the CLI would violate AC010). The CLI still reaches the core-owned phase
      # mutations exclusively over REST via ProjectEdge.
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
    importable_by:
      - architecture-conformance.boundary.cli
    may_import_component_groups: any
    may_import_boundary_modules:
      - architecture-conformance.boundary.config
      - architecture-conformance.boundary.shared
      - architecture-conformance.boundary.control_plane_records
      - architecture-conformance.boundary.control_plane_runtime
      - architecture-conformance.boundary.filesystem
      - architecture-conformance.boundary.concept_catalog
      - architecture-conformance.boundary.multi_llm_hub
      - architecture-conformance.boundary.auth
    # HTTP-Transport-Schicht. Nimmt Requests entgegen und ruft fachliche
    # Komponenten bzw. eng begrenzte Control-Plane-Runtime-Services.
    # Kein direkter StateBackend-/Repository-Zugriff: fachliche Read-
    # Models entstehen ueber Owner-BC-Ports, nicht ueber Persistenz-
    # Durchgriff. Boot-Punkt durch CLI.

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
    # Adapter-Schicht fuer eigene Control-Plane-Zustaende
    # (Session-/Lock-/Operationstabellen) und Telemetrie-Anbindung.
    # Kein universeller Domaenenleser fuer Story-, Pipeline-, KPI-,
    # Planning- oder Governance-Read-Models; solche Sichten muessen
    # ueber die fachlichen Ports der owning Components entstehen.

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
      - architecture-conformance.boundary.filesystem
    # Aeussere API-Auth-Schicht fuer UI-BFF und Project-API:
    # Strategen-Cookie-Sessions, CSRF und projektgebundene Thin-Client-
    # Tokens. Kein A-BC, keine Rollen-/Quota- oder fachliche Policy-Logik.

  - id: architecture-conformance.boundary.state_backend_repository
    name: StateBackendRepository
    bloodgroup: R
    boundary_kind: adapter_boundary
    module_prefixes:
      - agentkit.backend.state_backend.persistence_json_codec
      - agentkit.backend.state_backend.persistence_test_support
      - agentkit.backend.state_backend.state_backend_connection_manager
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
    # in persistence_mappers (boundary.state_backend_repository). Die Driver
    # erhalten und liefern ausschliesslich dict[str, Any]-Zeilen.
# ---------------------------------------------------------------------------
# Distributionen (FK-10 §10.1.0a/§10.2.12, FK-07 §7.9a)
#
# AK3 wird in drei Distributionen ausgeliefert. `module_prefixes` benennt die
# Zugehoerigkeit im HEUTIGEN Importbaum (`agentkit.*`), damit die Zuordnung
# gegen den tatsaechlichen Code messbar ist. `target_import_root` benennt die
# Importwurzel des ausgelieferten Artefakts. Die Umstellung der Prefixe auf
# den Target-Root ist EIN atomarer Schritt (AG3-209); es gibt keinen
# Zeitraum, in dem beide aufloesen.
#
# KEIN default_distribution (AG3-208 Runde 4). Eine Auffangregel macht die
# Zuordnung nur SCHEINBAR total: sie weist jedem nicht gemessenen Modul einen
# Eigentuemer zu, ohne dafuer einen Beleg zu haben. Genau so sind drei Runden
# lang unbelegte Zuweisungen entstanden. Die Klassifikation aller 44
# unmittelbaren Backend-Subpakete ist mit AG3-237 GESCHLOSSEN; jede Zuordnung
# traegt ihren Messbeleg in distribution_membership_evidence.
#
# `distribution_prefix_resolution: longest-match-wins` macht sie disjunkt:
# Prefixe verschiedener Distributionen duerfen sich schachteln, und das
# laengste treffende Prefix entscheidet. Beispiel -- alle vier Zeilen sind
# GEMESSENE Zuordnungen aus AG3-237, keine erfundenen Illustrationen:
# `agentkit.backend.governance`                    -> core (Adjudication, FK-01 §1.1a)
# `agentkit.backend.governance.runner`             -> edge (laenger, gewinnt)
# `agentkit.backend.installer`                     -> edge (Kommandopfade, §10.2.11)
# `agentkit.backend.installer.third_party_clients` -> core (laenger, gewinnt)
# Es gibt bewusst KEIN Beispiel mit `agentkit.backend` als Praefix: dieses
# Praefix existiert in keiner Distribution, weil es unter longest-match-wins
# die entfernte Auffangregel funktional wiederherstellen wuerde. Das
# Paketwurzelmodul `agentkit.backend` steht deshalb als `module_members`,
# nicht als Praefix.
# Zwei GLEICH lange treffende Prefixe verschiedener Distributionen sind ein
# Verstoss gegen architecture-conformance.rule.distribution_membership_is_total_and_disjoint,
# kein Aufloesungsfall.
# ---------------------------------------------------------------------------
distribution_classification_owner: AG3-237
distribution_classification_status: closed
distribution_classification_measured_on: "2026-08-07"
distribution_prefix_resolution: longest-match-wins
# ---------------------------------------------------------------------------
# Zaehleinheit und Mischungsfreiheit (AG3-237 AC 1)
#
# Ohne festgelegte Zaehleinheit ist "das Modul mischt keine Belange" nicht
# pruefbar. Die Vormessung aus AG3-208 mischte 13 Module, 33 importierte
# Symbole, 63 Klassen und fuer ein Paket gar keine Zahl. Die folgende
# Festlegung bindet architecture-conformance.rule.symbol_boundary_is_the_rule.
# ---------------------------------------------------------------------------
distribution_counting_unit:
  id: architecture-conformance.counting_unit.public_module_symbol
  unit: public-module-level-symbol
  definition: >-
    a name bound at module level that does not start with an underscore: class,
    function, module-level constant or type alias. a name WITH a leading
    underscore is not a counted symbol; it travels with the public symbol that
    owns it, and its own dependencies are still walked when the wire hull is
    proven. imported names re-exported through __all__ count for the module that
    DEFINES them, so a symbol is counted exactly once.
  population_scope: >-
    src/agentkit/backend/**. names outside backend/ are anchors or deployment
    units of their own (FK-10 section A) and are not part of the counted
    population.
  aggregation_unit: module
  rationale: >-
    the two gate checks that enforce distribution membership operate on exactly
    these two granularities. wire_surface_matches_symbol_boundaries compares the
    public surface of the built wheel, which is a set of symbols; the
    source_graph and wheel_reachability checks resolve membership by module
    prefix, which is a set of modules. nothing smaller than a symbol can be
    shipped and nothing larger than a module can be cut.
  measured_population:
    backend_public_module_symbols: 3838
    backend_modules: 955
    backend_immediate_subpackages: 44
    backend_root_modules: 2
  measurement_method: >-
    AST over every .py file under src/agentkit (1042 modules, 955 of them under
    backend/), 2026-08-07.
# ---------------------------------------------------------------------------
# Das Kriterium hat ZWEI Bedingungen. Eine dritte -- "kein Entry-Point der
# anderen Distribution erreicht das Paket" -- stand hier in Runde 1 und ist
# ENTFERNT, nicht ausgesetzt. Sie war sachlich falsch: eine Kante edge->core
# beweist nicht, dass die Zugehoerigkeit unbekannt ist, sondern dass jemand
# eine bekannte Grenze verletzt. Als Vorbedingung der Klassifikation gefuehrt
# haette sie die Klassifikation durch ihre eigenen Verstoesse unschliessbar
# gemacht. Die Kanten stehen jetzt als distribution_boundary_violations --
# Arbeitsliste von AG3-209, kein Bestandteil des Klassifikationsbeweises.
# ---------------------------------------------------------------------------
distribution_mixing_freedom_criterion:
  id: architecture-conformance.criterion.mixing_freedom
  conditions:
    - id: architecture-conformance.criterion.no_foreign_anchor
      rule: >-
        no module of the package DIRECTLY imports an anchor module of another
        distribution, and no module of the package itself declares a
        third-party distribution owned by another distribution.
      measured: true
      anchor_definition: >-
        an anchor is a module OUTSIDE src/agentkit/backend whose distribution
        FK-10 section A or C already assigns, listed in distribution_anchors.
        the section E dependency rule is a property of the DECLARING module
        alone and does not propagate to its importers -- otherwise a member of
        the 44 (for example backend.auth.credentials via argon2, or
        backend.vectordb.* via mcp) would decide other members of the 44, which
        is exactly the circularity this definition exists to prevent.
      why_direct_and_not_transitive: >-
        transitive anchor reach conflates two defects with two different
        remedies. a module that itself imports both sides mixes concerns and
        needs a symbol cut. a module that only REACHES both sides through
        another backend module has a forbidden edge on the path, and the remedy
        is removing that edge. measured 2026-08-07: 3 modules mix directly,
        transitive reach marks 222.
    - id: architecture-conformance.criterion.wire_rule_holds
      rule: >-
        if the target is the wire distribution, the TRANSITIVE HULL of every
        migrating symbol must close: every symbol the hull reaches either
        migrates too, or is a private helper travelling with its owner, or is
        stdlib-safe / pydantic. a hull that reaches forbidden stdlib, a
        non-pydantic third party, behaviour (function or plain class), or the
        other distribution does NOT close, and the symbol does not migrate.
      measured: true
      fixpoint_required: >-
        deferral iterates to a fixpoint. a symbol whose hull reached a symbol
        that was itself deferred in an earlier pass must be re-examined;
        measured 2026-08-07 this took 5 iterations and moved 23 symbols out,
        8 of which only failed in passes 2 to 5.
  fail_closed: >-
    a package whose no_foreign_anchor condition cannot be evaluated -- an
    unparseable module, a dynamic import onto a computed name -- counts as
    mixing, not as mixing-free.
# ---------------------------------------------------------------------------
# Wie die SEITE bestimmt wird. Das Kriterium oben ist ein Veto: es kann eine
# Zuweisung verbieten, es kann keine Seite waehlen. Die Seite bestimmen die
# folgenden Regeln, in dieser Reihenfolge.
#
# EHRLICHKEIT ZU E3: E3 ist eine WAHL, keine Ableitung, und sie entscheidet
# 859 der 955 Backend-Module. Eine konsumbasierte Ableitung ("alle heutigen
# Importer liegen auf einer Seite") ist erwogen und VERWORFEN worden: sie
# leitet die Seite aus dem heutigen, defekten Aufrufgraphen ab und lieferte
# unter anderem state_backend.store.fact_repository -> edge. Eine als
# Ableitung getarnte Wahl ist schlechter als eine benannte Wahl.
# ---------------------------------------------------------------------------
distribution_side_election_rules:
  - id: architecture-conformance.election.e1_anchor
    code: E1
    kind: derivation
    rule: direct anchor contact per no_foreign_anchor; both sides means split
    modules_decided: 85
    arithmetic: >-
      49 modules touch an edge anchor, 37 a core anchor, 1 touches both and is
      therefore split -- 49 + 37 - 1 = 85 distinct modules. an earlier figure of
      84 did not subtract the overlap.
  - id: architecture-conformance.election.e2_entry_point
    code: E2
    kind: derivation
    rule: >-
      the module implements a console-script command path named in FK-10
      section 10.2.11; a module carrying command paths of both distributions is
      split
    modules_decided: 11
  - id: architecture-conformance.election.e3_authority
    code: E3
    kind: election
    rule: >-
      residual election along the authority invariants: canonical state and
      adjudication belong to the core (I1/I3/I5, FK-01 section 1.1a, FK-10
      section 10.2.3); packages whose entry points are the edge command paths
      belong to the edge. this is a CHOICE with a named norm, not a measurement
    modules_decided: 859
    granularity: >-
      E3 is decided PER PACKAGE, not per module: 46 package-level reasons, some
      of them one line. saying it "decides 859 modules individually" overstates
      it. AC 3 asks for evidence per PREFIX ASSIGNMENT, and that is what the 46
      entries are
    is_not_a_default_distribution: >-
      a default distribution assigns an owner to a module nobody looked at.
      E3 is enumerated per package in distribution_membership_evidence, and
      each entry names the norm it follows. the difference is evidence, not
      mechanism
    rejected_alternative: >-
      a consumption-based DERIVATION ("every current importer sits on one
      side") was considered and rejected: it derives the side from today's
      defective call graph. the sound counter-example is
      state_backend.store.fact_repository, whose only importers are edge today
      although it is canonical state. two counter-examples named in round 2 --
      governance.principal_capabilities and implementation.worker_health -- were
      WRONG: both are imported by numerous core modules, so the rule does not
      yield edge for them. they are withdrawn; the rejection stands on the
      remaining case and on the principle
distributions:
  - id: architecture-conformance.distribution.edge
    code: edge
    distribution_name: agentkit-project-edge
    target_import_root: agentkit_project_edge
    runs_on: developer-machine
    meaning: >-
      Edge-Distribution. Hook-Wrapper, Guard-Engine, Project-Edge-Client,
      Bediener-CLI, Installer, lokal gestartete MCP-Server. Besitzt keinen
      kanonischen Zustand; erreicht den Kern ausschliesslich ausgehend ueber
      HTTPS /v1.
    console_scripts:
      - agentkit-project-edge
      - agentkit-hook-claude
      - agentkit-hook-codex
      - agentkit-story-mcp
      - agentkit-are-mcp
    # runtime_dependencies bedeutet: ALLE direkten Paketabhaengigkeiten der
    # Distribution, nicht nur Drittbibliotheken. Deshalb steht agentkit-wire
    # hier drin -- sonst waere eine korrekte Edge-Metadatei zugleich Pflicht
    # (FK-07 Paragraph 7.9a.2 Punkt 5b) und Ueberschuss (Punkt 5d).
    runtime_dependencies:
      - agentkit-wire
      # Direkt importiert, nicht nur transitiv ueber agentkit-wire:
      # harness_client/harness_adapters/claude_code_models.py:8 u. a.
      # (8 Dateien, gemessen 2026-08-07).
      - pydantic
      - pyyaml
      - tomlkit
      - mcp
      - weaviate-client
      - tokenizers
      - psutil
    # KEINE `agentkit.backend.*`-Praefixe. Jede solche Zeile waere eine
    # Klassifikation eines Backend-Subpakets und damit AG3-237 vorgegriffen --
    # auch dann, wenn der Laufzeitbefund eindeutig scheint.
    module_prefixes:
      - agentkit.harness_client
      - agentkit.bundles
      - agentkit.concepts
      - agentkit.resources
      - agentkit.integration_clients.vectordb
      - agentkit.integration_clients.mcp
      # --- Backend-Subpakete, gemessen 2026-08-07 (AG3-237) -----------------
      - agentkit.backend.cli
      - agentkit.backend.installer
      - agentkit.backend.story_creation
      - agentkit.backend.vectordb
      # --- Einzelmodule in kern-basierten Paketen (longest-match gewinnt) ----
      - agentkit.backend.bootstrap.composition_project
      - agentkit.backend.failure_corpus.cli
      - agentkit.backend.failure_corpus.writer_client
      - agentkit.backend.governance.guard_evaluation
      - agentkit.backend.governance.rest_edge
      - agentkit.backend.governance.runner
      - agentkit.backend.implementation.worker_health.rest_repository
      - agentkit.backend.core_types.mcp_server_registration
      - agentkit.backend.governance.default_hook_definitions
      - agentkit.backend.telemetry.rest_emitter
  - id: architecture-conformance.distribution.core
    code: core
    distribution_name: agentkit-backend
    target_import_root: agentkit_backend
    runs_on: core-host
    meaning: >-
      Kern-Distribution. Pipeline, QA-Subflow, Governance-Adjudication,
      Closure, Control-Plane-HTTP, State-Backend, KPI-Analytics und die
      Frontend-Auslieferung. Alleiniger Eigentuemer des kanonischen Zustands.
      Oeffnet nie eine Verbindung zu einem Entwicklerrechner.
    console_scripts:
      - agentkit-backend
    # Siehe Kommentar bei der Edge-Distribution: ALLE direkten
    # Paketabhaengigkeiten, inklusive agentkit-wire.
    runtime_dependencies:
      - agentkit-wire
      # Direkt importiert: backend/execution_planning/scheduling.py:34 u. a.
      # (134 Dateien, gemessen 2026-08-07).
      - pydantic
      - pyyaml
      - psycopg
      - psycopg-pool
      - argon2-cffi
      # AG3-208 B5: heute NICHT in [project.dependencies]; kommt nur transitiv
      # ueber huggingface-hub/hatchling mit. Einziger Importer:
      # backend/skills/version_policy.py:7. Ohne Deklaration waere das
      # Kern-Wheel nach dem Split ohne notwendige Laufzeitabhaengigkeit baubar.
      - packaging
    # KEIN Praefix `agentkit.backend`. Unter longest-match-wins wuerde er
    # jedes nicht ueberschriebene Backend-Modul einfangen und damit die
    # entfernte Auffangregel funktional wiederherstellen. Die 40 kern-basierten
    # Subpakete stehen deshalb EINZELN, nicht als ein Sammelpraefix.
    module_prefixes:
      - agentkit.frontend
      - agentkit.integration_clients
      # --- Backend-Subpakete, gemessen 2026-08-07 (AG3-237) -----------------
      - agentkit.backend.artifacts
      - agentkit.backend.auth
      - agentkit.backend.bootstrap
      - agentkit.backend.boundary
      - agentkit.backend.closure
      - agentkit.backend.code_backend
      - agentkit.backend.concept_catalog
      - agentkit.backend.config
      - agentkit.backend.control_plane
      - agentkit.backend.control_plane_http
      - agentkit.backend.core_types
      - agentkit.backend.exceptions
      - agentkit.backend.execution_planning
      - agentkit.backend.exploration
      - agentkit.backend.failure_corpus
      - agentkit.backend.governance
      - agentkit.backend.implementation
      - agentkit.backend.integration_stabilization
      - agentkit.backend.kpi_analytics
      - agentkit.backend.phase_state_store
      - agentkit.backend.pipeline_engine
      - agentkit.backend.process
      - agentkit.backend.project
      - agentkit.backend.project_management
      - agentkit.backend.project_ops
      - agentkit.backend.prompt_runtime
      - agentkit.backend.requirements_coverage
      - agentkit.backend.schemas
      - agentkit.backend.skills
      - agentkit.backend.state_backend
      - agentkit.backend.story
      - agentkit.backend.story_context_manager
      - agentkit.backend.story_exit
      - agentkit.backend.story_reset
      - agentkit.backend.story_split
      - agentkit.backend.task_management
      - agentkit.backend.telemetry
      - agentkit.backend.telemetry_service
      - agentkit.backend.utils
      - agentkit.backend.verify_system
      - agentkit.backend.workers
      # --- Einzelmodule in edge-basierten Paketen (longest-match gewinnt) ----
      - agentkit.backend.cli.serve
      - agentkit.backend.installer.integration_checkpoints.branch_plugin_self_test
      - agentkit.backend.installer.integration_checkpoints.ci_preflight
      - agentkit.backend.installer.integration_checkpoints.jenkins_selftest_harness
      - agentkit.backend.installer.integration_checkpoints.scanner_harness
      - agentkit.backend.installer.integration_checkpoints.sonar_preflight
      - agentkit.backend.installer.integration_checkpoints.sonar_probes
      - agentkit.backend.installer.third_party_clients
    # `agentkit.backend` ist ein MODUL (das Paket-__init__), kein Praefix.
    # Als Praefix gefuehrt wuerde es unter longest-match-wins jedes nicht
    # ueberschriebene Backend-Modul einfangen und die entfernte Auffangregel
    # funktional wiederherstellen. `module_members` bindet genau ein Modul und
    # wird VOR den Praefixen aufgeloest; damit ist die Funktion total, ohne
    # dass ein Sammelpraefix entsteht.
    module_members:
      - agentkit.backend
  - id: architecture-conformance.distribution.wire
    code: wire
    distribution_name: agentkit-wire
    target_import_root: agentkit_wire
    runs_on: both
    meaning: >-
      Vertragspaket. Ausschliesslich das /v1-Vokabular, das Edge und Kern
      beide brauchen. I/O-freies Blatt ohne Dateisystem-, Netz-, Datenbank-,
      Subprozess- oder Umgebungszugriff; einzige Drittabhaengigkeit pydantic.
      Kein Ablageort fuer geteilten Code.
    console_scripts: []
    runtime_dependencies:
      - pydantic
    # KEIN Praefix im heutigen Importbaum -- und das ist kein Versaeumnis.
    #
    # Das Vertragspaket ist kein Umetikettieren bestehender Module: es ist
    # neuer Code, in den Symbole WANDERN. Die sechs Praefixe, die hier bis
    # AG3-208 standen (control_plane.third_party_models, core_types.operating_mode,
    # core_types.verify_evidence, story_{exit,reset,split}.http_models), waren
    # eine Modulzuweisung ohne symbolgenaue Messung; AG3-237 hat sie durch
    # wire_target_modules ersetzt. `module_prefixes` bleibt leer, weil jedes
    # `agentkit.backend.*`-Praefix hier zugleich behaupten wuerde, das ganze
    # Modul sei Vertragsvokabular -- genau die Aussage, die in drei
    # Reviewrunden viermal widerlegt worden ist.
    #
    # Die Zugehoerigkeit der Wire-Distribution ergibt sich stattdessen aus
    # wire_target_modules (nach dem Schnitt) und distribution_symbol_boundaries
    # (welches Symbol welches Zielmodul erreicht).
    #
    # AG3-239 hat `src/agentkit_wire/` ANGELEGT und die ersten vier Symbole
    # hineingezogen (HookDefinition, HookEventName aus governance.hook_registration;
    # TelemetryConfig aus config.models; GuardCounterMutationRequest aus
    # control_plane.models). Der Praefix steht deshalb jetzt hier -- er ist kein
    # `agentkit.backend.*`-Praefix und behauptet nichts ueber fremde Module,
    # sondern beansprucht genau den neuen Importwurzel-Baum.
    #
    # Der leere Wert war ab dem Moment schaedlich, in dem das Paket existierte:
    # eine Messung gegen eine unbeanspruchte Wurzel haelt fail-closed an
    # (belegt: AG3-239 Messlauf nach dem Anlegen), und ohne den Halt haette sie
    # jede Kante an das Vertragspaket still uebersehen.
    #
    # Die dritte DISTRIBUTION -- eigenes Wheel, eigene Metadaten -- ist davon
    # unberuehrt und bleibt Liefergegenstand von AG3-209. Hier entsteht der
    # Importwurzel-Baum, nicht das Paketartefakt.
    module_prefixes:
      - agentkit_wire
    target_module_prefixes:
      - agentkit_wire
# ---------------------------------------------------------------------------
# Symbolgenaue Zugehoerigkeit (FK-10 Paragraph 10.2.12 D, FK-07 Paragraph 7.9a.2 Punkt 4a)
#
# Eine Modulpraefix-Regel kann "dieses Symbol ja, jenes nein" nicht ausdruecken.
# Wo die Distributionsgrenze mitten durch ein Modul laeuft, ist die folgende
# Liste die SPEZIFIKATION DES SCHNITTS: AG3-209 teilt das Modul so, dass danach
# die Praefixregel wieder allein traegt. Bis dahin ist die Praefixzuordnung
# dieser Module bewusst unscharf und darf nicht als "ganzes Modul gehoert der
# genannten Distribution" gelesen werden.
#
# Das Gate vergleicht die oeffentliche Oberflaeche des gebauten
# agentkit-wire-Wheels gegen exported_symbols; jedes zusaetzliche Symbol ist ein
# Verstoss.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Zugehoerigkeit aller 44 Backend-Subpakete: GEMESSEN und GESCHLOSSEN (AG3-237)
#
# ARITHMETIK, nachgerechnet (AC 6). 46 Eintraege = 44 unmittelbare Subpakete
# + das Wurzelmodul `exceptions.py` + das Paketwurzelmodul `backend/__init__.py`.
# Zusammen decken sie 955 von 955 Modulen; die Funktion ist total.
#
# AC 3 verlangt einen Beleg je PRAEFIXZUWEISUNG, nicht je Modul. Die 46
# Eintraege unten sind genau diese Zuweisungen; jede traegt ihre Messung und
# die Norm, der ihre Seitenwahl folgt.
#
# Vier Klassen, disjunkt:
#   37  Praefix, mischungsfrei (36 Kern inkl. `exceptions.py` und des
#       Paketwurzelmoduls, 1 Edge: `vectordb`)
#    7  Praefix + benannte Modulausnahmen
#    2  Praefix + Modulausnahmen + Symbolschnitt in einem Modul
#   ---
#   46  Eintraege ueber 955 von 955 Modulen
#
# Klassifikationszaehlung: CORE 36, SPLIT-PACKAGE 7, SPLIT-MODULE 2, EDGE 1.
#
# `pending_symbol_inventory` ist leer.
# ---------------------------------------------------------------------------
pending_symbol_inventory: []
distribution_membership_evidence:
  - id: architecture-conformance.membership.backend_root_package
    module_prefix: agentkit.backend
    unit: root-package-module
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      1 module, 0 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: none.
    why_this_side: >-
      the backend package root; it carries no public symbol and no anchor, and it belongs where the package it opens belongs.
  - id: architecture-conformance.membership.backend_artifacts
    module_prefix: agentkit.backend.artifacts
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      9 modules, 17 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      artifact envelopes, producer registry and validation are canonical-state machinery.
  - id: architecture-conformance.membership.backend_auth
    module_prefix: agentkit.backend.auth
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E1
    measured_evidence: >-
      10 modules, 29 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 1 core, 0 both.
      third-party declared: argon2, pydantic.
    why_this_side: >-
      the strategist credential store and session repository live on the core host (FK-91 section 91.1).
  - id: architecture-conformance.membership.backend_bootstrap
    module_prefix: agentkit.backend.bootstrap
    unit: subpackage
    distribution: core
    classification: SPLIT-PACKAGE
    decided_by: E1
    measured_evidence: >-
      23 modules, 82 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 1 edge, 5 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      the composition root wires the core runtime.
    prefix_exceptions:
      - module: agentkit.backend.bootstrap.composition_project
        distribution: edge
        decided_by: E1
        witness: >-
          agentkit.harness_client.projectedge.client,agentkit.integration_clients.vectordb,agentkit.integration_clients.vectordb.errors
  - id: architecture-conformance.membership.backend_boundary
    module_prefix: agentkit.backend.boundary
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      9 modules, 18 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      filesystem and network boundary helpers of the core runtime.
  - id: architecture-conformance.membership.backend_cli
    module_prefix: agentkit.backend.cli
    unit: subpackage
    distribution: edge
    classification: SPLIT-MODULE
    decided_by: E2
    measured_evidence: >-
      18 modules, 26 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 8 edge, 0 core, 0 both.
      third-party declared: none.
    why_this_side: >-
      31 of the 35 command paths are edge command paths (FK-10 section 10.2.11).
    prefix_exceptions:
      - module: agentkit.backend.cli.auth_commands
        distribution: split
        decided_by: E2
        witness: >-
          agentkit.harness_client.projectedge.auth_operator,agentkit.harness_client.projectedge.client,agentkit.harness_client.projectedge.credentials,agentkit.harness_client.projectedge.private_files,agentkit.harness_client.projectedge.runtime
      - module: agentkit.backend.cli.lifecycle
        distribution: split
        decided_by: E2
        witness: >-
          command paths of both distributions (FK-10 section 10.2.11)
      - module: agentkit.backend.cli.serve
        distribution: core
        decided_by: E2
        witness: >-
          command paths of both distributions (FK-10 section 10.2.11)
  - id: architecture-conformance.membership.backend_closure
    module_prefix: agentkit.backend.closure
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      14 modules, 59 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: none.
    why_this_side: >-
      closure adjudication, merge saga and integrity verdicts are core judgements.
  - id: architecture-conformance.membership.backend_code_backend
    module_prefix: agentkit.backend.code_backend
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      3 modules, 10 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: none.
    why_this_side: >-
      the provider port is resolved by the core when AK3 drives GitHub (I2).
  - id: architecture-conformance.membership.backend_concept_catalog
    module_prefix: agentkit.backend.concept_catalog
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      6 modules, 10 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic, yaml.
    why_this_side: >-
      the concept catalog is read by core-side prompt and verify machinery.
  - id: architecture-conformance.membership.backend_config
    module_prefix: agentkit.backend.config
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      7 modules, 53 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic, yaml.
    why_this_side: >-
      the configuration schema is carried as ProjectManagement state by the core (I5).
  - id: architecture-conformance.membership.backend_control_plane
    module_prefix: agentkit.backend.control_plane
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      60 modules, 295 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      the /v1 server-side command, claim and ownership model.
  - id: architecture-conformance.membership.backend_control_plane_http
    module_prefix: agentkit.backend.control_plane_http
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E1
    measured_evidence: >-
      25 modules, 40 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 3 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      the /v1 HTTP server itself.
  - id: architecture-conformance.membership.backend_core_types
    module_prefix: agentkit.backend.core_types
    unit: subpackage
    distribution: core
    classification: SPLIT-PACKAGE
    decided_by: E3
    measured_evidence: >-
      20 modules, 112 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      shared domain core types of the core runtime.
    prefix_exceptions:
      - module: agentkit.backend.core_types.mcp_server_registration
        distribution: edge
        decided_by: E3
        witness: >-
          FK-10 lines 119-122 -- the cut follows the RUNTIME OWNER, not the
          historical namespace, "auch dann, wenn es heute unter backend/
          liegt". the module describes locally started MCP servers with
          concrete command, argument and environment shapes
          (mcp_server_registration.py:121-145 and 233-248), and all six productive
          importers are edge; no core importer exists.
        withdrawn_derivations: >-
          round 3 derived EDGE via E2 -- withdrawn, because E2 requires
          implementing a named console-script command path and this module
          implements none. round 4 derived CORE via FK-76 76.9 -- withdrawn,
          because that section normes only import directions between bounded
          contexts and says nothing about a BC-neutral foundation or about
          distribution membership; that wording came from the module
          docstring, not from the concept. the distinction "contract ABOUT a
          process" vs "its implementation" stays correct and still refutes the
          E2 derivation -- it simply does not carry a core assignment.
  - id: architecture-conformance.membership.backend_exceptions
    module_prefix: agentkit.backend.exceptions
    unit: root-module
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      1 module, 22 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: none.
    why_this_side: >-
      the fachliche exception families of the core.
  - id: architecture-conformance.membership.backend_execution_planning
    module_prefix: agentkit.backend.execution_planning
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      26 modules, 121 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      scheduling and execution planning are core orchestration.
  - id: architecture-conformance.membership.backend_exploration
    module_prefix: agentkit.backend.exploration
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E1
    measured_evidence: >-
      26 modules, 67 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 2 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      the exploration phase runs in the core.
  - id: architecture-conformance.membership.backend_failure_corpus
    module_prefix: agentkit.backend.failure_corpus
    unit: subpackage
    distribution: core
    classification: SPLIT-PACKAGE
    decided_by: E1
    measured_evidence: >-
      19 modules, 61 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 2 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      the failure corpus is canonical state owned by the core.
    prefix_exceptions:
      - module: agentkit.backend.failure_corpus.cli
        distribution: edge
        decided_by: E1
        witness: >-
          agentkit.harness_client.projectedge.client,agentkit.harness_client.projectedge.runtime
      - module: agentkit.backend.failure_corpus.writer_client
        distribution: edge
        decided_by: E1
        witness: >-
          agentkit.harness_client.projectedge.client
  - id: architecture-conformance.membership.backend_governance
    module_prefix: agentkit.backend.governance
    unit: subpackage
    distribution: core
    classification: SPLIT-PACKAGE
    decided_by: E1
    measured_evidence: >-
      75 modules, 264 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 3 edge, 1 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      PolicyEngine, IntegrityGate, principal capabilities and adjudication are core logic (FK-01 section 1.1a).
    prefix_exceptions:
      - module: agentkit.backend.governance.guard_evaluation
        distribution: edge
        decided_by: E1
        witness: >-
          agentkit.harness_client.projectedge.runtime
      - module: agentkit.backend.governance.rest_edge
        distribution: edge
        decided_by: E1
        witness: >-
          agentkit.harness_client.projectedge.governance_client
      - module: agentkit.backend.governance.runner
        distribution: edge
        decided_by: E1
        witness: >-
          agentkit.harness_client.projectedge.governance_client,agentkit.harness_client.projectedge.runtime
        witness_correction: >-
          AG3-239 removed a third witness that used to stand here,
          agentkit.harness_client.harness_adapters.settings_writer. It was
          produced by exactly ONE symbol of the module,
          Governance._materialise_harness_settings -- and that symbol is the one
          the AG3-239 symbol cut identified as core-side. An edge assignment
          decided partly by the witness of a core symbol is not wrong in its
          outcome here (the two remaining witnesses carry the hook dispatch on
          their own), but it was wrong in its evidence. See
          architecture-conformance.symbol_boundary.governance_runner.
      - module: agentkit.backend.governance.default_hook_definitions
        distribution: edge
        decided_by: E3
        witness: >-
          the hook definition set is materialised on the developer machine by the installer (installer/ccag_settings.py:32) and there is no normative statement making the default set a core function. round 2 called it the 'canonical default set' -- that was a reinterpretation of the counter-example, not an anchor, and it is withdrawn
  - id: architecture-conformance.membership.backend_implementation
    module_prefix: agentkit.backend.implementation
    unit: subpackage
    distribution: core
    classification: SPLIT-PACKAGE
    decided_by: E1
    measured_evidence: >-
      20 modules, 67 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 1 edge, 1 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      the implementation phase and its QA subflow run in the core.
    prefix_exceptions:
      - module: agentkit.backend.implementation.worker_health.rest_repository
        distribution: edge
        decided_by: E1
        witness: >-
          agentkit.harness_client.projectedge.governance_client
  - id: architecture-conformance.membership.backend_installer
    module_prefix: agentkit.backend.installer
    unit: subpackage
    distribution: edge
    classification: SPLIT-PACKAGE
    decided_by: E2
    measured_evidence: >-
      82 modules, 442 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 10 edge, 7 core, 0 both.
      third-party declared: hatchling, mcp, psutil, pydantic, yaml.
    why_this_side: >-
      register-project, verify-project and upgrade-project are edge command paths writing the developer machine.
    prefix_exceptions:
      - module: agentkit.backend.installer.integration_checkpoints.branch_plugin_self_test
        distribution: core
        decided_by: E1
        witness: >-
          agentkit.integration_clients.jenkins,agentkit.integration_clients.sonar
      - module: agentkit.backend.installer.integration_checkpoints.ci_preflight
        distribution: core
        decided_by: E1
        witness: >-
          agentkit.integration_clients.jenkins
      - module: agentkit.backend.installer.integration_checkpoints.jenkins_selftest_harness
        distribution: core
        decided_by: E1
        witness: >-
          agentkit.integration_clients.jenkins,agentkit.integration_clients.sonar
      - module: agentkit.backend.installer.integration_checkpoints.scanner_harness
        distribution: core
        decided_by: E1
        witness: >-
          agentkit.integration_clients.sonar
      - module: agentkit.backend.installer.integration_checkpoints.sonar_preflight
        distribution: core
        decided_by: E1
        witness: >-
          agentkit.integration_clients.sonar
      - module: agentkit.backend.installer.integration_checkpoints.sonar_probes
        distribution: core
        decided_by: E1
        witness: >-
          agentkit.integration_clients.sonar
      - module: agentkit.backend.installer.third_party_clients
        distribution: core
        decided_by: E1
        witness: >-
          agentkit.integration_clients.are,agentkit.integration_clients.jenkins,agentkit.integration_clients.sonar
  - id: architecture-conformance.membership.backend_integration_stabilization
    module_prefix: agentkit.backend.integration_stabilization
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      12 modules, 68 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      integration manifests and seam allowlists are core-adjudicated.
  - id: architecture-conformance.membership.backend_kpi_analytics
    module_prefix: agentkit.backend.kpi_analytics
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      26 modules, 94 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      KPI aggregation reads canonical telemetry.
  - id: architecture-conformance.membership.backend_phase_state_store
    module_prefix: agentkit.backend.phase_state_store
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      2 modules, 9 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: none.
    why_this_side: >-
      phase state is canonical state (I5).
  - id: architecture-conformance.membership.backend_pipeline_engine
    module_prefix: agentkit.backend.pipeline_engine
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      26 modules, 87 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      the pipeline executes in the core.
  - id: architecture-conformance.membership.backend_process
    module_prefix: agentkit.backend.process
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      10 modules, 48 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      process language and flow definitions drive core orchestration.
  - id: architecture-conformance.membership.backend_project
    module_prefix: agentkit.backend.project
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      1 module, 0 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: none.
    why_this_side: >-
      project namespace of the core runtime.
  - id: architecture-conformance.membership.backend_project_management
    module_prefix: agentkit.backend.project_management
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      12 modules, 53 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      ProjectManagement is a core-owned aggregate (FK-07 section 7.4.6).
  - id: architecture-conformance.membership.backend_project_ops
    module_prefix: agentkit.backend.project_ops
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      4 modules, 0 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: none.
    why_this_side: >-
      project operations namespace of the core runtime.
  - id: architecture-conformance.membership.backend_prompt_runtime
    module_prefix: agentkit.backend.prompt_runtime
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      11 modules, 67 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      prompt materialisation and the prompt bundle lock are core-side.
  - id: architecture-conformance.membership.backend_requirements_coverage
    module_prefix: agentkit.backend.requirements_coverage
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      9 modules, 36 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      coverage adjudication is a core judgement.
  - id: architecture-conformance.membership.backend_schemas
    module_prefix: agentkit.backend.schemas
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      1 module, 0 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: none.
    why_this_side: >-
      schema namespace of the core runtime.
  - id: architecture-conformance.membership.backend_skills
    module_prefix: agentkit.backend.skills
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E1
    measured_evidence: >-
      13 modules, 46 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 1 core, 0 both.
      third-party declared: packaging, pydantic.
    why_this_side: >-
      skill bundle store and version policy are core-owned.
  - id: architecture-conformance.membership.backend_state_backend
    module_prefix: agentkit.backend.state_backend
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E1
    measured_evidence: >-
      118 modules, 641 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 7 core, 0 both.
      third-party declared: psycopg, psycopg_pool.
    why_this_side: >-
      the canonical state store.
  - id: architecture-conformance.membership.backend_story
    module_prefix: agentkit.backend.story
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      4 modules, 8 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      story namespace of the core runtime.
  - id: architecture-conformance.membership.backend_story_context_manager
    module_prefix: agentkit.backend.story_context_manager
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      20 modules, 74 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      StoryContext is canonical state (I5).
  - id: architecture-conformance.membership.backend_story_creation
    module_prefix: agentkit.backend.story_creation
    unit: subpackage
    distribution: edge
    classification: SPLIT-MODULE
    decided_by: E2
    measured_evidence: >-
      11 modules, 32 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 5 edge, 1 core, 1 both.
      third-party declared: pydantic, yaml.
    why_this_side: >-
      the reconciler is built and executed locally and speaks Weaviate directly (carve-out FK-01 section 1.1a).
    prefix_exceptions:
      - module: agentkit.backend.story_creation.runtime_factory
        distribution: split
        decided_by: E1
        witness: >-
          agentkit.integration_clients.vectordb
  - id: architecture-conformance.membership.backend_story_exit
    module_prefix: agentkit.backend.story_exit
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      4 modules, 16 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      the story exit decision is a core judgement.
  - id: architecture-conformance.membership.backend_story_reset
    module_prefix: agentkit.backend.story_reset
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      5 modules, 28 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      the story reset decision is a core judgement.
  - id: architecture-conformance.membership.backend_story_split
    module_prefix: agentkit.backend.story_split
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      6 modules, 25 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      the story split decision is a core judgement.
  - id: architecture-conformance.membership.backend_task_management
    module_prefix: agentkit.backend.task_management
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      6 modules, 19 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      task decomposition is core orchestration.
  - id: architecture-conformance.membership.backend_telemetry
    module_prefix: agentkit.backend.telemetry
    unit: subpackage
    distribution: core
    classification: SPLIT-PACKAGE
    decided_by: E1
    measured_evidence: >-
      35 modules, 81 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 1 edge, 0 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      canonical telemetry is core-owned state.
    prefix_exceptions:
      - module: agentkit.backend.telemetry.rest_emitter
        distribution: edge
        decided_by: E1
        witness: >-
          agentkit.harness_client.projectedge.governance_client
  - id: architecture-conformance.membership.backend_telemetry_service
    module_prefix: agentkit.backend.telemetry_service
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      5 modules, 0 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: none.
    why_this_side: >-
      telemetry service namespace of the core runtime.
  - id: architecture-conformance.membership.backend_utils
    module_prefix: agentkit.backend.utils
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      2 modules, 6 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: yaml.
    why_this_side: >-
      core-side helpers; each distribution carries its own copy under its own import root (FK-10 section D, as for utils.io).
  - id: architecture-conformance.membership.backend_vectordb
    module_prefix: agentkit.backend.vectordb
    unit: subpackage
    distribution: edge
    classification: EDGE
    decided_by: E2
    measured_evidence: >-
      32 modules, 187 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 18 edge, 0 core, 0 both.
      third-party declared: mcp, pydantic, yaml.
    why_this_side: >-
      the story-knowledge MCP server, the ingest and the concept corpus builder run on the developer machine (FK-13 section 13.4, F3).
  - id: architecture-conformance.membership.backend_verify_system
    module_prefix: agentkit.backend.verify_system
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E1
    measured_evidence: >-
      117 modules, 418 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 8 core, 0 both.
      third-party declared: pydantic.
    why_this_side: >-
      the four QA layers, the stage registry and the Sonar/Jenkins gates are core judgements (FK-33).
  - id: architecture-conformance.membership.backend_workers
    module_prefix: agentkit.backend.workers
    unit: subpackage
    distribution: core
    classification: CORE
    decided_by: E3
    measured_evidence: >-
      9 modules, 0 public module-level symbols,
      AST-measured 2026-08-07. modules of THIS package with a direct anchor
      contact: 0 edge, 0 core, 0 both.
      third-party declared: none.
    why_this_side: >-
      worker orchestration is core-side.

# ---------------------------------------------------------------------------
# Zielmodule des Vertragspakets (AC 4/AC 5)
#
# 181 qualifizierende beidseitige Vertragssymbole = 95 wandernde
# Wurzelsymbole + 28 zurueckgestellte + 58 ausgeschlossene.
# Die Huellenschliessung zieht 23 modul-interne Datentypen nach, die selbst
# keine Grenzueberquerer sind -- Endbestand 118 Symbole.
#
# Die Huelle wird REEXPORT-AUFLOESEND gelaufen: ein ueber ein Paket-__init__
# re-exportiertes Symbol wird bis zu seinem definierenden Modul verfolgt.
# Ohne diese Aufloesung wurde `FailureCategory` (ueber core_types/__init__)
# stillschweigend uebersprungen und zwei Failure-Corpus-Nutzlasten galten zu
# Unrecht als geschlossen -- sie haetten einen Wire->Kern-Import hinterlassen.
# ---------------------------------------------------------------------------
wire_hull_algorithm:
  id: architecture-conformance.algorithm.reexport_resolving_fixpoint
  # Ohne diese Beschreibung ist `hull_closed: true` eine Behauptung. Der
  # Huellen-Bug der zweiten Runde war genau ein stilles Weitergehen bei einer
  # Bindung, die der Walker nicht aufloesen konnte -- deshalb ist Punkt 6 die
  # wichtigste Zeile hier.
  input: one public module-level symbol
  hull_edges: >-
    the names referenced anywhere inside the symbol's AST node: base classes,
    decorators, type annotations (including pydantic field annotations),
    default values, default_factory arguments, and every Name or Attribute
    root in the body. a dotted Attribute contributes its leftmost Name.
  string_forward_refs: >-
    every string constant inside the node is tokenised on identifier
    boundaries and each token is treated as a candidate reference. this
    over-approximates and is deliberate: over-approximation defers a symbol,
    under-approximation ships a broken one.
  alias_resolution: >-
    an `as` alias binds the local name to its import target; the local name is
    resolved through the module's import table before the hull edge is formed.
  type_checking_and_conditional_imports: >-
    imports under `if TYPE_CHECKING:` and inside function bodies are collected
    exactly like module-level imports. an annotation-only dependency still
    forces the depended-on type into the wire package, so excluding them would
    understate the hull.
  reexport_resolution: >-
    if the imported module does not DEFINE the name, the walker follows the
    name through that module's own import table to the module that defines it,
    up to 8 hops. without this, a symbol re-exported through a package
    __init__ is invisible -- the defect that let FailureCategory through
    core_types/__init__ and marked two failure-corpus payloads closed when
    they would have left a wire-to-core import.
  private_names: >-
    a name with a leading underscore is not a counted symbol. it does not
    become a migration root, but it IS walked, and it is recorded in
    wire_private_bindings.
  fixpoint: >-
    deferral iterates until no symbol changes state. a symbol whose hull
    reached a symbol deferred in an earlier pass must be re-examined.
  unresolved_binding_is_fail_closed: >-
    a binding the walker cannot resolve -- star import, dynamic export,
    computed attribute, ambiguous name -- BLOCKS the symbol. it is deferred
    with reason `unresolved-binding`, never silently skipped. measured
    2026-08-07 over the touched modules: no star import and no module-level
    __getattr__ occurs in them, so this branch did not fire; it exists because
    the silent-skip variant is exactly what failed before.
  ambiguity: >-
    if two candidate definitions carry the same name in one resolution chain,
    the symbol is deferred rather than resolved by preference order.
wire_target_modules:
  - id: architecture-conformance.wire_module.control_plane_mutations
    target_module: agentkit_wire.control_plane_mutations
    why_both_sides: >-
      request and result models of the /v1 mutation endpoints
    symbol_count: 23
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.control_plane.models
        symbols:
          - AdminAbortRequest
          - ApiErrorResponse
          - CommandErrorResult
          - ControlPlaneMutationResult
          - CreatedStorySummary
          - FreezeConflictDetail  # pulled in by hull closure
          - GuardCounterMutationAccepted
          - GuardCounterMutationRequest
          - OwnershipTransferredDetail  # pulled in by hull closure
          - PendingHumanApprovalResponse  # pulled in by hull closure
          - PhaseDispatchResult  # pulled in by hull closure
          - RecoveryRequest
          - TakeoverApprovalView  # pulled in by hull closure
          - TakeoverChallenge  # pulled in by hull closure
          - TakeoverConfirmRequest
          - TakeoverErrorResult
          - TakeoverQuarantineDetail
          - TakeoverReconcileReportedResult  # pulled in by hull closure
          - TakeoverReconcileResponse  # pulled in by hull closure
          - TakeoverReconcileResultView  # pulled in by hull closure
          - TakeoverReconcileWorktreeRequest
          - TakeoverRepoChallenge  # pulled in by hull closure
          - TakeoverRequest
  - id: architecture-conformance.wire_module.edge_commands
    target_module: agentkit_wire.edge_commands
    why_both_sides: >-
      the core issues the edge command, the edge executes it and reports back
    symbol_count: 23
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.control_plane.models
        symbols:
          - EdgeBundle
          - EdgeCommandMutationResult
          - EdgeCommandView
          - EdgeFreezeStateView
          - EdgePointer
          - MergeLocalCommandPayload
          - MergeLocalRepoReport
          - MergeLocalReport
          - MergeLocalRepository  # pulled in by hull closure
          - OpenEdgeCommandsResponse
          - PreflightProbeCommandPayload
          - PreflightProbeReport
          - ProjectEdgeSyncRequest
          - ProvisionWorktreeCommandPayload
          - PushOwnershipConfirmation
          - PushStatusReport
          - ResetWorktreeCommandPayload
          - SessionRunBindingView  # pulled in by hull closure
          - StoryExecutionLockView  # pulled in by hull closure
          - SyncPushCommandPayload
          - TakeoverReconcileCommandPayload
          - TeardownWorktreeCommandPayload
          - WorktreeReport
  - id: architecture-conformance.wire_module.errors
    target_module: agentkit_wire.errors
    why_both_sides: >-
      the error contract of the /v1 boundary: the core raises it, the edge reads it
    symbol_count: 2
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.exceptions
        symbols:
          - AgentKitError
          - ControlPlaneApiError
  - id: architecture-conformance.wire_module.failure_corpus
    target_module: agentkit_wire.failure_corpus
    why_both_sides: >-
      review and effectiveness payloads of /v1
    symbol_count: 15
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.core_types.failure_corpus
        symbols:
          - FailureCategory  # pulled in by hull closure
      - from_module: agentkit.backend.failure_corpus.http_models
        symbols:
          - FailureCorpusCheckReviewRequest
          - FailureCorpusCheckReviewResponse
          - FailureCorpusEffectivenessRequest
          - FailureCorpusEffectivenessResponse
          - FailureCorpusIncidentMutationRequest
          - FailureCorpusIncidentMutationResponse
          - FailureCorpusPatternReviewRequest
          - FailureCorpusPatternReviewResponse
      - from_module: agentkit.backend.failure_corpus.pattern
        symbols:
          - PatternRiskLevel  # pulled in by hull closure
          - PromotionRule  # pulled in by hull closure
      - from_module: agentkit.backend.failure_corpus.top
        symbols:
          - CheckApprovalDecision  # pulled in by hull closure
          - PatternDecision  # pulled in by hull closure
      - from_module: agentkit.backend.failure_corpus.types
        symbols:
          - IncidentRole  # pulled in by hull closure
          - IncidentSeverity  # pulled in by hull closure
  - id: architecture-conformance.wire_module.governance_registration
    target_module: agentkit_wire.governance_registration
    why_both_sides: >-
      hook REGISTRATION travels over /v1; the guard DECISION does not
    symbol_count: 2
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.governance.hook_registration
        symbols:
          - HookDefinition
          - HookEventName
  - id: architecture-conformance.wire_module.installer_registration
    target_module: agentkit_wire.installer_registration
    why_both_sides: >-
      the edge registers, the core records
    symbol_count: 15
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.installer.http_models
        symbols:
          - GovernanceHookClearRequest
          - GovernanceHookListResponse
          - GovernanceHookRegistrationRequest
          - GovernanceHookRegistrationResponse
          - InstallerWriterReadyResponse
          - ProjectRegistrationListResponse
          - ProjectRegistrationMutationResponse
          - ProjectRegistrationReadResponse
          - ProjectRegistrationUpgradeRequest
          - SkillBindingDeleteRequest
          - SkillBindingListResponse
          - SkillBindingMutationResponse
          - SkillBindingReadResponse
      - from_module: agentkit.backend.installer.registration
        symbols:
          - CheckpointStatus
          - RuntimeProfile
  - id: architecture-conformance.wire_module.operating_mode
    target_module: agentkit_wire.operating_mode
    why_both_sides: >-
      an enumeration transported on the wire and interpreted on both sides
    symbol_count: 1
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.core_types.operating_mode
        symbols:
          - OperatingMode
  - id: architecture-conformance.wire_module.project_config
    target_module: agentkit_wire.project_config
    why_both_sides: >-
      payload of the registration and update endpoints
    symbol_count: 11
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.config.defaults
        symbols:
          - DEFAULT_MAX_FEEDBACK_ROUNDS
          - DEFAULT_MAX_REMEDIATION_ROUNDS
          - DEFAULT_STORY_TYPES
          - DEFAULT_VERIFY_LAYERS
      - from_module: agentkit.backend.config.models
        symbols:
          - JenkinsConfig
          - SUPPORTED_CONFIG_VERSION
          - SonarQubeBranchPluginConfig  # pulled in by hull closure
          - SonarQubeConfig
          - SonarQubePluginsConfig  # pulled in by hull closure
          - SonarQubeQualityGateConfig  # pulled in by hull closure
          - TelemetryConfig
  - id: architecture-conformance.wire_module.story_lifecycle
    target_module: agentkit_wire.story_lifecycle
    why_both_sides: >-
      exit, reset and split are spoken on the wire by both sides
    symbol_count: 6
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.story_exit.http_models
        symbols:
          - StoryExitMutationRequest
          - StoryExitMutationResponse
      - from_module: agentkit.backend.story_reset.http_models
        symbols:
          - StoryResetMutationRequest
          - StoryResetMutationResponse
      - from_module: agentkit.backend.story_split.http_models
        symbols:
          - StorySplitMutationRequest
          - StorySplitMutationResponse
  - id: architecture-conformance.wire_module.telemetry_ingest
    target_module: agentkit_wire.telemetry_ingest
    why_both_sides: >-
      the edge emits events, the core stores and answers them
    symbol_count: 5
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.control_plane.models
        symbols:
          - TelemetryEventAccepted
          - TelemetryEventIngestRequest
          - TelemetryEventQueryResponse
      - from_module: agentkit.backend.telemetry.contract.results
        symbols:
          - TelemetryScope
      - from_module: agentkit.backend.telemetry.events
        symbols:
          - EventType
  - id: architecture-conformance.wire_module.third_party_validation
    target_module: agentkit_wire.third_party_validation
    why_both_sides: >-
      the third-party validation contract of /v1
    symbol_count: 8
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.control_plane.third_party_models
        symbols:
          - AreValidationConfig
          - BranchPluginSelfTestOperation
          - BranchPluginSelfTestRequest
          - CiValidationConfig
          - SonarValidationConfig
          - ThirdPartySystemResult
          - ThirdPartyValidationRequest
          - ThirdPartyValidationResponse
  - id: architecture-conformance.wire_module.verify_evidence
    target_module: agentkit_wire.verify_evidence
    why_both_sides: >-
      the edge collects evidence, the core evaluates it
    symbol_count: 4
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.core_types.verify_evidence
        symbols:
          - MAX_EVIDENCE_FILE_BYTES
          - MAX_EVIDENCE_RESULT_BYTES
          - VerifyEvidenceObservationStatus
          - VerifyEvidenceStage
  - id: architecture-conformance.wire_module.worker_health
    target_module: agentkit_wire.worker_health
    why_both_sides: >-
      the edge sidecar reports, the core adjudicates
    symbol_count: 3
    hull_closed: true
    hull_closure_method: reexport-resolving-fixpoint
    receives:
      - from_module: agentkit.backend.control_plane.models
        symbols:
          - WorkerHealthSaveAccepted
          - WorkerHealthStateResponse
          - WorkerHealthStoryResponse
wire_target_symbol_total: 118
wire_hull_addition_total: 23
wire_deferred_symbols:
  - id: architecture-conformance.wire_deferred.config_models
    module: agentkit.backend.config.models
    symbols:
      - symbol: ProjectConfig
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.config.models.OrchestratorGuardConfig"
      - symbol: VectorDbConfig
        hull_blocker: "forbidden stdlib urllib via agentkit.backend.config.models.VectorDbConfig"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.control_plane_models
    module: agentkit.backend.control_plane.models
    symbols:
      - symbol: CreateStoryInputs
        hull_blocker: "hull crosses to edge: agentkit.backend.story_creation.reconciliation_evidence.ReconciliationEvidence"
      - symbol: CreateStoryRequest
        hull_blocker: "hull crosses to edge: agentkit.backend.story_creation.reconciliation_evidence.ReconciliationEvidence"
      - symbol: EdgeCommandResultPayload
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.core_types.verify_evidence._validated_relative_path"
      - symbol: EdgeCommandResultRequest
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.core_types.verify_evidence._validated_relative_path"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.core_types_verify_evidence
    module: agentkit.backend.core_types.verify_evidence
    symbols:
      - symbol: CollectVerifyEvidenceCommandPayload
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.core_types.verify_evidence._validated_relative_path"
      - symbol: VerifyEvidenceFile
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.core_types.verify_evidence._validated_relative_path"
      - symbol: VerifyEvidenceObservation
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.core_types.verify_evidence._validated_relative_path"
      - symbol: VerifyEvidenceReport
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.core_types.verify_evidence._validated_relative_path"
      - symbol: VerifyEvidenceRepository
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.core_types.verify_evidence._validated_relative_path"
      - symbol: VerifyEvidenceRequest
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.core_types.verify_evidence._validate_test_target"
      - symbol: VerifyTestCommand
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.core_types.verify_evidence._validate_test_target"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.governance_errors
    module: agentkit.backend.governance.errors
    symbols:
      - symbol: HookRegistrationError
        hull_blocker: "not proven as /v1 vocabulary (review round 2)"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.governance_guard_evaluation
    module: agentkit.backend.governance.guard_evaluation
    symbols:
      - symbol: HookEvent
        hull_blocker: "not proven as /v1 vocabulary (review round 2)"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.governance_guard_system_records
    module: agentkit.backend.governance.guard_system.records
    symbols:
      - symbol: GuardDecisionOutcome
        hull_blocker: "not proven as /v1 vocabulary (review round 2)"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.governance_hook_ids
    module: agentkit.backend.governance.hook_ids
    symbols:
      - symbol: POST_HOOK_IDS
        hull_blocker: "local dispatch/validation logic (governance/hook_ids.py:5), not a contract field"
      - symbol: PRE_HOOK_IDS
        hull_blocker: "local dispatch/validation logic (governance/hook_ids.py:5), not a contract field"
      - symbol: SUPPORTED_HOOK_IDS
        hull_blocker: "local dispatch/validation logic (governance/hook_ids.py:5), not a contract field"
      - symbol: SUPPORTED_PHASES
        hull_blocker: "local dispatch/validation logic (governance/hook_ids.py:5), not a contract field"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.governance_hook_registration
    module: agentkit.backend.governance.hook_registration
    symbols:
      - symbol: HookId
        hull_blocker: "local dispatch/validation logic (governance/hook_ids.py:5), not a contract field"
      - symbol: RegistrationResult
        hull_blocker: "hull reaches behaviour (exception): agentkit.backend.governance.errors.HookRegistrationError"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.governance_protocols
    module: agentkit.backend.governance.protocols
    symbols:
      - symbol: ViolationType
        hull_blocker: "not proven as /v1 vocabulary (review round 2)"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.implementation_worker_health_models
    module: agentkit.backend.implementation.worker_health.models
    symbols:
      - symbol: AgentHealthState
        hull_blocker: "hull reaches behaviour (function): agentkit.backend.implementation.worker_health.models.utc_now"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.installer_http_models
    module: agentkit.backend.installer.http_models
    symbols:
      - symbol: RegisterProjectStateRequest
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.installer.http_models.RegisterProjectStateRequest"
      - symbol: SkillBindingWriteRequest
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.installer.http_models.SkillBindingWriteRequest"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.installer_registration
    module: agentkit.backend.installer.registration
    symbols:
      - symbol: ProjectRegistration
        hull_blocker: "forbidden stdlib pathlib via agentkit.backend.installer.registration.ProjectRegistration"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
  - id: architecture-conformance.wire_deferred.story_creation_reconciliation_evidence
    module: agentkit.backend.story_creation.reconciliation_evidence
    symbols:
      - symbol: ReconciliationEvidence
        hull_blocker: "hull crosses to core: agentkit.backend.verify_system.llm_evaluator.roles.LlmVerdict"
    ag3_209_precondition: >-
      decompose before the symbol can migrate: replace Path-typed wire
      fields with strings validated in the core, and move behaviour out of
      the payload type. until then the symbol stays with its current side.
wire_deferred_symbol_total: 28
# ---------------------------------------------------------------------------
# UEBERHOLT UND OHNE AUTORITAET (AG3-237, Stand bei Storyschluss)
#
# `wire_excluded_crossings`, `wire_excluded_symbol_total` und
# `wire_qualifying_symbol_total` sind NICHT nachgezogen worden, nachdem
# `core_types.mcp_server_registration` zur Edge-Distribution gewechselt ist.
# Sie gelten nicht. Wer sie liest, liest einen ueberholten Stand.
#
# ZWEI GEMESSENE GRUENDE:
#
# 1. Die zehn Symbole aus `agentkit.backend.core_types.mcp_server_registration`
#    stehen unten mit Besitzer `core` und behaupteter Grenzverletzung. Das
#    Modul ist inzwischen Edge, und alle sechs Importeure sind ebenfalls Edge
#    -- sie ueberqueren keine Grenze mehr. Die Ausschlussbegruendung trifft
#    damit auf keines dieser zehn Symbole zu.
#
# 2. Sechs weitere, schon vorher gespeicherte Ausschluesse haben ueberhaupt
#    keinen Importeur auf der Gegenseite: `LoopbackBindHostError`, die drei
#    `CORE_*_PORT`-Konstanten, `StoryContext` und `StoryType`. Sie waren nie
#    Grenzueberquerer und gehoeren nicht in eine Liste von Ausschluessen aus
#    der Menge der Grenzueberquerer.
#
# WARUM HIER NICHT NACHGERECHNET WIRD: eine Teilkorrektur auf 48 oder 42 waere
# genau der halbe Schritt, der diese Story fuenf Reviewrunden gekostet hat. Die
# Population wird VOLLSTAENDIG neu abgeleitet, und zwar von AG3-209.
#
# UNBERUEHRT UND WEITERHIN GUELTIG: die 118er-Huelle. `wire_target_modules`,
# `wire_target_symbol_total`, `wire_hull_addition_total`,
# `wire_deferred_symbols` und `wire_private_bindings` sind gegen den
# veroeffentlichten Stand geprueft und geschlossen. Der Ueberholt-Vermerk
# betrifft ausschliesslich die drei unten benannten Felder.
# ---------------------------------------------------------------------------
wire_excluded_crossings_status: superseded-no-authority
wire_excluded_crossings_owner: AG3-209
wire_excluded_crossings:
  - id: architecture-conformance.wire_excluded.boundary_network
    module: agentkit.backend.boundary.network
    symbols:
      - LoopbackBindHostError
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.code_backend_provider_port
    module: agentkit.backend.code_backend.provider_port
    symbols:
      - StoryRefWriteCredentialClass
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.config_defaults
    module: agentkit.backend.config.defaults
    symbols:
      - CORE_PROJECT_API_PORT
      - CORE_UI_BFF_PORT
      - CORE_UI_PORT
      - DEFAULT_CONFIG_DIR
      - DEFAULT_CONFIG_FILE
      - DEFAULT_CONTROL_PLANE_BASE_URL
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.control_plane_writer_lease
    module: agentkit.backend.control_plane.writer_lease
    symbols:
      - ControlPlaneWriterAlreadyActiveError
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.core_types_mcp_server_registration
    module: agentkit.backend.core_types.mcp_server_registration
    symbols:
      - AK3_MCP_SERVER_NAMES
      - AK3_SERVER_SHAPES
      - ARE_MCP_SERVER
      - ARE_MCP_SERVER_ENV_KEY
      - ARE_MCP_WRAPPER_NAME
      - CODEX_HOOK_WRAPPER_NAME
      - MCP_JSON_STDIO_TYPE
      - McpServerRegistrationError
      - REGISTERED_ENV_KEYS
      - STORY_KNOWLEDGE_BASE_SERVER
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.core_types_plane_artifact_names
    module: agentkit.backend.core_types.plane_artifact_names
    symbols:
      - AGENT_SPAWN_SKILL_PROOF_KEY
      - INSTALLED_MANIFEST_FILENAME
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.core_types_qa_artifact_names
    module: agentkit.backend.core_types.qa_artifact_names
    symbols:
      - CHANGE_FRAME_FILE
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.exceptions
    module: agentkit.backend.exceptions
    symbols:
      - ConfigError
      - ConflictAdjudicationUnavailableError
      - InstallationError
      - ProjectError
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.governance_errors
    module: agentkit.backend.governance.errors
    symbols:
      - LockRecordNotFoundError
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.governance_locks
    module: agentkit.backend.governance.locks
    symbols:
      - DeactivationResult
      - LockRecordId
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.governance_principal_capabilities_operations
    module: agentkit.backend.governance.principal_capabilities.operations
    symbols:
      - WEB_FETCH
      - WEB_SEARCH
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.installer_paths
    module: agentkit.backend.installer.paths
    symbols:
      - QA_DIR
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (edge) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.installer_third_party_errors
    module: agentkit.backend.installer.third_party_errors
    symbols:
      - ThirdPartyOperationConflictError
      - ThirdPartyServiceUnavailableError
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (edge) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.installer_writer_service
    module: agentkit.backend.installer.writer_service
    symbols:
      - InstallerMigrationWitnessError
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (edge) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.integration_stabilization_state
    module: agentkit.backend.integration_stabilization.state
    symbols:
      - IS_MANIFEST_FILE
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.process_language_model
    module: agentkit.backend.process.language.model
    symbols:
      - FlowLevel
      - NodeKind
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.project_management_entities
    module: agentkit.backend.project_management.entities
    symbols:
      - ProjectConfiguration
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.skills_errors
    module: agentkit.backend.skills.errors
    symbols:
      - SkillBindingFailedError
      - SkillBindingPartialStateError
      - SkillBundleNotFoundError
      - SkillError
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.story_context_manager_models
    module: agentkit.backend.story_context_manager.models
    symbols:
      - StoryContext
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.story_context_manager_story_model
    module: agentkit.backend.story_context_manager.story_model
    symbols:
      - CreateStoryInput
      - Story
      - StorySpecification
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.story_context_manager_types
    module: agentkit.backend.story_context_manager.types
    symbols:
      - StoryType
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.story_split_plan_loader
    module: agentkit.backend.story_split.plan_loader
    symbols:
      - SplitPlanError
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.telemetry_audit_bundle
    module: agentkit.backend.telemetry.audit_bundle
    symbols:
      - AuditBundleExportError
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.telemetry_hooks_base
    module: agentkit.backend.telemetry.hooks.base
    symbols:
      - HookContext
      - HookTrigger
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.verify_system_llm_evaluator_bundle
    module: agentkit.backend.verify_system.llm_evaluator.bundle
    symbols:
      - ReviewBundle
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.verify_system_llm_evaluator_llm_client
    module: agentkit.backend.verify_system.llm_evaluator.llm_client
    symbols:
      - LlmClientError
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.verify_system_llm_evaluator_roles
    module: agentkit.backend.verify_system.llm_evaluator.roles
    symbols:
      - LlmVerdict
      - ReviewerRole
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.verify_system_llm_evaluator_structured_evaluator
    module: agentkit.backend.verify_system.llm_evaluator.structured_evaluator
    symbols:
      - StructuredEvaluatorResult
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
  - id: architecture-conformance.wire_excluded.verify_system_protocols
    module: agentkit.backend.verify_system.protocols
    symbols:
      - TrustClass
    why_not_wire: >-
      not /v1 payload vocabulary: the symbol belongs to the executing owner
      (core) and its cross-side use is a boundary violation
      on the AG3-209 work list, not a contract.
# UEBERHOLT -- siehe wire_excluded_crossings_status. Nicht verwenden.
wire_excluded_symbol_total: 58
# UEBERHOLT -- siehe wire_excluded_crossings_status. Die 181 setzt sich aus
# 95 + 28 + 58 zusammen; mit dem ueberholten 58er-Summanden traegt auch diese
# Zahl nicht mehr. Die 95 wandernden Wurzelsymbole und die 28 Zurueckgestellten
# sind davon NICHT betroffen -- sie sind Teil der geprueften 118er-Huelle.
wire_qualifying_symbol_total: 181
# 3 Namen der Rohkandidatenliste sind KEINE gezaehlten Symbole und deshalb
# nirgends oben gefuehrt: `agentkit.__version__` liegt ausserhalb von
# backend/, `_AGENT_TOOL` und `_MANIFEST_SKILL_PROOF_KEY` tragen einen
# fuehrenden Unterstrich (distribution_counting_unit).
distribution_symbol_boundaries:
  # Module, die Symbole an das Vertragspaket verlieren. `split_required:
  # false` heisst NICHT `kein Schnitt noetig` -- es heisst, dass die gesamte
  # oeffentliche Oberflaeche wandert und das Quellmodul verschwindet.
  - id: architecture-conformance.symbol_boundary.config_defaults
    module: agentkit.backend.config.defaults
    split_required: true
    public_symbols: 11
    wire_target_modules:
      - agentkit_wire.project_config
    wire_exported_symbols:
      - DEFAULT_MAX_FEEDBACK_ROUNDS
      - DEFAULT_MAX_REMEDIATION_ROUNDS
      - DEFAULT_STORY_TYPES
      - DEFAULT_VERIFY_LAYERS
    remainder_distribution: core
    remainder_symbols: 7
    core_symbols:
      - CORE_LOOPBACK_HOST
      - CORE_PROJECT_API_PORT
      - CORE_UI_BFF_PORT
      - CORE_UI_PORT
      - DEFAULT_CONFIG_DIR
      - DEFAULT_CONFIG_FILE
      - DEFAULT_CONTROL_PLANE_BASE_URL
  - id: architecture-conformance.symbol_boundary.config_models
    module: agentkit.backend.config.models
    split_required: true
    public_symbols: 24
    wire_target_modules:
      - agentkit_wire.project_config
    wire_exported_symbols:
      - JenkinsConfig
      - SUPPORTED_CONFIG_VERSION
      - SonarQubeBranchPluginConfig
      - SonarQubeConfig
      - SonarQubePluginsConfig
      - SonarQubeQualityGateConfig
      - TelemetryConfig
    remainder_distribution: core
    remainder_symbols: 17
  - id: architecture-conformance.symbol_boundary.control_plane_models
    module: agentkit.backend.control_plane.models
    split_required: true
    public_symbols: 68
    wire_target_modules:
      - agentkit_wire.control_plane_mutations
      - agentkit_wire.edge_commands
      - agentkit_wire.telemetry_ingest
      - agentkit_wire.worker_health
    wire_exported_symbols:
      - AdminAbortRequest
      - ApiErrorResponse
      - CommandErrorResult
      - ControlPlaneMutationResult
      - CreatedStorySummary
      - EdgeBundle
      - EdgeCommandMutationResult
      - EdgeCommandView
      - EdgeFreezeStateView
      - EdgePointer
      - FreezeConflictDetail
      - GuardCounterMutationAccepted
      - GuardCounterMutationRequest
      - MergeLocalCommandPayload
      - MergeLocalRepoReport
      - MergeLocalReport
      - MergeLocalRepository
      - OpenEdgeCommandsResponse
      - OwnershipTransferredDetail
      - PendingHumanApprovalResponse
      - PhaseDispatchResult
      - PreflightProbeCommandPayload
      - PreflightProbeReport
      - ProjectEdgeSyncRequest
      - ProvisionWorktreeCommandPayload
      - PushOwnershipConfirmation
      - PushStatusReport
      - RecoveryRequest
      - ResetWorktreeCommandPayload
      - SessionRunBindingView
      - StoryExecutionLockView
      - SyncPushCommandPayload
      - TakeoverApprovalView
      - TakeoverChallenge
      - TakeoverConfirmRequest
      - TakeoverErrorResult
      - TakeoverQuarantineDetail
      - TakeoverReconcileCommandPayload
      - TakeoverReconcileReportedResult
      - TakeoverReconcileResponse
      - TakeoverReconcileResultView
      - TakeoverReconcileWorktreeRequest
      - TakeoverRepoChallenge
      - TakeoverRequest
      - TeardownWorktreeCommandPayload
      - TelemetryEventAccepted
      - TelemetryEventIngestRequest
      - TelemetryEventQueryResponse
      - WorkerHealthSaveAccepted
      - WorkerHealthStateResponse
      - WorkerHealthStoryResponse
      - WorktreeReport
    remainder_distribution: core
    remainder_symbols: 16
  - id: architecture-conformance.symbol_boundary.control_plane_third_party_models
    module: agentkit.backend.control_plane.third_party_models
    split_required: false
    public_symbols: 8
    wire_target_modules:
      - agentkit_wire.third_party_validation
    wire_exported_symbols:
      - AreValidationConfig
      - BranchPluginSelfTestOperation
      - BranchPluginSelfTestRequest
      - CiValidationConfig
      - SonarValidationConfig
      - ThirdPartySystemResult
      - ThirdPartyValidationRequest
      - ThirdPartyValidationResponse
    module_dissolves: true
  - id: architecture-conformance.symbol_boundary.core_types_failure_corpus
    module: agentkit.backend.core_types.failure_corpus
    split_required: true
    public_symbols: 5
    wire_target_modules:
      - agentkit_wire.failure_corpus
    wire_exported_symbols:
      - FailureCategory
    remainder_distribution: core
    remainder_symbols: 4
    core_symbols:
      - CheckStatus
      - CheckType
      - IncidentStatus
      - PatternStatus
  - id: architecture-conformance.symbol_boundary.core_types_operating_mode
    module: agentkit.backend.core_types.operating_mode
    split_required: false
    public_symbols: 1
    wire_target_modules:
      - agentkit_wire.operating_mode
    wire_exported_symbols:
      - OperatingMode
    module_dissolves: true
  - id: architecture-conformance.symbol_boundary.core_types_verify_evidence
    module: agentkit.backend.core_types.verify_evidence
    split_required: true
    public_symbols: 15
    wire_target_modules:
      - agentkit_wire.verify_evidence
    wire_exported_symbols:
      - MAX_EVIDENCE_FILE_BYTES
      - MAX_EVIDENCE_RESULT_BYTES
      - VerifyEvidenceObservationStatus
      - VerifyEvidenceStage
    remainder_distribution: core
    remainder_symbols: 11
    core_symbols:
      - CollectVerifyEvidenceCommandPayload
      - SHA256_PATTERN
      - VERIFY_EVIDENCE_RESULT_TYPE
      - VERIFY_EVIDENCE_SCHEMA_VERSION
      - VerifyEvidenceCanonicalRequest
      - VerifyEvidenceFile
      - VerifyEvidenceObservation
      - VerifyEvidenceReport
      - VerifyEvidenceRepository
      - VerifyEvidenceRequest
      - VerifyTestCommand
  - id: architecture-conformance.symbol_boundary.exceptions
    module: agentkit.backend.exceptions
    split_required: true
    public_symbols: 22
    wire_target_modules:
      - agentkit_wire.errors
    wire_exported_symbols:
      - AgentKitError
      - ControlPlaneApiError
    remainder_distribution: core
    remainder_symbols: 20
  - id: architecture-conformance.symbol_boundary.failure_corpus_http_models
    module: agentkit.backend.failure_corpus.http_models
    split_required: false
    public_symbols: 8
    wire_target_modules:
      - agentkit_wire.failure_corpus
    wire_exported_symbols:
      - FailureCorpusCheckReviewRequest
      - FailureCorpusCheckReviewResponse
      - FailureCorpusEffectivenessRequest
      - FailureCorpusEffectivenessResponse
      - FailureCorpusIncidentMutationRequest
      - FailureCorpusIncidentMutationResponse
      - FailureCorpusPatternReviewRequest
      - FailureCorpusPatternReviewResponse
    module_dissolves: true
  - id: architecture-conformance.symbol_boundary.failure_corpus_pattern
    module: agentkit.backend.failure_corpus.pattern
    split_required: true
    public_symbols: 3
    wire_target_modules:
      - agentkit_wire.failure_corpus
    wire_exported_symbols:
      - PatternRiskLevel
      - PromotionRule
    remainder_distribution: core
    remainder_symbols: 1
    core_symbols:
      - FailurePatternRecord
  - id: architecture-conformance.symbol_boundary.failure_corpus_top
    module: agentkit.backend.failure_corpus.top
    split_required: true
    public_symbols: 7
    wire_target_modules:
      - agentkit_wire.failure_corpus
    wire_exported_symbols:
      - CheckApprovalDecision
      - PatternDecision
    remainder_distribution: core
    remainder_symbols: 5
    core_symbols:
      - CheckProposal
      - EffectivenessReport
      - FailureCorpus
      - FailurePattern
      - PatternCandidate
  - id: architecture-conformance.symbol_boundary.failure_corpus_types
    module: agentkit.backend.failure_corpus.types
    split_required: true
    public_symbols: 5
    wire_target_modules:
      - agentkit_wire.failure_corpus
    wire_exported_symbols:
      - IncidentRole
      - IncidentSeverity
    remainder_distribution: core
    remainder_symbols: 3
    core_symbols:
      - CheckId
      - IncidentId
      - PatternId
  # -------------------------------------------------------------------------
  # AG3-239: der einzige Eintrag dieser Liste, der NICHT an das Vertragspaket
  # abgibt, sondern die edge/core-Grenze INNERHALB von backend/ zieht. Die
  # Modulzuordnung `governance.runner -> edge` war fuer einen Teil der Symbole
  # falsch: E1 hat sie an einem Zeugen entschieden (`settings_writer`), den
  # ausschliesslich `Governance._materialise_harness_settings` erzeugte -- also
  # genau das Symbol, das nicht auf die Edge-Seite gehoert. Die uebrigen zwei
  # E1-Zeugen (`projectedge.governance_client`, `projectedge.runtime`) gehoeren
  # zur Hook-Dispatch-Haelfte und tragen deren Zuordnung weiterhin.
  # -------------------------------------------------------------------------
  - id: architecture-conformance.symbol_boundary.governance_runner
    module: agentkit.backend.governance.runner
    split_required: true
    public_symbols: 11
    remainder_distribution: edge
    remainder_symbols: 10
    core_symbols:
      - Governance
    measured_evidence: >-
      measured 2026-08-07 with the AG3-239 measurement command against
      distribution_boundary_violations. `Governance` holds a
      HookRegistrationRepository and a LockRecordRepository and is constructed
      only by core composition (composition_closure, composition_project,
      story_reset_adapters) and by the installer; `deactivate_locks` is called by
      ClosureSequence (FK-29 section 29.5). Ten import edges crossed the boundary
      solely because those symbols shared a module with the hook dispatch: six
      disappeared with the symbol cut, and four more with the follow-up cut of
      `register_hooks` (see below). Counter-evidence that the module was mixed
      rather than merely large: all four construction sites supplied a dummy for
      the half they did not use -- the installer a fail-closed
      `_UnavailableInstallerLockRepository`, the three composition sites a
      direct-DB `StateBackendHookRegistrationRepository` they never called.
    remainder_stays_edge_because: >-
      GuardRunner, run_hook, parse_hook_wrapper_args, validate_hook_selector and
      the per-hook dispatch functions decide synchronously inside the short-lived
      hook process before a tool runs (FK-30). A network call per tool use is
      neither fast enough nor available enough, so they stay on the developer
      machine.
    register_hooks_is_edge_orchestration: >-
      `register_hooks` did NOT move to the core with `Governance`. It persists
      through a HookRegistrationRepository (core, in production the REST-backed
      WriterHookRegistrationRepository) and then materialises
      `.claude/settings.json` and `.codex/hooks.json` on the DEVELOPER machine.
      The second half is edge work the core cannot perform in a split
      deployment -- as core code it produced a core-to-edge import into
      harness_client.harness_adapters.settings_writer. The composed operation
      therefore lives on the edge, in
      installer.writer_client.InstallerHookGovernance.
  - id: architecture-conformance.symbol_boundary.governance_hook_registration
    module: agentkit.backend.governance.hook_registration
    split_required: true
    public_symbols: 5
    wire_target_modules:
      - agentkit_wire.governance_registration
    wire_exported_symbols:
      - HookDefinition
      - HookEventName
    remainder_distribution: core
    remainder_symbols: 3
    core_symbols:
      - HookHarness
      - HookId
      - RegistrationResult
  - id: architecture-conformance.symbol_boundary.installer_http_models
    module: agentkit.backend.installer.http_models
    split_required: true
    public_symbols: 15
    wire_target_modules:
      - agentkit_wire.installer_registration
    wire_exported_symbols:
      - GovernanceHookClearRequest
      - GovernanceHookListResponse
      - GovernanceHookRegistrationRequest
      - GovernanceHookRegistrationResponse
      - InstallerWriterReadyResponse
      - ProjectRegistrationListResponse
      - ProjectRegistrationMutationResponse
      - ProjectRegistrationReadResponse
      - ProjectRegistrationUpgradeRequest
      - SkillBindingDeleteRequest
      - SkillBindingListResponse
      - SkillBindingMutationResponse
      - SkillBindingReadResponse
    remainder_distribution: edge
    remainder_symbols: 2
    edge_symbols:
      - RegisterProjectStateRequest
      - SkillBindingWriteRequest
  - id: architecture-conformance.symbol_boundary.installer_registration
    module: agentkit.backend.installer.registration
    split_required: true
    public_symbols: 8
    wire_target_modules:
      - agentkit_wire.installer_registration
    wire_exported_symbols:
      - CheckpointStatus
      - RuntimeProfile
    remainder_distribution: edge
    remainder_symbols: 6
    edge_symbols:
      - CP7_STATE_BACKEND_REGISTRATION
      - CheckpointResult
      - ProjectRegistration
      - REASON_CONFIG_DIGEST_UNCHANGED
      - REASON_INVALID_GITHUB_COORDINATES
      - REASON_MISSING_GITHUB_COORDINATES
  - id: architecture-conformance.symbol_boundary.story_exit_http_models
    module: agentkit.backend.story_exit.http_models
    split_required: false
    public_symbols: 2
    wire_target_modules:
      - agentkit_wire.story_lifecycle
    wire_exported_symbols:
      - StoryExitMutationRequest
      - StoryExitMutationResponse
    module_dissolves: true
  - id: architecture-conformance.symbol_boundary.story_reset_http_models
    module: agentkit.backend.story_reset.http_models
    split_required: false
    public_symbols: 2
    wire_target_modules:
      - agentkit_wire.story_lifecycle
    wire_exported_symbols:
      - StoryResetMutationRequest
      - StoryResetMutationResponse
    module_dissolves: true
  - id: architecture-conformance.symbol_boundary.story_split_http_models
    module: agentkit.backend.story_split.http_models
    split_required: false
    public_symbols: 2
    wire_target_modules:
      - agentkit_wire.story_lifecycle
    wire_exported_symbols:
      - StorySplitMutationRequest
      - StorySplitMutationResponse
    module_dissolves: true
  - id: architecture-conformance.symbol_boundary.telemetry_contract_results
    module: agentkit.backend.telemetry.contract.results
    split_required: true
    public_symbols: 5
    wire_target_modules:
      - agentkit_wire.telemetry_ingest
    wire_exported_symbols:
      - TelemetryScope
    remainder_distribution: core
    remainder_symbols: 4
    core_symbols:
      - ContractRuleResult
      - ContractStatus
      - rule_fail
      - rule_pass
  - id: architecture-conformance.symbol_boundary.telemetry_events
    module: agentkit.backend.telemetry.events
    split_required: true
    public_symbols: 7
    wire_target_modules:
      - agentkit_wire.telemetry_ingest
    wire_exported_symbols:
      - EventType
    remainder_distribution: core
    remainder_symbols: 6
    core_symbols:
      - Event
      - EventPayloadContractError
      - INTEGRITY_VIOLATION_PROMPT_GUARD
      - INTEGRITY_VIOLATION_STAGES
      - MANDATORY_PAYLOAD_FIELDS
      - validate_event_payload
  # --- Schnitte, die NICHT ins Vertragspaket fuehren -----------------------
  # Vier Module tragen Edge- und Kern-Inhalt zugleich. Keines ihrer Symbole
  # ist /v1-Vokabular; der Schnitt trennt Verhalten, nicht Vertrag.
  - id: architecture-conformance.symbol_boundary.cli_auth_commands
    module: agentkit.backend.cli.auth_commands
    split_required: true
    wire_exported_symbols: []
    core_symbols:
      - _cmd_bootstrap
    edge_symbols:
      - add_auth_parser
      - dispatch_auth_command
      - prepare_installer_auth_context
      - provision_installer_project_token
      - InstallerAuthContext
    note: >-
      `auth bootstrap` ist der vierte Kern-Kommandopfad (FK-91 Paragraph 91.1):
      es schreibt das Strategenpasswort lokal ueber `backend.auth.credentials`.
      Die fuenf uebrigen `auth`-Unterverben sind REST-Aufrufe und bleiben Edge.
  - id: architecture-conformance.symbol_boundary.cli_lifecycle
    module: agentkit.backend.cli.lifecycle
    split_required: true
    wire_exported_symbols: []
    core_symbols:
      - cmd_serve
      - cmd_ui
      - cmd_decommission
    edge_symbols:
      - add_lifecycle_parsers
      - cmd_update
      - cmd_detach
    note: >-
      Kommandopfadmix ohne Ankermix: drei der sechs oeffentlichen Funktionen
      sind Kern-Verben (FK-10 Paragraph 10.2.11). Ohne diesen Eintrag zoege das
      edge-basierte `agentkit.backend.cli` `serve`, `ui` und `decommission` mit.
  - id: architecture-conformance.symbol_boundary.bootstrap_composition_project
    module: agentkit.backend.bootstrap.composition_project
    split_required: true
    wire_exported_symbols: []
    edge_symbols:
      - build_compat_window_reader
    core_symbols:
      - build_story_exit_service
      - build_story_reset_service
      - build_kpi_analytics
      - build_kpi_analytics_read_facade
      - build_story_read_service
      - build_project_telemetry_event_source
      - build_takeover_approval_read_source
      - build_dashboard_service
      - build_task_management_routes
      - build_project_repository
      - build_project_read_model_routes
      - cli_load_story_context
      - cli_read_phase_state_record
    unresolved:
      - symbol: resolve_split_export_project_id
        why: >-
          listed as a core symbol, but it reaches edge VectorDB code itself
          (composition_project.py:96,105). it shares the fate of
          build_story_split_service and is not core-assignable until the gap
          below is decided.
      - symbol: build_story_split_service
        why: >-
          it builds a core service AND resolves a Weaviate story adapter locally
          (composition_project.py:114,171). that is the SAME open question the
          named gap in FK-10 Paragraph 10.2.12 C carries for
          `backend/closure/runtime_ports.py`. owner is the Product Owner;
          AG3-237 does not decide it a second time.
    note: >-
      Das Modul traegt einen Edge-Anker (`build_compat_window_reader` baut einen
      ProjectEdgeClient, composition_project.py:636) und faellt deshalb unter
      longest-match-wins ins Edge-Praefix. Der Eintrag hier holt die 14
      Kern-Builder zurueck.
  - id: architecture-conformance.symbol_boundary.story_creation_runtime_factory
    module: agentkit.backend.story_creation.runtime_factory
    split_required: true
    wire_exported_symbols: []
    edge_symbols:
      - build_story_creation_reconciler
      - reconciliation_to_evidence_dict
    core_symbols:
      - FailClosedConflictEvaluator
      - build_create_time_conflict_evaluator
    note: >-
      Der Reconciler spricht Weaviate direkt vom Entwicklerrechner (Carve-out
      FK-01 Paragraph 1.1a), der Conflict-Evaluator treibt den Multi-LLM-Hub,
      der nach I2 Core-vermittelt ist.
distribution_anchors:
  # Die Anker sind Eingang der Messung und liegen ALLE ausserhalb von
  # src/agentkit/backend. AC 3 gilt auch fuer sie: jeder traegt seinen
  # Messbeleg. Ihre Zuordnung stammt aus FK-10 Abschnitt A/C und ist in
  # AG3-208 entschieden; AG3-237 hat sie nachgemessen, nicht neu gesetzt.
  - id: architecture-conformance.anchor.harness_client
    module_prefix: agentkit.harness_client
    distribution: edge
    source: FK-10 section A
    measured_evidence: >-
      25 modules, all hook adapters and the project-edge client; runs on the
      developer machine only. measured 2026-08-07.
  - id: architecture-conformance.anchor.bundles
    module_prefix: agentkit.bundles
    distribution: edge
    source: FK-10 section A
    measured_evidence: >-
      30 modules, 132 files; everything below is materialised on the developer
      machine. consumers are installer/, skills/bundle_store and the codex
      adapter. measured 2026-08-07.
  - id: architecture-conformance.anchor.concepts
    module_prefix: agentkit.concepts
    distribution: edge
    source: FK-10 section A
    measured_evidence: >-
      7 modules (parser, chunking, tokenizer, frontmatter); the only consumers
      are backend/vectordb and backend/story_creation, both edge. measured
      2026-08-07.
  - id: architecture-conformance.anchor.resources
    module_prefix: agentkit.resources
    distribution: edge
    source: FK-10 section A
    measured_evidence: >-
      tokenizer asset, loaded only by concepts/tokenizer.py. measured
      2026-08-07.
  - id: architecture-conformance.anchor.integration_clients_vectordb
    module_prefix: agentkit.integration_clients.vectordb
    distribution: edge
    source: FK-10 section C
    measured_evidence: >-
      sole importer of weaviate-client, an edge-only distribution; FK-01
      section 1.1a runs Weaviate as a local-direct edge. measured 2026-08-07.
  - id: architecture-conformance.anchor.integration_clients_mcp
    module_prefix: agentkit.integration_clients.mcp
    distribution: edge
    source: FK-10 section C
    measured_evidence: >-
      shared client mechanics of the locally started MCP servers. measured
      2026-08-07.
  - id: architecture-conformance.anchor.frontend
    module_prefix: agentkit.frontend
    distribution: core
    source: FK-10 section A
    measured_evidence: >-
      0 Python modules, TS/React tree; delivered by the core (`agentkit-backend
      ui`) and speaking REST only (I6). no edge process loads frontend assets.
      measured 2026-08-07.
  - id: architecture-conformance.anchor.integration_clients
    module_prefix: agentkit.integration_clients
    distribution: core
    source: FK-10 section C
    measured_evidence: >-
      collective prefix for the six core-driven adapters (github, jenkins,
      sonar, multi_llm_hub, llm_pools, are); the two edge adapters carry longer
      prefixes and win under longest-match-wins. github/jenkins/sonar/are are
      driven by core judgements (I2, FK-33). measured 2026-08-07.
# ---------------------------------------------------------------------------
# Grenzverletzungen im heutigen Importgraphen. NICHT Teil des
# Klassifikationsbeweises -- eine Kante beweist eine Verletzung, nicht eine
# unbekannte Zugehoerigkeit. Arbeitsliste von AG3-209.
#
# ZAEHLEINHEIT, ausdruecklich: eindeutige geordnete Paare
# (importierendes Modul -> importiertes Modul). Das ist die Einheit, die der
# Gate-Check source_graph unter `forbidden_edges_with_locator` meldet. Zwei
# andere Zaehlungen desselben Sachverhalts liefern andere Zahlen und sind
# hier ausdruecklich NICHT gemeint: 724 (Importer, Ziel, Symbol, Zeile) und
# 725 rohe AST-Import-Vorkommen.
# ---------------------------------------------------------------------------
distribution_boundary_violations:
  counting_unit: unique-ordered-module-pair
  resolution: longest-match-wins over the module_prefixes and module_members above
  derived_from: the frozen classification above -- recomputed in full, never patched line by line
  measured_on: "2026-08-07"
  total: 347
  edge_to_core: 297
  core_to_edge: 50
  owner: AG3-209
  # Diese Liste ist ein ABGELEITETES Artefakt. Sie wird nach JEDER
  # Zuordnungsaenderung vollstaendig neu gerechnet, nie nachgepflegt.
  # Belegter Anlassfall: zwei Modulausnahmen aus Runde 3 verschoben die
  # Klassifikation, und die Liste trug danach sechs Paare auf ein Modul, das
  # nicht mehr dort lag, waehrend die reale Kante
  # default_hook_definitions -> hook_registration fehlte.
  #
  # Auf den Gate-Report kann sich die Liste nicht berufen: das Packaging-Gate
  # ist Liefergegenstand von AG3-209 und existiert nicht. Deshalb steht jedes
  # Paar hier einzeln.
  pairs:
    - importer: agentkit.backend.bootstrap.composition_closure
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.composition_exploration
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.composition_governance
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.composition_installer
      imported: agentkit.backend.installer.bounded_executor
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.composition_installer
      imported: agentkit.backend.installer.mutation_idempotency
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.composition_installer
      imported: agentkit.backend.installer.third_party_preflight
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.composition_installer
      imported: agentkit.backend.installer.writer_service
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.bootstrap.composition_project_types
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.bootstrap.composition_state
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.bootstrap.story_reset_adapters
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.control_plane.edge_command_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.control_plane.repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.kpi_analytics
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.kpi_analytics.aggregation
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.kpi_analytics.dashboard
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.kpi_analytics.fact_store
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.project_management.read_model_routes
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.pipeline_runtime_store
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.analytics_source
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.control_plane_writer_lease
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.fact_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.freeze_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.governance_hook_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.lock_record_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.parallelization_config_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.project_management_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.story_are_link_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.story_dependency_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.story_read_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.story_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.takeover_approval_read_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.telemetry_projection_repository_misc
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.store.telemetry_read_repository
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.state_backend.story_lifecycle_store
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.story
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.story_context_manager.service
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.story_exit.service
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.story_reset
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.story_split.service
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.task_management.http.routes
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_project
      imported: agentkit.backend.task_management.service
      direction: edge-to-core
    - importer: agentkit.backend.bootstrap.composition_root
      imported: agentkit.backend.bootstrap.composition_project
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.composition_state
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.composition_verify
      imported: agentkit.backend.installer.github_coordinates
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.edge_provisioning_adapter
      imported: agentkit.backend.installer.github_coordinates
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.story_reset_adapters
      imported: agentkit.backend.governance.runner
      direction: core-to-edge
    - importer: agentkit.backend.bootstrap.story_reset_adapters
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.cli._operator_ownership_commands
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.backend.cli._operator_ownership_commands
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.cli._operator_recovery_admin
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.backend.cli._operator_recovery_admin
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.cli._operator_recovery_config
      imported: agentkit.backend.config.loader
      direction: edge-to-core
    - importer: agentkit.backend.cli._operator_recovery_phase
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.backend.cli._operator_recovery_phase
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.cli._operator_recovery_state
      imported: agentkit.backend.bootstrap.composition_root
      direction: edge-to-core
    - importer: agentkit.backend.cli._operator_recovery_telemetry
      imported: agentkit.backend.bootstrap.composition_root
      direction: edge-to-core
    - importer: agentkit.backend.cli._operator_recovery_telemetry
      imported: agentkit.backend.telemetry.audit_bundle
      direction: edge-to-core
    - importer: agentkit.backend.cli._operator_recovery_telemetry
      imported: agentkit.backend.telemetry.events
      direction: edge-to-core
    - importer: agentkit.backend.cli._operator_recovery_telemetry
      imported: agentkit.backend.telemetry.storage
      direction: edge-to-core
    - importer: agentkit.backend.cli.auth_commands
      imported: agentkit.backend.auth.credentials
      direction: edge-to-core
    - importer: agentkit.backend.cli.evidence_commands
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.backend.cli.evidence_commands
      imported: agentkit.backend.verify_system.evidence
      direction: edge-to-core
    - importer: agentkit.backend.cli.evidence_commands
      imported: agentkit.backend.verify_system.structural.system_evidence
      direction: edge-to-core
    - importer: agentkit.backend.cli.installer_commands
      imported: agentkit.backend.config.defaults
      direction: edge-to-core
    - importer: agentkit.backend.cli.installer_commands
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.cli.installer_commands
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.cli.lifecycle
      imported: agentkit.backend.bootstrap.composition_root
      direction: edge-to-core
    - importer: agentkit.backend.cli.lifecycle
      imported: agentkit.backend.cli.serve
      direction: edge-to-core
    - importer: agentkit.backend.cli.lifecycle
      imported: agentkit.backend.control_plane.writer_lease
      direction: edge-to-core
    - importer: agentkit.backend.cli.main
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.backend.cli.story_commands
      imported: agentkit.backend.config.defaults
      direction: edge-to-core
    - importer: agentkit.backend.cli.story_commands
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.cli.story_commands
      imported: agentkit.backend.implementation.worker_health.sidecar
      direction: edge-to-core
    - importer: agentkit.backend.cli.story_commands
      imported: agentkit.backend.story_context_manager.service
      direction: edge-to-core
    - importer: agentkit.backend.cli.story_commands
      imported: agentkit.backend.story_exit
      direction: edge-to-core
    - importer: agentkit.backend.cli.story_commands
      imported: agentkit.backend.story_exit.http_models
      direction: edge-to-core
    - importer: agentkit.backend.cli.story_commands
      imported: agentkit.backend.story_reset.http_models
      direction: edge-to-core
    - importer: agentkit.backend.cli.story_commands
      imported: agentkit.backend.story_split.http_models
      direction: edge-to-core
    - importer: agentkit.backend.cli.story_commands
      imported: agentkit.backend.story_split.plan_loader
      direction: edge-to-core
    - importer: agentkit.backend.closure.phase
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.closure.post_merge_finalization.finalization
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.closure.runtime_ports
      imported: agentkit.backend.vectordb.client_port
      direction: core-to-edge
    - importer: agentkit.backend.closure.runtime_ports
      imported: agentkit.backend.vectordb.engine
      direction: core-to-edge
    - importer: agentkit.backend.closure.runtime_ports
      imported: agentkit.backend.vectordb.mcp_server
      direction: core-to-edge
    - importer: agentkit.backend.control_plane.models
      imported: agentkit.backend.story_creation.reconciliation_evidence
      direction: core-to-edge
    - importer: agentkit.backend.control_plane.workspace_locator
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.control_plane.workspace_locator
      imported: agentkit.backend.installer.registration
      direction: core-to-edge
    - importer: agentkit.backend.control_plane_http.installer_writer_routes
      imported: agentkit.backend.installer.http_models
      direction: core-to-edge
    - importer: agentkit.backend.control_plane_http.installer_writer_routes
      imported: agentkit.backend.installer.mutation_idempotency
      direction: core-to-edge
    - importer: agentkit.backend.control_plane_http.installer_writer_routes
      imported: agentkit.backend.installer.registration
      direction: core-to-edge
    - importer: agentkit.backend.control_plane_http.installer_writer_routes
      imported: agentkit.backend.installer.writer_service
      direction: core-to-edge
    - importer: agentkit.backend.control_plane_http.third_party_validation_routes
      imported: agentkit.backend.installer.third_party_errors
      direction: core-to-edge
    - importer: agentkit.backend.control_plane_http.third_party_validation_routes
      imported: agentkit.backend.installer.third_party_preflight
      direction: core-to-edge
    - importer: agentkit.backend.failure_corpus.cli
      imported: agentkit.backend.bootstrap.composition_root
      direction: edge-to-core
    - importer: agentkit.backend.failure_corpus.cli
      imported: agentkit.backend.config.defaults
      direction: edge-to-core
    - importer: agentkit.backend.failure_corpus.cli
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.failure_corpus.cli
      imported: agentkit.backend.failure_corpus.http_models
      direction: edge-to-core
    - importer: agentkit.backend.failure_corpus.writer_client
      imported: agentkit.backend.failure_corpus.http_models
      direction: edge-to-core
    - importer: agentkit.backend.governance
      imported: agentkit.backend.governance.runner
      direction: core-to-edge
    - importer: agentkit.backend.governance.default_hook_definitions
      imported: agentkit.backend.governance.hook_registration
      direction: edge-to-core
    - importer: agentkit.backend.governance.guard_evaluation
      imported: agentkit.backend.core_types.qa_artifact_names
      direction: edge-to-core
    - importer: agentkit.backend.governance.guard_evaluation
      imported: agentkit.backend.governance.guards.artifact_guard
      direction: edge-to-core
    - importer: agentkit.backend.governance.guard_evaluation
      imported: agentkit.backend.governance.guards.branch_guard
      direction: edge-to-core
    - importer: agentkit.backend.governance.guard_evaluation
      imported: agentkit.backend.governance.guards.scope_guard
      direction: edge-to-core
    - importer: agentkit.backend.governance.guard_evaluation
      imported: agentkit.backend.governance.protocols
      direction: edge-to-core
    - importer: agentkit.backend.governance.guard_evaluation
      imported: agentkit.backend.integration_stabilization.budget_guard
      direction: edge-to-core
    - importer: agentkit.backend.governance.guard_evaluation
      imported: agentkit.backend.integration_stabilization.preconditions
      direction: edge-to-core
    - importer: agentkit.backend.governance.guard_evaluation
      imported: agentkit.backend.integration_stabilization.seam_allowlist_guard
      direction: edge-to-core
    - importer: agentkit.backend.governance.guard_evaluation
      imported: agentkit.backend.integration_stabilization.state
      direction: edge-to-core
    - importer: agentkit.backend.governance.guard_evaluation
      imported: agentkit.backend.story_context_manager.operating_mode_resolver
      direction: edge-to-core
    - importer: agentkit.backend.governance.guard_evaluation
      imported: agentkit.backend.telemetry.emitters
      direction: edge-to-core
    - importer: agentkit.backend.governance.guards.self_protection_guard
      imported: agentkit.backend.governance.guard_evaluation
      direction: core-to-edge
    - importer: agentkit.backend.governance.guards.story_creation_guard
      imported: agentkit.backend.governance.guard_evaluation
      direction: core-to-edge
    - importer: agentkit.backend.governance.hook_event_inputs
      imported: agentkit.backend.governance.guard_evaluation
      direction: core-to-edge
    - importer: agentkit.backend.governance.principal_capabilities.enforcement
      imported: agentkit.backend.governance.guard_evaluation
      direction: core-to-edge
    - importer: agentkit.backend.governance.principal_capabilities.principals
      imported: agentkit.backend.governance.guard_evaluation
      direction: core-to-edge
    - importer: agentkit.backend.governance.principal_capabilities.service_paths
      imported: agentkit.backend.governance.guard_evaluation
      direction: core-to-edge
    - importer: agentkit.backend.governance.rest_edge
      imported: agentkit.backend.telemetry.emitters
      direction: edge-to-core
    - importer: agentkit.backend.governance.rest_edge
      imported: agentkit.backend.telemetry.events
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.config.loader
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.capability_blocks
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.errors
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.guard_system
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.guard_system.records
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.guards.self_protection_guard
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.guards.story_creation_guard
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.hook_event_inputs
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.hook_ids
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.hook_registration
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.locks
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.principal_capabilities
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.principal_capabilities.operations
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.protocols
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.governance.repository
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.implementation.worker_health
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.implementation.worker_health.interventions
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.state_backend.store.freeze_repository
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.state_backend.store.lock_record_repository
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.telemetry.emitters
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.telemetry.hooks.base
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.telemetry.hooks.budget_event_emitter
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.telemetry.hooks.commit_hook
      direction: edge-to-core
    - importer: agentkit.backend.governance.runner
      imported: agentkit.backend.telemetry.hooks.review_guard
      direction: edge-to-core
    - importer: agentkit.backend.governance.setup_preflight_gate.phase
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.implementation.phase
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.implementation.worker_health.artifacts
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.implementation.worker_health.engine
      imported: agentkit.backend.governance.guard_evaluation
      direction: core-to-edge
    - importer: agentkit.backend.implementation.worker_health.engine
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.implementation.worker_health.rest_repository
      imported: agentkit.backend.implementation.worker_health.models
      direction: edge-to-core
    - importer: agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.bootstrap_checkpoints.cp07_to_09
      imported: agentkit.backend.prompt_runtime.runtime
      direction: edge-to-core
    - importer: agentkit.backend.installer.bootstrap_checkpoints.cp07_to_09
      imported: agentkit.backend.skills.errors
      direction: edge-to-core
    - importer: agentkit.backend.installer.bootstrap_checkpoints.cp10_mcp_registration
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.installer.bootstrap_checkpoints.cp10_mcp_registration
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.backend.installer.bootstrap_checkpoints.cp10a_initial_sync_checkpoint
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.bootstrap_checkpoints.cp10d_sonarqube
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.bootstrap_checkpoints.orchestrator
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.installer.bootstrap_checkpoints.orchestrator
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.ccag_settings
      imported: agentkit.backend.boundary.filesystem
      direction: edge-to-core
    - importer: agentkit.backend.installer.ccag_settings
      imported: agentkit.backend.governance.hook_registration
      direction: edge-to-core
    - importer: agentkit.backend.installer.checkpoint_engine.context
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.installer.checkpoint_engine.engine
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.checkpoint_engine.engine
      imported: agentkit.backend.process.language.model
      direction: edge-to-core
    - importer: agentkit.backend.installer.checkpoint_engine.flow
      imported: agentkit.backend.process.language.model
      direction: edge-to-core
    - importer: agentkit.backend.installer.codex_settings
      imported: agentkit.backend.boundary.filesystem
      direction: edge-to-core
    - importer: agentkit.backend.installer.codex_settings
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.codex_settings
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.backend.installer.config_boundary
      imported: agentkit.backend.config.loader
      direction: edge-to-core
    - importer: agentkit.backend.installer.config_boundary
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.installer.config_boundary
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.cp10a_initial_sync
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.installer.cp10a_initial_sync
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.file_ops
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.file_ops
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.backend.installer.git_hook_dispatch
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.backend.installer.http_models
      imported: agentkit.backend.governance.hook_registration
      direction: edge-to-core
    - importer: agentkit.backend.installer.http_models
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.installer.installed_manifest
      imported: agentkit.backend.core_types.plane_artifact_names
      direction: edge-to-core
    - importer: agentkit.backend.installer.installed_manifest
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.backend.installer.integration_checkpoints
      imported: agentkit.backend.installer.integration_checkpoints.branch_plugin_self_test
      direction: edge-to-core
    - importer: agentkit.backend.installer.integration_checkpoints
      imported: agentkit.backend.installer.integration_checkpoints.ci_preflight
      direction: edge-to-core
    - importer: agentkit.backend.installer.integration_checkpoints
      imported: agentkit.backend.installer.integration_checkpoints.jenkins_selftest_harness
      direction: edge-to-core
    - importer: agentkit.backend.installer.integration_checkpoints
      imported: agentkit.backend.installer.integration_checkpoints.scanner_harness
      direction: edge-to-core
    - importer: agentkit.backend.installer.integration_checkpoints
      imported: agentkit.backend.installer.integration_checkpoints.sonar_preflight
      direction: edge-to-core
    - importer: agentkit.backend.installer.interpreter
      imported: agentkit.backend.boundary.filesystem
      direction: edge-to-core
    - importer: agentkit.backend.installer.lifecycle.decommission
      imported: agentkit.backend.bootstrap.composition_root
      direction: edge-to-core
    - importer: agentkit.backend.installer.lifecycle.decommission
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.installer.lifecycle.decommission
      imported: agentkit.backend.state_backend.store.story_read_repository
      direction: edge-to-core
    - importer: agentkit.backend.installer.lifecycle.detach
      imported: agentkit.backend.boundary.filesystem
      direction: edge-to-core
    - importer: agentkit.backend.installer.lifecycle.detach
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.installer.lifecycle.detach
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.backend.installer.mcp_registration
      imported: agentkit.backend.boundary.filesystem
      direction: edge-to-core
    - importer: agentkit.backend.installer.mutation_idempotency
      imported: agentkit.backend.state_backend.store.inflight_idempotency_guard
      direction: edge-to-core
    - importer: agentkit.backend.installer.paths
      imported: agentkit.backend.core_types.plane_artifact_names
      direction: edge-to-core
    - importer: agentkit.backend.installer.project_structure
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.repo_probe
      imported: agentkit.backend.bootstrap.composition_root
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.config.defaults
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.config.loader
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.control_plane.third_party_models
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.governance.repository
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.installer.integration_checkpoints.sonar_preflight
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.project_management.entities
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.project_management.lifecycle
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.project_management.repository
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.skills.errors
      direction: edge-to-core
    - importer: agentkit.backend.installer.runner
      imported: agentkit.backend.skills.materialize
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_light
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_light
      imported: agentkit.backend.control_plane.third_party_models
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_light
      imported: agentkit.backend.installer.integration_checkpoints.ci_preflight
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_light
      imported: agentkit.backend.installer.integration_checkpoints.sonar_preflight
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_light
      imported: agentkit.backend.installer.third_party_clients
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_preflight
      imported: agentkit.backend.control_plane.records
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_preflight
      imported: agentkit.backend.control_plane.third_party_models
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_preflight
      imported: agentkit.backend.installer.third_party_clients
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_preflight
      imported: agentkit.backend.state_backend.store.inflight_idempotency_guard
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_self_test
      imported: agentkit.backend.control_plane.third_party_models
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_self_test
      imported: agentkit.backend.installer.integration_checkpoints.branch_plugin_self_test
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_self_test
      imported: agentkit.backend.installer.integration_checkpoints.jenkins_selftest_harness
      direction: edge-to-core
    - importer: agentkit.backend.installer.third_party_self_test
      imported: agentkit.backend.installer.third_party_clients
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade._digest
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade._skills_surface
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade._skills_surface
      imported: agentkit.backend.state_backend.store.skill_binding_repository
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.config_migration
      imported: agentkit.backend.boundary.filesystem.path_identity
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.config_migration
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.config_migration
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.engine
      imported: agentkit.backend.boundary.filesystem
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.engine
      imported: agentkit.backend.governance.hook_registration
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.engine
      imported: agentkit.backend.process.language.model
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.engine
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.entry
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.entry
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.footprint
      imported: agentkit.backend.config.loader
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.footprint
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.footprint
      imported: agentkit.backend.prompt_runtime.resources
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.footprint
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.footprint
      imported: agentkit.backend.skills.errors
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.hook_migration
      imported: agentkit.backend.governance.hook_registration
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.upgrade_flow
      imported: agentkit.backend.governance.hook_registration
      direction: edge-to-core
    - importer: agentkit.backend.installer.upgrade.upgrade_flow
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.installer.vectordb_preflight
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.installer.vectordb_preflight
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.writer_client
      imported: agentkit.backend.boundary.filesystem
      direction: edge-to-core
    - importer: agentkit.backend.installer.writer_client
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.installer.writer_client
      imported: agentkit.backend.governance.errors
      direction: edge-to-core
    - importer: agentkit.backend.installer.writer_client
      imported: agentkit.backend.governance.hook_registration
      direction: edge-to-core
    - importer: agentkit.backend.installer.writer_client
      imported: agentkit.backend.governance.repository
      direction: edge-to-core
    - importer: agentkit.backend.installer.writer_client
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.installer.writer_client
      imported: agentkit.backend.state_backend.store.lock_record_repository
      direction: edge-to-core
    - importer: agentkit.backend.installer.writer_service
      imported: agentkit.backend.governance.hook_registration
      direction: edge-to-core
    - importer: agentkit.backend.installer.writer_service
      imported: agentkit.backend.governance.repository
      direction: edge-to-core
    - importer: agentkit.backend.installer.writer_service
      imported: agentkit.backend.project_management.repository
      direction: edge-to-core
    - importer: agentkit.backend.installer.writer_service
      imported: agentkit.backend.skills
      direction: edge-to-core
    - importer: agentkit.backend.process.language.definitions
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.prompt_runtime.composer
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.prompt_runtime.pins
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.prompt_runtime.resources
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.prompt_runtime.runtime
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.skills.top
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.state_backend.store.exploration_change_frame_repository
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.state_backend.store.exploration_worker_runner
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.backend.state_backend.store.project_registration_repository
      imported: agentkit.backend.installer.registration
      direction: core-to-edge
    - importer: agentkit.backend.story_context_manager.http.routes
      imported: agentkit.backend.story_creation.reconciliation_evidence
      direction: core-to-edge
    - importer: agentkit.backend.story_creation.conflict_adjudicator
      imported: agentkit.backend.verify_system.llm_evaluator.bundle
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.conflict_adjudicator
      imported: agentkit.backend.verify_system.llm_evaluator.llm_client
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.conflict_adjudicator
      imported: agentkit.backend.verify_system.llm_evaluator.roles
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.conflict_adjudicator
      imported: agentkit.backend.verify_system.llm_evaluator.structured_evaluator
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.conflict_adjudicator
      imported: agentkit.backend.verify_system.protocols
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.create_flow
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.create_flow
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.create_flow
      imported: agentkit.backend.story_context_manager.service
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.create_flow
      imported: agentkit.backend.story_context_manager.story_model
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.create_flow
      imported: agentkit.backend.telemetry.emitters
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.create_scope_materializer
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.create_scope_materializer
      imported: agentkit.backend.prompt_runtime.resources
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.create_scope_materializer
      imported: agentkit.backend.verify_system.llm_evaluator.bundle
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.create_scope_materializer
      imported: agentkit.backend.verify_system.llm_evaluator.llm_client
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.create_scope_materializer
      imported: agentkit.backend.verify_system.llm_evaluator.roles
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.create_scope_materializer
      imported: agentkit.backend.verify_system.llm_evaluator.structured_evaluator
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.reconciliation_evidence
      imported: agentkit.backend.verify_system.llm_evaluator.roles
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.repo_affinity
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.runtime_factory
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.runtime_factory
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.runtime_factory
      imported: agentkit.backend.verify_system.llm_evaluator.bundle
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.runtime_factory
      imported: agentkit.backend.verify_system.llm_evaluator.llm_client
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.runtime_factory
      imported: agentkit.backend.verify_system.llm_evaluator.roles
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.runtime_factory
      imported: agentkit.backend.verify_system.llm_evaluator.structured_evaluator
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.runtime_factory
      imported: agentkit.integration_clients.multi_llm_hub.client
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.runtime_factory
      imported: agentkit.integration_clients.multi_llm_hub.config
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.runtime_factory
      imported: agentkit.integration_clients.multi_llm_hub.entities
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.story_md_export
      imported: agentkit.backend.story_context_manager.story_model
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.story_md_export
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.vectordb_reconciliation
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.vectordb_reconciliation
      imported: agentkit.backend.telemetry.emitters
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.vectordb_reconciliation
      imported: agentkit.backend.telemetry.events
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.vectordb_reconciliation
      imported: agentkit.backend.verify_system.llm_evaluator.bundle
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.vectordb_reconciliation
      imported: agentkit.backend.verify_system.llm_evaluator.roles
      direction: edge-to-core
    - importer: agentkit.backend.story_creation.vectordb_reconciliation
      imported: agentkit.backend.verify_system.llm_evaluator.structured_evaluator
      direction: edge-to-core
    - importer: agentkit.backend.telemetry.rest_emitter
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.backend.telemetry.rest_emitter
      imported: agentkit.backend.telemetry.events
      direction: edge-to-core
    - importer: agentkit.backend.vectordb.hook_dispatch
      imported: agentkit.backend.config.loader
      direction: edge-to-core
    - importer: agentkit.backend.vectordb.hook_dispatch
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.vectordb.project_binding
      imported: agentkit.backend.config.defaults
      direction: edge-to-core
    - importer: agentkit.backend.vectordb.project_binding
      imported: agentkit.backend.config.loader
      direction: edge-to-core
    - importer: agentkit.backend.vectordb.project_binding
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.backend.vectordb.wait_for_weaviate
      imported: agentkit.backend.config.loader
      direction: edge-to-core
    - importer: agentkit.backend.verify_system.qa_cycle.invalidation
      imported: agentkit.backend.installer.paths
      direction: core-to-edge
    - importer: agentkit.bundles.target_project.tools.agentkit.projectedge
      imported: agentkit.backend.config.loader
      direction: edge-to-core
    - importer: agentkit.bundles.target_project.tools.agentkit.projectedge
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.bundles.target_project.tools.agentkit.projectedge
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.bundles.target_project.tools.agentkit.projectedge
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.harness_client.harness_adapters.codex.decision_mapping
      imported: agentkit.backend.governance.protocols
      direction: edge-to-core
    - importer: agentkit.harness_client.harness_adapters.codex_config_toml
      imported: agentkit.backend.boundary.filesystem
      direction: edge-to-core
    - importer: agentkit.harness_client.harness_adapters.settings_writer
      imported: agentkit.backend.governance.errors
      direction: edge-to-core
    - importer: agentkit.harness_client.harness_adapters.settings_writer
      imported: agentkit.backend.governance.hook_registration
      direction: edge-to-core
    - importer: agentkit.harness_client.harness_adapters.settings_writer
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.client
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.client
      imported: agentkit.backend.control_plane.third_party_models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.client
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.client
      imported: agentkit.backend.story_exit.http_models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.client
      imported: agentkit.backend.story_reset.http_models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.client
      imported: agentkit.backend.story_split.http_models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.client
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.command_executor
      imported: agentkit.backend.code_backend.provider_port
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.command_executor
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.command_executor
      imported: agentkit.backend.control_plane.edge_commands
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.command_executor
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.command_executor
      imported: agentkit.backend.control_plane.push_sync
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.command_executor
      imported: agentkit.backend.core_types.verify_evidence
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.command_executor
      imported: agentkit.backend.utils.io
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.governance_client
      imported: agentkit.backend.config.loader
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.governance_client
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.governance_client
      imported: agentkit.backend.exceptions
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.merge_local
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.merge_local
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.reconcile
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.reconcile
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.runtime
      imported: agentkit.backend.config.loader
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.runtime
      imported: agentkit.backend.control_plane.models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.runtime
      imported: agentkit.backend.control_plane.ownership
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.runtime
      imported: agentkit.backend.core_types.operating_mode
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.verify_evidence
      imported: agentkit.backend.config.models
      direction: edge-to-core
    - importer: agentkit.harness_client.projectedge.verify_evidence
      imported: agentkit.backend.core_types.verify_evidence
      direction: edge-to-core
wire_private_bindings:
  # Die 118 oeffentlichen Symbole sind die Oberflaeche des Vertragspakets.
  # Diese privaten Namen sind KEINE Symbole im Sinne der Zaehleinheit, aber
  # sie tragen produktives Validierungsverhalten der wandernden Symbole.
  # `hull_closed: true` gilt nur zusammen mit dieser Festlegung: sie wandern
  # mit oder werden ersetzt. Ohne sie waere die Aussage falsch.
  total: 3
  bindings:
    - module: agentkit.backend.config.models
      names:
        - name: _SEMVER_RE
          role: regex constant behind _validate_semver
        - name: _validate_semver
          role: field validator of SonarQubeConfig and SonarQubeBranchPluginConfig (config/models.py:140,143,166,278)
      disposition: migrate-with-owner-or-replace
    - module: agentkit.backend.control_plane.models
      names:
        - name: _NO_EDGE_BUNDLE_STATUSES
          role: drives productive validator behaviour of ControlPlaneMutationResult (control_plane/models.py:780,930,945)
      disposition: migrate-with-owner-or-replace
core_only_distributions:
  - psycopg
  - psycopg-binary
  - psycopg-pool
  - argon2-cffi
  - agentkit-backend
# Abschliessende Liste der DRITTBIBLIOTHEKEN, die Edge UND Kern
# eigenstaendig deklarieren duerfen. Jede weitere Doppeldeklaration ist ein
# Verstoss -- sonst hoert die Liste auf, abschliessend zu sein.
#
# GELTUNGSBEREICH: nur Drittdistributionen. AK3-eigene Distributionen sind
# ausgenommen, weil ihre beidseitige Deklaration nicht geduldet, sondern
# VORGESCHRIEBEN ist. Die Pflicht kommt NICHT aus
# no_inter_distribution_package_dependency: diese Regel *erlaubt* die Kanten
# edge->wire und core->wire lediglich (und verbietet edge<->core).
# Vorgeschrieben werden sie durch die Runtime-Sollmengen -- agentkit-wire steht
# in beiden -- zusammen mit der beidseitigen Gleichheitspruefung
# declared_dependencies_match_normative_sets. agentkit-wire hier zu fuehren
# wuerde eine Pflicht als Ausnahme ausweisen.
dual_declared_dependencies:
  - pydantic
  - pyyaml
```
<!-- FORMAL-SPEC:END -->
