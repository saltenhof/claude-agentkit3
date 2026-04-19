---
id: formal.state-storage.events
title: State Storage Events
status: active
doc_kind: spec
context: state-storage
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/14_telemetrie_eventing_workflow_metriken.md
  - concept/technical-design/16_qa_telemetrie_aggregation_dashboard.md
  - concept/technical-design/91_api_event_katalog.md
---

# State Storage Events

Diese Events machen Speicherzustand und Degradation auditierbar.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.state-storage.events
schema_version: 1
kind: event-set
context: state-storage
events:
  - id: state-storage.event.canonical.persisted
    producer: pipeline_engine or story_context_manager
    payload:
      - project_key
      - story_id
      - family_id
      - operation_id
    role: canonical state persisted successfully
  - id: state-storage.event.derived.materialized
    producer: phase_state_store or analytics
    payload:
      - project_key
      - story_id
      - family_id
      - source_family_id
    role: derived family first materialized from canonical source
  - id: state-storage.event.derived.rebuilt
    producer: phase_state_store or analytics
    payload:
      - project_key
      - story_id
      - family_id
      - source_family_id
    role: derived family rebuilt after stale or reset follow-up
  - id: state-storage.event.derived.stale
    producer: phase_state_store or analytics
    payload:
      - project_key
      - story_id
      - family_id
    role: derived family explicitly marked stale
  - id: state-storage.event.derived.invalidated
    producer: story_reset_service
    payload:
      - project_key
      - story_id
      - family_id
      - reset_policy
    role: non-canonical family invalidated or deleted during reset closure
  - id: state-storage.event.telemetry.appended
    producer: telemetry_service
    payload:
      - project_key
      - story_id
      - family_id
      - event_type
    role: runtime observation appended successfully
  - id: state-storage.event.telemetry.degraded
    producer: telemetry_service
    payload:
      - project_key
      - story_id
      - family_id
      - degradation_reason
    role: telemetry append degraded but canonical progress remained allowed
  - id: state-storage.event.runtime.purged
    producer: story_reset_service
    payload:
      - project_key
      - story_id
      - reset_id
      - affected_family_ids
    role: runtime-facing families purged or invalidated for one story reset
  - id: state-storage.event.policy.violation
    producer: guard_system or runtime check
    payload:
      - project_key
      - story_id
      - violation_kind
      - family_id
    role: storage contract violation detected
```
<!-- FORMAL-SPEC:END -->
