---
id: formal.escalation.state-machine
title: Escalation State Machine
status: active
doc_kind: spec
context: escalation
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Escalation State Machine

Der Eskalationskontext modelliert die offizielle menschliche
Aufloesung nach `PAUSED` oder `ESCALATED`.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.escalation.state-machine
schema_version: 1
kind: state-machine
context: escalation
states:
  - id: escalation.status.triggered
    initial: true
  - id: escalation.status.paused
  - id: escalation.status.escalated
  - id: escalation.status.resumed
    terminal: true
  - id: escalation.status.reopened
    terminal: true
  - id: escalation.status.redirected
    terminal: true
transitions:
  - id: escalation.transition.triggered_to_paused
    from: escalation.status.triggered
    to: escalation.status.paused
  - id: escalation.transition.triggered_to_escalated
    from: escalation.status.triggered
    to: escalation.status.escalated
  - id: escalation.transition.paused_to_resumed
    from: escalation.status.paused
    to: escalation.status.resumed
    guard: escalation.invariant.paused_resume_preserves_run
  - id: escalation.transition.escalated_to_reopened
    from: escalation.status.escalated
    to: escalation.status.reopened
    guard: escalation.invariant.escalated_reset_requires_new_run
  - id: escalation.transition.paused_to_redirected
    from: escalation.status.paused
    to: escalation.status.redirected
    guard: escalation.invariant.scope_explosion_defaults_to_explicit_redirect_decision
compound_rules:
  - id: escalation.rule.no_automatic_recovery
    description: Neither pause nor escalation may resolve automatically; every transition out of them requires an explicit human action.
```
<!-- FORMAL-SPEC:END -->
