---
id: formal.integration-stabilization.commands
title: Integration Stabilization Commands
status: active
doc_kind: spec
context: integration-stabilization
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/57_integration_stabilization_contract.md
  - concept/technical-design/91_api_event_katalog.md
---

# Integration Stabilization Commands

Die Stabilisierung nutzt offizielle Pfade fuer Manifest-Freigabe und
Replan, nicht freie Guard-Ausnahmen.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integration-stabilization.commands
schema_version: 1
kind: command-set
context: integration-stabilization
commands:
  - id: integration-stabilization.command.approve-manifest
    actor: human_cli
    allowed_from:
      - integration-stabilization.status.manifest_required
    emits:
      - integration-stabilization.event.integration_manifest_approved
  - id: integration-stabilization.command.start-campaign
    actor: pipeline_deterministic
    allowed_from:
      - integration-stabilization.status.manifest_approved
    emits:
      - integration-stabilization.event.stabilization_campaign_started
  - id: integration-stabilization.command.run-e2e-verify
    actor: pipeline_deterministic
    allowed_from:
      - integration-stabilization.status.stabilizing
    emits:
      - integration-stabilization.event.integration_verify_passed
      - integration-stabilization.event.integration_verify_failed
  - id: integration-stabilization.command.request-manifest-amendment
    actor: human_cli
    allowed_from:
      - integration-stabilization.status.stabilizing
      - integration-stabilization.status.verifying_e2e
    emits:
      - integration-stabilization.event.manifest_amendment_requested
  - id: integration-stabilization.command.complete-stability-gate
    actor: pipeline_deterministic
    allowed_from:
      - integration-stabilization.status.verifying_e2e
    emits:
      - integration-stabilization.event.stability_gate_passed
```
<!-- FORMAL-SPEC:END -->
