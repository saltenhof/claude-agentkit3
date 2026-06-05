---
title: Task-Management Formal Spec
status: active
doc_kind: context
context: task-management
---

# Task-Management Formal Spec

## Zweck

Maschinenpruefbare Semantik des Bounded Context `task-management`:
offene Handlungspunkte (Tasks), deren Abarbeitung nicht von AK3 gemanagt
wird, ihre Zustaende und ihre Verlinkung zu Stories und anderen Tasks.

## Enthaltene Dateien

- `entities.md` — `Task` und `TaskLink`
- `state-machine.md` — `open → done | dismissed`
- `commands.md` — create / link / resolve / dismiss
- `events.md` — task_created / task_linked / task_resolved / task_dismissed
- `invariants.md` — u. a. „nicht AK3-gemanagt", „nie Benachrichtigung"
- `scenarios.md` — deklarierte Traces der regulaeren Abschluesse (resolve, dismiss)

## Abgrenzung

Tasks sind keine Stories (story-lifecycle), keine HumanGates
(execution-planning), keine Eskalationen (governance-and-guards) und
keine Incidents (failure-corpus). Details in DK-15 §5.

## Relevante Prosa-Konzepte

- DK-15 (fachliche Definition, Invariante, Abgrenzung)
- FK-77 (Datenmodell, Lifecycle, Verlinkung)
