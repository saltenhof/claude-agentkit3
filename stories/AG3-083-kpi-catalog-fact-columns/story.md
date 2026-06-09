# AG3-083: KPI-Katalog (40 KPIs) + Fact-Table-Spaltensaetze nach §62.2

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `kpi-and-dashboard` / KPI-Katalog & Aggregations-Schema (BC16). Die vollstaendige Population des `KpiCatalog` (40 AKTIV-KPIs) und die Erweiterung der heute reduzierten `fact_*`-Spaltensaetze auf den FK-62-Sollstand inklusive angereicherter Event-Payloads.
**Quell-Konzepte (autoritativ):**
- `FK-60 §60.4` — Vollstaendiger versionierter KPI-Katalog: §60.4.2-§60.4.11 listen pro Domaene KPI, Status (AKTIV/INVENTAR), Datenklasse (`[R]`/`[N]`), Koernung und Beschreibung; §60.4.12 fixiert die Bilanz auf **genau 40 AKTIV** ueber **10 Domaenen**.
- `FK-61 §61.2-§61.11` — KPI-Erhebung nach Domaenen: pro AKTIV-KPI der vollstaendige Mapping-Vertrag (Source-Event/Payload, Prozesspunkt, `[R]`/`[N]`, Ziel-`fact_*`-Spalte); `§61.4.3` Guard-Scratchpad; `§61.12.2` angereicherte Payloads (`integrity_gate_result.blocked_dimensions[]`, `are_gate_result.total_requirements`/`covered_requirements`).
- `FK-62 §62.2.1-§62.2.5` — Sollstand der fuenf Fact-Tabellen-Spaltensaetze (`fact_story`, `fact_guard_period`, `fact_pool_period`, `fact_pipeline_period`, `fact_corpus_period`); `§62.2.6/§62.2.7` Scratchpad + Sync-State; `§62.6` Schreib-Owner (`FactStore`).

---

## 1. Kontext / Ist-Zustand (belegt)

Der Katalog ist ein bewusster Skeleton und die Fact-Spalten sind eine reduzierte „binding spec":

- `src/agentkit/kpi_analytics/catalog.py:139` `catalog_status: CatalogStatus = CatalogStatus.SKELETON`; der `KpiCatalog.__init__` registriert nichts (`catalog.py:141-142`). Modul-Docstring (Z. 3-5): „The full 40-KPI population is a follow-up story." → **0 von 40 AKTIV-KPIs registriert** (Gap FK-60 §60.4 UNVOLLSTAENDIG).
- Die Typ-Infrastruktur ist vollstaendig vorhanden: `KpiDefinition` (`catalog.py:95-123`: kpi_id/name/decision_question/formula_repr/granularity/collection_point/domain), `KpiGranularity` (`catalog.py:15-25`: STORY/ENTITY_PERIOD/PERIOD), `KpiDomain` (`catalog.py:28-65`: 10 Domaenen, FK-60-konform), `KpiCollectionPoint` (`catalog.py:78-92`: hook_or_event/data_available/notes). → Es fehlt **die Population**, nicht das Modell.
- Die `fact_*`-Records sind die reduzierte AG3-038-„binding spec" (`src/agentkit/kpi_analytics/fact_store/models.py:25-120`) und weichen vom FK-62-Sollstand sowohl in **Spaltenmenge** als auch in **Namen** ab:
  - `FactStory` (`models.py:25-53`) fehlen ggue. FK-62 §62.2.1 u. a. `processing_time_ms`, `blocked_ac_count`, `blocked_ac_detail_json`, `adversarial_hit_rate`, `findings_fully_resolved`, `findings_partially_resolved`, `findings_not_resolved`, `final_status`, `are_total_requirements`, `are_covered_requirements`, `increment_count`, `phase_exploration_ms`, `phase_verify_ms`, `computed_at`.
  - Namensabweichungen ggue. FK-62 §62.2.1: Code `story_mode`/`started_at`/`completed_at`/`qa_rounds`/`adversarial_findings`/`are_gate_status` vs. FK `pipeline_mode`/`opened_at`/`closed_at`/`qa_round_count`/`adversarial_findings_count`/`are_gate_passed`.
  - `FactGuardPeriod` (`models.py:56-69`): Code-PK `guard_id` vs. FK `guard_key` (§62.2.2); fehlende Spalten `period_grain`, `violation_rate`, `violation_stage_escape`, `violation_stage_schema`, `violation_stage_template`, `escape_detection_count`, `computed_at`.
  - `FactPoolPeriod` (`models.py:72-87`): Code-PK `llm_role` vs. FK `pool_key` (§62.2.3); fehlende Spalten `period_grain`, `response_time_p50_ms`, `verdict_adopted_count`, `verdict_total_count`, `finding_true_positive_count`, `finding_false_positive_count`, `quorum_triggered_count`, `template_finding_rate_json`, `computed_at`.
  - `FactPipelinePeriod` (`models.py:90-104`): fehlende Spalten ~18 (u. a. `story_count`, `story_count_closed`, `execution_count`, `exploration_count`, `stage_miss_*`, `impact_*`, `integrity_gate_*`, `doc_fidelity_conflict_by_level_json`, `first_pass_count`, `finding_*_count`, `effective_check_ids_json`, `vectordb_*`, `processing_time_*`, `qa_round_avg`, `period_grain`, `computed_at`) (§62.2.4).
  - `FactCorpusPeriod` (`models.py:107-120`): Code `incidents_recorded`/`patterns_promoted`/`checks_approved` vs. FK `new_incident_count`/`patterns_total_count`/`patterns_with_active_check`; fehlend `period_grain`, `computed_at` (§62.2.5).
- Die DDL-/Mapper-Wahrheit der Fact-Tabellen liegt heute an **fuenf** realen Orten, nicht an dreien:
  1. `src/agentkit/kpi_analytics/fact_store/models.py:25-145` — typisierte Records (A-Bloodtype).
  2. `src/agentkit/state_backend/postgres_schema.sql:809` (`fact_story` DDL ff.) — kanonische Postgres-Wahrheit.
  3. `src/agentkit/state_backend/sqlite_store.py:976` `_ensure_analytics_tables` — SQLite-Bootstrap.
  4. `src/agentkit/state_backend/migration/versions/v_3_4_analytics.sql:18` — versionierte Migrations-Cursor-DDL (MigrationRunner, fuer beide Backends).
  5. `src/agentkit/state_backend/store/fact_repository.py:173-331` — Column-Liste/Mapper/UPSERT-Wahrheit (`_FACT_STORY_COLUMNS`, `_FACT_STORY_UPDATE`, `_fact_story_params`, `_row_to_fact_*`).
- `are_gate_result`-Payload-Feldnamen weichen vom FK-61-Wortlaut ab; FK-61 §61.12.2 fixiert die kanonischen Wire-Keys `total_requirements`/`covered_requirements` (Gap FK-61 §61.9.2/§61.12.2).
- Anknuepfung: depends_on **AG3-038** (Fact-Schema/Records/Repository) und **AG3-081** (BC14/BC15-EventTypes + die angereicherten `integrity_gate_result`/`are_gate_result`-Payloads). AG3-083 **unblockt AG3-082** (RefreshWorker), der **gegen** die hier definierten Spalten rechnet (`sync_analytics`/`_percentile`). Die Fuelllogik gehoert AG3-082; diese Story liefert Katalog + Zielspalten + Schema/Mapper-Migration. Damit ist die fachlich korrekte Reihenfolge eindeutig: **AG3-082 depends_on AG3-083** (der Worker befuellt die hier definierten Spalten); AG3-083 selbst haengt **nicht** von AG3-082 ab.
- **Reihenfolge-Konsolidierung (Routing, nicht in dieser Story behebbar):** Drei externe Quellen widersprechen heute noch dieser Richtung und sind ueber ihre jeweiligen Owner-Stories zu korrigieren (diese Story darf sie nicht editieren):
  1. `var/concept-gap-analysis/_STORY_INDEX.md:89` listet AG3-083 noch mit `depends_on AG3-038, AG3-082` — falsch herum; Korrektur auf `depends_on AG3-038, AG3-081` gehoert dem Index-Owner (Backlog-/Index-Pflege), nicht AG3-083.
  2. `stories/AG3-082-kpi-refresh-worker/status.yaml:11-12` kodiert `unblocks: [AG3-083]` und damit **genau die umgekehrte** Richtung: laut dieser Metadaten kaeme AG3-082 vor AG3-083 und AG3-083 haenge von AG3-082 ab. Das widerspricht der hier (und vom Review) bestaetigten korrekten Richtung (AG3-082 rechnet gegen AG3-083-Spalten -> **AG3-082 depends_on AG3-083**, **AG3-083 unblocks AG3-082**). Korrektur gehoert **AG3-082** (Owner): `status.yaml` auf `depends_on: [AG3-038, AG3-081, AG3-083]` und `unblocks: [...]`-frei (kein `AG3-083`) umstellen. **Die fruehere Behauptung, AG3-082 `status.yaml` sei bereits korrekt, ist falsch und wird hier zurueckgenommen** — die `unblocks: [AG3-083]`-Zeile ist Teil der zu korrigierenden Abweichung.
  3. `stories/AG3-082-kpi-refresh-worker/story.md` ist durchgaengig auf „AG3-082 VOR AG3-083" gebaut (u. a. `:25`, `:48`, `:52`, `:56`, `:70`, `:92`, §6 W1) und schreibt an `:52` „AG3-083 (depends_on AG3-082; kommt also NACH AG3-082)". Die p50-Persistenz (`response_time_p50_ms`) wird dort als AG3-083-Schreibziel gefuehrt (`:52`), p95 bleibt in beiden Stories INVENTAR (`:48`). Die Richtungs-Prosa ist gegen die korrekte Reihenfolge — Korrektur gehoert **AG3-082** (Owner). Hinweis zur Konsistenz: wer auch immer die Richtung dreht, muss AG3-082 und AG3-083 **gemeinsam** ziehen, sonst entsteht ein Reihenfolge-Zyklus; AG3-083 persistiert keine Perzentile und beansprucht hier nur die FK-62-Zielspalte `response_time_p50_ms` (Scope-Punkt 6).
  AG3-083 haelt seine eigene Wahrheit konsistent (status.yaml `depends_on: [AG3-038, AG3-081]`, `unblocks: [AG3-082]`; p95 strikt INVENTAR, siehe Scope-Punkt 6) und meldet die drei externen Abweichungen (Index + AG3-082 `status.yaml` + AG3-082-Prosa) an ihre Owner, statt sie still zu erben.

## 2. Scope

### 2.1 In Scope
1. **40 AKTIV-KPIs im `KpiCatalog`** vollstaendig registrieren (FK-60 §60.4.2-§60.4.11), je KPI als `KpiDefinition` mit kpi_id/name/decision_question/formula_repr/granularity/collection_point/domain. Die `kpi_id`-Menge ist **exakt** die FK-60-AKTIV-Menge (40 IDs, siehe §2.1.1); keine INVENTAR-KPI wird registriert. `catalog_status` wechselt auf `COMPLETE`, sobald genau diese 40 registriert sind (konzept-definierter Trigger fuer `CatalogStatus.COMPLETE`, `catalog.py:74-75`). Der Skeleton-Docstring (`catalog.py:1-6`, `126-137`) wird durch die reale COMPLETE-Semantik ersetzt.
2. **Vollstaendiger FK-61-Mapping-Vertrag pro AKTIV-KPI** als typisierter, pruefbarer Katalog-Annex (kein zweiter Wahrheits-String-Satz): pro KPI Source-Event/Payload, Prozesspunkt, `[R]`/`[N]`-Klasse und **Ziel-`fact_*`-Spalte** gemaess FK-61 §61.2-§61.11. Modelliert ueber die vorhandenen Felder `KpiDefinition.collection_point.hook_or_event` (= Source-Event/Payload), `collection_point.data_available` (= `[R]`=True / `[N]`=False) und `collection_point.notes` (= Prozesspunkt). Die Ziel-Fact-Spalte wird als typisierte Zuordnung gefuehrt (siehe §2.1.2); jede genannte Ziel-Spalte MUSS im FK-62-Sollschema (Scope-Punkt 3) existieren — sonst Test rot (FAIL-CLOSED). Der Source-Owner einer KPI ist **genau der von FK-61 §61.2-§61.11 fuer diese KPI benannte** Erhebungspunkt — eine der fuenf FK-61-Quellklassen (siehe §2.1.3); ein pauschaler „AG3-081-EventType/Payload"-Owner fuer alle `[N]`-KPIs ist fachlich falsch und wird **nicht** angenommen.
3. **Fact-Spaltensaetze auf den FK-62-Sollstand erweitern** (alle fuenf Tabellen, §62.2.1-§62.2.5). **FK-62 ist die verbindliche Namens- und Spaltenwahrheit** (kein „Code-Realitaet"-Alternativpfad): alle in §1 gelisteten Namensabweichungen werden **auf die FK-62-Namen umgestellt** (`pipeline_mode`, `opened_at`, `closed_at`, `qa_round_count`, `adversarial_findings_count`, `are_gate_passed`, `guard_key`, `pool_key`, `new_incident_count`, `patterns_total_count`, `patterns_with_active_check`) und alle fehlenden FK-62-Spalten ergaenzt. Die Migration ist konsistent ueber **alle fuenf** Wahrheitsorte aus §1 (models.py + postgres_schema.sql + sqlite_store._ensure_analytics_tables + v_3_4_analytics.sql + fact_repository.py Column-Listen/Mapper/UPSERT) plus die `FactRepository`-Protocol-Signaturen, falls beruehrt.
4. **Rename-und-additiv-Migration explizit in Scope** (Versionierungsstrategie selbst bleibt Out-of-Scope, §2.2): die Spalten-Renames aus Scope-Punkt 3 sind **keine** rein additiven `ADD COLUMN`. Diese Story liefert die konsistente Schema-/Record-/Mapper-Umstellung; FK-62 §62.4 (`ADD COLUMN IF NOT EXISTS`) bleibt die Strategie fuer **neue** Spalten, die Renames werden als koordinierte Eindeutigkeits-Umstellung ueber alle fuenf Orte gefahren (Side-by-Side-Schema-Versionierung bleibt unveraendert; kein zweiter paralleler Spaltensatz).
5. **Angereicherte Event-Payloads** (FK-61 §61.12.2): die Ziel-Fact-Spalten fuer `integrity_gate_result.blocked_dimensions[]` (→ `fact_pipeline_period.integrity_gate_block_count`/`integrity_gate_total_count`) und `are_gate_result.total_requirements`/`covered_requirements` (→ `fact_story.are_total_requirements`/`are_covered_requirements`) sind im Sollschema vorhanden und auf **die in AG3-081 definierte Payload-Wahrheit** abgebildet (kein zweiter Feldname-Satz). Kanonische Wire-Keys (FK-61 §61.12.2 verbatim): `integrity_gate_result.blocked_dimensions`, `are_gate_result.total_requirements`, `are_gate_result.covered_requirements`.
6. **AKTIV-`_percentile`-Zielspalte**: `fact_pool_period.response_time_p50_ms` (P50, FK-60 §60.4.3 `llm_response_time_p50` AKTIV, FK-61 §61.3.1 → `fact_pool_period.response_time_p50_ms`) existiert im Sollschema, sodass der AG3-082-Worker sie befuellen kann. **`response_time_p95_ms` ist und bleibt ausserhalb dieser Story** (FK-60 §60.4.3 `llm_response_time_p95` = INVENTAR; FK-62 §62.2.3 markiert die Spalte explizit „INVENTAR, wird bei Aktivierung ergaenzt"). Keine P95-Spalte, keine P95-KPI in AG3-083 (Aktivierung waere eine eigene Konzept-/Code-Story).
7. **Contract-Tests** (Erweiterung der AG3-038-Contract-Test-Familie, nicht Ersatz): siehe Akzeptanzkriterien — exakte 40-AKTIV-ID-Menge + Pro-KPI-Feldvalidierung, Fact-Spalten-Schema-Stabilitaet ueber alle fuenf Orte, Mapping-Vertrag-Vollstaendigkeit, Payload-Wire-Keys.
8. **Negativpfade**: eine KPI der FK-61-Klasse 2/3 (§2.1.3) ohne den zugehoerigen AG3-081-EventType/-Payload schlaegt im Test fehl; eine KPI mit leerem `collection_point.hook_or_event` (keine FK-61-Quelle) schlaegt fehl; ein `KpiDefinition` mit leerer `decision_question` ist unzulaessig (FK-60 §60.2 P1: keine KPI ohne Entscheidungsfrage); eine im Mapping genannte Ziel-`fact_*`-Spalte, die nicht im FK-62-Sollschema existiert, ist ein Fehler (FAIL-CLOSED).

#### 2.1.1 Verbindliche AKTIV-KPI-ID-Menge (FK-60 §60.4, genau 40)

Die `kpi_id`-Menge des COMPLETE-Katalogs ist exakt diese (Domaenen-Bilanz §60.4.12 = 7/5/7/1/7/1/2/2/2/6 = 40):

- **D1 Story-Sizing (7):** `compaction_count_per_story`, `qa_round_count`, `processing_time_by_type_and_size`, `feedback_loop_convergence`, `execution_vs_exploration_ratio`, `blocked_ac_distribution`, `policy_required_stage_miss_rate`
- **D2 LLM-Selection (5):** `llm_response_time_p50`, `llm_verdict_adoption_rate`, `llm_finding_precision`, `llm_call_count_per_story`, `quorum_trigger_rate`
- **D3 Governance (7):** `guard_violation_count_by_type`, `guard_violation_rate_by_guard`, `prompt_integrity_violation_by_stage`, `governance_escape_detection_count`, `orchestrator_governance_violation_count`, `impact_violation_rate`, `integrity_gate_block_rate`
- **D4 Doc-Fidelity (1):** `doc_fidelity_conflict_rate_by_level`
- **D5 QA-Effectiveness (7):** `first_pass_success_rate`, `finding_survival_rate`, `check_effectiveness_by_id`, `adversarial_hit_rate`, `adversarial_findings_count`, `adversarial_tests_created_count`, `finding_resolution_quality`
- **D6 Review-Quality (1):** `review_template_effectiveness`
- **D7 VectorDB (2):** `vectordb_similarity_threshold_calibration`, `vectordb_duplicate_detection_rate`
- **D8 ARE (2):** `are_gate_result`, `are_evidence_coverage_rate`
- **D9 Failure-Corpus (2):** `incident_volume_per_month`, `pattern_to_check_conversion_rate`
- **D10 Process-Efficiency (6):** `phase_time_distribution`, `story_predictability`, `processing_time_trend`, `qa_round_trend`, `files_changed_per_story`, `increment_count_per_story`

Der Contract-Test pinnt diese Menge als Frozenset und vergleicht ID-fuer-ID gegen den registrierten Katalog (kein blosses Count). Aenderungen an dieser Menge sind nur ueber FK-60 §60.4 zulaessig (Konzept-Aenderung, nicht Code-Realitaet).

#### 2.1.2 Ziel-Fact-Spalten-Zuordnung (typisiert)

Die Ziel-`fact_*`-Spalte je AKTIV-KPI wird als typisierte Zuordnung gefuehrt (Enum/typed mapping in `kpi_analytics`, ARCH-55-englisch), abgeleitet aus den FK-61-Mapping-Tabellen (§61.2-§61.11, Spalte `→ fact_*`). Beispiele (autoritativ in FK-61): `qa_round_count → fact_story.qa_round_count` (§61.2.1), `llm_call_count_per_story → fact_story.llm_call_count` (§61.3.1), `adversarial_hit_rate → fact_story.adversarial_hit_rate` (§61.6.1), `are_gate_result → fact_story.are_gate_passed` (§61.9.1), `are_evidence_coverage_rate → fact_story.are_total_requirements`/`are_covered_requirements` (§61.9.2), `integrity_gate_block_rate → fact_pipeline_period.integrity_gate_block_count`/`integrity_gate_total_count` (§61.4.2), `phase_time_distribution → fact_story.phase_{setup,exploration,implementation,verify,closure}_ms` (§61.11.2). Jede Zuordnung MUSS gegen das FK-62-Sollschema (Scope-Punkt 3) aufloesbar sein.

#### 2.1.3 FK-61-Source-Owner-Klassen (kein pauschaler AG3-081-Owner)

FK-61 §61.2-§61.11 ordnet jeder AKTIV-KPI **genau eine** Erhebungsquelle zu. Diese faellt in eine von fuenf Klassen; nur ein Teil davon ist ein in AG3-081 gebauter EventType/Payload. Der Mapping-Vertrag (§2.1) und der Negativtest (§3 AC3) pruefen je KPI **gegen die laut FK-61 erforderliche Quellklasse**, nicht pauschal gegen AG3-081:

1. **Bestehendes Event** (`[R]`/`[N]`, schon vorhanden) — z. B. `llm_call_count_per_story` (`COUNT(execution_events ... event_type='llm_call')`, §61.3.1), `quorum_trigger_rate` (`review_divergence` „existiert bereits", §61.3.2), `are_gate_result` (`event_type='are_gate_result'`, §61.9.1).
2. **Neues Event** (`[N]`, von AG3-081 gebaut) — z. B. `impact_violation_rate` (`impact_violation_check`, §61.4.2), `vectordb_similarity_threshold_calibration` (`vectordb_search`, §61.8.1), `compaction_count_per_story` (`compaction_event`, §61.2.2). **Diese** Klasse verweist auf AG3-081.
3. **Angereicherte Payload eines bestehenden Events** (`[N]`, von AG3-081 konsolidiert) — z. B. `integrity_gate_block_rate` (`integrity_gate_result.blocked_dimensions[]`, §61.4.2/§61.12.2), `are_evidence_coverage_rate` (`are_gate_result.total_requirements`/`covered_requirements`, §61.9.2/§61.12.2), `prompt_integrity_violation_by_stage` (`integrity_violation.stage`, §61.4.2). **Diese** Klasse verweist auf AG3-081.
4. **Runtime-Metric / Read-Model / Projection** (`[N]`, **kein** neues Event noetig) — z. B. `execution_vs_exploration_ratio` (`runtime.story_metrics.mode`, §61.2.2: „Kein neues Event noetig"), `phase_time_distribution` (`phase_state_projection`, §61.11.2: „Kein neues Event"), `story_predictability` (Varianz aus `story_metrics`, §61.11.2). **Diese** Klasse verweist **nicht** auf einen AG3-081-EventType/-Payload.
5. **Scratchpad-Counter** (`[N]`, bewusst **kein** Event) — `guard_violation_rate_by_guard` (`runtime.guard_invocation_counters`, §61.4.3/§61.12.1: „guard_invocation ist bewusst KEIN Event-Typ"). Source-Owner ist der Scratchpad, nicht ein AG3-081-EventType.

Der Negativtest (§3 AC3) prueft pro KPI: gehoert die KPI laut FK-61 zu Klasse 2 oder 3 und fehlt der zugehoerige AG3-081-EventType/-Payload, ist das ein Fehler; gehoert die KPI zu Klasse 1/4/5, ist **kein** AG3-081-Event erforderlich und die Pruefung gilt der jeweils benannten FK-61-Quelle (bestehendes Event / Runtime-Read-Model / Scratchpad). Ein KPI ohne **irgendeine** FK-61-Quelle (`collection_point.hook_or_event` leer) ist immer ein Fehler.

### 2.2 Out of Scope (mit Owner aus `var/concept-gap-analysis/_STORY_INDEX.md`)
- **RefreshWorker / Aggregations-/Fuelllogik** (`sync_analytics`/`purge_story_analytics`/`_percentile`/Dirty-Sets) — **AG3-082** (Welle 4). Diese Story liefert Zielspalten + Katalog + Mapping; AG3-082 rechnet dagegen. **AG3-083 unblockt AG3-082** (Reihenfolge: erst Spalten/Mapping, dann Fuelllogik).
- **BC14/BC15-EventTypes + Integrity-Dim-8-Verdrahtung + Mandatory-Payload-Contracts** (die Erhebungs-Events und die Payload-Wahrheit selbst) — **AG3-081** (Welle 4, depends_on). Hier werden Collection-Points darauf verwiesen und die Ziel-Spalten konsolidiert; die Events/Payloads werden nicht definiert.
- **P95-Aktivierung** (`response_time_p95_ms` / `llm_response_time_p95` von INVENTAR → AKTIV) — eigene zukuenftige Konzept- + Code-Story; nicht in diesem Backlog-Schnitt enthalten. Hier strikt INVENTAR (kein Code).
- **KPI-API-Endpoints / Dashboard-Views / Trust-Boundary-Fix** — **AG3-084** (Welle 4).
- **Schema-Versionierungs-Migrationsstrategie der DB** (Side-by-Side-`ak3_v<slug>`) — bereits konform (`state_backend/postgres_schema.sql:792-808` Schema-Placement-Decision, AG3-005/AG3-053); diese Story aendert die Versionierungsstrategie nicht, nur den Spaltensatz innerhalb des aktuellen Schemas.

## 3. Akzeptanzkriterien
1. Der `KpiCatalog` registriert **genau** die 40 AKTIV-`kpi_id`s aus §2.1.1 als `KpiDefinition` (Contract-Test vergleicht die exakte ID-Menge als Frozenset, nicht nur den Count); `catalog_status` ist `COMPLETE`; keine INVENTAR-ID ist registriert.
2. Pro registrierter KPI validiert der Contract-Test gegen FK-60 §60.4: nicht-leere `decision_question` (P1), `name` gesetzt, `formula_repr` gesetzt, gueltige `granularity` (FK-60-Koernung der KPI), gueltige `domain` (10-Domaenen-Enum), `collection_point.data_available` passend zur FK-60-Datenklasse (`[R]`/`[N]`).
3. **FK-61-Mapping-Vertrag vollstaendig**: pro AKTIV-KPI traegt der Katalog Source-Event/Payload (`collection_point.hook_or_event`), Prozesspunkt (`collection_point.notes`), `[R]`/`[N]` und eine typisierte Ziel-`fact_*`-Spalte (§2.1.2); der Test prueft fuer alle 40, dass die Ziel-Spalte im FK-62-Sollschema existiert. Der Source-Owner wird je KPI gegen die laut FK-61 §61.2-§61.11 zustaendige Quellklasse (§2.1.3) geprueft, **nicht** pauschal gegen AG3-081. Negativtest: eine KPI der FK-61-Klasse 2/3 (neues Event bzw. angereicherte Payload) ohne den zugehoerigen AG3-081-EventType/-Payload schlaegt fehl; eine KPI der Klasse 1/4/5 (bestehendes Event / Runtime-Read-Model / Scratchpad) erfordert keinen AG3-081-Event und wird gegen ihre jeweils benannte FK-61-Quelle geprueft; ein leerer `collection_point.hook_or_event` ist immer ein Fehler.
4. Die fuenf `fact_*`-Tabellen tragen den FK-62-Sollspaltensatz (§62.2.1-§62.2.5) mit den **FK-62-Namen** als einziger Wahrheit; alle in §1 gelisteten Renames sind umgestellt; der Contract-Test belegt **identische** Spaltensaetze ueber alle fuenf Orte (`fact_store/models.py`, `postgres_schema.sql`, `sqlite_store._ensure_analytics_tables`, `v_3_4_analytics.sql`, `fact_repository.py` Column-Listen/Mapper/UPSERT) — Drift an einem Ort = Test rot.
5. Die angereicherten Event-Payload-Ziele sind mit AG3-081 konsolidiert (kein doppelter Feldname-Satz). Der Test nagelt die kanonischen Wire-Keys fest: `integrity_gate_result.blocked_dimensions`, `are_gate_result.total_requirements`, `are_gate_result.covered_requirements` (FK-61 §61.12.2) und ihre Ziel-Spalten (§2.1.2).
6. `fact_pool_period.response_time_p50_ms` existiert im Sollschema (P50 AKTIV). **`response_time_p95_ms` existiert NICHT** und keine P95-KPI ist registriert (Test belegt die Abwesenheit; FK-60/§62.2.3 INVENTAR).
7. Die AG3-038-Contract-Test-Familie ist **erweitert** (nicht ersetzt) und gruen; die bestehenden AG3-038-Records/Repository-Tests bleiben kohaerent (angepasst, wo Renames sie beruehren).
8. Alle neuen KPI-IDs/Spalten/Feldnamen/Enum-Werte englisch (ARCH-55).
9. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage ≥ 85 %.

## 4. Definition of Done
- AK 1–9 erfuellt; giftige Codex-Review PASS; Implementierung/Commit erst nach Execution-Plan-Freigabe — diese Story wird zunaechst nur autorisiert/reviewt.

## 5. Guardrail-Referenzen
- **FAIL CLOSED:** keine KPI ohne FK-61-Source-Owner (§2.1.3: bestehendes Event / neues AG3-081-Event / angereicherte AG3-081-Payload / Runtime-Read-Model / Scratchpad); KPIs der Klasse 2/3 ohne den zugehoerigen AG3-081-EventType/-Payload sind Fehler; keine KPI ohne Entscheidungsfrage; keine Mapping-Ziel-Spalte ausserhalb des FK-62-Sollschemas; Spaltensaetze ueber alle fuenf Orte konsistent oder Test rot.
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** FK-62 ist die einzige Namens-/Spaltenwahrheit (keine „Code-Realitaet"-Ausnahme ohne Konzept-Aenderung); eine Payload-Wahrheit gemeinsam mit AG3-081; kein paralleler Spaltensatz, keine zweite KPI-Definition.
- **TYPISIERT STATT STRINGS:** KPIs als `KpiDefinition`-Instanzen, Mapping als typisierte Ziel-Fact-Spalten-Zuordnung, Fact-Spalten als typisierte Records.
- **ZERO DEBT:** der Skeleton wird real auf 40 KPIs gehoben (kein „follow-up"-Docstring mehr); kein TODO-Rest; P95 bleibt sauber als INVENTAR ausgewiesen, nicht als halbe Spalte.
- **ARCH-55:** alle KPI-IDs/Spalten/Feldnamen/Enum-Werte englisch.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Die Typ-Infrastruktur (`catalog.py`) ist fertig — nur **Population + Status-Wechsel auf COMPLETE**; kein neues Katalog-Modell bauen. Die 40 IDs/Domaenen/Koernungen stehen verbindlich in §2.1.1 und FK-60 §60.4.
- FK-62 ist die **verbindliche** Namenswahrheit. Renames (`guard_id→guard_key`, `llm_role→pool_key`, `story_mode→pipeline_mode`, `started_at→opened_at`, `completed_at→closed_at`, `qa_rounds→qa_round_count`, `adversarial_findings→adversarial_findings_count`, `are_gate_status→are_gate_passed`, Corpus-Spalten) MUESSEN ueber **fuenf** Orte gemeinsam laufen: `kpi_analytics/fact_store/models.py`, `state_backend/postgres_schema.sql` (`fact_story`-Block ab :809), `state_backend/sqlite_store.py` `_ensure_analytics_tables` (:976), `state_backend/migration/versions/v_3_4_analytics.sql`, `state_backend/store/fact_repository.py` (Column-Listen `_FACT_*_COLUMNS`/`_FACT_*_UPDATE`, Mapper `_fact_*_params`/`_row_to_fact_*`). Keinen Ort vergessen, sonst Drift → Test rot.
- Den FK-61-Mapping-Vertrag (Source-Event/Payload + Prozesspunkt + Ziel-Fact-Spalte) je KPI aus FK-61 §61.2-§61.11 ablesen; die Ziel-Spalte als typisierte Zuordnung modellieren (kein loser String-Satz neben dem Katalog).
- Feldnamen-Konsolidierung mit AG3-081 abstimmen (eine ARE-/Integrity-Payload-Wahrheit, kanonische Wire-Keys aus FK-61 §61.12.2); bei Reihenfolgekonflikt die gemeinsame Wahrheit dokumentieren und melden.
- P95 NICHT bauen (INVENTAR). Die Fuelllogik gehoert AG3-082 — hier nur Zielspalten + Katalog + Mapping + Contract-Tests.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Test-Namen der exakten 40-AKTIV-ID-Pruefung + des Fact-Spalten-Contract-Tests ueber alle fuenf Orte.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
