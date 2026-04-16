---
concept_id: FK-18
title: "Relationales Abbildungsmodell fuer PostgreSQL"
module: relational-schema
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
---

# 18 — Relationales Abbildungsmodell fuer PostgreSQL

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
- `node_executions`
- `attempt_records`

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

- `artifact_records`

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

- `phase_state_projection`
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
| `NodeExecution` | `node_executions` | kanonisch |
| `AttemptRecord` | `attempt_records` | kanonisch append-only |
| `OverrideRecord` | `override_records` | kanonisch append-only |
| `GuardDecision` | `guard_decisions` | kanonisch append-only |
| `ArtifactRecord` | `artifact_records` | kanonisch |
| `ExecutionEvent` | `execution_events` | runtime-nahe Beobachtung und Audit, append-only pro gültiger Umsetzung |
| `PhaseState` | `phase_state_projection` | Projektion |
| `KpiProjection` | `kpi_projections` | Projektion |

## 18.5 Relationale Leitentscheidung pro Tabelle

### 18.5.1 Stark relational halten

- `project_spaces`
- `stories`
- `story_custom_field_definitions`
- `flow_executions`
- `node_executions`
- `attempt_records`
- `override_records`
- `guard_decisions`

**Grund:** Diese Tabellen tragen Identität, Status, Owner-Logik,
Zeitachsen oder harte Filter-/Join-Felder.

### 18.5.2 Relational mit `jsonb`-Anteilen

- `story_contexts`
- `story_custom_field_values`
- `artifact_records`
- `execution_events`

**Grund:** Diese Tabellen enthalten fachlich variable, aber dennoch
kanonische Payloads wie:

- Kontext-/Scope-Strukturen
- flexible Custom-Field-Werte
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
- `node_executions`:
  referenziert `flow_executions` per `(project_key, run_id, flow_id)`
- `attempt_records`:
  referenziert `flow_executions` per `(project_key, run_id, flow_id)`

### 18.6.3 Governance / Artifacts / Telemetry

- `override_records`, `guard_decisions`, `artifact_records`,
  `execution_events` referenzieren fachlich mindestens:
  `project_key`, `story_id`, `run_id`
- falls vorhanden zusaetzlich:
  `flow_id`, `node_id`, `attempt_no`

## 18.6a Identität und Unique-Regeln

### 18.6a.1 Catalog

| Tabelle | Fachlicher Identitätskandidat | Unique-Regeln |
|---------|-------------------------------|---------------|
| `project_spaces` | `(project_key)` | `project_key` systemweit eindeutig |
| `stories` | `(project_key, story_id)` | pro Projekt genau eine Story-ID |
| `story_contexts` | `(project_key, story_id)` | pro Story genau ein aktiver Kontext |
| `story_custom_field_definitions` | `(project_key, field_key)` | `field_key` pro Projekt eindeutig |
| `story_custom_field_values` | `(project_key, story_id, field_key)` | pro Story höchstens ein aktueller Wert je Feld |

### 18.6a.2 Execution

| Tabelle | Fachlicher Identitätskandidat | Unique-Regeln |
|---------|-------------------------------|---------------|
| `flow_executions` | `(project_key, run_id, flow_id)` | pro Run genau ein Flow je `flow_id` |
| `node_executions` | `(project_key, run_id, flow_id, node_id)` | pro Flow genau ein aktueller Node-Ledger je `node_id` |
| `attempt_records` | `(project_key, run_id, flow_id, phase, attempt_no)` | `attempt_no` innerhalb von `(run_id, flow_id, phase)` eindeutig |

### 18.6a.3 Governance / Artifacts / Telemetry

| Tabelle | Fachlicher Identitätskandidat | Unique-Regeln |
|---------|-------------------------------|---------------|
| `override_records` | `(project_key, run_id, flow_id, override_id)` | `override_id` innerhalb des Flow-Kontexts eindeutig |
| `guard_decisions` | `(project_key, run_id, flow_id, guard_decision_id)` | jede Guard-Entscheidung hat eigene Identität |
| `artifact_records` | `(project_key, run_id, artifact_id)` | `artifact_id` innerhalb eines Runs eindeutig |
| `execution_events` | `(project_key, run_id, event_id)` | `event_id` innerhalb eines Runs eindeutig |

### 18.6a.4 Read Models

| Tabelle | Fachlicher Identitätskandidat | Unique-Regeln |
|---------|-------------------------------|---------------|
| `phase_state_projection` | `(project_key, story_id, run_id)` | genau eine aktuelle Projektion pro Run |
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
| `node_executions` | update-fähig | Ledger je Node wird fortgeschrieben |
| `attempt_records` | append-only | nach dem Schreiben keine fachliche Mutation |
| `override_records` | append-mostly | nur `consumed_at` darf nachträglich gesetzt werden |
| `guard_decisions` | append-only | Entscheidung ist nach Persistenz unveränderlich |
| `artifact_records` | update-fähig | Status/Integrity/Freeze dürfen fortgeschrieben werden |
| `execution_events` | append-only innerhalb eines Runs | Event darf nach Persistenz nicht verändert werden, wird aber bei vollständigem Story-Reset physisch gelöscht |
| `phase_state_projection` | replace/update | vollständig rebuildbar |
| `kpi_projections` | replace/update | vollständig rebuildbar |

## 18.6c Append-only-Regeln

Die folgenden Tabellen sind fachlich append-only und dürfen nach
Persistenz nicht inhaltlich umgeschrieben werden:

- `attempt_records`
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
- `flow_executions` → `node_executions`
- `flow_executions` → `attempt_records`
- `flow_executions` → `override_records`
- `flow_executions` → `guard_decisions`
- `flow_executions` → `artifact_records`
- `flow_executions` → `execution_events`

**Regel:** Projektionstabellen zeigen fachlich nach unten auf
kanonische Tabellen, nie umgekehrt.

## 18.6e Pflichtspalten pro Tabelle

### 18.6e.1 Catalog

| Tabelle | Pflichtspalten |
|---------|----------------|
| `project_spaces` | `project_key`, `display_name`, `project_root`, `runtime_profile`, `registration_status`, `skill_bundle_version`, `prompt_bundle_version` |
| `stories` | `project_key`, `story_id`, `external_item_ref`, `title`, `story_type`, `mode`, `status` |
| `story_contexts` | `project_key`, `story_id`, `story_type`, `mode`, `scope`, `repo_bindings`, `tracker_binding`, `created_at`, `last_refreshed_at` |
| `story_custom_field_definitions` | `project_key`, `field_key`, `display_name`, `field_type`, `provider`, `provider_field_ref`, `is_required`, `is_writable_by_agentkit` |
| `story_custom_field_values` | `project_key`, `story_id`, `field_key`, `source`, `provider_sync_status`, `conflict_detected` |

### 18.6e.2 Execution

| Tabelle | Pflichtspalten |
|---------|----------------|
| `flow_executions` | `project_key`, `story_id`, `run_id`, `flow_id`, `flow_level`, `owner_component`, `status`, `attempt_no`, `started_at` |
| `node_executions` | `project_key`, `story_id`, `run_id`, `flow_id`, `node_id`, `attempt_no`, `outcome`, `started_at` |
| `attempt_records` | `project_key`, `story_id`, `run_id`, `flow_id`, `phase`, `attempt_no`, `outcome`, `started_at`, `ended_at` |

### 18.6e.3 Governance

| Tabelle | Pflichtspalten |
|---------|----------------|
| `override_records` | `project_key`, `story_id`, `run_id`, `flow_id`, `override_id`, `override_type`, `actor_type`, `actor_id`, `reason`, `created_at` |
| `guard_decisions` | `project_key`, `story_id`, `run_id`, `flow_id`, `guard_decision_id`, `guard_key`, `outcome`, `decided_at` |

### 18.6e.4 Artifacts

| Tabelle | Pflichtspalten |
|---------|----------------|
| `artifact_records` | `project_key`, `story_id`, `run_id`, `artifact_id`, `artifact_class`, `artifact_kind`, `artifact_format`, `artifact_status`, `produced_in_phase`, `producer_component`, `producer_trust`, `protection_level`, `frozen`, `integrity_verified`, `created_at`, `storage_ref` |

### 18.6e.5 Telemetry

| Tabelle | Pflichtspalten |
|---------|----------------|
| `execution_events` | `project_key`, `story_id`, `run_id`, `event_id`, `event_type`, `occurred_at`, `source_component`, `severity` |

### 18.6e.6 Read Models

| Tabelle | Pflichtspalten |
|---------|----------------|
| `phase_state_projection` | `project_key`, `story_id`, `run_id`, `phase`, `status`, `updated_at` |
| `kpi_projections` | `project_key`, `projection_key`, `metric_name`, `metric_value`, `computed_at` |

## 18.6f Optionale Spalten nach Fachregel

Die folgenden Spalten sind nur unter bestimmten fachlichen Bedingungen
gesetzt und deshalb logisch optional:

| Tabelle | Optionale Spalten | Bedingung |
|---------|-------------------|-----------|
| `stories` | `labels`, `size` | nur wenn im Tracker oder Projektprofil genutzt |
| `story_contexts` | `scope_keys`, `concept_refs`, `guardrail_refs`, `external_sources`, `related_story_ids`, `story_semantics` | nur wenn Setup/Exploration diese Daten liefert |
| `story_custom_field_values` | `value`, `value_status`, `last_synced_at`, `last_written_by`, `last_sync_attempt_at` | nur wenn Feld belegt oder Sync stattgefunden hat |
| `flow_executions` | `current_node_id`, `finished_at` | nur im Lauf oder nach terminalem Abschluss |
| `node_executions` | `finished_at`, `resume_trigger`, `backtrack_target` | nur bei Abschluss/Yield/Ruecksprung |
| `attempt_records` | `failure_cause` | nur bei nicht erfolgreichem Outcome |
| `override_records` | `target_node_id`, `consumed_at` | knotenspezifisch bzw. nach Konsum |
| `guard_decisions` | `node_id`, `reason`, `evidence_ref` | falls nodebezogen oder begruendet/evidenzgestuetzt |
| `artifact_records` | `attempt_no`, `qa_cycle_id`, `qa_cycle_round`, `evidence_epoch`, `finished_at` | nur fuer QA-/attemptgebundene Artefakte |
| `execution_events` | `flow_id`, `node_id`, `event_payload_ref` | nur wenn Event fachlich darauf bezogen ist |
| `kpi_projections` | `window_start`, `window_end` | nur bei fensterbezogenen Kennzahlen |

## 18.7 Projektionen

### 18.7.1 `phase_state_projection`

Lesemodell fuer:

- Resume
- Statusabfragen
- Dashboard-nahe Laufzeitsicht

**Regel:** Kein Single Source of Truth.

### 18.7.2 `kpi_projections`

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
| `stories` | `(project_key, story_id)` |
| `story_contexts` | `(project_key, story_id)` |
| `story_custom_field_definitions` | `(project_key, field_key)` |
| `story_custom_field_values` | `(project_key, story_id, field_key)` |

### 18.12.2 Execution

| Tabelle | Primärschlüssel |
|---------|-----------------|
| `flow_executions` | `(project_key, run_id, flow_id)` |
| `node_executions` | `(project_key, run_id, flow_id, node_id)` |
| `attempt_records` | `(project_key, run_id, flow_id, phase, attempt_no)` |

### 18.12.3 Governance / Artifacts / Telemetry

| Tabelle | Primärschlüssel |
|---------|-----------------|
| `override_records` | `(project_key, run_id, flow_id, override_id)` |
| `guard_decisions` | `(project_key, run_id, flow_id, guard_decision_id)` |
| `artifact_records` | `(project_key, run_id, artifact_id)` |
| `execution_events` | `(project_key, run_id, event_id)` |

### 18.12.4 Read Models

| Tabelle | Primärschlüssel |
|---------|-----------------|
| `phase_state_projection` | `(project_key, story_id, run_id)` |
| `kpi_projections` | `(project_key, projection_key)` |

## 18.13 Fremdschlüssel

Fremdschlüssel werden nur entlang der fachlichen Ownership-Kette
modelliert.

| Kindtabelle | Referenziert |
|-------------|--------------|
| `stories` | `project_spaces(project_key)` |
| `story_contexts` | `stories(project_key, story_id)` |
| `story_custom_field_values` | `stories(project_key, story_id)` |
| `story_custom_field_values` | `story_custom_field_definitions(project_key, field_key)` |
| `flow_executions` | `stories(project_key, story_id)` |
| `node_executions` | `flow_executions(project_key, run_id, flow_id)` |
| `attempt_records` | `flow_executions(project_key, run_id, flow_id)` |
| `override_records` | `flow_executions(project_key, run_id, flow_id)` |
| `guard_decisions` | `flow_executions(project_key, run_id, flow_id)` |
| `artifact_records` | `flow_executions(project_key, run_id, flow_id)` |
| `execution_events` | `flow_executions(project_key, run_id, flow_id)` nur wenn `flow_id` gesetzt ist |
| `phase_state_projection` | `flow_executions(project_key, run_id, flow_id)` fachlich indirekt; technisch auch nur über `(project_key, story_id, run_id)` zulässig |

**Regel:** Für optionale Beziehungen wie `execution_events.flow_id` oder
`node_id` sind nullable FK-Pfade zulässig. Ein Event muss nicht immer
an Flow und Node gebunden sein.

## 18.14 Indizes

### 18.14.1 Pflichtindizes

| Tabelle | Indexzweck |
|---------|------------|
| `stories` | Lookup nach `project_key, status` |
| `story_custom_field_values` | Lookup nach `project_key, field_key` |
| `flow_executions` | Lookup nach `project_key, story_id`; Lookup nach `project_key, status` |
| `node_executions` | Lookup nach `project_key, run_id, flow_id`; Lookup nach `project_key, story_id` |
| `attempt_records` | Lookup nach `project_key, story_id`; Zeitachsen-Lookup nach `started_at` |
| `override_records` | offene Overrides nach `project_key, run_id, flow_id, consumed_at` |
| `guard_decisions` | Lookup nach `project_key, guard_key, decided_at` |
| `artifact_records` | Lookup nach `project_key, story_id`; Lookup nach `project_key, artifact_kind`; Lookup nach `project_key, run_id` |
| `execution_events` | Zeitachsen-Lookup nach `project_key, run_id, occurred_at`; Lookup nach `project_key, event_type`; optional nach `project_key, story_id, occurred_at` |
| `phase_state_projection` | Lookup nach `project_key, story_id`; Lookup nach `project_key, status` |
| `kpi_projections` | Lookup nach `project_key, metric_name`; optional Fenster-Lookup |

### 18.14.2 JSONB-Indizes

`GIN`-Indizes sind nur dort zulässig, wo fachlich variable Daten
regelmäßig gefiltert werden:

- `story_contexts` auf ausgewählte Kontextfelder
- `story_custom_field_values.value`
- `artifact_records` auf variable Artefakt-Metadaten, falls nötig
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
- `ended_at >= started_at` bei `attempt_records`
- `consumed_at >= created_at`, falls `consumed_at` gesetzt ist
- `last_refreshed_at >= created_at` bei `story_contexts`

### 18.15.4 Enum-Regeln

Für folgende Spalten sind `CHECK`-Constraints mit den geschlossenen
Wertemengen aus FK-17 zu definieren:

- `runtime_profile`
- `registration_status`
- `story_type`
- `mode`
- `status`-Spalten in `stories`, `flow_executions`, `phase_state_projection`
- `outcome`-Spalten in `node_executions`, `attempt_records`, `guard_decisions`
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
- `node_executions`
- `attempt_records`
- `override_records`
- `guard_decisions`
- umsetzungsbezogene `artifact_records`
- `execution_events`
- `phase_state_projection`

**Normative Regel:** Nach Reset darf kein verbliebener Datensatz aus
diesen Tabellen den neuen Story-Start blockieren oder Guards/Detectoren
indirekt beeinflussen.

### 18.16.2 Story-Löschung

Bei fachlicher Story-Löschung dürfen auch die dazugehörigen Runtime- und
Beobachtungsdaten vollständig entfernt werden. Eine etwaige historische
Aufbewahrung ist kein Teil des operativen Schemas, sondern ein
separater Export-/Archivpfad.

### 18.16.3 Projektionen

`phase_state_projection` und `kpi_projections` dürfen jederzeit aus den
kanonischen Daten neu aufgebaut werden. `phase_state_projection` wird
beim vollständigen Story-Reset immer mit entfernt.

### 18.16.4 Retention

Retention betrifft:

- Export-/Archivierungsstrategien
- kalte Historisierung
- eventuelle Auslagerung alter Telemetrie

Retention darf nie dazu führen, dass operative Restdaten eine
zurückgesetzte Story weiterhin beeinflussen. Wenn alte Telemetrie oder
Auditspuren aufbewahrt werden sollen, müssen sie vor dem Reset in ein
separates Archivmodell überführt werden, das von Runtime, Guards und
Startlogik nicht gelesen wird.
