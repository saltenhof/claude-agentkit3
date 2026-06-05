---
id: formal.task-management.state-machine
title: Task-Management State Machine
status: active
doc_kind: spec
context: task-management
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/77_task_management.md
---

# Task-Management State Machine

Ein Task ist `open`, bis er explizit erledigt (`done`) oder verworfen
(`dismissed`) wird. Beide Endzustaende sind terminal; v1 kennt kein
Reopen.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.task-management.state-machine
schema_version: 1
kind: state-machine
context: task-management

states:
  - id: task-management.state.open
    initial: true
  - id: task-management.state.done
    terminal: true
  - id: task-management.state.dismissed
    terminal: true

transitions:
  - id: task-management.transition.resolve
    from: task-management.state.open
    to: task-management.state.done
    guard: task-management.invariant.resolution_requires_actor
  - id: task-management.transition.dismiss
    from: task-management.state.open
    to: task-management.state.dismissed
    guard: task-management.invariant.resolution_requires_actor

compound_rules:
  - id: task-management.rule.terminal-no-reopen
    description: >
      done und dismissed sind terminal. v1 hat keine Reopen-Transition.
```
<!-- FORMAL-SPEC:END -->
