---
id: formal.implementation.state-machine
title: Implementation State Machine
status: active
doc_kind: spec
context: implementation
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/20_workflow_engine_state_machine.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Implementation State Machine

Implementation ist der Herstellungsprozess bis zum verify-faehigen
Handover oder zur Eskalation.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.implementation.state-machine
schema_version: 1
kind: state-machine
context: implementation
states:
  - id: implementation.status.requested
    initial: true
  - id: implementation.status.worker_spawned
  - id: implementation.status.worker_running
  - id: implementation.status.handover_ready
  - id: implementation.status.completed
    terminal: true
  - id: implementation.status.escalated
    terminal: true
transitions:
  - id: implementation.transition.requested_to_worker_spawned
    from: implementation.status.requested
    to: implementation.status.worker_spawned
    guard: implementation.invariant.start_requires_setup_or_exploration_gate
  - id: implementation.transition.worker_spawned_to_worker_running
    from: implementation.status.worker_spawned
    to: implementation.status.worker_running
  - id: implementation.transition.worker_running_to_handover_ready
    from: implementation.status.worker_running
    to: implementation.status.handover_ready
    guard: implementation.invariant.completed_requires_manifest_and_handover
  - id: implementation.transition.handover_ready_to_completed
    from: implementation.status.handover_ready
    to: implementation.status.completed
  - id: implementation.transition.worker_running_to_escalated
    from: implementation.status.worker_running
    to: implementation.status.escalated
    guard: implementation.invariant.worker_blocked_escalates
compound_rules:
  - id: implementation.rule.verify-failure-may-reenter-implementation
    description: A failed verify may re-enter implementation through the same official run-phase implementation path with a new remediation worker spawn.
```
<!-- FORMAL-SPEC:END -->
