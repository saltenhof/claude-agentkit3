---
id: formal.conformance.state-machine
title: Conformance State Machine
status: active
doc_kind: spec
context: conformance
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/32_dokumententreue_conformance_service.md
---

# Conformance State Machine

Conformance ist ein normativer Bewertungsprozess bis zu einem
Verdikt fuer genau eine Ebene.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.conformance.state-machine
schema_version: 1
kind: state-machine
context: conformance
states:
  - id: conformance.status.pending
    initial: true
  - id: conformance.status.references_resolved
  - id: conformance.status.evaluating
  - id: conformance.status.passed
    terminal: true
  - id: conformance.status.passed_with_concerns
    terminal: true
  - id: conformance.status.failed
    terminal: true
transitions:
  - id: conformance.transition.pending_to_references_resolved
    from: conformance.status.pending
    to: conformance.status.references_resolved
    guard: conformance.invariant.only_curated_references_enter_assessment
  - id: conformance.transition.references_resolved_to_evaluating
    from: conformance.status.references_resolved
    to: conformance.status.evaluating
    guard: conformance.invariant.subject_and_reference_bundle_required
  - id: conformance.transition.evaluating_to_passed
    from: conformance.status.evaluating
    to: conformance.status.passed
  - id: conformance.transition.evaluating_to_passed_with_concerns
    from: conformance.status.evaluating
    to: conformance.status.passed_with_concerns
  - id: conformance.transition.evaluating_to_failed
    from: conformance.status.evaluating
    to: conformance.status.failed
    guard: conformance.invariant.payload_limit_fail_closed
compound_rules:
  - id: conformance.rule.feedback-level-only-after-merge
    description: Feedback fidelity is the only level that may run after merge; all other levels must complete before the story may leave their owning phase.
```
<!-- FORMAL-SPEC:END -->
