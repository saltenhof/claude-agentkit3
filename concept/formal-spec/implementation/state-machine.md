---
id: formal.implementation.state-machine
title: Implementation State Machine
status: active
doc_kind: spec
context: implementation
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/45_phase_runner_cli.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Implementation State Machine

Implementation ist der Herstellungsprozess bis zum vollstaendigen
Handover oder zur Eskalation. Der QA-Subflow gegen die Capability
`verify-system` (4-Schichten-QA inkl. Subflow-internem Remediation-Loop)
laeuft innerhalb der Implementation-Phase und ist Voraussetzung fuer den
Uebergang in die Implementation-Endzustaende `handover_ready` und
`completed`. Ein gescheiterter QA-Subflow loest keinen Phasenwechsel
aus, sondern eine Subflow-interne Remediation-Iteration in derselben
Phase.

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
  - id: implementation.rule.qa-subflow-failure-loops-internally
    description: A failed QA-subflow run against the verify-system capability triggers a subflow-internal remediation iteration within the same implementation phase (qa_feedback_rounds++); it never causes a phase transition or a re-entry into a separate verify phase.
```
<!-- FORMAL-SPEC:END -->
