---
id: formal.task-management.entities
title: Task-Management Entities
status: active
doc_kind: spec
context: task-management
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/77_task_management.md
---

# Task-Management Entities

Die Entitaeten des Bounded Context `task-management`. `Task` traegt
Identitaet und Lifecycle; `TaskLink` ist die n:m-Verknuepfung zu Stories
und anderen Tasks.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.task-management.entities
schema_version: 1
kind: entity-set
context: task-management

entities:
  - id: task-management.entity.task
    identity: [project_key, task_id]
    description: >
      Offener Handlungspunkt, dessen Abarbeitung nicht von AK3 gemanagt
      wird. Entweder Merker (kind=reminder) oder konkrete leichtgewichtige
      Aufgabe (kind=actionable). Niemals eine passive Benachrichtigung.
    attributes:
      - name: task_id
        kind: string
        required: true
      - name: project_key
        kind: string
        required: true
      - name: kind
        kind: enum
        required: true
        values: [reminder, actionable]
      - name: type
        kind: string
        required: true
        notes:
          - Fachliche Herkunftskategorie, erweiterbar. v1-Wert. concept_update.
      - name: title
        kind: string
        required: true
      - name: body
        kind: string
        required: true
      - name: priority
        kind: enum
        required: true
        values: [low, normal, high]
      - name: status
        kind: enum
        required: true
        values: [open, done, dismissed]
      - name: origin
        kind: enum
        required: true
        values: [closure, verify, governance, human]
      - name: source_story_id
        kind: string
        required: false
        notes:
          - Provenienz. Getrennt von den n:m-Verknuepfungen (task_link).
      - name: execution_report_ref
        kind: string
        required: false
      - name: created_at
        kind: timestamp
        required: true
      - name: resolved_at
        kind: timestamp
        required: false
      - name: resolved_by
        kind: enum
        required: false
        values: [human, agent]
    lifecycle_ref: formal.task-management.state-machine

  - id: task-management.entity.task_link
    identity: [project_key, task_id, target_kind, target_id, kind]
    description: >
      Typisierte, von beiden Seiten lesbare Verknuepfung eines Tasks mit
      einem anderen Task oder einer Story. n:m. Reine Referenz, kein
      gespiegelter Status.
    attributes:
      - name: project_key
        kind: string
        required: true
      - name: task_id
        kind: string
        required: true
      - name: target_kind
        kind: enum
        required: true
        values: [task, story]
      - name: target_id
        kind: string
        required: true
      - name: kind
        kind: enum
        required: true
        values: [relates_to, spawned_story, duplicate_of]
```
<!-- FORMAL-SPEC:END -->
