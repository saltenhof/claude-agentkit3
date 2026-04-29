---
id: formal.implementation.events
title: Implementation Events
status: active
doc_kind: spec
context: implementation
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/45_phase_runner_cli.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Implementation Events

Diese Events bilden den Implementation-Pfad fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.implementation.events
schema_version: 1
kind: event-set
context: implementation
events:
  - id: implementation.event.worker.spawned
    producer: implementation
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
  - id: implementation.event.worker.blocked
    producer: implementation
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
        - blocker_reason
  - id: implementation.event.handover.written
    producer: implementation
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
  - id: implementation.event.implementation.completed
    producer: implementation
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
  - id: implementation.event.implementation.escalated
    producer: implementation
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
        - escalation_reason
```
<!-- FORMAL-SPEC:END -->
