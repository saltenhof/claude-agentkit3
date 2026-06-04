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
  - concept/technical-design/45_phase_runner_cli.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Story Workflow Commands

Diese Kommandos bilden nur die offiziellen Workflow-Eingriffe fuer den
laufenden Story-Run ab. Normative Aufruf-Parameter (story_id, phase,
mode, op_id) sind in FK-91 §91.1a (Service-API) als Schema-Owner
definiert. Die CLI-Signaturen (FK-91 §91.1) sind menschliche
Operator-Recovery-Pfade.

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
    signature: POST /v1/story-runs/{run_id}/phases/<phase>/start {story_id, mode}
    allowed_statuses:
      - story-workflow.status.in_progress
      - story-workflow.status.failed
    restrictions:
      - target phase must be legal under the phase transition rules
      - failed is only legal as part of an official remediation re-entry that returns the workflow status to in_progress before phase work continues
      - setup is the only legal entry phase for a fresh run
      - a fresh-run setup entry is rejected fail-closed unless StoryStatus is Approved and ExecutionPlanning reports READY with scheduling admission (story-workflow.invariant.phase_start_requires_release_and_readiness)
    requires:
      - story-workflow.invariant.phase_start_requires_release_and_readiness
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
