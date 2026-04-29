---
id: formal.integration-stabilization.events
title: Integration Stabilization Events
status: active
doc_kind: spec
context: integration-stabilization
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/05_integration_stabilization_contract.md
  - concept/technical-design/37_verify_context_und_qa_bundle.md
  - concept/technical-design/91_api_event_katalog.md
---

# Integration Stabilization Events

Die Ereignisse machen Manifest-Freigabe, Scope-Verletzung und
Budgetverbrauch auditierbar.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integration-stabilization.events
schema_version: 1
kind: event-set
context: integration-stabilization
events:
  - id: integration-stabilization.event.integration_manifest_approved
    producer: human_cli
  - id: integration-stabilization.event.stabilization_campaign_started
    producer: pipeline_deterministic
  - id: integration-stabilization.event.integration_verify_passed
    producer: pipeline_deterministic
  - id: integration-stabilization.event.integration_verify_failed
    producer: pipeline_deterministic
  - id: integration-stabilization.event.undeclared_surface_detected
    producer: guard_system
  - id: integration-stabilization.event.stabilization_budget_exhausted
    producer: guard_system
  - id: integration-stabilization.event.manifest_amendment_requested
    producer: human_cli
  - id: integration-stabilization.event.stability_gate_passed
    producer: pipeline_deterministic
```
<!-- FORMAL-SPEC:END -->
