---
id: formal.conformance.scenarios
title: Conformance Scenarios
status: active
doc_kind: spec
context: conformance
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/32_dokumententreue_conformance_service.md
---

# Conformance Scenarios

Diese Traces pruefen die regulaeren Ausgaenge der vier Ebenen.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.conformance.scenarios
schema_version: 1
kind: scenario-set
context: conformance
scenarios:
  - id: conformance.scenario.goal-fidelity-pass
    start:
      status: conformance.status.pending
    trace:
      - command: conformance.command.evaluate-goal-fidelity
    expected_end:
      status: conformance.status.passed
    requires:
      - conformance.invariant.subject_and_reference_bundle_required
      - conformance.invariant.one_verdict_per_assessment
  - id: conformance.scenario.design-fidelity-concern
    start:
      status: conformance.status.pending
    trace:
      - command: conformance.command.evaluate-design-fidelity
    expected_end:
      status: conformance.status.passed_with_concerns
    requires:
      - conformance.invariant.only_curated_references_enter_assessment
  - id: conformance.scenario.impl-fidelity-hard-limit-fails
    start:
      status: conformance.status.pending
    trace:
      - command: conformance.command.evaluate-implementation-fidelity
    expected_end:
      status: conformance.status.failed
    requires:
      - conformance.invariant.payload_limit_fail_closed
```
<!-- FORMAL-SPEC:END -->
