---
id: formal.governance-observation.scenarios
title: Governance Observation Scenarios
status: active
doc_kind: spec
context: governance-observation
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Governance Observation Scenarios

Diese Traces pruefen die regulaeren Incident-Ausgaenge.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.governance-observation.scenarios
schema_version: 1
kind: scenario-set
context: governance-observation
scenarios:
  - id: governance-observation.scenario.low-risk-dismissed
    start:
      status: governance-observation.status.monitoring
    trace:
      - command: governance-observation.command.ingest-signal
      - command: governance-observation.command.open-incident-candidate
      - command: governance-observation.command.run-adjudication
    expected_end:
      status: governance-observation.status.dismissed
    requires:
      - governance-observation.invariant.non_hard_signals_require_adjudication
  - id: governance-observation.scenario.secret-access-immediate-escalation
    start:
      status: governance-observation.status.monitoring
    trace:
      - command: governance-observation.command.ingest-signal
      - command: governance-observation.command.open-incident-candidate
      - command: governance-observation.command.apply-measure
    expected_end:
      status: governance-observation.status.escalated
    requires:
      - governance-observation.invariant.hard_signals_bypass_adjudication
  - id: governance-observation.scenario.looping-behaviour-pauses
    start:
      status: governance-observation.status.monitoring
    trace:
      - command: governance-observation.command.ingest-signal
      - command: governance-observation.command.open-incident-candidate
      - command: governance-observation.command.run-adjudication
      - command: governance-observation.command.apply-measure
    expected_end:
      status: governance-observation.status.paused
    requires:
      - governance-observation.invariant.measure_requires_signal_or_adjudication
```
<!-- FORMAL-SPEC:END -->
