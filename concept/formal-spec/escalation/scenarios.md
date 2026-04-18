---
id: formal.escalation.scenarios
title: Escalation Scenarios
status: active
doc_kind: spec
context: escalation
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Escalation Scenarios

Diese Traces pruefen die regulaeren Aufloesungen von `PAUSED` und
`ESCALATED`.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.escalation.scenarios
schema_version: 1
kind: scenario-set
context: escalation
scenarios:
  - id: escalation.scenario.paused_governance_resume
    start:
      status: escalation.status.triggered
    trace:
      - command: escalation.command.pause-run
      - command: escalation.command.resume-run
    expected_end:
      status: escalation.status.resumed
    requires:
      - escalation.invariant.paused_resume_preserves_run
      - escalation.invariant.explicit_human_intervention_required
  - id: escalation.scenario.integrity_gate_fail_reopens_new_run
    start:
      status: escalation.status.triggered
    trace:
      - command: escalation.command.escalate-run
      - command: escalation.command.reset-escalation
    expected_end:
      status: escalation.status.reopened
    requires:
      - escalation.invariant.escalated_reset_requires_new_run
  - id: escalation.scenario.scope_explosion_redirects_to_split
    start:
      status: escalation.status.triggered
    trace:
      - command: escalation.command.pause-run
      - command: escalation.command.redirect-to-split
    expected_end:
      status: escalation.status.redirected
    requires:
      - escalation.invariant.scope_explosion_defaults_to_explicit_redirect_decision
```
<!-- FORMAL-SPEC:END -->
