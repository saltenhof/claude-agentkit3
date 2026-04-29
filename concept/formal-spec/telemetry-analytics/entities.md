---
id: formal.telemetry-analytics.entities
title: Telemetry Analytics Entities
status: active
doc_kind: spec
context: telemetry-analytics
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/68_telemetrie_eventing_workflow_metriken.md
  - concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md
  - concept/technical-design/60_kpi_katalog_und_architektur.md
  - concept/technical-design/62_kpi_aggregation.md
---

# Telemetry Analytics Entities

Dieser Kontext modelliert die fachlichen Datenobjekte zwischen
Event-Erhebung und read-only Auswertung.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.telemetry-analytics.entities
schema_version: 1
kind: entity-set
context: telemetry-analytics
entities:
  - id: telemetry-analytics.entity.event-stream
    identity_key: stream_id
    attributes:
      - stream_id
      - project_key
      - story_id
      - run_id
      - validity_scope
      - source_component
  - id: telemetry-analytics.entity.read-model-family
    identity_key: family_id
    attributes:
      - family_id
      - project_key
      - read_model_kind
      - source_stream_id
      - freshness_status
      - reset_sensitive
  - id: telemetry-analytics.entity.fact-family
    identity_key: fact_family_id
    attributes:
      - fact_family_id
      - project_key
      - fact_granularity
      - source_family_ids
      - refresh_status
      - validity_status
  - id: telemetry-analytics.entity.dashboard-query
    identity_key: query_id
    attributes:
      - query_id
      - project_key
      - query_scope
      - source_fact_family
      - read_only
```
<!-- FORMAL-SPEC:END -->
