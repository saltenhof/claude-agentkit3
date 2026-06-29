---
id: formal.architecture-conformance.invariants
title: Architecture Conformance Invariants
status: active
doc_kind: spec
context: architecture-conformance
spec_kind: invariant-set
version: 2
prose_refs:
  - concept/technical-design/01_systemkontext_und_architekturprinzipien.md
  - concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md
---

# Architecture Conformance Invariants

Diese Invarianten definieren die importbasierten, fail-closed
Architektur-Konformanz-Invarianten fuer AK3 — den maschinenlesbaren
Kern der Konformanz-Suite (FK-07 §7.7).

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.architecture-conformance.invariants
schema_version: 1
kind: invariant-set
context: architecture-conformance
dependency_rules:
  - id: architecture-conformance.rule.story_dashboard_must_not_depend_on_transport_or_hook_adapters
    source_module_prefixes:
      - agentkit.backend.story
      - agentkit.dashboard
    forbidden_module_prefixes:
      - agentkit.backend.control_plane.http
      - agentkit.harness_client.projectedge.client
      - agentkit.backend.governance.hookruntime
    message: story and dashboard application code may not depend on control-plane transport, project-edge transport, or hook runtime adapters
  - id: architecture-conformance.rule.story_dashboard_control_plane_must_not_depend_on_raw_state_drivers
    source_module_prefixes:
      - agentkit.backend.story
      - agentkit.dashboard
      - agentkit.backend.control_plane
    forbidden_module_prefixes:
      - agentkit.backend.state_backend.postgres_store
      - agentkit.backend.state_backend.sqlite_store
    message: application and control-plane modules may not import raw state-backend drivers directly
  - id: architecture-conformance.rule.projectedge_must_not_depend_on_control_plane_http
    source_module_prefixes:
      - agentkit.harness_client.projectedge
    forbidden_module_prefixes:
      - agentkit.backend.control_plane.http
    message: project-edge client must not depend on the control-plane HTTP adapter implementation
  - id: architecture-conformance.rule.control_plane_http_must_not_depend_on_state_backend_repository
    source_module_prefixes:
      - agentkit.backend.control_plane_http
      - agentkit.backend.control_plane.http
    forbidden_module_prefixes:
      - agentkit.backend.state_backend.store
    message: control-plane HTTP/BFF modules may not bypass owner BC ports via direct state-backend repository access
acyclic_group_sets:
  - id: architecture-conformance.acyclic.application_surface
    group_ids:
      - architecture-conformance.group.story_types
      - architecture-conformance.group.kpi_analytics_dashboard
      - architecture-conformance.group.story_context_manager
      - architecture-conformance.group.kpi_analytics
  - id: architecture-conformance.acyclic.runtime_core
    group_ids:
      - architecture-conformance.group.pipeline_engine
      - architecture-conformance.group.story_context_manager
      - architecture-conformance.group.phase_state_store
      - architecture-conformance.group.telemetry
      - architecture-conformance.group.prompt_runtime
      - architecture-conformance.group.llm_evaluator
  - id: architecture-conformance.acyclic.governance_core
    group_ids:
      - architecture-conformance.group.guard_system
      - architecture-conformance.group.governance_observer
      - architecture-conformance.group.conformance_service
      - architecture-conformance.group.stage_registry
      - architecture-conformance.group.failure_corpus
mutation_surface_rules:
  - id: architecture-conformance.rule.story_context_write_surface
    writer_symbols:
      - save_story_context
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.pipeline_engine
      - agentkit.backend.exploration
      - agentkit.backend.implementation
      - agentkit.backend.closure
      - agentkit.backend.state_backend.store
    message: story context mutation may only be imported from state-backend or pipeline-phase surfaces
  - id: architecture-conformance.rule.phase_state_projection_write_surface
    writer_symbols:
      - save_phase_state
      - save_phase_snapshot
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.pipeline
      - agentkit.backend.pipeline_engine
    message: phase-state projection mutation may only be imported from pipeline surfaces
  - id: architecture-conformance.rule.execution_runtime_write_surface
    writer_symbols:
      - save_flow_execution
      - save_node_execution_ledger
      - save_override_record
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.pipeline
      - agentkit.backend.pipeline_engine
      - agentkit.backend.phase_state_store
    message: execution ledger mutation may only be imported from pipeline or phase-state-store surfaces
  - id: architecture-conformance.rule.attempt_write_surface
    writer_symbols:
      - save_attempt
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.pipeline
      - agentkit.backend.pipeline_engine
    message: attempt mutation may only be imported from pipeline surfaces
  - id: architecture-conformance.rule.telemetry_event_write_surface
    writer_symbols:
      - append_execution_event
      - append_execution_event_global
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.telemetry
      - agentkit.backend.telemetry_service
      - agentkit.backend.control_plane
    message: execution event append may only be imported from telemetry or control-plane surfaces
  - id: architecture-conformance.rule.control_plane_binding_write_surface
    writer_symbols:
      - save_session_run_binding_global
      - delete_session_run_binding_global
      - save_story_execution_lock_global
      - save_control_plane_operation_global
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.control_plane
    message: session, lock, and control-plane operation mutation may only be imported from control-plane surfaces
  - id: architecture-conformance.rule.closure_projection_write_surface
    writer_symbols:
      - upsert_story_metrics
      - record_closure_report
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.closure
    message: closure projections may only be imported from closure surfaces
read_surface_rules:
  - id: architecture-conformance.rule.story_read_surface
    reader_symbols:
      - load_story_contexts_global
      - load_story_context_global
      - load_phase_state_global
      - load_flow_execution_global
      - load_latest_story_metrics_global
      - load_execution_events_global
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.story.repository
    message: story read loaders may only be imported from the explicit story repository surface
  - id: architecture-conformance.rule.control_plane_runtime_read_surface
    reader_symbols:
      - load_control_plane_operation_global
      - load_session_run_binding_global
      - load_story_execution_lock_global
    allowed_module_prefixes:
      - agentkit.backend.state_backend
      - agentkit.backend.control_plane.repository
    message: control-plane runtime read loaders may only be imported from the explicit control-plane repository surface
invariants:
  - id: architecture-conformance.invariant.story_dashboard_transport_boundary
    scope: static-analysis
    rule: story and dashboard modules may not directly import transport or hook adapters
  - id: architecture-conformance.invariant.raw_driver_boundary
    scope: static-analysis
    rule: stable application-surface modules may not import raw state backend drivers directly
  - id: architecture-conformance.invariant.control_plane_http_has_no_persistence_bypass
    scope: static-analysis
    rule: control-plane HTTP/BFF modules compose frontend read models through owner BC read/query ports and never import state-backend repository internals directly
  - id: architecture-conformance.invariant.application_surface_is_acyclic
    scope: static-analysis
    rule: story-types, kpi-analytics dashboard, story-context-manager and kpi-analytics must not form dependency cycles. control_plane and projectedge cyclicity is enforced separately via boundary_module dependency rules.
  - id: architecture-conformance.invariant.runtime_core_is_acyclic
    scope: static-analysis
    rule: pipeline_engine, story_context_manager, phase_state_store, telemetry, prompt_runtime and llm_evaluator must not form dependency cycles
  - id: architecture-conformance.invariant.governance_core_is_acyclic
    scope: static-analysis
    rule: guard_system, governance_observer, conformance_service, stage_registry and failure_corpus must not form dependency cycles
  - id: architecture-conformance.invariant.canonical_write_surface_is_bounded
    scope: static-analysis
    rule: imports of canonical write symbols must stay within explicitly approved mutation surfaces
  - id: architecture-conformance.invariant.story_read_surface_is_bounded
    scope: static-analysis
    rule: imports of global story read loaders must stay within the explicit story repository surface
  - id: architecture-conformance.invariant.control_plane_runtime_read_surface_is_bounded
    scope: static-analysis
    rule: imports of global control-plane runtime read loaders must stay within the explicit control-plane repository surface
```
<!-- FORMAL-SPEC:END -->
