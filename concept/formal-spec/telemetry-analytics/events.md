---
id: formal.telemetry-analytics.events
title: Telemetry Analytics Events
status: active
doc_kind: spec
context: telemetry-analytics
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/68_telemetrie_eventing_workflow_metriken.md
  - concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md
  - concept/technical-design/61_kpi_erhebung_nach_domaenen.md
  - concept/technical-design/62_kpi_aggregation.md
  - concept/technical-design/63_auswertung_und_dashboard.md
  - concept/technical-design/91_api_event_katalog.md
---

# Telemetry Analytics Events

Diese Events machen Collection, Refresh und Dashboard-Auswertung
auditierbar.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.telemetry-analytics.events
schema_version: 1
kind: event-set
context: telemetry-analytics
events:
  - id: telemetry-analytics.event.collection.completed
    producer: telemetry_service or analytics intake worker
    payload:
      - project_key
      - collected_event_count
      - validity_scope
    role: valid runtime events collected for downstream processing
  - id: telemetry-analytics.event.read_models.materialized
    producer: qa_read_model_projection or failure_corpus_projection
    payload:
      - project_key
      - source_stream_id
      - affected_read_models
    role: operational read models materialized from valid sources
  - id: telemetry-analytics.event.facts.refreshed
    producer: analytics refresh worker
    payload:
      - project_key
      - refreshed_fact_families
      - aggregation_window
    role: analytics facts refreshed from valid telemetry and read-model sources
  - id: telemetry-analytics.event.dashboard.served
    producer: dashboard service
    payload:
      - project_key
      - query_scope
      - source_fact_family
    role: dashboard served a read-only result set
  - id: telemetry-analytics.event.data.invalidated
    producer: story_reset_service or analytics invalidation worker
    payload:
      - project_key
      - story_id
      - affected_families
    role: telemetry, read-model, or fact data invalidated due to reset or source invalidation
  - id: telemetry-analytics.event.policy.violation
    producer: dashboard service or analytics guard
    payload:
      - project_key
      - violation_kind
      - query_scope
    role: invalid analytics or dashboard serving path detected
```
<!-- FORMAL-SPEC:END -->
