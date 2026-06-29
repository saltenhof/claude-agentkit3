---
concept_id: FK-77
title: Task-Management — Datenmodell, Lifecycle und Verlinkung
module: task-management
domain: task-management
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: task-data-model
  - scope: task-lifecycle-transitions
  - scope: task-linking-model
defers_to:
  - target: DK-15
    scope: task-domain
    reason: Fachliches Domaenenmodell und Sprache liegen in DK-15
  - target: FK-68
    scope: telemetry-storage
    reason: Persistenz und Projektionen laufen ueber telemetry-and-events als Speicher-Substrat
  - target: FK-29
    scope: closure-producer
    reason: Closure ist erster Producer von Tasks; die konkrete Einspeise-Verdrahtung ist in FK-29 verankert
supersedes: []
superseded_by:
formal_refs:
  - formal.task-management.entities
  - formal.task-management.state-machine
  - formal.task-management.commands
  - formal.task-management.events
  - formal.task-management.invariants
  - formal.task-management.scenarios
prose_anchor_policy: strict
tags: [task, todo, reminder, lifecycle, linking, action-item]
---

# 77 — Task-Management — Datenmodell, Lifecycle und Verlinkung

<!-- PROSE-FORMAL: formal.task-management.entities, formal.task-management.state-machine, formal.task-management.commands, formal.task-management.events, formal.task-management.invariants, formal.task-management.scenarios -->

Dieses Dokument konkretisiert DK-15 technisch. Die maschinenpruefbare
Semantik liegt in `formal.task-management.*`; diese Prosa erklaert und
grenzt ab.

## 77.1 Datenmodell

Entitaet `Task` (`formal.task-management.entities`):

- `task_id` — Primaerschluessel, Format `TM-YYYY-NNNN`, eindeutig pro `project_key`
- `project_key` — tenant-scoped
- `kind` — `reminder | actionable`
- `type` — fachliche Herkunftskategorie, erweiterbar; v1: `concept_update`
- `title`, `body` — Prosa (was / warum / wo)
- `priority` — `low | normal | high`
- `status` — `open | done | dismissed`
- `origin` — `closure | verify | governance | human`
- `source_story_id` (optional), `execution_report_ref` (optional) —
  Provenienz, getrennt von den n:m-Verknuepfungen
- `created_at`, `resolved_at` (optional), `resolved_by` (optional:
  `human | agent`)

Entitaet `TaskLink`: `task_id`, `target_kind` (`task | story`),
`target_id`, `kind` (typisierte Beziehung: `relates_to | spawned_story |
duplicate_of`). n:m, von beiden Seiten lesbar, reine Referenz ohne
Statusspiegelung.

## 77.2 Lifecycle-Uebergaenge

`formal.task-management.state-machine`:

```
[ - ]        -- create  -->  [open]
[open]       -- resolve -->  [done]
[open]       -- dismiss -->  [dismissed]
[done]       -- terminal (kein Reopen in v1)
[dismissed]  -- terminal (kein Reopen in v1)
```

Geschlossen wird **explizit** durch Mensch oder Agent; `resolved_by` ist
dann gesetzt.

## 77.3 Verlinkungsmodell

Die `TaskLink`-Kante verbindet einen Task mit einem anderen Task oder
einer Story. Aufloesung ist bidirektional: die Story-Detailsicht listet
verlinkte Tasks, der Task listet verlinkte Stories und Tasks. Ueber die
Kante wird **kein** Status gespiegelt.

Die Kante traegt eine typisierte Beziehung `kind` (`relates_to`,
`spawned_story`, `duplicate_of`) — analog `StoryDependency.kind` (FK-02
§2.11.3). `spawned_story` markiert die aus dem Task erzeugte Story; damit
ist „Task hat Story X erzeugt" von „verwandt" unterscheidbar.

## 77.4 Producer und Orchestrator-Sichtbarkeit

Producer erzeugen Tasks ueber die Top-Surface. Der Orchestrator erhaelt
ausschliesslich ein Flag („offene Tasks vorhanden"), nie Inhalte —
Control-Plane-Disziplin analog zum Orchestrator-Guard (DK-03).

## 77.5 Speicher und relationale Abbildung

Kanonische Wahrheit sind Postgres-Tabellen im zentralen State-Backend.
Schema-Owner ist `task_management`; geschrieben wird ueber
`Telemetry.write_projection`, gelesen ueber `Telemetry.read_projection`
(`fc_*`-Muster, FK-41). Kein eigenes Datei-Format, keine zweite Wahrheit.

| Entitaet | Tabelle | Rolle | Key | Mutabilitaet |
|----------|---------|-------|-----|--------------|
| `Task` | `tm_tasks` | kanonisch | `(project_key, task_id)` | update (Status/Resolution) |
| `TaskLink` | `tm_task_links` | kanonisch | `(project_key, task_id, target_kind, target_id, kind)` | append + delete |

- `project_key` ist auf beiden Tabellen Pflichtfeld (FK-18 §18.2).
- `tm_task_links.task_id` referenziert `tm_tasks` per `(project_key, task_id)`.
  Bei `target_kind=story` zeigt `target_id` auf die Story-Anzeige-ID, bei
  `target_kind=task` auf eine `task_id` derselben Projekt-Partition.
- Provenienz (`source_story_id`, `execution_report_ref`) sind Spalten auf
  `tm_tasks`, **getrennt** von den `TaskLink`-Kanten.
- `tm_task_links` traegt keinen Status; der Task-Status lebt allein auf
  `tm_tasks`.

## 77.6 Abgrenzung (technisch)

Siehe DK-15 §5. Technisch massgeblich: ein Task wird **nie** an die
`PipelineEngine` uebergeben; es existiert **kein** Phase-Handler fuer
Tasks. Damit ist die Kern-Invariante „nicht AK3-gemanagt" strukturell
erzwungen, nicht nur konventionell.

## 77.7 Aufruf-Surface (Task-API)

Task-Management exponiert eine Top-Surface, ueber die Producer — **Agents**,
Menschen und andere BCs — Tasks anlegen, verlinken, schliessen **und lesen**:

- Schreibend: `create_task`, `link_task`, `unlink_task`, `resolve_task`,
  `dismiss_task` (vgl. `formal.task-management.commands`).
- Lesend: `get_task(project_key, task_id)`, `list_tasks(project_key,
  filter: status | type | kind | origin)`,
  `list_tasks_for_target(project_key, target_kind, target_id)` fuer die
  Rueckschau von der Story-Detailseite, sowie
  `list_task_links(project_key)`: liefert alle `TaskLink`-Kanten
  einer Projekt-Partition, damit eine Task-Listensicht die *eigenen*
  (ausgehenden) Links pro Task in EINEM Read aus der Backend-Wahrheit
  hydrieren kann (kein Session-Schattenstate). Diese Read exponiert nur das
  bereits modellierte `TaskLink` (FK-77 §77.3) und spiegelt keinen Status.

Erster konkreter Konsument ist der **Agent**, der ueber die Schnittstelle
Tasks anlegt und wieder ausliest; daneben der Mensch (Frontend/CLI). Die
Surface ist transport-agnostisch — das konkrete Binding (HTTP, MCP, CLI)
ist Boundary-Control des aufrufenden BC, nicht von task-management. Der
Orchestrator bleibt ausgenommen (nur Flag, §77.4).

**Abgrenzung API vs. Events:** Die API ist Request/Response. Die
Task-Lifecycle-Events (`formal.task-management.events`) dienen separaten
Konsumenten (Telemetrie/KPI, Frontend-Live-Updates, Audit-Trail) und
werden erst dann als publizierte EventTypeId-/Wire-Surface (FK-91,
frontend-contracts) katalogisiert, wenn ein konkreter Konsument
modelliert ist — ein Event rechtfertigt sich ueber seinen Konsumenten,
nicht seinen Emittenten.

## 77.8 Producer- und Sicht-Verankerung in anderen Konzepten

Die Verdrahtung der Task-Producer und der Frontend-Sicht ist in den
jeweils zustaendigen Konzepten verankert:

- Producer sind die Rueckkopplungstreue Ebene 4 (**FK-38**) und Closure /
  `PostMergeFinalization` (**FK-29**): deren Ergebnis fliesst in einen
  Task statt in den Failure Corpus (FK-41).
- Die Frontend-Sicht „Tasks / Offene Punkte" ist in **FK-72** und
  `frontend-contracts` verortet.
