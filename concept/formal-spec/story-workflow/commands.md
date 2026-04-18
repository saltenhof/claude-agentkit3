---
id: formal.story-workflow.commands
title: Story Workflow Commands
status: active
doc_kind: spec
context: story-workflow
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/20_workflow_engine_state_machine.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Story Workflow Commands

Diese Kommandos bilden nur die offiziellen Workflow-Eingriffe fuer den
laufenden Story-Run ab.

`split-story` und `reset-story` gehoeren bewusst nicht in diesen
Kontext, weil sie administrative Services ausserhalb des normalen
Run-Kontrollflusses sind.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-workflow.commands
schema_version: 1
kind: command-set
context: story-workflow
commands:
  - id: story-workflow.command.run-phase
    signature: agentkit run-phase <phase> --story <story_id>
    allowed_statuses:
      - story-workflow.status.in_progress
      - story-workflow.status.failed
    restrictions:
      - target phase must be legal under the phase transition rules
      - failed is only legal for verify to implementation remediation
      - setup is the only legal entry phase for a fresh run
    emits:
      - story-workflow.event.phase.started
      - story-workflow.event.phase.completed
      - story-workflow.event.phase.failed
      - story-workflow.event.phase.paused
      - story-workflow.event.phase.escalated
      - story-workflow.event.transition.rejected
  - id: story-workflow.command.resume
    signature: agentkit resume --story <story_id>
    allowed_statuses:
      - story-workflow.status.paused
    restrictions:
      - resumes the same run_id
      - resumes the same current_phase
    emits:
      - story-workflow.event.phase.resumed
  - id: story-workflow.command.reset-escalation
    signature: agentkit reset-escalation --story <story_id>
    allowed_statuses:
      - story-workflow.status.escalated
    restrictions:
      - does not continue the existing run
      - creates a new run_id before workflow processing can continue
    emits:
      - story-workflow.event.run.restarted
```
<!-- FORMAL-SPEC:END -->
