---
id: formal.state-storage.state-machine
title: State Storage State Machine
status: active
doc_kind: spec
context: state-storage
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/18_relationales_abbildungsmodell_postgres.md
  - concept/technical-design/16_qa_telemetrie_aggregation_dashboard.md
  - concept/technical-design/53_story_reset_service_recovery_flow.md
---

# State Storage State Machine

Die State-Machine bildet nicht den Story-Lebenszyklus, sondern die
Kohärenz einer fachlichen Storage-Episode.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.state-storage.state-machine
schema_version: 1
kind: state-machine
context: state-storage
states:
  - id: state-storage.status.ready
    initial: true
  - id: state-storage.status.canonical_current
  - id: state-storage.status.derived_current
    terminal: true
  - id: state-storage.status.derived_stale
    terminal: true
  - id: state-storage.status.resetting
  - id: state-storage.status.purged
    terminal: true
  - id: state-storage.status.blocked
    terminal: true
transitions:
  - id: state-storage.transition.ready_to_canonical_current
    from: state-storage.status.ready
    to: state-storage.status.canonical_current
    guard: state-storage.invariant.tenant_scoped_families_require_project_key
  - id: state-storage.transition.canonical_current_to_derived_current
    from: state-storage.status.canonical_current
    to: state-storage.status.derived_current
    guard: state-storage.invariant.derived_families_never_become_source_of_truth
  - id: state-storage.transition.derived_current_to_derived_stale
    from: state-storage.status.derived_current
    to: state-storage.status.derived_stale
  - id: state-storage.transition.derived_stale_to_derived_current
    from: state-storage.status.derived_stale
    to: state-storage.status.derived_current
    guard: state-storage.invariant.rebuild_only_families_require_canonical_source
  - id: state-storage.transition.canonical_current_to_resetting
    from: state-storage.status.canonical_current
    to: state-storage.status.resetting
  - id: state-storage.transition.derived_current_to_resetting
    from: state-storage.status.derived_current
    to: state-storage.status.resetting
  - id: state-storage.transition.derived_stale_to_resetting
    from: state-storage.status.derived_stale
    to: state-storage.status.resetting
  - id: state-storage.transition.resetting_to_purged
    from: state-storage.status.resetting
    to: state-storage.status.purged
    guard: state-storage.invariant.reset_closure_cleans_dependent_families
  - id: state-storage.transition.ready_to_blocked
    from: state-storage.status.ready
    to: state-storage.status.blocked
  - id: state-storage.transition.canonical_current_to_blocked
    from: state-storage.status.canonical_current
    to: state-storage.status.blocked
  - id: state-storage.transition.derived_current_to_blocked
    from: state-storage.status.derived_current
    to: state-storage.status.blocked
  - id: state-storage.transition.derived_stale_to_blocked
    from: state-storage.status.derived_stale
    to: state-storage.status.blocked
compound_rules:
  - id: state-storage.rule.telemetry-failure-does-not-block-canonical-write
    description: Telemetry degradation may reduce observability, but must not prevent a canonical state write from completing.
```
<!-- FORMAL-SPEC:END -->
