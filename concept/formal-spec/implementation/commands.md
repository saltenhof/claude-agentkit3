---
id: formal.implementation.commands
title: Implementation Commands
status: active
doc_kind: spec
context: implementation
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/45_phase_runner_cli.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Implementation Commands

Implementation laeuft ueber den offiziellen Phase-Runner-Service.
Normative Aufruf-Parameter (story_id, phase, mode) sind in FK-91 §91.1a definiert.
Die Operator-Recovery-CLI `agentkit run-phase implementation --story <story_id>`
ist ein Spezialfall (FK-91 §91.1, FK-45 §45.4).

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.implementation.commands
schema_version: 1
kind: command-set
context: implementation
commands:
  - id: implementation.command.run-phase
    signature: POST /v1/story-runs/{run_id}/phases/implementation/start {story_id, mode}
    allowed_statuses:
      - implementation.status.requested
    requires:
      - implementation.invariant.start_requires_setup_or_exploration_gate
    emits:
      - implementation.event.worker.spawned
      - implementation.event.worker.blocked
      - implementation.event.handover.written
      - implementation.event.implementation.completed
      - implementation.event.implementation.escalated
```
<!-- FORMAL-SPEC:END -->
