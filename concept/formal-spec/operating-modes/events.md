---
id: formal.operating-modes.events
title: Operating Mode Events
status: active
doc_kind: spec
context: operating-modes
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Operating Mode Events

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.operating-modes.events
schema_version: 1
kind: event-set
context: operating-modes
events:
  - id: operating-modes.event.operating_mode_resolved
    role: lifecycle
  - id: operating-modes.event.interactive_mode_assumed
    role: lifecycle
  - id: operating-modes.event.session_run_binding_created
    role: governance
  - id: operating-modes.event.session_run_binding_removed
    role: governance
  - id: operating-modes.event.story_execution_regime_activated
    role: governance
  - id: operating-modes.event.story_execution_regime_deactivated
    role: governance
  - id: operating-modes.event.binding_invalid_detected
    role: audit
  - id: operating-modes.event.local_edge_bundle_materialized
    role: governance
  - id: operating-modes.event.edge_operation_reconciled
    role: audit
```
<!-- FORMAL-SPEC:END -->
