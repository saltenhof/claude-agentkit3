---
id: formal.escalation.events
title: Escalation Events
status: active
doc_kind: spec
context: escalation
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Escalation Events

Diese Events bilden die offiziellen menschlichen Aufloesungspfade ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.escalation.events
schema_version: 1
kind: event-set
context: escalation
events:
  - id: escalation.event.run.paused
    producer: escalation
    role: lifecycle
    payload:
      required:
        - escalation_id
        - story_id
        - run_id
        - trigger
  - id: escalation.event.run.escalated
    producer: escalation
    role: lifecycle
    payload:
      required:
        - escalation_id
        - story_id
        - run_id
        - trigger
  - id: escalation.event.run.resumed
    producer: escalation
    role: lifecycle
    payload:
      required:
        - escalation_id
        - story_id
        - run_id
  - id: escalation.event.run.reopened
    producer: escalation
    role: lifecycle
    payload:
      required:
        - escalation_id
        - story_id
        - previous_run_id
        - next_run_id
  - id: escalation.event.run.redirected
    producer: escalation
    role: governance
    payload:
      required:
        - escalation_id
        - story_id
        - target_process
```
<!-- FORMAL-SPEC:END -->
