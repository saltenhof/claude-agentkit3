---
concept_id: FK-18
title: "Relationales Abbildungsmodell fuer PostgreSQL"
module: relational-schema
cross_cutting: true
status: draft
doc_kind: detail
parent_concept_id: FK-17
authority_over:
  - scope: relational-schema
  - scope: postgres-table-families
  - scope: runtime-vs-projection-tabellen
defers_to:
  - FK-10
  - FK-15
  - FK-17
supersedes: []
superseded_by:
tags: [postgres, schema-design, relational, table-families, ownership]
prose_anchor_policy: strict
formal_refs:
  - formal.story-creation.entities
  - formal.dependency-rebinding.entities
  - formal.story-closure.entities
  - formal.story-split.entities
  - formal.story-reset.entities
  - formal.state-storage.entities
  - formal.state-storage.state-machine
  - formal.state-storage.commands
  - formal.state-storage.events
  - formal.state-storage.invariants
  - formal.state-storage.scenarios
---

# 18 — Relationales Abbildungsmodell fuer PostgreSQL

<!-- PROSE-FORMAL: formal.story-creation.entities, formal.dependency-rebinding.entities, formal.story-closure.entities, formal.story-split.entities, formal.story-reset.entities, formal.state-storage.entities, formal.state-storage.state-machine, formal.state-storage.commands, formal.state-storage.events, formal.state-storage.invariants, formal.state-storage.scenarios -->

## 18.1 Zweck

Dieses Dokument bildet das fachliche Datenmodell aus FK-17 auf ein
logisches relationales Modell fuer PostgreSQL ab.

Es definiert:

- logische Table-Families
- kanonische Tabellen
- Projekt-/Mandanten-Schluessel
- Abgrenzung zwischen Wahrheit, Audit und Projektion

Es definiert **noch kein finales SQL**.

## 18.2 Grundregeln

- `project_key` ist auf **jeder** kanonischen Tabelle Pflichtfeld.
- Jede kanonische Tabelle hat genau einen fachlichen Writer.
- Cross-Aggregate-Referenzen erfolgen per ID.
- Variable Payloads werden nicht voll normalisiert, sondern gezielt in
  `jsonb`-Feldern gehalten.
- Projektionen sind rebuildbar und nie operative Hauptwahrheit.

Die formale Gegenkopplung dieses Dokuments liegt in
`formal.state-storage.*`. Dort werden die Table-Families nicht als
SQL-Strukturen, sondern als fachliche Record-Families mit expliziten
Reset-, Scope- und Kanonizitaetsregeln beschrieben.

## 18.3 Logische Table-Families

### 18.3.1 Catalog

**Owner:** `story_context_manager` / `installer`

Enthaelt stabile Projekt-, Story- und Kontextdaten.

**Tabellen:**

- `project_spaces`
- `stories`
- `story_contexts`
- `story_custom_field_definitions`
- `story_custom_field_values`

### 18.3.2 Execution

**Owner:** `pipeline_engine`

Enthaelt die operative Ablaufwahrheit.

**Tabellen:**

- `flow_executions`
- `node_execution_ledgers`
- `attempts`

### 18.3.3 Governance

**Owner:** `guard_system`

Enthaelt explizite Eingriffe und Entscheidungen.

**Tabellen:**

- `override_records`
- `guard_decisions`

### 18.3.4 Artifacts

**Owner:** `artifact_manager`

Enthaelt typisierte Artefakt-Referenzen und Provenienz.

**Tabellen:**

- `artifact_envelopes`

### 18.3.5 Telemetry

**Owner:** `telemetry_service`

Enthaelt append-only Laufzeitbeobachtung und Auditdaten gültiger
Story-Umsetzungen. Diese Daten sind nicht die operative Wahrheit; bei
vollständigem Story-Reset werden die Events der korrupten Umsetzung mit
entfernt.

**Tabellen:**

- `execution_events`

### 18.3.6 Read Models

**Owner:** Projektion/Analytics

Enthaelt nur rebuildbare Lesemodelle.

**Tabellen:**

- `phase_states`
- `phase_snapshots`
- `kpi_projections`

## 18.4 Tabellen pro Entität

| FK-17 Entität | Logische Tabelle | Modelltyp |
|---------------|------------------|-----------|
| `ProjectSpace` | `project_spaces` | kanonisch |
| `Story` | `stories` | kanonisch |
| `StoryContext` | `story_contexts` | kanonisch |
| `StoryCustomFieldDefinition` | `story_custom_field_definitions` | kanonisch |
| `StoryCustomFieldValue` | `story_custom_field_values` | kanonisch |
| `FlowExecution` | `flow_executions` | kanonisch |
| `NodeExecution` | `node_execution_ledgers` | kanonisch |
| `AttemptRecord` | `attempts` | kanonisch append-only |
| `OverrideRecord` | `override_records` | kanonisch append-only |
| `GuardDecision` | `guard_decisions` | kanonisch append-only |
| `ArtifactRecord` | `artifact_envelopes` | kanonisch |
| `ExecutionEvent` | `execution_events` | runtime-nahe Beobachtung und Audit, append-only pro gültiger Umsetzung |
| `PhaseState` | `phase_states` | aktuelle Projektion |
| `PhaseSnapshot` | `phase_snapshots` | abgeschlossene Phasenprojektion |
| `KpiProjection` | `kpi_projections` | Projektion |

## 18.5 Relationale Leitentscheidung pro Tabelle

### 18.5.1 Stark relational halten

- `project_spaces`
- `stories`
- `story_custom_field_definitions`
- `flow_executions`
- `node_execution_ledgers`
- `attempts`
- `override_records`
- `guard_decisions`

**Grund:** Diese Tabellen tragen Identität, Status, Owner-Logik,
Zeitachsen oder harte Filter-/Join-Felder.

### 18.5.2 Relational mit `jsonb`-Anteilen

- `story_contexts`
- `story_custom_field_values`
- `artifact_envelopes`
- `execution_events`

**Grund:** Diese Tabellen enthalten fachlich variable, aber dennoch
kanonische Payloads wie:

- Kontext-/Scope-Strukturen
- flexible Story-Attribut-Werte
- Artefakt-Metadaten
- Event-Details

## 18.6 Minimale Schlüssel- und Referenzstruktur

### 18.6.1 Catalog

- `project_spaces`:
  Root durch `project_key`
- `stories`:
  eindeutig innerhalb von `project_key` über `story_id`
- `story_contexts`:
  genau ein aktiver Runtime-Kontext pro `(project_key, story_id)`
- `story_custom_field_definitions`:
  eindeutig pro `(project_key, field_key)`
- `story_custom_field_values`:
  eindeutig pro `(project_key, story_id, field_key)`

### 18.6.2 Execution

- `flow_executions`:
  Root pro `(project_key, run_id, flow_id)`
- `node_execution_ledgers`:
  referenziert `flow_executions` per `(project_key, run_id, flow_id)`
- `attempts`:
  referenziert `flow_executions` per `(project_key, run_id, flow_id)`

### 18.6.3 Governance / Artifacts / Telemetry

- `override_records`, `guard_decisions`, `artifact_envelopes`,
  `execution_events` referenzieren fachlich mindestens:
  `project_key`, `story_id`, `run_id`
- falls vorhanden zusaetzlich:
  `flow_id`, `node_id`, `attempt_no`

## 18.6a Identität und Unique-Regeln

### 18.6a.1 Catalog

| Tabelle | Fachlicher Identitätskandidat | Unique-Regeln |
|---------|-------------------------------|---------------|
| `project_spaces` | `(project_key)` | `project_key` systemweit eindeutig |
| `stories` | `(project_key, story_number)` fachlich; `story_uuid` technisch | `story_uuid` global eindeutig; `(project_key, story_number)` pro Projekt eindeutig; `story_display_id` **global UNIQUE** (materialisierte Anzeige-ID, keine `story_id`-Spalte); zusätzlich `(project_key, story_display_id)` UNIQUE (trägt die projektgescopten StoryDependency-FKs) |
| `story_contexts` | `(project_key, story_id)` | pro Story genau ein aktiver Kontext (`story_id` trägt hier die Display-ID als Laufzeit-Korrelations-String) |
| `story_custom_field_definitions` | `(project_key, field_key)` | `field_key` pro Projekt eindeutig |
| `story_custom_field_values` | `(project_key, story_id, field_key)` | pro Story höchstens ein aktueller Wert je Feld |

> **Identität `stories` (FK-02 §2.11.2):** Die `stories`-Stammdaten
> tragen **keine** `story_id`-Spalte. Kanonische Identität ist fachlich
> `(project_key, story_number)`, technisch `story_uuid`. `story_display_id`
> (z.B. `AK3-042`) ist die einmal materialisierte Anzeige-Repräsentation aus
> `Project.story_id_prefix + story_number` und global `UNIQUE`. Wo nachfolgende
> Abschnitte FK-Ziele „auf `stories`" beschreiben, ist als Zielspalte
> `story_display_id` (bzw. `(project_key, story_display_id)`) gemeint, nicht eine
> `story_id`-Spalte.

### 18.6a.2 Execution

| Tabelle | Fachlicher Identitätskandidat | Unique-Regeln |
|---------|-------------------------------|---------------|
| `flow_executions` | `(project_key, run_id, flow_id)` | pro Run genau ein Flow je `flow_id` |
| `node_execution_ledgers` | `(project_key, run_id, flow_id, node_id)` | pro Flow genau ein aktueller Node-Ledger je `node_id` |
| `attempts` | `(project_key, run_id, flow_id, phase, attempt_no)` | `attempt_no` innerhalb von `(run_id, flow_id, phase)` eindeutig |

### 18.6a.3 Governance / Artifacts / Telemetry

| Tabelle | Fachlicher Identitätskandidat | Unique-Regeln |
|---------|-------------------------------|---------------|
| `override_records` | `(project_key, run_id, flow_id, override_id)` | `override_id` innerhalb des Flow-Kontexts eindeutig |
| `guard_decisions` | `(project_key, run_id, flow_id, guard_decision_id)` | jede Guard-Entscheidung hat eigene Identität |
| `artifact_envelopes` | `(project_key, run_id, artifact_id)` | `artifact_id` innerhalb eines Runs eindeutig |
| `execution_events` | `(project_key, run_id, event_id)` | `event_id` innerhalb eines Runs eindeutig |

### 18.6a.4 Read Models

| Tabelle | Fachlicher Identitätskandidat | Unique-Regeln |
|---------|-------------------------------|---------------|
| `phase_states` | `(project_key, story_id, run_id)` | genau eine aktuelle Projektion pro Run |
| `phase_snapshots` | `(project_key, story_id, run_id, phase)` | höchstens ein Snapshot je Run und Phase |
| `kpi_projections` | `(project_key, projection_key)` | `projection_key` pro Projekt eindeutig |

## 18.6b Mutierbarkeit und Lebenszyklusregeln

| Tabelle | Mutierbarkeit | Regel |
|---------|---------------|-------|
| `project_spaces` | update-fähig | Versions-/Statuswechsel zulässig |
| `stories` | update-fähig | Story-Stammdaten und Status ändern sich |
| `story_contexts` | replace/update | Snapshot darf erneuert, nicht beliebig historisiert werden |
| `story_custom_field_definitions` | selten update-fähig | Definitionen ändern sich kontrolliert |
| `story_custom_field_values` | update-fähig | aktueller Feldwert wird überschrieben |
| `flow_executions` | update-fähig | laufender Zustand mutiert bis terminal |
| `node_execution_ledgers` | update-fähig | Ledger je Node wird fortgeschrieben |
| `attempts` | append-only | nach dem Schreiben keine fachliche Mutation |
| `override_records` | append-mostly | nur `consumed_at` darf nachträglich gesetzt werden |
| `guard_decisions` | append-only | Entscheidung ist nach Persistenz unveränderlich |
| `artifact_envelopes` | update-fähig | Status/Integrity/Freeze dürfen fortgeschrieben werden |
| `execution_events` | append-only innerhalb eines Runs | Event darf nach Persistenz nicht verändert werden, wird aber bei vollständigem Story-Reset physisch gelöscht |
| `phase_states` | replace/update | vollständig rebuildbar |
| `phase_snapshots` | replace/update | vollständig rebuildbar |
| `kpi_projections` | replace/update | vollständig rebuildbar |

## 18.6c Append-only-Regeln

Die folgenden Tabellen sind fachlich append-only und dürfen nach
Persistenz nicht inhaltlich umgeschrieben werden:

- `attempts`
- `guard_decisions`

Sonderfall:

- `override_records` ist append-only mit fachlicher Konsum-Markierung;
  nur `consumed_at` darf nach der Erzeugung ergänzt werden.
- `execution_events` ist append-only innerhalb einer konkreten
  Story-Umsetzung, aber nicht retentionspflichtig über einen
  vollständigen Story-Reset hinweg.

## 18.6d Fremdschlüsselrichtung

Fremdschlüssel oder äquivalente fachliche Referenzen verlaufen nur in
folgender Richtung:

- `project_spaces` → `stories`
- `stories` → `story_contexts`
- `stories` → `story_custom_field_values`
- `stories` → `flow_executions`
- `flow_executions` → `node_execution_ledgers`
- `flow_executions` → `attempts`
- `flow_executions` → `override_records`
- `flow_executions` → `guard_decisions`
- `flow_executions` → `artifact_envelopes`
- `flow_executions` → `execution_events`

**Regel:** Projektionstabellen zeigen fachlich nach unten auf
kanonische Tabellen, nie umgekehrt.

## 18.6e Pflichtspalten pro Tabelle

### 18.6e.1 Catalog

| Tabelle | Pflichtspalten |
|---------|----------------|
| `project_spaces` | `project_key`, `display_name`, `project_root`, `runtime_profile`, `registration_status`, `skill_bundle_version`, `prompt_bundle_version` |
| `stories` | `project_key`, `story_id`, `title`, `story_type`, `mode`, `status` |
| `story_contexts` | `project_key`, `story_id`, `story_type`, `mode`, `scope`, `repo_bindings`, `created_at`, `last_refreshed_at` |
| `story_custom_field_definitions` | `project_key`, `field_key`, `display_name`, `field_type`, `provider`, `provider_field_ref`, `is_required`, `is_writable_by_agentkit` |
| `story_custom_field_values` | `project_key`, `story_id`, `field_key`, `source`, `provider_sync_status`, `conflict_detected` |

### 18.6e.2 Execution

| Tabelle | Pflichtspalten |
|---------|----------------|
| `flow_executions` | `project_key`, `story_id`, `run_id`, `flow_id`, `flow_level`, `owner_component`, `status`, `attempt_no`, `started_at` |
| `node_execution_ledgers` | `project_key`, `story_id`, `run_id`, `flow_id`, `node_id`, `attempt_no`, `outcome`, `started_at` |
| `attempts` | `project_key`, `story_id`, `run_id`, `flow_id`, `phase`, `attempt_no`, `outcome`, `started_at`, `ended_at` |

### 18.6e.3 Governance

| Tabelle | Pflichtspalten |
|---------|----------------|
| `override_records` | `project_key`, `story_id`, `run_id`, `flow_id`, `override_id`, `override_type`, `actor_type`, `actor_id`, `reason`, `created_at` |
| `guard_decisions` | `project_key`, `story_id`, `run_id`, `flow_id`, `guard_decision_id`, `guard_key`, `outcome`, `decided_at` |

### 18.6e.4 Artifacts

| Tabelle | Pflichtspalten |
|---------|----------------|
| `artifact_envelopes` | `project_key`, `story_id`, `run_id`, `artifact_id`, `artifact_class`, `artifact_kind`, `artifact_format`, `artifact_status`, `produced_in_phase`, `producer_component`, `producer_trust`, `protection_level`, `frozen`, `integrity_verified`, `created_at`, `storage_ref` |

### 18.6e.5 Telemetry

| Tabelle | Pflichtspalten |
|---------|----------------|
| `execution_events` | `project_key`, `story_id`, `run_id`, `event_id`, `event_type`, `occurred_at`, `source_component`, `severity` |

### 18.6e.6 Read Models

| Tabelle | Pflichtspalten |
|---------|----------------|
| `phase_states` | `project_key`, `story_id`, `run_id`, `phase`, `status`, `updated_at` |
| `phase_snapshots` | `project_key`, `story_id`, `run_id`, `phase`, `status`, `completed_at` |
| `kpi_projections` | `project_key`, `projection_key`, `metric_name`, `metric_value`, `computed_at` |

## 18.6f Optionale Spalten nach Fachregel

Die folgenden Spalten sind nur unter bestimmten fachlichen Bedingungen
gesetzt und deshalb logisch optional:

| Tabelle | Optionale Spalten | Bedingung |
|---------|-------------------|-----------|
| `stories` | `labels`, `size` | nur wenn im AK3-Story-Profil genutzt |
| `story_contexts` | `scope_keys`, `concept_refs`, `guardrail_refs`, `external_sources`, `related_story_ids`, `story_semantics` | nur wenn Setup/Exploration diese Daten liefert |
| `story_custom_field_values` | `value`, `value_status`, `last_synced_at`, `last_written_by`, `last_sync_attempt_at` | nur wenn Feld belegt oder Sync stattgefunden hat |
| `flow_executions` | `current_node_id`, `finished_at` | nur im Lauf oder nach terminalem Abschluss |
| `node_execution_ledgers` | `finished_at`, `resume_trigger`, `backtrack_target` | nur bei Abschluss/Yield/Ruecksprung |
| `attempts` | `failure_cause` | nur bei nicht erfolgreichem Outcome |
| `override_records` | `target_node_id`, `consumed_at` | knotenspezifisch bzw. nach Konsum |
| `guard_decisions` | `node_id`, `reason`, `evidence_ref` | falls nodebezogen oder begruendet/evidenzgestuetzt |
| `artifact_envelopes` | `attempt_no`, `qa_cycle_id`, `qa_cycle_round`, `evidence_epoch`, `finished_at` | nur fuer QA-/attemptgebundene Artefakte |
| `execution_events` | `flow_id`, `node_id`, `event_payload_ref` | nur wenn Event fachlich darauf bezogen ist |
| `kpi_projections` | `window_start`, `window_end` | nur bei fensterbezogenen Kennzahlen |

## 18.7 Projektionen

### 18.7.1 `phase_states` und `phase_snapshots`

Lesemodell fuer:

- Resume
- Statusabfragen
- Dashboard-nahe Laufzeitsicht

**Regel:** Kein Single Source of Truth.

### 18.7.2 `kpi_projections`

`kpi_projections` ist als Read-Model fachlich vorgesehen.

Lesemodell fuer:

- Metriken
- Laufzeittrends
- Durchsatz- und Qualitaetskennzahlen

**Regel:** Nur aus kanonischen Tabellen und Events abgeleitet.

## 18.8 Nicht relational ausmodellieren

Die folgenden Dinge werden **nicht** als eigene Tabellenfamilien
ausmodelliert:

- DSL-Definitionen (`FlowDefinition`, `NodeDefinition`, `EdgeRule`)
- stage-registry-Definitionen als Runtime-Tabellen
- jede einzelne Artefaktart als eigene Tabelle
- event-spezifische Payload-Details als stark normalisierte Subtabellen
- phasenspezifische Sondertabellen pro Workflow-Schritt

## 18.9 Physische PostgreSQL-Schemas

Die logischen Table-Families muessen nicht 1:1 auf physische
PostgreSQL-Schemas abgebildet werden.

**Normative Regel:** Die fachliche Ownership aus diesem Dokument ist
wichtiger als die spaetere physische Schemaaufteilung.

Zulaessige physische Varianten:

- ein gemeinsames PostgreSQL-Schema mit sauberem Tabellenprefix
- mehrere PostgreSQL-Schemas entlang der Table-Families

Unzulaessig ist:

- eine physische Zusammenlegung, die den Single-Writer fachlich
  aufweicht oder Projektionen mit kanonischer Wahrheit vermischt

## 18.9a Schema-Versionierung und Side-by-Side-Datenbanken

AK3 fuehrt eine **explizite
Schema-Version** als Code-Konstante. Bei einer Versionsaenderung
wird **automatisch eine neue Datenbank daneben** angelegt — die alte
DB bleibt unangetastet.

### 18.9a.1 Schema-Version als Konstante

Eine Code-Konstante (z. B. `agentkit.backend.state_backend.config.SCHEMA_VERSION`)
haelt die aktuelle Schema-Version im SemVer-Stil — z. B. `"3.0.0"`.
Diese Version wird bei AK3-Builds mitgepflegt; Schema-Aenderungen
fuehren zu einer Versions-Erhoehung.

Implementierungsanker: `agentkit.backend.state_backend.config.SCHEMA_VERSION`
ist die einzige Quelle fuer die Ableitung der physischen
Speicherorte. Postgres verwendet daraus
`agentkit.backend.state_backend.config.versioned_postgres_schema_name()` (z. B.
`ak3_v3_0_0`); SQLite verwendet
`agentkit.backend.state_backend.config.versioned_sqlite_db_file()` (z. B.
`agentkit_3_0_0.sqlite`).

**Innerhalb einer Major-Version (z. B. 3.0.0 → 3.0.1, 3.1.0 etc.)
sind Schema-Aenderungen tabu.** Eine Schema-Aenderung **ist** ein
Versions-Bump.

Vor dem ersten produktiven Release (Pre-1.0-Phase) sind
Schema-Wechsel **destructive resets**: die DB wird neu angelegt,
keine Daten-Uebertragung. Es gibt vor Release noch keine
schuetzenswerten Bestandsdaten.

### 18.9a.2 DB-Bezeichnung mit Versions-Kennung

Die DB-Bezeichnung enthaelt die Schema-Version. Zwei zulaessige
Realisierungs-Wege:

| Treiber | Konvention |
|---|---|
| **Postgres** | Eigenes Schema pro Version: `ak3_v3_0_0`, `ak3_v3_1_0`. Tabellen liegen unter dem versionierten Schema. |
| **SQLite** | Eigene Datei pro Version: `agentkit_3_0_0.sqlite`, `agentkit_3_1_0.sqlite`. |

Welche Realisierung zum Einsatz kommt, ist Driver-Detail. Der A-Kern
kennt die Schema-Version nur als Konstante; die Mapping-Disziplin
liegt im Driver.

### 18.9a.3 Bootstrap-Verhalten

Beim AK3-Start prueft der Driver, ob fuer die aktuelle
`SCHEMA_VERSION` bereits eine DB existiert:

- **Existiert**: AK3 startet auf der vorhandenen DB.
- **Existiert nicht**: AK3 legt **automatisch eine neue, leere DB
  unter der aktuellen Versions-Kennung an** und startet darauf.
- **Aeltere DB unter alter Version vorhanden**: bleibt
  **unangetastet**. Sie ist fuer Forensik, Rollback und optionale
  Daten-Uebertragung erreichbar.

Es gibt **kein Auto-Upgrade-Verhalten** — die alte DB wird nicht
ueberbuegelt, nicht migriert, nicht angetastet.

### 18.9a.4 Optionale Daten-Uebertragung zwischen Versionen

Wenn ein Stratege Daten von einer alten in eine neue Version
uebernehmen will, ist das eine **separate, gezielt gestartete
Aktion** — nicht Auto-Boot-Verhalten. Der Mechanismus dafuer ist
nicht-kriegsentscheidend; ein einfacher Migrations-Befehl wie
`agentkit migrate --from=3.0.0 --to=3.1.0` reicht. Die detaillierte
Mechanik wird erst bei der ersten realen Migrations-Anforderung
spezifiziert; wesentlich sind das Side-by-Side-Verhalten und das
Bootstrap-Auto-Anlage-Verhalten.

Bis zur ersten realen Daten-Uebertragung gilt: **leere neue DB
neben der alten leben lassen.**

### 18.9a.5 Was bewusst NICHT Teil ist

- Kein Migrations-Framework (Alembic etc.).
- Kein automatisches Daten-Upgrade-Verhalten.
- Kein Down-Mechanismus (Rollback geschieht durch Wechsel auf die
  alte Version, die ihre eigene DB hat).
- Keine Schema-Diff-Tools.

Bootstrap-Mechanik fuer die Auto-Anlage ist in **FK-50 (Installer)**
und **FK-51 (Upgrade)** beschrieben.

## 18.10 Erste Zielgröße

Die kleinste sinnvolle relationale Zielstruktur fuer AK3 besteht aus
folgenden **13 kanonischen Tabellen** plus **2 Projektionstabellen**:

- 5 Catalog-Tabellen
- 3 Execution-Tabellen
- 2 Governance-Tabellen
- 1 Artifact-Tabelle
- 1 Telemetry-Tabelle
- 2 Projektionstabellen

Diese Zielgröße ist absichtlich kompakt. Sie vermeidet sowohl ein
Gott-Schema als auch eine zu feine Zerlegung in viele Spezialtabellen.

## 18.11 PostgreSQL-Typabbildung

Diese Abbildung ist jetzt normativ für die relationale Umsetzung.

| Fachlicher Typ | PostgreSQL-Zieltyp | Regel |
|----------------|--------------------|-------|
| `ProjectKey` | `TEXT` | nicht leer |
| `StoryId` | `TEXT` | nicht leer |
| `RunId` | `TEXT` | nicht leer |
| `FlowId` | `TEXT` | nicht leer |
| `NodeId` | `TEXT` | nicht leer |
| `FieldKey` | `TEXT` | nicht leer |
| `ArtifactId` | `TEXT` | nicht leer |
| `Text` | `TEXT` | Unicode-Text |
| `Boolean` | `BOOLEAN` | kein Tristate |
| `Integer` | `INTEGER` | fachliche Mindestwerte über `CHECK` |
| `StringSet` | `JSONB` | Array von Strings ohne Duplikate fachlich durch Writer sicherzustellen |
| `StringList` | `JSONB` | geordnete Stringliste |
| `JsonValue` | `JSONB` | variable Payload |
| `JsonObject` | `JSONB` | strukturiertes Objekt |
| `UriRef` | `TEXT` | URI oder fachliche Referenz |
| `PathRef` | `TEXT` | kanonische Speicherreferenz |
| `Instant` | `TIMESTAMPTZ` | UTC-normalisiert, Mikrosekundenpräzision |
| `Enum<T>` | `TEXT` | zulässige Werte über `CHECK` erzwungen |

**Regel:** Für AK3 werden fachliche Enums nicht als PostgreSQL-Enum-Typen
modelliert, sondern als `TEXT` mit `CHECK`-Constraints. Das hält
Migrationen einfacher und bleibt näher am fachlichen Modell.

## 18.12 Primärschlüssel

### 18.12.1 Catalog

| Tabelle | Primärschlüssel |
|---------|-----------------|
| `project_spaces` | `(project_key)` |
| `stories` | `story_uuid` (technischer PK); fachlich eindeutig `(project_key, story_number)` und `story_display_id` global UNIQUE — keine `story_id`-Spalte |
| `story_contexts` | `(project_key, story_id)` |
| `story_custom_field_definitions` | `(project_key, field_key)` |
| `story_custom_field_values` | `(project_key, story_id, field_key)` |

### 18.12.2 Execution

| Tabelle | Primärschlüssel |
|---------|-----------------|
| `flow_executions` | `(project_key, run_id, flow_id)` |
| `node_execution_ledgers` | `(project_key, run_id, flow_id, node_id)` |
| `attempts` | `(project_key, run_id, flow_id, phase, attempt_no)` |

### 18.12.3 Governance / Artifacts / Telemetry

| Tabelle | Primärschlüssel |
|---------|-----------------|
| `override_records` | `(project_key, run_id, flow_id, override_id)` |
| `guard_decisions` | `(project_key, run_id, flow_id, guard_decision_id)` |
| `artifact_envelopes` | `(project_key, run_id, artifact_id)` |
| `execution_events` | `(project_key, run_id, event_id)` |

### 18.12.4 Read Models

| Tabelle | Primärschlüssel |
|---------|-----------------|
| `phase_states` | `(project_key, story_id, run_id)` |
| `phase_snapshots` | `(project_key, story_id, run_id, phase)` |
| `kpi_projections` | `(project_key, projection_key)` |

## 18.13 Fremdschlüssel

Fremdschlüssel werden nur entlang der fachlichen Ownership-Kette
modelliert.

| Kindtabelle | Referenziert |
|-------------|--------------|
| `stories` | `project_spaces(project_key)` |
| `story_contexts` | `stories(project_key, story_display_id)` (Display-ID-Identität; `story_contexts.story_id` trägt die Display-ID) |
| `story_dependencies` | `stories(project_key, story_display_id)` als **komposite** FK für **beide** Endpunkte (`(project_key, story_id)` und `(project_key, depends_on_story_id)`); zusätzlich `projects(key)` |
| `story_custom_field_values` | `stories(project_key, story_display_id)` |
| `story_custom_field_values` | `story_custom_field_definitions(project_key, field_key)` |
| `flow_executions` | `stories(project_key, story_display_id)` |
| `node_execution_ledgers` | `flow_executions(project_key, run_id, flow_id)` |
| `attempts` | `flow_executions(project_key, run_id, flow_id)` |
| `override_records` | `flow_executions(project_key, run_id, flow_id)` |
| `guard_decisions` | `flow_executions(project_key, run_id, flow_id)` |
| `artifact_envelopes` | `flow_executions(project_key, run_id, flow_id)` |
| `execution_events` | `flow_executions(project_key, run_id, flow_id)` nur wenn `flow_id` gesetzt ist |
| `phase_states` | `flow_executions(project_key, run_id, flow_id)` fachlich indirekt; technisch auch nur über `(project_key, story_id, run_id)` zulässig |

**Regel:** Für optionale Beziehungen wie `execution_events.flow_id` oder
`node_id` sind nullable FK-Pfade zulässig. Ein Event muss nicht immer
an Flow und Node gebunden sein.

**StoryDependency → STATISCHE Story-Stammdaten.** Die Kanten der
`story_dependencies`-Edge-Tabelle referenzieren die statische `stories`-Entität
(FK-02 §2.11.3), **nicht** die Laufzeit-Projektion `story_contexts`.
Abhängigkeiten sind Story-Inhalt, kein Laufzeitzustand. Als FK-Ziel wird
`stories.story_display_id` (global `UNIQUE`, siehe §18.6a.1) gewählt, weil die
Spalten `story_id`/`depends_on_story_id` Display-ID-**Strings** tragen: so
bleibt der Wire-/Datenstand unverändert. `story_uuid` schiede aus, weil die
Spalten keine UUIDs halten; `(project_key, story_number)` schiede aus, weil das
das Speichern von Nummern statt der Display-ID erzwänge. Der FK ist **komposit**
über `(project_key, story_id) → stories(project_key, story_display_id)` (analog
für `depends_on_story_id`), gestützt auf das zusätzliche `(project_key,
story_display_id)`-UNIQUE aus §18.6a.1. Damit wird eine Kante auf eine nicht
vorhandene **oder** projektfremde Story **fail-closed** am FK abgewiesen — die
projektgescopte Edge kann keine Endpunkte aus einem anderen Projekt binden.

## 18.14 Indizes

### 18.14.1 Pflichtindizes

| Tabelle | Indexzweck |
|---------|------------|
| `stories` | Lookup nach `project_key, status` |
| `story_custom_field_values` | Lookup nach `project_key, field_key` |
| `flow_executions` | Lookup nach `project_key, story_id`; Lookup nach `project_key, status` |
| `node_execution_ledgers` | Lookup nach `project_key, run_id, flow_id`; Lookup nach `project_key, story_id` |
| `attempts` | Lookup nach `project_key, story_id`; Zeitachsen-Lookup nach `started_at` |
| `override_records` | offene Overrides nach `project_key, run_id, flow_id, consumed_at` |
| `guard_decisions` | Lookup nach `project_key, guard_key, decided_at` |
| `artifact_envelopes` | Lookup nach `project_key, story_id`; Lookup nach `project_key, artifact_kind`; Lookup nach `project_key, run_id` |
| `execution_events` | Zeitachsen-Lookup nach `project_key, run_id, occurred_at`; Lookup nach `project_key, event_type`; optional nach `project_key, story_id, occurred_at` |
| `phase_states` | Lookup nach `project_key, story_id`; Lookup nach `project_key, status` |
| `phase_snapshots` | Lookup nach `project_key, story_id`; Lookup nach `project_key, phase` |
| `kpi_projections` | Lookup nach `project_key, metric_name`; optional Fenster-Lookup |

### 18.14.2 JSONB-Indizes

`GIN`-Indizes sind nur dort zulässig, wo fachlich variable Daten
regelmäßig gefiltert werden:

- `story_contexts` auf ausgewählte Kontextfelder
- `story_custom_field_values.value`
- `artifact_envelopes` auf variable Artefakt-Metadaten, falls nötig
- `execution_events` auf Event-Payload nur bei nachgewiesenem Bedarf

**Regel:** JSONB wird nicht reflexartig mit GIN indiziert. Erst
nachgewiesene Query-Bedarfe rechtfertigen einen GIN-Index.

## 18.15 Check-Constraints

Die folgenden Regeln sind als Datenbank-Constraints abzubilden:

### 18.15.1 Nichtleer-Regeln

- alle Identitätsbestandteile dürfen nicht leer sein
- `reason` in `override_records` darf nicht leer sein
- `title` in `stories` darf nicht leer sein

### 18.15.2 Mindestwerte

- `attempt_no >= 1`
- `qa_cycle_round >= 1`, falls gesetzt
- `evidence_epoch >= 0`, falls gesetzt

### 18.15.3 Zeitregeln

- `finished_at >= started_at`, falls `finished_at` gesetzt ist
- `ended_at >= started_at` bei `attempts`
- `consumed_at >= created_at`, falls `consumed_at` gesetzt ist
- `last_refreshed_at >= created_at` bei `story_contexts`

### 18.15.4 Enum-Regeln

Für folgende Spalten sind `CHECK`-Constraints mit den geschlossenen
Wertemengen aus FK-17 zu definieren:

- `runtime_profile`
- `registration_status`
- `story_type`
- `mode`
- `status`-Spalten in `stories`, `flow_executions`, `phase_states`
- `outcome`-Spalten in `node_execution_ledgers`, `attempts`, `guard_decisions`
- `override_type`
- `actor_type`
- `artifact_status`
- `protection_level`
- `severity`
- `provider_sync_status`

## 18.16 Lösch- und Retentionregeln

### 18.16.1 Vollständiger Story-Reset

Ein vollständiger Story-Reset löscht alle umsetzungsbezogenen
Runtime-Daten physisch. Die relationale Abbildung muss diesen Reset
über klare Abhängigkeiten und konsistente Löschpfade unterstützen.

Pflichtumfang des Reset:

- `flow_executions`
- `node_execution_ledgers`
- `attempts`
- `override_records`
- `guard_decisions`
- umsetzungsbezogene `artifact_envelopes`
- `execution_events`
- `phase_states`
- `phase_snapshots`

**Normative Regel:** Nach Reset darf kein verbliebener Datensatz aus
diesen Tabellen den neuen Story-Start blockieren oder Guards/Detectoren
indirekt beeinflussen.

### 18.16.2 Story-Split

Ein Story-Split loescht die Ausgangs-Story **nicht**. Die relationale
Abbildung muss stattdessen unterstuetzen:

- sichtbaren Story-Status `Cancelled`
- ein eigenes `story_split_records`-Auditmodell
- Story-Lineage zwischen `source_story_id` und Nachfolgern
- Rebinding expliziter Dependency-Beziehungen
- Purge der operativen Runtime-Projektionen, Locks und Worktree-/Branch-
  Bindungen der Ausgangs-Story

`execution_events` der Ausgangs-Story bleiben beim Split erhalten,
werden aber fachlich nicht mehr als offene Delivery interpretiert und
duerfen keine Nachfolger-Starts blockieren.

### 18.16.3 Story-Löschung

Bei fachlicher Story-Löschung dürfen auch die dazugehörigen Runtime- und
Beobachtungsdaten vollständig entfernt werden. Eine etwaige historische
Aufbewahrung ist kein Teil des operativen Schemas, sondern ein
separater Export-/Archivpfad.

### 18.16.4 Projektionen

`phase_states` und `phase_snapshots` dürfen jederzeit aus den kanonischen
Daten neu aufgebaut werden. Beide werden beim vollständigen Story-Reset
immer mit entfernt. `kpi_projections` ist als Read-Model vorgesehen und
wird vollständig aus den kanonischen Daten abgeleitet.

### 18.16.5 Retention

Retention betrifft:

- Export-/Archivierungsstrategien
- kalte Historisierung
- eventuelle Auslagerung alter Telemetrie

Retention darf nie dazu führen, dass operative Restdaten eine
zurückgesetzte Story weiterhin beeinflussen. Wenn alte Telemetrie oder
Auditspuren aufbewahrt werden sollen, müssen sie vor dem Reset in ein
separates Archivmodell überführt werden, das von Runtime, Guards und
Startlogik nicht gelesen wird.
