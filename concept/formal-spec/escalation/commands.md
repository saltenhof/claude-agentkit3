---
id: formal.escalation.commands
title: Escalation Commands
status: active
doc_kind: spec
context: escalation
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Escalation Commands

Die offiziellen Aufloesungsbefehle liegen ausschliesslich bei
menschlich initiierten CLI-Pfaden.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.escalation.commands
schema_version: 1
kind: command-set
context: escalation
commands:
  - id: escalation.command.pause-run
    signature: set current run to PAUSED after non-terminal human review dependency
    allowed_statuses:
      - escalation.status.triggered
    emits:
      - escalation.event.run.paused
  - id: escalation.command.escalate-run
    signature: set current run to ESCALATED after terminal stop condition
    allowed_statuses:
      - escalation.status.triggered
    emits:
      - escalation.event.run.escalated
  - id: escalation.command.resume-run
    signature: agentkit resume --story {story_id}
    allowed_statuses:
      - escalation.status.paused
    requires:
      - escalation.invariant.paused_resume_preserves_run
    emits:
      - escalation.event.run.resumed
  - id: escalation.command.reset-escalation
    signature: agentkit reset-escalation --story {story_id}
    allowed_statuses:
      - escalation.status.escalated
    requires:
      - escalation.invariant.escalated_reset_requires_new_run
    emits:
      - escalation.event.run.reopened
  - id: escalation.command.redirect-to-split
    signature: agentkit split-story --story {story_id} ...
    allowed_statuses:
      - escalation.status.paused
    requires:
      - escalation.invariant.scope_explosion_defaults_to_explicit_redirect_decision
    emits:
      - escalation.event.run.redirected
```
<!-- FORMAL-SPEC:END -->
