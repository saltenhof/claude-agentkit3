---
id: formal.telemetry-analytics.state-machine
title: Telemetry Analytics State Machine
status: active
doc_kind: spec
context: telemetry-analytics
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/68_telemetrie_eventing_workflow_metriken.md
  - concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md
  - concept/technical-design/62_kpi_aggregation.md
  - concept/technical-design/63_auswertung_und_dashboard.md
---

# Telemetry Analytics State Machine

Die State-Machine bildet die gueltige Kette von Collection ueber
Aggregation bis zur read-only Auswertung ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.telemetry-analytics.state-machine
schema_version: 1
kind: state-machine
context: telemetry-analytics
states:
  - id: telemetry-analytics.status.requested
    initial: true
  - id: telemetry-analytics.status.collected
  - id: telemetry-analytics.status.read_models_materialized
  - id: telemetry-analytics.status.facts_refreshed
  - id: telemetry-analytics.status.served
    terminal: true
  - id: telemetry-analytics.status.invalidated
    terminal: true
  - id: telemetry-analytics.status.rejected
    terminal: true
transitions:
  - id: telemetry-analytics.transition.requested_to_collected
    from: telemetry-analytics.status.requested
    to: telemetry-analytics.status.collected
    guard: telemetry-analytics.invariant.only-valid-runs-feed-telemetry-analytics
  - id: telemetry-analytics.transition.collected_to_read_models_materialized
    from: telemetry-analytics.status.collected
    to: telemetry-analytics.status.read_models_materialized
    guard: telemetry-analytics.invariant.read-models-are-derived-and-reset-sensitive
  - id: telemetry-analytics.transition.read_models_materialized_to_facts_refreshed
    from: telemetry-analytics.status.read_models_materialized
    to: telemetry-analytics.status.facts_refreshed
    guard: telemetry-analytics.invariant.facts-derive-from-valid-sources-only
  - id: telemetry-analytics.transition.facts_refreshed_to_served
    from: telemetry-analytics.status.facts_refreshed
    to: telemetry-analytics.status.served
    guard: telemetry-analytics.invariant.dashboard-is-read-only-over-runtime-and-analytics
  - id: telemetry-analytics.transition.collected_to_invalidated
    from: telemetry-analytics.status.collected
    to: telemetry-analytics.status.invalidated
  - id: telemetry-analytics.transition.read_models_materialized_to_invalidated
    from: telemetry-analytics.status.read_models_materialized
    to: telemetry-analytics.status.invalidated
    guard: telemetry-analytics.invariant.reset-invalidates-read-models-and-facts
  - id: telemetry-analytics.transition.facts_refreshed_to_invalidated
    from: telemetry-analytics.status.facts_refreshed
    to: telemetry-analytics.status.invalidated
    guard: telemetry-analytics.invariant.reset-invalidates-read-models-and-facts
  - id: telemetry-analytics.transition.invalidated_to_rejected
    from: telemetry-analytics.status.invalidated
    to: telemetry-analytics.status.rejected
    guard: telemetry-analytics.invariant.invalidated-data-never-contributes-to-kpis
  - id: telemetry-analytics.transition.requested_to_rejected
    from: telemetry-analytics.status.requested
    to: telemetry-analytics.status.rejected
  - id: telemetry-analytics.transition.collected_to_rejected
    from: telemetry-analytics.status.collected
    to: telemetry-analytics.status.rejected
  - id: telemetry-analytics.transition.read_models_materialized_to_rejected
    from: telemetry-analytics.status.read_models_materialized
    to: telemetry-analytics.status.rejected
compound_rules:
  - id: telemetry-analytics.rule.invalidated-data-must-not-be-served
    description: Once telemetry, read-models, or facts are invalidated by reset, they may not be served or counted until rebuilt from a valid source.
```
<!-- FORMAL-SPEC:END -->
