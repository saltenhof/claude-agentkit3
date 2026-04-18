---
id: formal.governance-observation.state-machine
title: Governance Observation State Machine
status: active
doc_kind: spec
context: governance-observation
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Governance Observation State Machine

Governance-Beobachtung ist ein laufender Incident-Prozess von Signal
bis Massnahme.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.governance-observation.state-machine
schema_version: 1
kind: state-machine
context: governance-observation
states:
  - id: governance-observation.status.monitoring
    initial: true
  - id: governance-observation.status.incident_candidate_open
  - id: governance-observation.status.adjudicating
  - id: governance-observation.status.dismissed
    terminal: true
  - id: governance-observation.status.paused
    terminal: true
  - id: governance-observation.status.escalated
    terminal: true
transitions:
  - id: governance-observation.transition.monitoring_to_incident_candidate_open
    from: governance-observation.status.monitoring
    to: governance-observation.status.incident_candidate_open
    guard: governance-observation.invariant.threshold_breach_or_hard_signal_opens_incident
  - id: governance-observation.transition.incident_candidate_open_to_adjudicating
    from: governance-observation.status.incident_candidate_open
    to: governance-observation.status.adjudicating
    guard: governance-observation.invariant.non_hard_signals_require_adjudication
  - id: governance-observation.transition.adjudicating_to_dismissed
    from: governance-observation.status.adjudicating
    to: governance-observation.status.dismissed
  - id: governance-observation.transition.adjudicating_to_paused
    from: governance-observation.status.adjudicating
    to: governance-observation.status.paused
  - id: governance-observation.transition.incident_candidate_open_to_escalated
    from: governance-observation.status.incident_candidate_open
    to: governance-observation.status.escalated
    guard: governance-observation.invariant.hard_signals_bypass_adjudication
compound_rules:
  - id: governance-observation.rule.measures-derive-from-signal-or-adjudication
    description: Every pause or escalation measure must be justified either by a hard signal or by an adjudication result and may not be emitted ad hoc.
```
<!-- FORMAL-SPEC:END -->
