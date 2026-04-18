---
id: formal.integrity-gate.state-machine
title: Integrity Gate State Machine
status: active
doc_kind: spec
context: integrity-gate
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Integrity Gate State Machine

Das Gate ist ein eigener Closure-Prozess bis zu PASS FAIL oder
bewusstem Override.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integrity-gate.state-machine
schema_version: 1
kind: state-machine
context: integrity-gate
states:
  - id: integrity-gate.status.open
    initial: true
  - id: integrity-gate.status.mandatory_artifacts_checked
  - id: integrity-gate.status.telemetry_and_dimensions_checked
  - id: integrity-gate.status.passed
    terminal: true
  - id: integrity-gate.status.failed
    terminal: true
  - id: integrity-gate.status.overridden
    terminal: true
transitions:
  - id: integrity-gate.transition.open_to_mandatory_artifacts_checked
    from: integrity-gate.status.open
    to: integrity-gate.status.mandatory_artifacts_checked
    guard: integrity-gate.invariant.mandatory_artifacts_checked_first
  - id: integrity-gate.transition.mandatory_artifacts_checked_to_telemetry_and_dimensions_checked
    from: integrity-gate.status.mandatory_artifacts_checked
    to: integrity-gate.status.telemetry_and_dimensions_checked
    guard: integrity-gate.invariant.only_current_valid_run_is_evaluated
  - id: integrity-gate.transition.telemetry_and_dimensions_checked_to_passed
    from: integrity-gate.status.telemetry_and_dimensions_checked
    to: integrity-gate.status.passed
  - id: integrity-gate.transition.mandatory_artifacts_checked_to_failed
    from: integrity-gate.status.mandatory_artifacts_checked
    to: integrity-gate.status.failed
  - id: integrity-gate.transition.telemetry_and_dimensions_checked_to_failed
    from: integrity-gate.status.telemetry_and_dimensions_checked
    to: integrity-gate.status.failed
  - id: integrity-gate.transition.failed_to_overridden
    from: integrity-gate.status.failed
    to: integrity-gate.status.overridden
    guard: integrity-gate.invariant.override_requires_explicit_human_reason
compound_rules:
  - id: integrity-gate.rule.fail-prevents-closure-until-human-decision
    description: A failed gate ends the current run in ESCALATED state; merge may continue only through the official override path.
```
<!-- FORMAL-SPEC:END -->
