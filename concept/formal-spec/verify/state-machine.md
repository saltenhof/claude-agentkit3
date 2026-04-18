---
id: formal.verify.state-machine
title: Verify State Machine
status: active
doc_kind: spec
context: verify
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
  - concept/technical-design/20_workflow_engine_state_machine.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Verify State Machine

Verify ist ein vierstufiger QA-Prozess bis Policy-Entscheidung.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.verify.state-machine
schema_version: 1
kind: state-machine
context: verify
states:
  - id: verify.status.pending
    initial: true
  - id: verify.status.layer1_complete
  - id: verify.status.layer2_complete
  - id: verify.status.layer3_complete
  - id: verify.status.policy_evaluated
  - id: verify.status.passed
    terminal: true
  - id: verify.status.failed
    terminal: true
  - id: verify.status.escalated
    terminal: true
transitions:
  - id: verify.transition.pending_to_layer1_complete
    from: verify.status.pending
    to: verify.status.layer1_complete
    guard: verify.invariant.verify_context_required
  - id: verify.transition.layer1_complete_to_layer2_complete
    from: verify.status.layer1_complete
    to: verify.status.layer2_complete
    guard: verify.invariant.full_qa_required_for_both_contexts
  - id: verify.transition.layer2_complete_to_layer3_complete
    from: verify.status.layer2_complete
    to: verify.status.layer3_complete
    guard: verify.invariant.full_qa_required_for_both_contexts
  - id: verify.transition.layer3_complete_to_policy_evaluated
    from: verify.status.layer3_complete
    to: verify.status.policy_evaluated
  - id: verify.transition.policy_evaluated_to_passed
    from: verify.status.policy_evaluated
    to: verify.status.passed
    guard: verify.invariant.pass_requires_no_blocking_findings
  - id: verify.transition.policy_evaluated_to_failed
    from: verify.status.policy_evaluated
    to: verify.status.failed
  - id: verify.transition.layer1_complete_to_escalated
    from: verify.status.layer1_complete
    to: verify.status.escalated
    guard: verify.invariant.impact_violation_escalates_immediately
compound_rules:
  - id: verify.rule.failed-reenters-implementation
    description: A failed verify does not close the story; the official next step is re-entry into implementation through the story-workflow remediaton path.
```
<!-- FORMAL-SPEC:END -->
