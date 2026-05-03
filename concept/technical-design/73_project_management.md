---
concept_id: FK-73
title: Project-Management — Datenmodell, Lifecycle und API
module: project-management
domain: project-management
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: project-data-model
  - scope: project-lifecycle-transitions
  - scope: project-api
defers_to:
  - target: DK-14
    scope: project-domain
    reason: Fachliches Domaenenmodell und Sprache liegen in DK-14
  - target: FK-02
    scope: data-model-anchors
    reason: Project-Entitaet ist als Datenmodell-Anker in FK-02 §2.11.1 normiert
  - target: FK-91
    scope: api-catalog
    reason: API-Vertrag laeuft offiziell ueber FK-91
supersedes: []
superseded_by:
tags: [project, project-key, configuration, lifecycle, api]
formal_scope: prose-only
---

# 73 — Project-Management — Datenmodell, Lifecycle und API

Dieses Dokument konkretisiert DK-14 technisch: Datenmodell,
Lifecycle-Uebergaenge, API-Endpunkte und Storage.

## 73.1 Datenmodell

Die Project-Entitaet ist als Datenmodell-Anker in FK-02 §2.11.1
verankert. Pflichtfelder im Ueberblick:

- `key` — unveraenderlich, Primaerschluessel
- `name` — Anzeige, aenderbar
- `story_id_prefix` — projekt-spezifisches Story-Praefix, **immutable**
  nach Anlage (sonst wuerden bestehende Story-Anzeige-IDs ihre
  Identitaet verlieren)
- `configuration` — strukturiertes Konfigurationsobjekt:
  - `repo_url` (String)
  - `default_branch` (String)
  - `are_url` (String, optional)
  - `default_worker_count` (Integer)
  - weitere projekt-spezifische Felder, dokumentiert pro Konfigurationsbereich

## 73.2 Lifecycle-Uebergaenge

```
[ - ] -- create -->   [active]
[active] -- update -->   [active]
[active] -- archive -->   [archived]
[archived] -- (read-only, kein Re-Aktivieren in v1) -->   [archived]
```

- **create:** legt das Project an. `key` und `story_id_prefix` werden
  einmalig festgelegt und sind danach unveraenderlich.
- **update:** mutiert `name` und Felder in `configuration`. Aenderungen
  am `key` oder `story_id_prefix` sind nicht erlaubt.
- **archive:** entfernt das Projekt aus der aktiven Liste. Daten
  bleiben lesbar fuer Audit, aber keine neuen Stories werden erzeugt.

## 73.3 API-Endpunkte

Offiziell katalogisiert in **FK-91**. Tabellarisch:

| Methode | Pfad | Zweck |
|---|---|---|
| `GET` | `/v1/projects` | Liste aller Projekte (gefiltert auf nicht archiviert, ausser explizit `?include_archived=true`) |
| `GET` | `/v1/projects/{key}` | Detail eines Projekts |
| `POST` | `/v1/projects` | Anlegen |
| `PATCH` | `/v1/projects/{key}` | Konfiguration aktualisieren (nicht `key`, nicht `story_id_prefix`) |
| `POST` | `/v1/projects/{key}/archive` | Archivieren |

Schreibende Endpunkte folgen dem Korrelations-Vertrag aus FK-91
(`op_id`, `correlation_id`).

## 73.4 Storage

Postgres als single source of truth (siehe FK-18 Relational Mapping).
Tabelle `projects` mit:

- Primary Key auf `key`
- Unique Index auf `story_id_prefix`
- JSONB-Spalte fuer `configuration` (Konfigurations-Schema validiert
  in der Anwendungsschicht)
- `archived_at` Timestamp (NULL fuer aktive Projekte)

## 73.5 Beziehung zum Cross-Cutting `project_key`

Der `project_key` durchzieht alle BC-Tabellen (`story_contexts`,
`execution_events`, `story_metrics`, …) als Filter-Spalte. Die
Filterung wird im control_plane_http als Middleware durchgesetzt —
hier in FK-73 nicht beschrieben. FK-73 beschreibt nur, **woher**
`project_key` kommt: aus `Project.key`.

## 73.6 Abgrenzung zu Bootstrap

Bootstrap (FK-50/FK-51) installiert AK3 auf einem System. Nach
Bootstrap ist die Maschine lauffaehig, hat aber noch kein Projekt.
Das erste Project wird ueber Project-Management angelegt — nicht im
Installer.
