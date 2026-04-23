---
id: formal.architecture-conformance.invariants
title: Architecture Conformance Invariants
status: active
doc_kind: spec
context: architecture-conformance
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/01_systemkontext_und_architekturprinzipien.md
  - concept/technical-design/65_komponentenarchitektur_und_architekturkonformanz.md
---

# Architecture Conformance Invariants

Diese Invarianten definieren die erste fail-closed
Architektur-Konformanzschicht fuer AK3.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.architecture-conformance.invariants
schema_version: 1
kind: invariant-set
context: architecture-conformance
dependency_rules:
  - id: architecture-conformance.rule.story_dashboard_must_not_depend_on_transport_or_hook_adapters
    source_module_prefixes:
      - agentkit.story
      - agentkit.dashboard
    forbidden_module_prefixes:
      - agentkit.control_plane.http
      - agentkit.projectedge.client
      - agentkit.governance.hookruntime
    message: story and dashboard application code may not depend on control-plane transport, project-edge transport, or hook runtime adapters
  - id: architecture-conformance.rule.story_dashboard_control_plane_must_not_depend_on_raw_state_drivers
    source_module_prefixes:
      - agentkit.story
      - agentkit.dashboard
      - agentkit.control_plane
    forbidden_module_prefixes:
      - agentkit.state_backend.postgres_store
      - agentkit.state_backend.sqlite_store
    message: application and control-plane modules may not import raw state-backend drivers directly
  - id: architecture-conformance.rule.projectedge_must_not_depend_on_control_plane_http
    source_module_prefixes:
      - agentkit.projectedge
    forbidden_module_prefixes:
      - agentkit.control_plane.http
    message: project-edge client must not depend on the control-plane HTTP adapter implementation
acyclic_group_sets:
  - id: architecture-conformance.acyclic.application_surface
    group_ids:
      - architecture-conformance.group.story
      - architecture-conformance.group.dashboard
      - architecture-conformance.group.control_plane
      - architecture-conformance.group.projectedge
invariants:
  - id: architecture-conformance.invariant.story_dashboard_transport_boundary
    scope: static-analysis
    rule: story and dashboard modules may not directly import transport or hook adapters
  - id: architecture-conformance.invariant.raw_driver_boundary
    scope: static-analysis
    rule: stable application-surface modules may not import raw state backend drivers directly
  - id: architecture-conformance.invariant.application_surface_is_acyclic
    scope: static-analysis
    rule: story, dashboard, control_plane and projectedge must not form dependency cycles
```
<!-- FORMAL-SPEC:END -->
