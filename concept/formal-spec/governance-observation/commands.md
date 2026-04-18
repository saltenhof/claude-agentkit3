---
id: formal.governance-observation.commands
title: Governance Observation Commands
status: active
doc_kind: spec
context: governance-observation
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Governance Observation Commands

Governance-Beobachtung sammelt Signale billig und eskaliert erst nach
Schwelle oder hartem Verstoss.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.governance-observation.commands
schema_version: 1
kind: command-set
context: governance-observation
commands:
  - id: governance-observation.command.ingest-signal
    signature: normalize hook or phase signal into rolling window
    allowed_statuses:
      - governance-observation.status.monitoring
    emits:
      - governance-observation.event.signal.ingested
  - id: governance-observation.command.open-incident-candidate
    signature: materialize incident candidate after threshold breach or hard signal
    allowed_statuses:
      - governance-observation.status.monitoring
    requires:
      - governance-observation.invariant.threshold_breach_or_hard_signal_opens_incident
    emits:
      - governance-observation.event.incident_candidate.opened
  - id: governance-observation.command.run-adjudication
    signature: structured evaluator judges incident candidate severity and action
    allowed_statuses:
      - governance-observation.status.incident_candidate_open
    requires:
      - governance-observation.invariant.non_hard_signals_require_adjudication
    emits:
      - governance-observation.event.adjudication.completed
  - id: governance-observation.command.apply-measure
    signature: deterministically apply pause or escalation according to hard signal or adjudication
    allowed_statuses:
      - governance-observation.status.incident_candidate_open
      - governance-observation.status.adjudicating
    requires:
      - governance-observation.invariant.measure_requires_signal_or_adjudication
    emits:
      - governance-observation.event.measure.applied
```
<!-- FORMAL-SPEC:END -->
