---
id: formal.guard-system.events
title: Guard System Events
status: active
doc_kind: spec
context: guard-system
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/30_hook_adapter_guard_enforcement.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/91_api_event_katalog.md
---

# Guard System Events

Diese Events bilden Guard-Entscheidungen fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.guard-system.events
schema_version: 1
kind: event-set
context: guard-system
events:
  - id: guard-system.event.guard.allowed
    producer: guard-system
    role: lifecycle
    payload:
      required:
        - check_id
        - guard_id
        - tool_name
  - id: guard-system.event.guard.blocked
    producer: guard-system
    role: lifecycle
    payload:
      required:
        - check_id
        - guard_id
        - tool_name
        - reason
```
<!-- FORMAL-SPEC:END -->
