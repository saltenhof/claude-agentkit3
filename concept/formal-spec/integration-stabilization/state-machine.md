---
id: formal.integration-stabilization.state-machine
title: Integration Stabilization State Machine
status: active
doc_kind: spec
context: integration-stabilization
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/57_integration_stabilization_contract.md
  - concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md
  - concept/technical-design/37_verify_context_und_qa_bundle.md
---

# Integration Stabilization State Machine

Die Stabilisierung ist eine budgetierte Schleife, kein freies
Endlos-Arbeiten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integration-stabilization.state-machine
schema_version: 1
kind: state-machine
context: integration-stabilization
states:
  - id: integration-stabilization.status.manifest_required
    initial: true
  - id: integration-stabilization.status.manifest_approved
  - id: integration-stabilization.status.stabilizing
  - id: integration-stabilization.status.verifying_e2e
  - id: integration-stabilization.status.stabilized
    terminal: true
  - id: integration-stabilization.status.requires_decomposition
    terminal: true
  - id: integration-stabilization.status.escalated
    terminal: true
transitions:
  - id: integration-stabilization.transition.manifest_required_to_manifest_approved
    from: integration-stabilization.status.manifest_required
    to: integration-stabilization.status.manifest_approved
    guard: integration-stabilization.invariant.integration_contract_requires_approved_manifest
  - id: integration-stabilization.transition.manifest_approved_to_stabilizing
    from: integration-stabilization.status.manifest_approved
    to: integration-stabilization.status.stabilizing
    guard: integration-stabilization.invariant.integration_contract_requires_exploration_first
  - id: integration-stabilization.transition.stabilizing_to_verifying_e2e
    from: integration-stabilization.status.stabilizing
    to: integration-stabilization.status.verifying_e2e
  - id: integration-stabilization.transition.verifying_e2e_to_stabilizing
    from: integration-stabilization.status.verifying_e2e
    to: integration-stabilization.status.stabilizing
    guard: integration-stabilization.invariant.failed_e2e_verify_may_continue_only_inside_budget
  - id: integration-stabilization.transition.verifying_e2e_to_stabilized
    from: integration-stabilization.status.verifying_e2e
    to: integration-stabilization.status.stabilized
    guard: integration-stabilization.invariant.closure_requires_stability_gate_pass
  - id: integration-stabilization.transition.stabilizing_to_requires_decomposition
    from: integration-stabilization.status.stabilizing
    to: integration-stabilization.status.requires_decomposition
    guard: integration-stabilization.invariant.undeclared_surface_is_not_normal_stabilization_work
  - id: integration-stabilization.transition.verifying_e2e_to_requires_decomposition
    from: integration-stabilization.status.verifying_e2e
    to: integration-stabilization.status.requires_decomposition
    guard: integration-stabilization.invariant.budget_exhaustion_requires_replan_or_decomposition
  - id: integration-stabilization.transition.stabilizing_to_escalated
    from: integration-stabilization.status.stabilizing
    to: integration-stabilization.status.escalated
    guard: integration-stabilization.invariant.manifest_may_not_be_mutated_in_place_during_active_stabilization
compound_rules:
  - id: integration-stabilization.rule.no-new-operating-mode
    description: integration stabilization remains inside story_execution and does not create a third operating mode
  - id: integration-stabilization.rule.scope-explosion-remains-active
    description: scope explosion is evaluated against story specification plus approved integration scope manifest and is never globally disabled
```
<!-- FORMAL-SPEC:END -->
