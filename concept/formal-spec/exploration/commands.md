---
id: formal.exploration.commands
title: Exploration Commands
status: active
doc_kind: spec
context: exploration
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/23_modusermittlung_exploration_change_frame.md
  - concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Exploration Commands

Exploration laeuft ueber offizielle Phase-Runner-Service- und Resume-Pfade.
Normative Aufruf-Parameter (story_id, phase) sind in FK-91 §91.1a definiert.
Die Operator-Recovery-CLI `agentkit run-phase exploration --story <story_id>`
ist ein Spezialfall (FK-91 §91.1, FK-45 §45.4).

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.exploration.commands
schema_version: 1
kind: command-set
context: exploration
commands:
  - id: exploration.command.run-phase
    signature: POST /v1/story-runs/{run_id}/phases/exploration/start {story_id}
    allowed_statuses:
      - exploration.status.draft_in_progress
      - exploration.status.review_aggregated
      - exploration.status.feindesign_active
    requires:
      - exploration.invariant.gate_requires_approved_for_exit
    emits:
      - exploration.event.draft.written
      - exploration.event.review.aggregated
      - exploration.event.h2.classified
      - exploration.event.feindesign.started
      - exploration.event.exploration.paused
      - exploration.event.gate.approved
      - exploration.event.gate.rejected
  - id: exploration.command.resume
    signature: agentkit resume --story <story_id>
    allowed_statuses:
      - exploration.status.paused_for_human
    requires:
      - exploration.invariant.paused_resume_same_run_same_phase
    emits:
      - exploration.event.exploration.resumed
```
<!-- FORMAL-SPEC:END -->
