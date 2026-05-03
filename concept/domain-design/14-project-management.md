---
concept_id: DK-14
title: Project-Management
module: project-management
domain: project-management
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: project-entity
  - scope: project-lifecycle
  - scope: project-id-prefix
defers_to:
  - target: DK-10
    scope: story-lifecycle
    reason: Story-Identitaet und Story-Counter liegen bei story-lifecycle, nicht hier
supersedes: []
superseded_by:
tags: [project, multi-tenant, configuration, lifecycle]
formal_scope: prose-only
---

# 14 — Project-Management

## 1. Zweck

AK3 ist von Anfang an **multi-projektfaehig**: dieselbe AK3-Instanz
betreibt mehrere fachlich getrennte Projekte (z. B. `claude-agentkit3`,
`brainbox-2`, `odin`). Project-Management ist der fachliche Owner
dieses Konzeptes — es haelt Identitaet, Konfiguration und Lebenszyklus
eines Projekts in einem eigenen Bounded Context.

Der Kernauftrag von AK3 (siehe `00-uebersicht.md`) bezieht sich auf die
Skalierung agentischer Software-Entwicklung. Multi-Projektfaehigkeit
ist Teil dieser Skalierung: ein Stratege betreibt mehrere Vorhaben
parallel, ohne dass deren Zustaende sich vermischen.

## 2. Project als Domaenen-Entitaet

Ein Projekt traegt:

- einen eindeutigen internen **`key`** (`claude-agentkit3`, `brainbox-2`, …)
- einen menschenlesbaren **`name`** (Anzeige)
- ein projekt-spezifisches **Story-ID-Praefix** (`AK3`, `BB2`, `ODIN`),
  das in jeder Story-Anzeige-ID auftaucht
- eine **Konfiguration** mit Repo-URL, Default-Branch, ARE-URL,
  externen Tools, Default-Worker-Anzahl und weiteren projekt-bezogenen
  Stellschrauben

Project-Management ist **Quelle des Projekt-Kontextes** fuer alle
anderen BCs. Der Cross-Cutting-Filter `project_key` durchzieht
Telemetrie, Story-Daten, Verify-Ergebnisse, KPI-Aggregationen — der
Filter selbst lebt als Routing-Disziplin im control_plane_http, das
**Konzept** Projekt aber lebt hier.

## 3. Was hier nicht entschieden wird

- **Story-Counter pro Projekt** liegt bei `story_context_manager`
  (DK-10). Project-Management liefert nur das Praefix-Schema; die
  laufende Nummer-Sequenz ist Story-Lifecycle-Zustand.
- **Cross-Cutting-Filter** (jeder Endpoint filtert nach `project_key`)
  ist Routing-Disziplin im control_plane_http, keine fachliche Aussage
  von Project-Management.
- **Berechtigung pro Projekt** (Multi-User-Szenarien) ist heute kein
  Thema — AK3 wird aktuell von einem Stratege betrieben. Falls
  Mehrnutzer-Szenarien hinzukommen, gehoert die fachliche Logik
  hierher.

## 4. Lebenszyklus

Ein Projekt durchlaeuft:

1. **Anlegen** — Project-Entitaet wird erzeugt; Praefix, Repo-URL,
   ARE-URL und initiale Konfiguration werden gesetzt.
2. **Konfigurieren** — laufende Pflege der Konfigurations-Felder
   (z. B. neuer Default-Branch, geaenderte ARE-URL).
3. **Aktiv** — das Projekt ist Quelle aktiver Story-Arbeit.
4. **Archivieren** (optional spaeter) — das Projekt wird von der
   aktiven Liste genommen, Daten bleiben lesbar.

Konkrete Lifecycle-Uebergaenge und Validierungen werden in **FK-73**
spezifiziert.

## 5. Beziehung zu anderen BCs

- **`story_context_manager`** liest `Project.story_id_prefix` bei der
  Story-Anlage und allokiert die naechste Nummer in seinem eigenen
  Counter-Zustand.
- **alle BCs** filtern Lese- und Schreibwege nach `project_key`. Die
  Filterung ist Cross-Cutting (control_plane_http-Middleware), das
  Konzept Projekt liegt hier.
- **Frontend** zeigt den **Topbar-Projekt-Selector** als
  Slot-Komponente von `project_management` in der App-Shell.

## 6. Abgrenzung

Project-Management ist nicht:

- **Tenant-Management** — heute gibt es keine Tenant-Ebene oberhalb
  des Projekts. Wenn das in Zukunft kommt, wird sie als eigener BC
  modelliert, nicht hier hineingedrueckt.
- **Repo-Verwaltung** — die Repo-URL ist Konfigurationsfeld, das
  Repository selbst ist externes System (Git/GitHub), nicht
  AK3-Domain.
- **Bootstrap der AK3-Installation** — das ist `installer` (DK-08).
  Project-Management setzt erst auf, wenn AK3 bereits installiert
  ist.

## 7. Technisches Konzept

Datenmodell, Lifecycle-Uebergaenge, API-Endpunkte und Storage liegen
in **FK-73** (Project-Management technisches Konzept).
