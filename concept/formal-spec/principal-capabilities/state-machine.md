---
id: formal.principal-capabilities.state-machine
title: Principal Capability State Machine
status: active
doc_kind: spec
context: principal-capabilities
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/55_principal_capability_model_story_scope_enforcement.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Principal Capability State Machine

Der relevante Lebenszyklus ist die Freeze- und Freigabesemantik einer
storybezogenen Capability-Zone.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.principal-capabilities.state-machine
schema_version: 1
kind: state-machine
context: principal-capabilities
states:
  - id: principal-capabilities.status.normal
    initial: true
  - id: principal-capabilities.status.story_scoped
  - id: principal-capabilities.status.permission_pending
  - id: principal-capabilities.status.frozen
  - id: principal-capabilities.status.official_service_active
  - id: principal-capabilities.status.released
    terminal: true
  - id: principal-capabilities.status.denied
    terminal: true
transitions:
  - id: principal-capabilities.transition.normal_to_story_scoped
    from: principal-capabilities.status.normal
    to: principal-capabilities.status.story_scoped
  - id: principal-capabilities.transition.story_scoped_to_frozen
    from: principal-capabilities.status.story_scoped
    to: principal-capabilities.status.frozen
    guard: principal-capabilities.invariant.freeze_removes_orchestrator_mutation_rights
  - id: principal-capabilities.transition.story_scoped_to_permission_pending
    from: principal-capabilities.status.story_scoped
    to: principal-capabilities.status.permission_pending
    guard: principal-capabilities.invariant.no_native_prompt_during_story_lock
  - id: principal-capabilities.transition.permission_pending_to_released
    from: principal-capabilities.status.permission_pending
    to: principal-capabilities.status.released
  - id: principal-capabilities.transition.permission_pending_to_denied
    from: principal-capabilities.status.permission_pending
    to: principal-capabilities.status.denied
  - id: principal-capabilities.transition.frozen_to_official_service_active
    from: principal-capabilities.status.frozen
    to: principal-capabilities.status.official_service_active
    guard: principal-capabilities.invariant.only_official_service_or_human_cli_may_mutate_during_freeze
  - id: principal-capabilities.transition.official_service_active_to_released
    from: principal-capabilities.status.official_service_active
    to: principal-capabilities.status.released
  - id: principal-capabilities.transition.frozen_to_denied
    from: principal-capabilities.status.frozen
    to: principal-capabilities.status.denied
  - id: principal-capabilities.transition.story_scoped_to_denied
    from: principal-capabilities.status.story_scoped
    to: principal-capabilities.status.denied
  - id: principal-capabilities.transition.story_scoped_to_released
    from: principal-capabilities.status.story_scoped
    to: principal-capabilities.status.released
  - id: principal-capabilities.transition.normal_to_released
    from: principal-capabilities.status.normal
    to: principal-capabilities.status.released
compound_rules:
  - id: principal-capabilities.rule.same_run_keeps_same_authority_basis
    description: A running story may not swap its authoritative setup basis in place; a frozen conflict requires an official continuation path.
```
<!-- FORMAL-SPEC:END -->
