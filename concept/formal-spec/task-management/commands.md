---
id: formal.task-management.commands
title: Task-Management Commands
status: active
doc_kind: spec
context: task-management
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/77_task_management.md
---

# Task-Management Commands

Commands ueber die Top-Surface von `task-management`. Erzeugung,
Verlinkung und Schliessung. Abarbeitung selbst ist kein Command dieses
Kontexts — sie geschieht ungemanagt ausserhalb von AK3.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.task-management.commands
schema_version: 1
kind: command-set
context: task-management

commands:
  - id: task-management.command.create_task
    description: Legt einen neuen Task im Zustand open an.
    allowed_from: []
    effect: Erzeugt task-management.entity.task im Zustand open.
    emits:
      - task-management.event.task_created

  - id: task-management.command.link_task
    description: >
      Verknuepft einen Task mit einem anderen Task oder einer Story
      (n:m, bidirektional lesbar). Aendert keinen Status.
    allowed_from:
      - task-management.state.open
      - task-management.state.done
      - task-management.state.dismissed
    effect: Erzeugt task-management.entity.task_link.
    emits:
      - task-management.event.task_linked

  - id: task-management.command.unlink_task
    description: >
      Entfernt eine bestehende TaskLink-Kante. Aendert keinen Status.
    allowed_from:
      - task-management.state.open
      - task-management.state.done
      - task-management.state.dismissed
    effect: Loescht task-management.entity.task_link.
    emits:
      - task-management.event.task_unlinked

  - id: task-management.command.resolve_task
    description: Schliesst einen Task als erledigt.
    allowed_from:
      - task-management.state.open
    effect: Transition task-management.transition.resolve; setzt resolved_by und resolved_at.
    emits:
      - task-management.event.task_resolved

  - id: task-management.command.dismiss_task
    description: Verwirft einen Task ohne Erledigung.
    allowed_from:
      - task-management.state.open
    effect: Transition task-management.transition.dismiss; setzt resolved_by und resolved_at.
    emits:
      - task-management.event.task_dismissed
```
<!-- FORMAL-SPEC:END -->
