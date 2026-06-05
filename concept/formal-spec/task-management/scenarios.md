---
id: formal.task-management.scenarios
title: Task-Management Scenarios
status: active
doc_kind: spec
context: task-management
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/77_task_management.md
---

# Task-Management Scenarios

Deklarierte Traces fuer die regulaeren Abschluesse eines Tasks:
Erledigung (done) und Verwerfung (dismissed). Beide schliessen explizit
durch Mensch oder Agent.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.task-management.scenarios
schema_version: 1
kind: scenario-set
context: task-management
scenarios:
  - id: task-management.scenario.task_resolved
    start:
      status: task-management.state.open
    trace:
      - command: task-management.command.resolve_task
    expected_end:
      status: task-management.state.done
    requires:
      - task-management.invariant.always_actionable
      - task-management.invariant.resolution_requires_actor
  - id: task-management.scenario.task_dismissed
    start:
      status: task-management.state.open
    trace:
      - command: task-management.command.dismiss_task
    expected_end:
      status: task-management.state.dismissed
    requires:
      - task-management.invariant.resolution_requires_actor
```
<!-- FORMAL-SPEC:END -->
