---
concept_id: FK-17
title: "Fachliches Datenmodell und Ownership"
module: data-model
status: draft
doc_kind: detail
parent_concept_id: FK-02
authority_over:
  - scope: fachliches-datenmodell
  - scope: bounded-context-ownership
  - scope: runtime-vs-analytics-abgrenzung
defers_to:
  - FK-02
  - FK-20
  - FK-60
supersedes: []
superseded_by:
tags: [datenmodell, ownership, bounded-context, runtime-state, analytics]
---

# 17 — Fachliches Datenmodell und Ownership

## 17.1 Zweck

Dieses Dokument beschreibt das **fachliche Datenmodell** von AgentKit 3.
Es definiert Entitäten, Eigenschaften, Beziehungen und fachliche
Verantwortung. Es ist **kein** Tabellenentwurf und **kein** DB-Schema.

## 17.2 Grundregeln

- Das fachliche Modell wird entlang von **Komponenten-Ownership** geschnitten,
  nicht als globales Gott-Datenmodell.
- Das Modell unterscheidet sauber zwischen **Entity**,
  **Value Object** und **Aggregate**.
- Die Prozess-DSL (`FlowDefinition`, `NodeDefinition`, `EdgeRule`,
  `ExecutionPolicy`, `RetryPolicy`, `OverridePolicy`) bleibt **Code-Definition**
  und ist keine kanonische Runtime-Entität.
- Kanonische Runtime- und Analytics-Daten sind immer an `project_key`
  gebunden.
- Operativer Laufzeitstate und analytische Projektionen sind fachlich
  getrennt.

## 17.2a Modellbausteine

- **Entity:** fachliches Objekt mit Identität über Zeit
- **Value Object:** identitätsloses, rein wertdefiniertes Objekt
- **Aggregate:** Konsistenzgrenze aus einer Root-Entity und ihren
  intern mitgeführten Objekten

**Faustregel:** Wenn zwei Objekte mit denselben Attributwerten fachlich
dieselben sind, ist es eher ein Value Object. Wenn nicht, ist es eine
Entity.

## 17.2b Fachliche Basistypen

Die folgenden Typen sind **fachliche Datentypen**. Sie beschreiben
Bedeutung, Pflichtregeln und Wertebereiche, aber noch keine konkrete
PostgreSQL-Notation.

| Typ | Bedeutung | Regel |
|-----|-----------|-------|
| `ProjectKey` | Mandanten-Schlüssel | systemweit eindeutig, stabil, nicht leer |
| `StoryId` | Story-Kennung | innerhalb eines `ProjectKey` eindeutig |
| `RunId` | Laufkennung | innerhalb eines `ProjectKey` eindeutig |
| `FlowId` | Kennung eines Flows | innerhalb eines `RunId` eindeutig |
| `NodeId` | Kennung eines Nodes | innerhalb eines `FlowId` eindeutig |
| `FieldKey` | Kennung eines Custom Fields | innerhalb eines `ProjectKey` eindeutig |
| `ArtifactId` | Kennung eines Artefakts | innerhalb eines `RunId` eindeutig |
| `Enum<T>` | geschlossener Wertebereich | nur definierte Werte zulässig |
| `Text` | freier Text | Unicode, kann leer oder nicht leer eingeschränkt werden |
| `Boolean` | Wahr/Falsch | kein Tristate ohne explizite Modellierung |
| `Integer` | Ganzzahl | optional mit Mindestwert |
| `StringSet` | ungeordnete Menge von Strings | keine Duplikate |
| `StringList` | geordnete Liste von Strings | Duplikate fachlich erlaubt |
| `JsonValue` | strukturierter variabler Inhalt | nur wenn keine stabile Unterstruktur modelliert wird |
| `JsonObject` | strukturiertes Key-Value-Objekt | nur für variable Payloads |
| `UriRef` | Referenz auf externe oder interne Ressource | fachlich auflösbare Referenz |
| `PathRef` | kanonische Pfad-/Speicherreferenz | kein Dateisystem als Wahrheit impliziert |
| `Instant` | Zeitpunkt | Zeitzonenbewusst; bei Persistenz UTC-normalisiert; ISO-8601 mit Offset; Mikrosekundenpräzision |

## 17.2c Fachliche Enum-Räume

Die wichtigsten Attributräume dieses Dokuments sind als geschlossene
Wertemengen zu behandeln:

- `RuntimeProfile = core | are`
- `RegistrationStatus = registered | suspended | archived`
- `StoryType = implementation | bugfix | concept | research`
- `StoryMode = execution | exploration`
- `StoryStatus = backlog | approved | in_progress | done`
- `FlowLevel = pipeline | phase | component`
- `FlowStatus = ready | in_progress | yielded | completed | failed | escalated | blocked | aborted`
- `NodeOutcome = pass | fail | skip | yield | backtrack`
- `AttemptOutcome = completed | failed | escalated | yielded | blocked | skipped`
- `OverrideType = skip_node | force_gate_pass | force_gate_fail | jump_to | truncate_flow | freeze_retries`
- `ActorType = human | orchestrator | pipeline | admin_tool`
- `GuardOutcome = pass | fail | waived`
- `ArtifactStatus = planned | produced | validated | rejected | superseded`
- `ProtectionLevel = unprotected | hook_locked | frozen`
- `EventSeverity = debug | info | warning | error | critical`
- `ProviderSyncStatus = pending | synced | conflict | failed`

## 17.3 Kanonische Entitäten

### 17.3.1 ProjectSpace

**Owner:** `installer`

Repräsentiert ein registriertes Zielprojekt, gegen das eine zentrale
AgentKit-Installation arbeitet.

**Eigenschaften:**

- `project_key`
- `display_name`
- `project_root`
- `runtime_profile` (`core` | `are`)
- `registration_status`
- `skill_bundle_version`
- `prompt_bundle_version`

### 17.3.2 Story

**Owner:** `story_context_manager`

Repräsentiert die fachliche Arbeitseinheit, die von AgentKit bearbeitet
wird.

**Eigenschaften:**

- `project_key`
- `story_id`
- `external_item_ref`
- `title`
- `story_type`
- `mode`
- `labels`
- `size`
- `status`

**Normative Auslegung:** `Story` beschreibt die fachliche
Arbeitseinheit als Stammdatensatz und externe Tracker-Identität. Diese
Entität soll klein und stabil bleiben. Laufzeitnahe, phaseninvariante
Semantik gehört nicht in `Story`, sondern in `StoryContext`.

### 17.3.3 StoryContext

**Owner:** `story_context_manager`

Persistierter, phaseninvarianter Laufzeitkontext einer Story. Diese
Entität ist kein bloßes Aggregat zur Laufzeit, sondern ein kanonischer
Runtime-Snapshot für die Pipeline.

**Eigenschaften:**

- `project_key`
- `story_id`
- `story_type`
- `mode`
- `scope`
- `scope_keys`
- `repo_bindings`
- `concept_refs`
- `guardrail_refs`
- `external_sources`
- `related_story_ids`
- `story_semantics`
- `tracker_binding`
- `created_at`
- `last_refreshed_at`

**Normative Auslegung:** `StoryContext` ist die kanonische,
persistierte Laufzeitsicht der Story für die Pipeline. Er bündelt die
Semantik, die nach dem Setup ohne erneute Außenabfragen verfügbar sein
muss.

### 17.3.4 StoryCustomFieldDefinition

**Owner:** `story_context_manager`

Beschreibt ein fachliches oder trackerbezogenes Custom Field, das an
einer Story existieren kann und von AgentKit gelesen oder geschrieben
wird.

**Eigenschaften:**

- `project_key`
- `field_key`
- `display_name`
- `field_type`
- `provider`
- `provider_field_ref`
- `is_required`
- `is_writable_by_agentkit`
- `allowed_values`

### 17.3.5 StoryCustomFieldValue

**Owner:** `story_context_manager`

Repräsentiert den konkreten Wert eines Custom Fields an einer Story.

**Eigenschaften:**

- `project_key`
- `story_id`
- `field_key`
- `value`
- `value_status`
- `source`
- `last_synced_at`
- `last_written_by`
- `provider_sync_status`
- `conflict_detected`
- `last_sync_attempt_at`

**Normative Auslegung:** Custom Fields sind kein loses Zusatzobjekt,
sondern Teil des kanonischen Story-Kontexts. AgentKit darf nur Felder
beschreiben, deren Definition `is_writable_by_agentkit = true` erlaubt.

### 17.3.6 FlowExecution

**Owner:** `pipeline_engine`

Repräsentiert einen konkreten Lauf eines Flows fuer eine Story.

**Eigenschaften:**

- `project_key`
- `story_id`
- `run_id`
- `flow_id`
- `flow_level`
- `owner_component`
- `status`
- `current_node_id`
- `attempt_no`
- `started_at`
- `finished_at`

### 17.3.7 NodeExecution

**Owner:** `pipeline_engine`

Repräsentiert die Ausführung eines konkreten Nodes innerhalb einer
`FlowExecution`.

**Eigenschaften:**

- `project_key`
- `story_id`
- `run_id`
- `flow_id`
- `node_id`
- `attempt_no`
- `outcome`
- `started_at`
- `finished_at`
- `resume_trigger`
- `backtrack_target`

**Normative Auslegung:** `NodeExecution` ist der kanonische
Node-/Policy-Ledger des Flows. Er dient der Auswertung von
`ExecutionPolicy`, Wiederholungen, Rueckspruengen und Skip-Semantik.

### 17.3.8 AttemptRecord

**Owner:** `pipeline_engine`

Append-only Historie eines Phasenversuchs. `AttemptRecord` ist kein
Ersatz für `NodeExecution`, sondern der crash-sichere Audit-Fakt auf
Phasenebene.

**Eigenschaften:**

- `project_key`
- `story_id`
- `run_id`
- `phase`
- `attempt_no`
- `outcome`
- `failure_cause`
- `started_at`
- `ended_at`

### 17.3.9 PhaseState

**Owner:** `phase_state_store`

Repräsentiert die aktuelle Top-Level-Sicht auf den aktiven
Pipelinezustand. `PhaseState` ist eine Arbeitsprojektion und keine
zweite, unabhängige Wahrheit neben `FlowExecution`.

**Normative Auslegung:** `PhaseState` bleibt eine durable
Runtime-Projektion für Resume und Komfort. Er muss aus den kanonischen
Runtime-Fakten rekonstruierbar sein und ist nicht die operative
Hauptwahrheit.

### 17.3.10 OverrideRecord

**Owner:** `guard_system`

Repräsentiert einen expliziten Eingriff von Mensch oder Orchestrator in
den Ablauf.

**Eigenschaften:**

- `project_key`
- `story_id`
- `run_id`
- `flow_id`
- `target_node_id`
- `override_type`
- `actor_type`
- `actor_id`
- `reason`
- `created_at`
- `consumed_at`

### 17.3.11 GuardDecision

**Owner:** `guard_system`

Repräsentiert die fachliche Entscheidung eines Guards oder Gates.

**Eigenschaften:**

- `project_key`
- `story_id`
- `run_id`
- `flow_id`
- `node_id`
- `guard_key`
- `outcome`
- `reason`
- `evidence_ref`
- `decided_at`

### 17.3.12 ArtifactRecord

**Owner:** `artifact_manager`

Repräsentiert die fachliche Referenz auf ein erzeugtes oder verwendetes
Artefakt. Der Inhalt des Artefakts ist nicht Teil dieser Entität.

**Eigenschaften:**

- `project_key`
- `story_id`
- `run_id`
- `artifact_id`
- `artifact_class`
- `artifact_kind`
- `artifact_format`
- `artifact_status`
- `produced_in_phase`
- `producer_component`
- `producer_trust`
- `attempt_no`
- `qa_cycle_id`
- `qa_cycle_round`
- `evidence_epoch`
- `protection_level`
- `frozen`
- `integrity_verified`
- `created_at`
- `finished_at`
- `storage_ref`

**Normative Auslegung:** Die im Legacy-Bestand beobachteten
storybezogenen Dateien wie `entwurfsartefakt.json`,
`design-review.json`, `design-challenge.json`, `preflight.json`,
`policy-precheck.json`, `structural.json`, `qa_review.json`,
`semantic_review.json`, `decision.json`, `execution-report.md`,
`are_bundle.json`, `feedback.json`, `handover.json`,
`worker-manifest.json`, `worker-manifest-implementation.json`,
`protocol.md`, `mediation-log.md`, `exploration-summary.md` und
mehrstufige Review-Artefakte werden fachlich nicht als je eigene
Hauptentität modelliert, sondern als typisierte Artefakte im
`ArtifactRecord`-Modell.

### 17.3.13 ExecutionEvent

**Owner:** `telemetry_service`

Append-only Ereignis über einen Lauf. `ExecutionEvent` dient der
Beobachtung und Auditierbarkeit gültiger Story-Umsetzungen, ist aber
weder die operative Hauptwahrheit des Systems noch eine eigenständige
Steuerungsquelle.

**Eigenschaften:**

- `project_key`
- `story_id`
- `run_id`
- `event_type`
- `occurred_at`
- `source_component`
- `flow_id`
- `node_id`
- `severity`
- `event_payload_ref`

**Normative Auslegung:** `ExecutionEvent` beschreibt fachlich nur das
beobachtbare Ereignis einer gültigen Story-Umsetzung. Event-spezifische
Detailpayloads bleiben variabel und gehören nicht in das kanonische
Entitätsgerüst dieses Dokuments. Ein vollständiger Story-Reset
invalidiert die `ExecutionEvent`-Daten der korrupten bisherigen
Umsetzung; sie werden zusammen mit den übrigen Runtime-Zuständen
entfernt. Gültige, nicht zurückgesetzte Runs bleiben dagegen
langfristig auditierbar.

### 17.3.14 KpiProjection

**Owner:** `analytics`

Repräsentiert abgeleitete Kennzahlen und Auswertungen. Diese Entität ist
nicht kanonisch fuer die operative Steuerung.

## 17.3a Attributverträge

Die folgenden Tabellen machen aus der Entitätenliste ein belastbares
fachliches Datenmodell. Sie definieren Typ, Pflicht und die wichtigste
Regel pro Attribut.

### 17.3a.1 ProjectSpace

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Identität, unveränderlich |
| `display_name` | `Text` | ja | menschenlesbarer Name |
| `project_root` | `PathRef` | ja | kanonische Projektwurzel |
| `runtime_profile` | `Enum<RuntimeProfile>` | ja | `core` oder `are` |
| `registration_status` | `Enum<RegistrationStatus>` | ja | steuert Nutzbarkeit |
| `skill_bundle_version` | `Text` | ja | gebundene Skill-Version |
| `prompt_bundle_version` | `Text` | ja | gebundene Prompt-Version |

### 17.3a.2 Story

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Teil der Identität |
| `story_id` | `StoryId` | ja | Teil der Identität |
| `external_item_ref` | `UriRef` | ja | Referenz auf externes Tracker-Objekt |
| `title` | `Text` | ja | fachlicher Titel |
| `story_type` | `Enum<StoryType>` | ja | geschlossener Wertebereich |
| `mode` | `Enum<StoryMode>` | ja | aktueller Bearbeitungsmodus |
| `labels` | `StringSet` | nein | deduplizierte Label-Menge |
| `size` | `Text` | nein | vorläufig als klassifizierter Textwert |
| `status` | `Enum<StoryStatus>` | ja | sichtbarer Story-Lebenszyklus |

### 17.3a.3 StoryContext

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Teil der Identität |
| `story_id` | `StoryId` | ja | genau ein aktiver Kontext pro Story |
| `story_type` | `Enum<StoryType>` | ja | Snapshot-Wert aus Setup |
| `mode` | `Enum<StoryMode>` | ja | Snapshot-Wert aus Setup/Modusermittlung |
| `scope` | `Text` oder `JsonValue` | ja | fachlicher Scope, nicht leer |
| `scope_keys` | `StringSet` | nein | kanonische Scope-Schlüssel |
| `repo_bindings` | `JsonObject` | ja | Repo-/Worktree-Bindungen |
| `concept_refs` | `StringList` | nein | referenzierte Konzepte |
| `guardrail_refs` | `StringList` | nein | referenzierte Guardrails |
| `external_sources` | `StringList` | nein | externe Quellen/Referenzen |
| `related_story_ids` | `StringSet` | nein | referenzierte andere Stories |
| `story_semantics` | `JsonObject` | nein | acceptance-/scope-/non-negotiable-Semantik |
| `tracker_binding` | `JsonObject` | ja | Binding auf externen Tracker |
| `created_at` | `Instant` | ja | Erstpersistierung |
| `last_refreshed_at` | `Instant` | ja | letzte Snapshot-Aktualisierung |

### 17.3a.4 StoryCustomFieldDefinition

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Teil der Identität |
| `field_key` | `FieldKey` | ja | Teil der Identität |
| `display_name` | `Text` | ja | menschenlesbar |
| `field_type` | `Text` | ja | fachlicher Feldtyp |
| `provider` | `Text` | ja | z. B. GitHub |
| `provider_field_ref` | `UriRef` oder `Text` | ja | Mapping auf Fremdsystem |
| `is_required` | `Boolean` | ja | Pflichtfeldregel |
| `is_writable_by_agentkit` | `Boolean` | ja | Single-Writer-Schranke |
| `allowed_values` | `StringList` | nein | nur bei enumerierten Feldern |

### 17.3a.5 StoryCustomFieldValue

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Teil der Identität |
| `story_id` | `StoryId` | ja | Teil der Identität |
| `field_key` | `FieldKey` | ja | Teil der Identität |
| `value` | `JsonValue` | nein | feldtypspezifischer Wert |
| `value_status` | `Text` | nein | fachlicher Gültigkeits-/Bearbeitungsstatus |
| `source` | `Text` | ja | Herkunft des aktuellen Werts |
| `last_synced_at` | `Instant` | nein | letzter erfolgreicher Sync |
| `last_written_by` | `Text` | nein | letzter fachlicher Writer |
| `provider_sync_status` | `Enum<ProviderSyncStatus>` | ja | externer Sync-Zustand |
| `conflict_detected` | `Boolean` | ja | zeigt Wertkonflikt an |
| `last_sync_attempt_at` | `Instant` | nein | letzter Sync-Versuch |

### 17.3a.6 FlowExecution

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Teil der Identität |
| `story_id` | `StoryId` | ja | fachlicher Bezug |
| `run_id` | `RunId` | ja | Teil der Identität |
| `flow_id` | `FlowId` | ja | Teil der Identität |
| `flow_level` | `Enum<FlowLevel>` | ja | pipeline/phase/component |
| `owner_component` | `Text` | ja | schreibender Owner |
| `status` | `Enum<FlowStatus>` | ja | aktueller Flowstatus |
| `current_node_id` | `NodeId` | nein | aktueller Kontrollpunkt |
| `attempt_no` | `Integer` | ja | >= 1 |
| `started_at` | `Instant` | ja | Eintritt in den Flow |
| `finished_at` | `Instant` | nein | nur in terminalen Zuständen |

### 17.3a.7 NodeExecution

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Teil der Identität |
| `story_id` | `StoryId` | ja | fachlicher Bezug |
| `run_id` | `RunId` | ja | Teil der Identität |
| `flow_id` | `FlowId` | ja | Teil der Identität |
| `node_id` | `NodeId` | ja | Teil der Identität |
| `attempt_no` | `Integer` | ja | >= 1 |
| `outcome` | `Enum<NodeOutcome>` | ja | letzter fachlicher Ausgang |
| `started_at` | `Instant` | ja | Start des Node-Laufs |
| `finished_at` | `Instant` | nein | Ende des Node-Laufs |
| `resume_trigger` | `Text` | nein | nur bei Resume/Yield |
| `backtrack_target` | `NodeId` | nein | nur bei Rücksprung |

### 17.3a.8 AttemptRecord

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Teil der Identität |
| `story_id` | `StoryId` | ja | fachlicher Bezug |
| `run_id` | `RunId` | ja | fachlicher Bezug |
| `phase` | `Text` | ja | Phase des Versuchs |
| `attempt_no` | `Integer` | ja | innerhalb der Phase eindeutig |
| `outcome` | `Enum<AttemptOutcome>` | ja | append-only Ergebnis |
| `failure_cause` | `Text` oder `JsonValue` | nein | nur bei nicht erfolgreichem Ausgang |
| `started_at` | `Instant` | ja | Beginn des Versuchs |
| `ended_at` | `Instant` | ja | Ende des Versuchs |

### 17.3a.9 PhaseState

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Projektion pro Projekt |
| `story_id` | `StoryId` | ja | Projektion pro Story |
| `run_id` | `RunId` | ja | Projektion pro Run |
| `phase` | `Text` | ja | aktuelle Top-Level-Phase |
| `status` | `Enum<FlowStatus>` | ja | abgeleitete Laufzeitsicht |
| `payload` | `JsonObject` | nein | phasenspezifische Projektion |
| `updated_at` | `Instant` | ja | letzte Projektionserneuerung |

### 17.3a.10 OverrideRecord

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Teil der Identität |
| `story_id` | `StoryId` | ja | fachlicher Bezug |
| `run_id` | `RunId` | ja | fachlicher Bezug |
| `flow_id` | `FlowId` | ja | Ziel-Flow |
| `target_node_id` | `NodeId` | nein | Ziel-Node falls knotenspezifisch |
| `override_type` | `Enum<OverrideType>` | ja | geschlossene Eingriffsart |
| `actor_type` | `Enum<ActorType>` | ja | wer ausgelöst hat |
| `actor_id` | `Text` | ja | fachliche Actor-Kennung |
| `reason` | `Text` | ja | nie leer |
| `created_at` | `Instant` | ja | Erzeugungszeitpunkt |
| `consumed_at` | `Instant` | nein | nur wenn angewendet |

### 17.3a.11 GuardDecision

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Teil der Identität |
| `story_id` | `StoryId` | ja | fachlicher Bezug |
| `run_id` | `RunId` | ja | fachlicher Bezug |
| `flow_id` | `FlowId` | ja | zugehöriger Flow |
| `node_id` | `NodeId` | nein | zugehöriger Node falls vorhanden |
| `guard_key` | `Text` | ja | Kennung des Guards/Gates |
| `outcome` | `Enum<GuardOutcome>` | ja | pass/fail/waived |
| `reason` | `Text` | nein | Begründung des Ergebnisses |
| `evidence_ref` | `UriRef` oder `PathRef` | nein | Evidenz-Verweis |
| `decided_at` | `Instant` | ja | Entscheidungszeitpunkt |

### 17.3a.12 ArtifactRecord

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Teil der Identität |
| `story_id` | `StoryId` | ja | fachlicher Bezug |
| `run_id` | `RunId` | ja | fachlicher Bezug |
| `artifact_id` | `ArtifactId` | ja | Teil der Identität |
| `artifact_class` | `Text` | ja | grobe Artefaktklasse |
| `artifact_kind` | `Text` | ja | konkreter Artefakttyp |
| `artifact_format` | `Text` | ja | z. B. json/md |
| `artifact_status` | `Enum<ArtifactStatus>` | ja | Lebenszyklusstatus |
| `produced_in_phase` | `Text` | ja | erzeugende Phase |
| `producer_component` | `Text` | ja | fachlicher Producer |
| `producer_trust` | `Text` | ja | Trust-Zuordnung |
| `attempt_no` | `Integer` | nein | falls attemptgebunden |
| `qa_cycle_id` | `Text` | nein | falls QA-Zyklus gebunden |
| `qa_cycle_round` | `Integer` | nein | >= 1 falls gesetzt |
| `evidence_epoch` | `Integer` | nein | monoton je Evidenzstand |
| `protection_level` | `Enum<ProtectionLevel>` | ja | Schutzregime |
| `frozen` | `Boolean` | ja | fachlich eingefroren oder nicht |
| `integrity_verified` | `Boolean` | ja | Gate/Integrity-Status |
| `created_at` | `Instant` | ja | Erzeugungszeitpunkt |
| `finished_at` | `Instant` | nein | Abschlusszeitpunkt |
| `storage_ref` | `PathRef` oder `UriRef` | ja | Speicherreferenz |

### 17.3a.13 ExecutionEvent

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Teil der Identität |
| `story_id` | `StoryId` | ja | fachlicher Bezug |
| `run_id` | `RunId` | ja | fachlicher Bezug |
| `event_type` | `Text` | ja | normierter Eventtyp |
| `occurred_at` | `Instant` | ja | Zeitpunkt des Ereignisses |
| `source_component` | `Text` | ja | emittierende Komponente |
| `flow_id` | `FlowId` | nein | falls flowgebunden |
| `node_id` | `NodeId` | nein | falls nodegebunden |
| `severity` | `Enum<EventSeverity>` | ja | Fachschweregrad |
| `event_payload_ref` | `UriRef` oder `JsonValue` | nein | Detailpayload oder Referenz |

**Reset-Regel:** `ExecutionEvent` ist nur innerhalb einer gültigen,
nicht vollständig zurückgesetzten Story-Umsetzung fachlich gültig. Ein
vollständiger Story-Reset löscht die Events der korrupten bisherigen
Umsetzung physisch mit.

### 17.3a.14 KpiProjection

| Attribut | Typ | Pflicht | Regel |
|----------|-----|---------|-------|
| `project_key` | `ProjectKey` | ja | Projekt-Scope |
| `projection_key` | `Text` | ja | Identität innerhalb des Projekts |
| `metric_name` | `Text` | ja | Kennzahlname |
| `metric_value` | `JsonValue` | ja | skalar oder strukturierter Wert |
| `window_start` | `Instant` | nein | Beginn des Aggregationsfensters |
| `window_end` | `Instant` | nein | Ende des Aggregationsfensters |
| `computed_at` | `Instant` | ja | letzter Projektionslauf |

## 17.4 Beziehungen

- Ein `ProjectSpace` hat viele `Story`.
- Eine `Story` hat genau einen langlebigen `StoryContext`.
- Eine `Story` hat viele `StoryCustomFieldValue`.
- Eine `StoryCustomFieldValue` referenziert genau eine
  `StoryCustomFieldDefinition`.
- Eine `Story` hat viele `FlowExecution`.
- Eine `FlowExecution` hat viele `NodeExecution`.
- Eine `FlowExecution` hat viele `AttemptRecord`.
- Eine `FlowExecution` kann viele `OverrideRecord`, `GuardDecision`,
  `ArtifactRecord` und `ExecutionEvent` haben.
- `KpiProjection` wird aus `FlowExecution`, `NodeExecution`,
  `AttemptRecord`, `GuardDecision` und `ExecutionEvent` abgeleitet.

## 17.4a Aggregatgrenzen

- `ProjectSpace` ist eigenes Aggregat.
- `Story` ist eigenes Aggregat.
- `Story` ist das Aggregat für Stammdaten, externe Tracker-Referenz und
  sichtbaren Story-Lebenszyklus.
- `StoryContext` ist ein eigenes Runtime-Aggregat und nicht bloß ein
  Unterobjekt von `Story`.
- `StoryCustomFieldDefinition` und `StoryCustomFieldValue` gehören
  fachlich zum `Story`-/`StoryContext`-Umfeld, aber nicht zur
  Ausführungs-Ownership der Pipeline.
- `FlowExecution` ist das Aggregat der Ablaufausführung.
- `NodeExecution` und `AttemptRecord` sind keine losen Nebenobjekte,
  sondern unterschiedliche Historien innerhalb des
  `FlowExecution`-Umfelds:
  `NodeExecution` für DSL-/Policy-Semantik,
  `AttemptRecord` für Phasen-Audit und Crash-Sicherheit.
- `PhaseState` ist bewusst kein eigenes Wahrheitsaggregat, sondern eine
  rekonstruierbare Projektion über dem Runtime-Umfeld.

**Normative Regel:** Auf Aggregate wird fachlich nur über ihre jeweilige
Root zugegriffen. Querverweise zwischen Aggregaten erfolgen nur per ID,
nicht per eingebettetem Fremdobjekt.

## 17.4b Aggregate Roots und interne Objekte

### Aggregate Root: `ProjectSpace`

- Root-Entity: `ProjectSpace`
- Intern geführte Objekte:
  keine weiteren kanonischen Unterobjekte in diesem Dokument

### Aggregate Root: `Story`

- Root-Entity: `Story`
- Intern geführte Objekte:
  - `StoryCustomFieldValue`
- Zugeordnete, aber getrennte Aggregate:
  - `StoryContext`
  - `FlowExecution`

**Normative Auslegung:** `StoryCustomFieldDefinition` ist kein
Story-Instanzobjekt, sondern ein definitorisches Umfeldobjekt des
`story_context_manager`.

### Aggregate Root: `StoryContext`

- Root-Entity: `StoryContext`
- Intern geführte Objekte:
  - kontextbezogene Referenzmengen wie `concept_refs`
  - Scope-/Binding-Werte

**Normative Auslegung:** `StoryContext` bleibt als eigenes
Runtime-Aggregat getrennt von `Story`, weil er eine andere
Änderungsdynamik und andere Invarianten hat.

### Aggregate Root: `FlowExecution`

- Root-Entity: `FlowExecution`
- Intern geführte Objekte:
  - `NodeExecution`
  - `AttemptRecord`
- Zugeordnete, aber getrennte Aggregate:
  - `OverrideRecord`
  - `GuardDecision`
  - `ArtifactRecord`
  - `ExecutionEvent`

**Normative Auslegung:** `NodeExecution` und `AttemptRecord` gehören zum
Ausführungsaggregat, weil ihre Invarianten direkt an der
Flow-Ausführung hängen. Overrides, Guard-Entscheidungen, Artefakte und
Events bleiben dagegen fachlich getrennte Aggregate mit eigenem Owner.

### Aggregate Root: `OverrideRecord`

- Root-Entity: `OverrideRecord`
- Intern geführte Objekte:
  keine weiteren kanonischen Unterobjekte in diesem Dokument

### Aggregate Root: `GuardDecision`

- Root-Entity: `GuardDecision`
- Intern geführte Objekte:
  keine weiteren kanonischen Unterobjekte in diesem Dokument

### Aggregate Root: `ArtifactRecord`

- Root-Entity: `ArtifactRecord`
- Intern geführte Objekte:
  keine weiteren kanonischen Unterobjekte in diesem Dokument

### Aggregate Root: `ExecutionEvent`

- Root-Entity: `ExecutionEvent`
- Intern geführte Objekte:
  keine weiteren kanonischen Unterobjekte in diesem Dokument

### Aggregate Root: `KpiProjection`

- Root-Entity: `KpiProjection`
- Intern geführte Objekte:
  projektionseigene Verdichtungen oder Kennzahlwerte

### Kein Aggregate Root: `PhaseState`

`PhaseState` ist bewusst kein Aggregate Root, weil er nur eine
rekonstruierbare Laufzeitprojektion ist.

## 17.5 Ownership-Regeln

- `story_context_manager` owns Story-Stammdaten, `StoryContext` und
  Story-Custom-Fields.
- `pipeline_engine` owns Flow- und Node-Ausführung.
- `pipeline_engine` owns zusätzlich `AttemptRecord` als
  phasenbezogenen Audit-Fakt.
- `phase_state_store` owns die aktuelle Laufzeitsicht als Projektion.
- `guard_system` owns Overrides und Guard-Entscheidungen.
- `artifact_manager` owns Artefakt-Referenzen.
- `telemetry_service` owns Events.
- `analytics` owns Projektionen und KPIs.

**Strikte Regel:** Komponenten dürfen übergreifend lesen, aber nicht
beliebig fremde kanonische Entitäten schreiben.

**Single-Writer-Prinzip:** Jede kanonische Entity hat genau einen
schreibenden Owner.

**Cross-Aggregate-Regel:** Konsistenz über Aggregatgrenzen hinweg wird
nicht über eine gemeinsame Wahrheit erzwungen, sondern über
Domain-Events, Projektionen und explizite Folgereaktionen.

**Telemetrie-Schranke:** `ExecutionEvent` darf Beobachtung und
Mustererkennung liefern, aber nie direkt über Start, Resume oder Reset
einer Story entscheiden. Steuernde Entscheidungen müssen als eigene
Runtime-Zustände materialisiert werden oder nach Reset vollständig
verschwinden.

## 17.6 Nicht als kanonische Entitäten modellieren

- DSL-Definitionen wie `FlowDefinition`, `NodeDefinition`, `EdgeRule`
- beliebige Handler-interne Payloads
- rohe Prompt-/LLM-Kontexte
- KPI-Rollups als operative Wahrheit
- phasenspezifische Sonderentitäten pro Schritt

**Normative Auslegung:** Die fachliche Verallgemeinerung fuer die
Ausführung ist `FlowExecution` + `NodeExecution`, nicht eine eigene
Entität pro Phase oder Schritt.

## 17.7 Persistenzmodell-Tags

Jede Entität dieses Dokuments muss bei der späteren relationalen
Abbildung genau einem Persistenzmodell zugeordnet werden:

- `canonical_runtime_snapshot`
- `canonical_runtime_ledger`
- `canonical_audit_append`
- `runtime_observation_append`
- `runtime_projection`
- `analytics_projection`

**Vorläufige Zuordnung:**

- `ProjectSpace`, `Story`, `StoryContext`,
  `StoryCustomFieldDefinition`, `StoryCustomFieldValue`:
  `canonical_runtime_snapshot`
- `FlowExecution`, `NodeExecution`, `ArtifactRecord`:
  `canonical_runtime_ledger`
- `AttemptRecord`, `OverrideRecord`, `GuardDecision`:
  `canonical_audit_append`
- `ExecutionEvent`: `runtime_observation_append`
- `PhaseState`: `runtime_projection`
- `KpiProjection`: `analytics_projection`

## 17.7a Vollständiger Story-Reset

Ein vollständiger Story-Reset setzt die Umsetzung fachlich auf
"zurück auf Los". Dabei bleiben die Story-Definition und ihre
langlebigen Metadaten bestehen, aber alle umsetzungsbezogenen
Runtime-Zustände werden entfernt.

**Pflichtumfang des Reset:**

- `FlowExecution`
- `NodeExecution`
- `AttemptRecord`
- `OverrideRecord`
- `GuardDecision`
- umsetzungsbezogene `ArtifactRecord`
- `ExecutionEvent`
- `PhaseState`

**Normative Regel:** Nach vollständigem Story-Reset darf kein
verbliebenes Artefakt, Event oder Guard-Ergebnis die erneute Aufnahme
der Story verhindern. Ein neuer Run muss gegen einen sauberen
Runtime-Zustand starten.

## 17.8 Vorläufige Value Objects

Die folgenden fachlichen Begriffe sind im Regelfall als Value Objects zu
modellieren und nicht als eigene Entities:

- `ProjectKey`
- `StoryId`
- `RunId`
- `FlowId`
- `NodeId`
- `TrustLevel`
- `RuntimeProfile`
- `ProtectionLevel`
- `Outcome`
- `Status`
- `ScopeKey`
- `ArtifactKind`
- `ArtifactStatus`
- `QACycleId`
- `EvidenceEpoch`

## 17.9 Reality-Check gegen Legacy-Artefakte

Stichprobe geprüft gegen:

- `BB2-001`
- `BB2-012`
- `BB2-029`
- `BB2-179`

**Befund:**

- `context.json` bestätigt, dass `StoryContext` mehr als nur
  `story_type` und `mode` tragen muss:
  Scope, Repo-Bindings, Semantik, Konzept-/Guardrail-Referenzen,
  externe Quellen und Story-Beziehungen sind fachlich relevant.
- `phase-state*.json` bestätigt die Einstufung von `PhaseState` als
  runtime-nahe Projektion mit phasenspezifischen Payloads und nicht als
  alleinige Hauptwahrheit.
- Review-, Challenge-, Preflight-, Structural-, Policy- und
  Decision-Dateien sprechen für einen stärker typisierten
  `ArtifactRecord`, nicht für viele neue Hauptentitäten.
- `integrity-violations.log` ist fachlich kein neues Hauptobjekt,
  sondern Export-/Auditmaterial aus `ExecutionEvent` und
  `GuardDecision`.

## 17.10 Reality-Check gegen Story-Pakete

Stichprobe geprüft gegen:

- `BB2-005`
- `BB2-029`
- `BB2-098`
- `BB2-167`

**Befund:**

- Die Verzeichnisse unter `stories/` sind fachlich Story-Pakete und
  keine zusätzlichen Runtime-Hauptentitäten.
- `story.md` ist ein spezifizierendes Story-Artefakt und kein Ersatz
  für die kanonischen Entitäten `Story` oder `StoryContext`.
- `handover.json`, `worker-manifest*.json`, `protocol.md`,
  `mediation-log.md`, `exploration-summary.md` und gestufte
  Review-Dateien bestätigen die Entscheidung, diese als typisierte
  Artefakte unter `ArtifactRecord` zu führen.
- Aus den Story-Paketen ergibt sich kein Bedarf für neue kanonische
  Hauptentitäten, wohl aber für saubere `artifact_kind`-Klassifikation.
