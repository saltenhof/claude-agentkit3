---
id: formal.story-workflow.commands
title: Story Workflow Commands
status: active
doc_kind: spec
context: story-workflow
spec_kind: command-set
version: 2
prose_refs:
  - concept/technical-design/20_workflow_engine_state_machine.md
  - concept/technical-design/45_phase_runner_cli.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Story Workflow Commands

Diese Kommandos bilden nur die offiziellen Workflow-Eingriffe fuer den
laufenden Story-Run ab. Die ``signature`` jedes Kommandos ist die
normative Control-Plane-**Service-API** (FK-91 §91.1a Endpunkt +
``PhaseMutationRequest``-Payload/``op_id``-Idempotenz), der Schema-Owner
der Aufruf-Parameter (project_key, story_id, phase, session_id,
principal_type, worktree_roots, op_id, detail.resume_trigger). Die
CLI-Verben (FK-91 §91.1, z. B. ``agentkit run-phase`` / ``agentkit
resume``) sind menschliche Operator-Recovery-Pfade, die diese Service-API
seit AG3-130 ausschliesslich als duenne REST-Anforderer treiben (kein
in-process Runtime-Build).

`split-story` und `reset-story` gehoeren bewusst nicht in diesen
Kontext, weil sie administrative Services ausserhalb des normalen
Run-Kontrollflusses sind.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-workflow.commands
schema_version: 2
kind: command-set
context: story-workflow
commands:
  - id: story-workflow.command.run-phase
    signature: POST /v1/projects/{project_key}/story-runs/{run_id}/phases/<phase>/start (PhaseMutationRequest {project_key, story_id, session_id, principal_type, worktree_roots, op_id})
    allowed_statuses:
      - story-workflow.status.in_progress
      - story-workflow.status.failed
    restrictions:
      - target phase must be legal under the phase transition rules
      - failed is only legal as part of an official remediation re-entry that returns the workflow status to in_progress before phase work continues
      - setup is the only legal entry phase for a fresh run
      - a fresh-run setup entry is rejected fail-closed unless StoryStatus is Approved and ExecutionPlanning reports READY with scheduling admission (story-workflow.invariant.phase_start_requires_release_and_readiness)
      - op_id is the client-supplied idempotency key (an in-flight operation claim — instance-bound, object-serialized — serializes concurrent same-op_id dispatches; mutations additionally serialize per declared serialization object, default (project_key, story_id); a replay returns the stored result without re-dispatching)
      - the operator CLI run-phase is a thin REST requester and drives the core dispatch exclusively over the control-plane API (never an in-process runtime build)
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
    signature: POST /v1/projects/{project_key}/story-runs/{run_id}/phases/<phase>/resume (PhaseMutationRequest {project_key, story_id, session_id, principal_type, worktree_roots, op_id, detail.resume_trigger})
    allowed_statuses:
      - story-workflow.status.paused
    restrictions:
      - resumes the same run_id
      - resumes the same current_phase
      - the resume trigger travels in PhaseMutationRequest.detail.resume_trigger and must be valid for the current yield point
      - op_id is the idempotency key reserved by the SAME in-flight operation claim (instance-bound, object-serialized) as run-phase BEFORE the engine resume runs (no double resume); a replay returns the stored result
      - a resume that does not advance or re-pause the phase (absent context, not paused, invalid trigger, failed or escalated) is a fail-closed rejection that stores no operation and materializes no binding/lock side effects
      - the operator CLI resume is a thin REST requester and drives the core resume path exclusively over the control-plane API (never an in-process runtime build)
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
