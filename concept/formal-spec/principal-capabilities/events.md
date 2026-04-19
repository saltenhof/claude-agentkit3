---
id: formal.principal-capabilities.events
title: Principal Capability Events
status: active
doc_kind: spec
context: principal-capabilities
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/55_principal_capability_model_story_scope_enforcement.md
  - concept/technical-design/91_api_event_katalog.md
---

# Principal Capability Events

Die Capability-Schicht muss auditierbar sein.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.principal-capabilities.events
schema_version: 1
kind: event-set
context: principal-capabilities
events:
  - id: principal-capabilities.event.capability_context_resolved
    role: lifecycle
  - id: principal-capabilities.event.capability_allowed
    role: verdict
  - id: principal-capabilities.event.capability_denied
    role: verdict
  - id: principal-capabilities.event.unauthorized_mutation_detected
    role: audit
  - id: principal-capabilities.event.conflict_freeze_entered
    role: governance
  - id: principal-capabilities.event.conflict_freeze_released
    role: governance
  - id: principal-capabilities.event.official_service_path_entered
    role: lifecycle
  - id: principal-capabilities.event.official_service_path_completed
    role: lifecycle
  - id: principal-capabilities.event.conflict_resolution_requested
    role: governance
  - id: principal-capabilities.event.conflict_resolution_applied
    role: governance
  - id: principal-capabilities.event.conflict_resolution_rejected
    role: governance
  - id: principal-capabilities.event.permission_request_opened
    role: governance
  - id: principal-capabilities.event.permission_request_approved
    role: governance
  - id: principal-capabilities.event.permission_request_rejected
    role: governance
  - id: principal-capabilities.event.permission_request_expired
    role: governance
  - id: principal-capabilities.event.permission_lease_issued
    role: lifecycle
  - id: principal-capabilities.event.external_permission_interference_detected
    role: audit
```
<!-- FORMAL-SPEC:END -->
