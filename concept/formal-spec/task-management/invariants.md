---
id: formal.task-management.invariants
title: Task-Management Invariants
status: active
doc_kind: spec
context: task-management
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/77_task_management.md
---

# Task-Management Invariants

Die normativen Regeln des Kontexts. Tragend sind `not_ak3_managed` und
`always_actionable` — sie definieren, was ein Task ist und was nicht.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.task-management.invariants
schema_version: 1
kind: invariant-set
context: task-management

invariants:
  - id: task-management.invariant.not_ak3_managed
    scope: task
    rule: >
      Ein Task wird nie an die Pipeline-Engine uebergeben und durchlaeuft
      nie die Story-Zustands-Pipeline (keine Phase, kein Worktree, kein
      Guard, kein QA-Subflow, kein Merge). Es existiert kein
      Phase-Handler fuer Tasks.

  - id: task-management.invariant.always_actionable
    scope: task
    rule: >
      Jeder Task repraesentiert offene Arbeit ("kuemmere dich darum") und
      ist nie eine passive Benachrichtigung, Info- oder System-Meldung.

  - id: task-management.invariant.resolution_requires_actor
    scope: task
    rule: >
      Ein Task in done oder dismissed hat resolved_by gesetzt
      (human oder agent).

  - id: task-management.invariant.terminal_no_reopen
    scope: task
    rule: >
      done und dismissed sind terminal; aus ihnen fuehrt in v1 keine
      Status-Transition heraus (kein Reopen). Nicht-Status-Mutationen wie
      das Setzen/Loesen von TaskLinks bleiben zulaessig.

  - id: task-management.invariant.link_target_valid
    scope: task_link
    rule: >
      Jeder TaskLink hat target_kind in {task, story} und ein target_id,
      das auf eine existierende Entitaet aufloest. Bei target_kind=task
      liegt das Ziel im selben project_key wie der Quell-Task.

  - id: task-management.invariant.no_status_mirroring
    scope: task_link
    rule: >
      Der Status eines Tasks wird nie aus verlinkten Tasks oder Stories
      abgeleitet oder in diese gespiegelt. Cross-Entity-Bezug ist
      ausschliesslich die TaskLink-Kante.
```
<!-- FORMAL-SPEC:END -->
