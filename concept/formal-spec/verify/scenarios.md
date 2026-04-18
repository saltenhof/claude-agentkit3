---
id: formal.verify.scenarios
title: Verify Scenarios
status: active
doc_kind: spec
context: verify
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
  - concept/technical-design/20_workflow_engine_state_machine.md
---

# Verify Scenarios

Diese Traces pruefen die drei Pflichtausgaenge von Verify.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.verify.scenarios
schema_version: 1
kind: scenario-set
context: verify
scenarios:
  - id: verify.scenario.full-pass
    start:
      status: verify.status.pending
    trace:
      - command: verify.command.run-phase
    expected_end:
      status: verify.status.passed
    requires:
      - verify.invariant.verify_context_required
      - verify.invariant.pass_requires_no_blocking_findings
  - id: verify.scenario.failed-after-policy
    start:
      status: verify.status.pending
    trace:
      - command: verify.command.run-phase
    expected_end:
      status: verify.status.failed
    requires:
      - verify.invariant.full_qa_required_for_both_contexts
  - id: verify.scenario.impact-violation-escalates
    start:
      status: verify.status.pending
    trace:
      - command: verify.command.run-phase
    expected_end:
      status: verify.status.escalated
    requires:
      - verify.invariant.impact_violation_escalates_immediately
```
<!-- FORMAL-SPEC:END -->
