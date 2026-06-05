---
id: formal.task-management.events
title: Task-Management Events
status: active
doc_kind: spec
context: task-management
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/77_task_management.md
---

# Task-Management Events

Events des Kontexts. `task_created` kann von mehreren Producern stammen;
die uebrigen werden von task-management selbst emittiert.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.task-management.events
schema_version: 1
kind: event-set
context: task-management

events:
  - id: task-management.event.task_created
    producer: closure | verify | governance | human
    payload:
      - task_id
      - type
      - kind
      - origin
    role: Ein neuer offener Task existiert.

  - id: task-management.event.task_linked
    producer: task-management
    payload:
      - task_id
      - target_kind
      - target_id
      - kind
    role: Ein Task wurde mit einem Task oder einer Story verknuepft.

  - id: task-management.event.task_unlinked
    producer: task-management
    payload:
      - task_id
      - target_kind
      - target_id
      - kind
    role: Eine TaskLink-Kante wurde entfernt.

  - id: task-management.event.task_resolved
    producer: task-management
    payload:
      - task_id
      - resolved_by
    role: Ein Task wurde als erledigt geschlossen.

  - id: task-management.event.task_dismissed
    producer: task-management
    payload:
      - task_id
      - resolved_by
    role: Ein Task wurde verworfen.
```
<!-- FORMAL-SPEC:END -->
