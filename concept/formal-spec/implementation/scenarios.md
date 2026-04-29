---
id: formal.implementation.scenarios
title: Implementation Scenarios
status: active
doc_kind: spec
context: implementation
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/45_phase_runner_cli.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Implementation Scenarios

Diese Traces pruefen den normalen Implementation-Pfad und seine
offizielle Remediation-Re-Entry-Semantik.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.implementation.scenarios
schema_version: 1
kind: scenario-set
context: implementation
scenarios:
  - id: implementation.scenario.happy-path
    start:
      status: implementation.status.requested
    trace:
      - command: implementation.command.run-phase
    expected_end:
      status: implementation.status.completed
    requires:
      - implementation.invariant.start_requires_setup_or_exploration_gate
      - implementation.invariant.completed_requires_manifest_and_handover
  - id: implementation.scenario.worker-blocked
    start:
      status: implementation.status.requested
    trace:
      - command: implementation.command.run-phase
    expected_end:
      status: implementation.status.escalated
    requires:
      - implementation.invariant.worker_blocked_escalates
  - id: implementation.scenario.verify-remediation-reentry
    start:
      status: implementation.status.requested
    trace:
      - command: implementation.command.run-phase
    expected_end:
      status: implementation.status.completed
    requires:
      - implementation.invariant.start_requires_setup_or_exploration_gate
```
<!-- FORMAL-SPEC:END -->
