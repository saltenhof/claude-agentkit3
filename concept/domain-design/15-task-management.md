---
concept_id: DK-15
title: Task-Management
module: task-management
domain: task-management
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: task-entity
  - scope: task-lifecycle
  - scope: task-linking
defers_to:
  - target: DK-10
    scope: story-lifecycle
    reason: Story-Identitaet und Story-Lebenszyklus liegen bei story-lifecycle; ein Task ist keine Story
  - target: FK-77
    scope: task-technical
    reason: Datenmodell, Lifecycle-Uebergaenge und Verlinkung werden technisch in FK-77 normiert
supersedes: []
superseded_by:
tags: [task, todo, reminder, lifecycle, action-item]
formal_scope: prose-only
---

# 15 — Task-Management

## 1. Zweck

Task-Management ist der fachliche Owner fuer **offene Handlungspunkte
(Tasks)**, deren Abarbeitung **ausserhalb** der von AK3 gemanagten
Story-Pipeline stattfindet. Es haelt fest, dass etwas zu tun ist, in
welchem Zustand das ist und wann es geschlossen wurde — ein „Jira in
klein". Es ist die einzige Heimat fuer nicht von AK3 gemanagte Arbeit.

## 2. Kern-Invariante

> Ein Task ist offene, von AK3 ungemanagte Arbeit fuer jemanden
> (Mensch oder Agent). Niemals eine passive Benachrichtigung.

Daraus:

- **Abarbeitung wird nicht von AK3 gemanagt** → ein Task durchlaeuft
  **nie** die Zustands-Pipeline (keine Phasen, kein Worktree, keine
  Guards, kein QA-Subflow, kein Merge). *Wer* erledigt — Mensch oder
  Agent — ist irrelevant. Das ist die definierende Linie des BC.
- **Kein Publikationskanal.** Warnings, Infos oder Systemmeldungen
  gehoeren nicht hierher. Traegt ein Befund aufschiebbare **Handlung**,
  erzeugt er einen Task — der Task ist die Handlung, nicht die Meldung.
  Reines „zur Info" bleibt draussen.

## 3. Task als Domaenen-Entitaet

Ein Task traegt:

- eine eindeutige `task_id` und einen `project_key` (tenant-scoped)
- ein `kind`: `reminder` (Merker/Notiz, damit nichts verloren geht) oder
  `actionable` (konkrete, leichtgewichtige Aufgabe). Beide Auspraegungen
  stehen unter derselben Invariante: „da hast du was zu tun".
- ein `type` als fachliche Herkunftskategorie, erweiterbar; erster Wert
  `concept_update`
- `title` und `body` (Prosa: was / warum / wo)
- eine `priority`
- einen `status` (`open` → `done` | `dismissed`)
- Provenienz (`origin`, optional Story-/Report-Bezug)

## 4. Verlinkung (n:m, bidirektional)

Tasks und Stories werden ueber eine generische Link-Kante verbunden, von
beiden Seiten lesbar:

- Task → mehrere Tasks und → mehrere Stories
- Story → mehrere Tasks, navigierbar von der Story-Detailseite („hier ist
  ein offenes Konzept-Issue")

Die Verbindung ist eine **Referenz, kein gespiegelter Status** (Muster wie
`pattern_ref`/`check_ref`, DK-07). Die Kante traegt eine **typisierte
Beziehung** (`relates_to`, `spawned_story`, `duplicate_of`); `spawned_story`
markiert die aus dem Task erzeugte Story.

## 5. Abgrenzung

- **Story (DK-10, story-lifecycle):** wird von der AK3-Pipeline gemanagt
  ausgefuehrt und produziert Code/Doku/Research. Ein Task wird nicht
  gemanagt und produziert selbst nichts. Braucht ein Task echte Arbeit,
  ist sein Ergebnis „→ Story anlegen"; die Story macht die Arbeit, der
  Task verweist darauf.
- **HumanGate (execution-planning):** blockiert Story-Start. Ein Task ist
  standalone und meist nicht-blockierend.
- **Eskalation (governance-and-guards):** unterbricht einen laufenden
  Run. Ein Task ist post-hoc / out-of-band.
- **Incident (failure-corpus):** Defekt-Log zum Lernen. Ein Task ist
  actionable Arbeit, kein protokollierter Fehler.

## 6. Lebenszyklus

Geoeffnet von einem Producer (System) oder einem Menschen; geschlossen
**explizit** durch den, der erledigt oder verwirft (`done` / `dismissed`)
— Mensch oder Agent. Explizit ist der Normalfall, weil ungemanagt.

## 7. Producer

Erste Producer: story-closure (Konzept-Feedback), verify-system /
governance (handlungstragende Befunde), Mensch (manuell). Der
Orchestrator erhaelt nur ein Flag „es gibt offene Tasks", keine Inhalte
(Control-Plane-Disziplin).

## 8. Beziehung zu anderen BCs

- **story-lifecycle:** Tasks verweisen auf Stories und umgekehrt; keine
  geteilten Zustaende.
- **telemetry-and-events:** Speicher-Substrat (Projektionen);
  Task-Management ist Schema-Owner.
- **Frontend:** eigene „Tasks / Offene Punkte"-Sicht (technisch ueber
  FK-72 / frontend-contracts).

## 9. Technisches Konzept

Datenmodell, Lifecycle-Uebergaenge, Verlinkungsmodell und Speicher liegen
in **FK-77**; die maschinenpruefbare Semantik in `formal.task-management.*`.
