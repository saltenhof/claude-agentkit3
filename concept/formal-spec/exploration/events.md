---
id: formal.exploration.events
title: Exploration Events
status: active
doc_kind: spec
context: exploration
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/23_modusermittlung_exploration_change_frame.md
  - concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Exploration Events

Diese Events bilden den Exploration- und H2-Pfad fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.exploration.events
schema_version: 1
kind: event-set
context: exploration
events:
  - id: exploration.event.draft.written
    producer: exploration
    role: lifecycle
    payload:
      required:
        - story_id
        - draft_ref
  - id: exploration.event.review.aggregated
    producer: exploration
    role: lifecycle
    payload:
      required:
        - story_id
        - finding_refs
  - id: exploration.event.h2.classified
    producer: exploration
    role: lifecycle
    payload:
      required:
        - story_id
        - classes
  - id: exploration.event.feindesign.started
    producer: exploration
    role: lifecycle
    payload:
      required:
        - story_id
        - finding_refs
  - id: exploration.event.exploration.paused
    producer: exploration
    role: lifecycle
    payload:
      required:
        - story_id
        - escalation_class
  - id: exploration.event.exploration.resumed
    producer: human
    role: lifecycle
    payload:
      required:
        - story_id
  - id: exploration.event.gate.approved
    producer: exploration
    role: lifecycle
    payload:
      required:
        - story_id
        - gate_status
  - id: exploration.event.gate.rejected
    producer: exploration
    role: lifecycle
    payload:
      required:
        - story_id
        - gate_status
        - rejection_reason
```
<!-- FORMAL-SPEC:END -->
