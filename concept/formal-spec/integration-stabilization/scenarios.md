---
id: formal.integration-stabilization.scenarios
title: Integration Stabilization Scenarios
status: active
doc_kind: spec
context: integration-stabilization
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/05_integration_stabilization_contract.md
  - concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md
  - concept/technical-design/37_verify_context_und_qa_bundle.md
---

# Integration Stabilization Scenarios

Die Szenarien pruefen die intended Schleife gegen den formalen Vertrag.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integration-stabilization.scenarios
schema_version: 1
kind: scenario-set
context: integration-stabilization
scenarios:
  - id: integration-stabilization.scenario.approved-manifest-leads-to-stabilized
    start:
      status: integration-stabilization.status.manifest_required
    trace:
      - command: integration-stabilization.command.approve-manifest
      - command: integration-stabilization.command.start-campaign
      - command: integration-stabilization.command.run-e2e-verify
      - command: integration-stabilization.command.complete-stability-gate
    expected_end:
      status: integration-stabilization.status.stabilized
  - id: integration-stabilization.scenario.undeclared-surface-forces-decomposition
    start:
      status: integration-stabilization.status.stabilizing
    trace:
      - command: integration-stabilization.command.run-e2e-verify
      - command: integration-stabilization.command.run-e2e-verify
    expected_end:
      status: integration-stabilization.status.requires_decomposition
  - id: integration-stabilization.scenario.budget-exhaustion-stops-normal-loop
    start:
      status: integration-stabilization.status.verifying_e2e
    trace:
      - command: integration-stabilization.command.run-e2e-verify
    expected_end:
      status: integration-stabilization.status.requires_decomposition
```
<!-- FORMAL-SPEC:END -->
