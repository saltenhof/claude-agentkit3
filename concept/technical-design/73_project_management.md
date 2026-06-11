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

## 73.6 Owner des erwarteten SonarQube-Config-Baseline-Hash

Der **erwartete SonarQube-Config-Baseline-Hash** eines Projekts (World 1 des
Zwei-Welten-Modells: das feste Regelwerk — Quality Gate, Quality Profile,
Tool-Versionen, **Projekt-Default-Analyse-Scope** und New-Code-Definition,
verdichtet zum Config-Hash gemaess FK-03) ist ein **projekt-gebundener
Erwartungswert** und gehoert zu den `configuration`-Feldern der Project-Entitaet
(§73.1). Project-Management ist dessen **dauerhafter Owner**:

- **Halten/Pflegen:** Der Erwartungswert wird pro Projekt im
  `project_registry`/`projects`-Storage (§73.4) gefuehrt und ist die autoritative
  Vergleichsbasis fuer das Integrity-Gate Dimension 9 (FK-35 §35.2.4a, Pruefpunkt
  „World-1-Baseline-Gleichheit") und das SonarQube-Green-Gate (FK-33 §33.6.3/
  §33.6.4).
- **Operator-Re-Baseline:** Eine bewusste Aenderung am Regelwerk (Quality Gate,
  Profil, Default-Scope oder New-Code-Definition) ist ein **Policy-Change**. Der
  neue Baseline-Hash wird erst **nach erfolgreichem main-Rescan-Gruen** als neuer
  Erwartungswert uebernommen (operator-getriggerte Re-Baseline). So setzt keine
  Story auf einem nach altem Regelwerk gruenen, nach neuem Regelwerk aber
  ungemessenen `main` auf.
- **Abgrenzung:** Die **Gate-Semantik** und der **Reconciler/Ledger** liegen bei
  FK-33; die **initiale Erfassung** des Baseline-Hash beim Setup ist
  Installer-Input (FK-50 CP 7/CP 10d). FK-73 ownt ausschliesslich den
  **dauerhaften Erwartungswert** und die Re-Baseline-Aktion.

> **Code-Realitaet / Owner pro Wert (FEHLT heute):** Das `configuration`-Objekt
> der Project-Entitaet traegt heute **kein** Baseline-Hash-Feld:
> `ProjectConfiguration` (`src/agentkit/project_management/entities.py:14`)
> kennt nur `repo_url` (`:34`), `default_branch` (`:35`), `are_url`,
> `default_worker_count` und `repositories` — keinen erwarteten
> Config-Baseline-Hash. Das Integrity-Gate bestaetigt das Fehlen ausdruecklich
> (`src/agentkit/governance/integrity_gate/dim9_drift.py:26-30`: „no
> captured/registered baseline … the state backend stores no expected
> config-hash … deliberately does NOT fabricate one"). **Code-Owner ist der
> `project-management`-BC** (Project-Entitaet/`ProjectConfiguration`) — **nicht**
> AG3-070: AG3-070 ownt `project.yaml`/`project-config` (config_version,
> sonarqube-Stanza), nicht die Project-Entitaet, und liefert dieses Feld daher
> **nicht**. Es existiert **kein** Backlog-Owner fuer den Feld-Bau: die
> project-management-GAP-Analyse (`stories/project-management-gap-analyse.md`
> §4.1) listet nur `project_detail`/`mode_lock`/`story_counters`/
> `concept_anchors` (A1–A4), das Baseline-Hash-`configuration`-Feld ist **nicht**
> darunter. Der Feld-Bau ist daher als nummerierte PO-Eskalation (CP3) gegen
> `project-management` zu fuehren (Remediation-Report AG3-104); **kein** Feld-Bau
> und **kein** AG3-070-Lieferanspruch in dieser doc-only-Story.

## 73.7 Abgrenzung zu Bootstrap

Bootstrap (FK-50/FK-51) installiert AK3 auf einem System. Nach
Bootstrap ist die Maschine lauffaehig, hat aber noch kein Projekt.
Das erste Project wird ueber Project-Management angelegt — nicht im
Installer.
