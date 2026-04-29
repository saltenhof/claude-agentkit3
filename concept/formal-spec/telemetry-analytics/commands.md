---
id: formal.telemetry-analytics.commands
title: Telemetry Analytics Commands
status: active
doc_kind: spec
context: telemetry-analytics
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/68_telemetrie_eventing_workflow_metriken.md
  - concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md
  - concept/technical-design/61_kpi_erhebung_nach_domaenen.md
  - concept/technical-design/62_kpi_aggregation.md
  - concept/technical-design/63_auswertung_und_dashboard.md
  - concept/technical-design/91_api_event_katalog.md
---

# Telemetry Analytics Commands

Diese Commands beschreiben die offiziellen Datenpfade zwischen
Runtime-Telemetrie, Analytics und Dashboard.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.telemetry-analytics.commands
schema_version: 1
kind: command-set
context: telemetry-analytics
commands:
  - id: telemetry-analytics.command.collect-valid-events
    signature: internal ingest valid execution events into telemetry and analytics intake
    allowed_statuses:
      - telemetry-analytics.status.requested
    requires:
      - telemetry-analytics.invariant.only-valid-runs-feed-telemetry-analytics
    emits:
      - telemetry-analytics.event.collection.completed
  - id: telemetry-analytics.command.materialize-read-models
    signature: internal build or refresh operational QA and failure-corpus read models
    allowed_statuses:
      - telemetry-analytics.status.collected
    requires:
      - telemetry-analytics.invariant.read-models-are-derived-and-reset-sensitive
    emits:
      - telemetry-analytics.event.read_models.materialized
  - id: telemetry-analytics.command.refresh-facts
    signature: internal refresh analytics fact tables from valid telemetry and read-model sources
    allowed_statuses:
      - telemetry-analytics.status.read_models_materialized
    requires:
      - telemetry-analytics.invariant.facts-derive-from-valid-sources-only
    emits:
      - telemetry-analytics.event.facts.refreshed
  - id: telemetry-analytics.command.query-dashboard
    signature: agentkit dashboard or internal dashboard api query
    allowed_statuses:
      - telemetry-analytics.status.facts_refreshed
    requires:
      - telemetry-analytics.invariant.dashboard-is-read-only-over-runtime-and-analytics
    emits:
      - telemetry-analytics.event.dashboard.served
  - id: telemetry-analytics.command.invalidate-reset-affected-data
    signature: internal purge or invalidate telemetry, read models, and facts after full story reset
    allowed_statuses:
      - telemetry-analytics.status.collected
      - telemetry-analytics.status.read_models_materialized
      - telemetry-analytics.status.facts_refreshed
    requires:
      - telemetry-analytics.invariant.reset-invalidates-read-models-and-facts
    emits:
      - telemetry-analytics.event.data.invalidated
  - id: telemetry-analytics.command.illegal-serve-invalidated-data
    signature: illegal dashboard or analytics serving path over invalidated telemetry or facts
    allowed_statuses:
      - telemetry-analytics.status.invalidated
      - telemetry-analytics.status.read_models_materialized
      - telemetry-analytics.status.facts_refreshed
    requires:
      - telemetry-analytics.invariant.invalidated-data-never-contributes-to-kpis
    emits:
      - telemetry-analytics.event.policy.violation
```
<!-- FORMAL-SPEC:END -->
