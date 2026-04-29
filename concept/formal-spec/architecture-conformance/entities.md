---
id: formal.architecture-conformance.entities
title: Architecture Conformance Entities
status: active
doc_kind: spec
context: architecture-conformance
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/01_systemkontext_und_architekturprinzipien.md
  - concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md
---

# Architecture Conformance Entities

Diese Entitaeten beschreiben die initial maschinell pruefbare Sicht auf
Komponenten, Blutgruppen und stabile Namespace-Grenzen.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.architecture-conformance.entities
schema_version: 1
kind: entity-set
context: architecture-conformance
bloodgroups:
  - id: architecture-conformance.bloodgroup.a_code
    code: A
    meaning: fachliche Komponenten mit Geschaeftsregeln
  - id: architecture-conformance.bloodgroup.r_code
    code: R
    meaning: Adapter an Systemgrenzen
  - id: architecture-conformance.bloodgroup.t_code
    code: T
    meaning: Persistenz- und Infrastrukturtreiber
component_groups:
  - id: architecture-conformance.group.story
    name: StoryApplication
    bloodgroup: A
    module_prefixes:
      - agentkit.story
  - id: architecture-conformance.group.dashboard
    name: DashboardApplication
    bloodgroup: A
    module_prefixes:
      - agentkit.dashboard
  - id: architecture-conformance.group.control_plane
    name: ControlPlaneHttp
    bloodgroup: R
    module_prefixes:
      - agentkit.control_plane
  - id: architecture-conformance.group.projectedge
    name: ProjectEdgeClient
    bloodgroup: R
    module_prefixes:
      - agentkit.projectedge
  - id: architecture-conformance.group.hook_runtime
    name: HookRuntime
    bloodgroup: R
    module_prefixes:
      - agentkit.governance.hookruntime
  - id: architecture-conformance.group.state_backend_drivers
    name: StateBackendDrivers
    bloodgroup: T
    module_prefixes:
      - agentkit.state_backend.postgres_store
      - agentkit.state_backend.sqlite_store
  - id: architecture-conformance.group.story_context_manager
    name: StoryContextManager
    bloodgroup: A
    module_prefixes:
      - agentkit.story_context_manager
  - id: architecture-conformance.group.pipeline_engine
    name: PipelineEngine
    bloodgroup: A
    module_prefixes:
      - agentkit.pipeline
      - agentkit.pipeline_engine
  - id: architecture-conformance.group.guard_system
    name: GuardSystem
    bloodgroup: A
    module_prefixes:
      - agentkit.guard_system
      - agentkit.governance.guards
  - id: architecture-conformance.group.governance_observer
    name: GovernanceObserver
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.monitoring
      - agentkit.governance.integrity_gate
  - id: architecture-conformance.group.conformance_service
    name: ConformanceService
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.doc_fidelity
  - id: architecture-conformance.group.stage_registry
    name: StageRegistry
    bloodgroup: A
    module_prefixes:
      - agentkit.governance.policies
  - id: architecture-conformance.group.failure_corpus
    name: FailureCorpus
    bloodgroup: A
    module_prefixes:
      - agentkit.failure_corpus
  - id: architecture-conformance.group.prompt_composer
    name: PromptComposer
    bloodgroup: A
    module_prefixes:
      - agentkit.prompt_composer
  - id: architecture-conformance.group.llm_evaluator
    name: LlmEvaluator
    bloodgroup: A
    module_prefixes:
      - agentkit.llm_evaluator
  - id: architecture-conformance.group.telemetry_service
    name: TelemetryService
    bloodgroup: A
    module_prefixes:
      - agentkit.telemetry
      - agentkit.telemetry_service
  - id: architecture-conformance.group.phase_state_store
    name: PhaseStateStore
    bloodgroup: A
    module_prefixes:
      - agentkit.phase_state_store
  - id: architecture-conformance.group.installer
    name: Installer
    bloodgroup: A
    module_prefixes:
      - agentkit.installer
```
<!-- FORMAL-SPEC:END -->
