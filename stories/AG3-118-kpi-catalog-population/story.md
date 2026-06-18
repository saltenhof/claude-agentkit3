# AG3-118: KPI-Katalog (40 KPIs) + FK-61-Mapping + Contract-Tests

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** `kpi-and-dashboard` / KPI-Katalog (BC16). Vollstaendige Population des `KpiCatalog` mit den 40 AKTIV-KPIs aus FK-60 §60.4 plus dem typisierten FK-61-Pro-KPI-Mapping-Vertrag und den zugehoerigen Contract-Tests. Dies ist der additive neue Wert der Sequenz.
**Quell-Konzepte (autoritativ):**
- `FK-60 §60.4` (`concept/technical-design/60_*.md`) — versionierter KPI-Katalog; §60.4.2-§60.4.11 listen pro Domaene KPI/Status/Datenklasse (`[R]`/`[N]`)/Koernung; §60.4.12 fixiert die Bilanz auf **genau 40 AKTIV** ueber **10 Domaenen**.
- `FK-61 §61.2-§61.12` (`concept/technical-design/61_*.md`) — KPI-Erhebung: pro AKTIV-KPI der Mapping-Vertrag (Source-Event/Payload, Prozesspunkt, `[R]`/`[N]`, Ziel-`fact_*`-Spalte); §61.4.3 Guard-Scratchpad; §61.12.2 angereicherte Payloads (kanonische Wire-Keys `integrity_gate_result.blocked_dimensions`, `are_gate_result.total_requirements`/`covered_requirements`).
- `FK-62 §62.2.1-§62.2.5` — das FK-62-Sollschema, gegen das jede Mapping-Ziel-Spalte fail-closed aufloesbar sein muss (geliefert durch AG3-117).

---

## 1. Kontext / Ist-Zustand (belegt)

Der Katalog ist heute ein bewusster Skeleton; die Typ-Infrastruktur ist fertig, es fehlt die Population:

- `src/agentkit/kpi_analytics/catalog.py:139` `catalog_status: CatalogStatus = CatalogStatus.SKELETON`; `KpiCatalog.__init__` (`:141-142`) registriert **nichts** → **0 von 40 AKTIV-KPIs**. Modul-Docstring (`:1-6`) und Klassen-Docstring (`:126-137`) sagen explizit „skeleton … follow-up story".
- Die Typ-Infrastruktur ist vollstaendig vorhanden: `KpiDefinition` (`catalog.py:95-123`: `kpi_id`/`name`/`decision_question`/`formula_repr`/`granularity`/`collection_point`/`domain`), `KpiGranularity` (`:15-25`: STORY/ENTITY_PERIOD/PERIOD), `KpiDomain` (`:28-65`: genau **10** Domaenen, FK-60-konform — der Docstring `:32-34` korrigiert explizit die fruehere „zwoelf Domaenen"-Annahme), `KpiCollectionPoint` (`:78-92`: `hook_or_event`/`data_available`/`notes`), `CatalogStatus` (`:68-75`: COMPLETE = „All KPIs from FK-60 §60.4 are registered"). → Es fehlt die **Population**, nicht das Modell.
- `register()` (`:144-151`) und `list_definitions()`/`get()` (`:153-170`) existieren; `catalog_status` ist heute ein Klassenattribut (`:139`) und muss beim COMPLETE-Zustand korrekt gefuehrt werden.
- Die Ziel-`fact_*`-Spalten je KPI existieren erst im FK-62-Sollschema **nach AG3-117** — deshalb haengt die fail-closed-Aufloesung (AC3) an AG3-117.
- Bestehender Test, der den Skeleton anpinnt: `tests/unit/kpi_analytics/test_catalog.py` pinnt `CatalogStatus.SKELETON`/Leer-Katalog und muss auf COMPLETE/40 umgestellt werden (beabsichtigter, kein versehentlicher Bruch).

## 2. Scope

### 2.1 In Scope
1. **40 AKTIV-KPIs im `KpiCatalog` registrieren** (FK-60 §60.4.2-§60.4.11), je KPI als `KpiDefinition` mit `kpi_id`/`name`/`decision_question`/`formula_repr`/`granularity`/`collection_point`/`domain`. Die `kpi_id`-Menge ist **exakt** die FK-60-AKTIV-Menge (40 IDs, §2.1.1); keine INVENTAR-KPI wird registriert. `catalog_status` wechselt auf `COMPLETE`, sobald genau diese 40 registriert sind. Der Skeleton-Docstring (`catalog.py:1-6`, `:126-137`) wird durch die reale COMPLETE-Semantik ersetzt.
2. **Vollstaendiger FK-61-Mapping-Vertrag pro AKTIV-KPI** als typisierter, pruefbarer Katalog-Annex (kein zweiter String-Satz): pro KPI Source-Event/Payload, Prozesspunkt, `[R]`/`[N]`-Klasse und **typisierte Ziel-`fact_*`-Spalte** (FK-61 §61.2-§61.11). Modelliert ueber die vorhandenen Felder `collection_point.hook_or_event` (= Source-Event/Payload), `collection_point.data_available` (= `[R]`=True / `[N]`=False), `collection_point.notes` (= Prozesspunkt) plus eine typisierte Ziel-Fact-Spalten-Zuordnung (§2.1.2). Jede Ziel-Spalte MUSS im FK-62-Sollschema (AG3-117) aufloesbar sein — sonst Test rot (FAIL-CLOSED). Der Source-Owner einer KPI ist **genau der von FK-61 §61.2-§61.11 fuer diese KPI benannte** Erhebungspunkt (eine der fuenf FK-61-Quellklassen, §2.1.3); ein pauschaler „AG3-081-EventType/Payload"-Owner fuer alle `[N]`-KPIs ist fachlich falsch und wird **nicht** angenommen.
3. **Contract-Tests** (Erweiterung der AG3-038-Familie, nicht Ersatz): exakte 40-AKTIV-ID-Frozenset-Pruefung (ID-fuer-ID, nicht nur Count); Pro-KPI-Feldvalidierung; Ziel-Spalte-loest-in-FK-62-Schema-auf (fail-closed); Source-Owner-Klassen-Negativtests; P95 bleibt INVENTAR/abwesend.

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

Der Contract-Test pinnt diese Menge als Frozenset und vergleicht ID-fuer-ID gegen den registrierten Katalog (kein blosses Count). Aenderungen an dieser Menge sind nur ueber FK-60 §60.4 zulaessig (Konzept-Aenderung, nicht Code-Realitaet). **Re-Verify-Pflicht:** vor Implementierung die 40 IDs + die 7/5/7/1/7/1/2/2/2/6-Bilanz erneut gegen FK-60 §60.4 abgleichen.

#### 2.1.2 Ziel-Fact-Spalten-Zuordnung (typisiert)
Die Ziel-`fact_*`-Spalte je AKTIV-KPI wird als typisierte Zuordnung gefuehrt (Enum/typed mapping in `kpi_analytics`, ARCH-55-englisch), abgeleitet aus den FK-61-Mapping-Tabellen (§61.2-§61.11, Spalte `→ fact_*`). Beispiele (autoritativ in FK-61): `qa_round_count → fact_story.qa_round_count` (§61.2.1), `llm_call_count_per_story → fact_story.llm_call_count` (§61.3.1), `adversarial_hit_rate → fact_story.adversarial_hit_rate` (§61.6.1), `are_gate_result → fact_story.are_gate_passed` (§61.9.1), `are_evidence_coverage_rate → fact_story.are_total_requirements`/`are_covered_requirements` (§61.9.2), `integrity_gate_block_rate → fact_pipeline_period.integrity_gate_block_count`/`integrity_gate_total_count` (§61.4.2), `phase_time_distribution → fact_story.phase_{setup,exploration,implementation,verify,closure}_ms` (§61.11.2). Jede Zuordnung MUSS gegen das FK-62-Sollschema (AG3-117) aufloesbar sein.

**Konzept-Konflikt + Auflösung (FK-61 ↔ FK-62, verbindlich):** Bei **einer** KPI weicht der von FK-61 genannte Zielspaltenname vom FK-62-Sollschema ab: `prompt_integrity_violation_by_stage` zeigt in FK-61 §61.4.2 (`61_kpi_erhebung_nach_domaenen.md:172`) auf `fact_guard_period.violation_stage_escape_count` / `…schema_count` / `…template_count` (Suffix `_count`), waehrend FK-62 §62.2.2 (`62_kpi_aggregation.md:177-179`) die Spalten **ohne** Suffix fuehrt (`violation_stage_escape` / `violation_stage_schema` / `violation_stage_template`). **Auflösung (gesperrt, konsistent mit AG3-117):** Die **FK-62-Spaltennamen sind autoritativ** fuer die physischen Zielspalten-Identifier (vereinbarte Linie „FK-62 = einzige Namens-/Spalten-Wahrheit"); das FK-61-Mapping dieser Story zielt daher auf die FK-62-Namen **ohne** `_count`-Suffix. Die FK-61-§61.4.2-Namen mit `_count`-Suffix sind eine **Dokumentations-Drift**, die ueber eine **separate, reine Doc-Concept-Reconciliation** an den FK-61-Owner korrigiert wird — FK-61 wird in **dieser** Story NICHT editiert. Das ist explizit hier festgehalten, damit ein Implementer den Mismatch nicht erst als rot werdenden fail-closed-Test (AC3) entdeckt. **Vollstaendiger Divergenz-Scan (alle FK-61 `→ fact_*`-Targets, §61.2-§61.11 `:121-343`, gegen FK-62 §62.2 geprueft):** dies ist die **einzige** Target-Namens-Divergenz; alle uebrigen FK-61-Zielspalten loesen 1:1 ins FK-62-Sollschema auf (die per Ellipse verkuerzten Targets `:291` `...above_threshold`/`...classified_conflict` expandieren prefix-korrekt zu `vectordb_above_threshold`/`vectordb_classified_conflict`, FK-62-konform).

#### 2.1.3 FK-61-Source-Owner-Klassen (kein pauschaler AG3-081-Owner)
FK-61 §61.2-§61.11 ordnet jeder AKTIV-KPI **genau eine** Erhebungsquelle zu. Diese faellt in eine von fuenf Klassen; nur ein Teil ist ein in AG3-081 gebauter EventType/Payload. Der Mapping-Vertrag (§2.1) und der Negativtest (§3 AC4) pruefen je KPI **gegen die laut FK-61 erforderliche Quellklasse**, nicht pauschal gegen AG3-081:
1. **Bestehendes Event** (`[R]`/`[N]`, schon vorhanden) — z. B. `llm_call_count_per_story` (`COUNT(execution_events ... event_type='llm_call')`, §61.3.1), `quorum_trigger_rate` (`review_divergence` „existiert bereits", §61.3.2), `are_gate_result` (`event_type='are_gate_result'`, §61.9.1).
2. **Neues Event** (`[N]`, von AG3-081 gebaut) — z. B. `impact_violation_rate` (`impact_violation_check`, §61.4.2), `vectordb_similarity_threshold_calibration` (`vectordb_search`, §61.8.1), `compaction_count_per_story` (`compaction_event`, §61.2.2). **Diese** Klasse verweist auf AG3-081.
3. **Angereicherte Payload eines bestehenden Events** (`[N]`, von AG3-081 konsolidiert) — z. B. `integrity_gate_block_rate` (`integrity_gate_result.blocked_dimensions[]`, §61.4.2/§61.12.2), `are_evidence_coverage_rate` (`are_gate_result.total_requirements`/`covered_requirements`, §61.9.2/§61.12.2), `prompt_integrity_violation_by_stage` (`integrity_violation.stage`, §61.4.2). **Diese** Klasse verweist auf AG3-081.
4. **Runtime-Metric / Read-Model / Projection** (`[N]`, **kein** neues Event noetig) — z. B. `execution_vs_exploration_ratio` (`runtime.story_metrics.mode`, §61.2.2: „Kein neues Event noetig"), `phase_time_distribution` (`phase_state_projection`, §61.11.2: „Kein neues Event"), `story_predictability` (Varianz aus `story_metrics`, §61.11.2). **Diese** Klasse verweist **nicht** auf einen AG3-081-EventType/-Payload.
5. **Scratchpad-Counter** (`[N]`, bewusst **kein** Event) — `guard_violation_rate_by_guard` (`runtime.guard_invocation_counters`, §61.4.3/§61.12.1: „guard_invocation ist bewusst KEIN Event-Typ"). Source-Owner ist der Scratchpad, nicht ein AG3-081-EventType.

Der Negativtest (§3 AC4) prueft pro KPI: gehoert die KPI laut FK-61 zu Klasse 2 oder 3 und fehlt der zugehoerige AG3-081-EventType/-Payload, ist das ein Fehler; gehoert sie zu Klasse 1/4/5, ist **kein** AG3-081-Event erforderlich und die Pruefung gilt der jeweils benannten FK-61-Quelle. Ein KPI ohne **irgendeine** FK-61-Quelle (`collection_point.hook_or_event` leer) ist immer ein Fehler.

### 2.2 Out of Scope (mit Owner)
- **Fact-Spaltensaetze nach FK-62 (Renames/Adds/Drops, Truth-Locations, Migration)** — **AG3-117** (`depends_on`). Diese Story registriert nur den Katalog/das Mapping und verlaesst sich auf das von AG3-117 gelieferte FK-62-Sollschema als Aufloesungsziel.
- **KPI-Wire-DTO am HTTP-Rand** — **AG3-116**.
- **RefreshWorker / Aggregations-/Fuelllogik** (`sync_analytics`/`_percentile`/Dirty-Sets) — **AG3-082** (`completed`). Diese Story rechnet nichts; sie definiert Katalog + Mapping + Tests.
- **BC14/BC15-EventTypes + angereicherte Payload-Definitionen** — **AG3-081** (die Events/Payloads selbst; hier wird nur darauf verwiesen).
- **P95-Aktivierung** (`response_time_p95_ms` / `llm_response_time_p95` INVENTAR→AKTIV) — eigene zukuenftige Story; hier strikt INVENTAR (keine P95-KPI registriert).

## 3. Akzeptanzkriterien
1. Der `KpiCatalog` registriert **genau** die 40 AKTIV-`kpi_id`s aus §2.1.1 als `KpiDefinition` (Contract-Test vergleicht die exakte ID-Menge als Frozenset, nicht nur den Count); `catalog_status` ist `COMPLETE`; keine INVENTAR-ID ist registriert.
2. Pro registrierter KPI validiert der Contract-Test gegen FK-60 §60.4: nicht-leere `decision_question` (P1), `name` gesetzt, `formula_repr` gesetzt, gueltige `granularity` (FK-60-Koernung), gueltige `domain` (10-Domaenen-Enum), `collection_point.data_available` passend zur FK-60-Datenklasse (`[R]`/`[N]`).
3. **FK-61-Mapping-Vertrag vollstaendig + fail-closed gegen FK-62:** pro AKTIV-KPI traegt der Katalog Source-Event/Payload, Prozesspunkt, `[R]`/`[N]` und eine typisierte Ziel-`fact_*`-Spalte (§2.1.2); der Test prueft fuer alle 40, dass die Ziel-Spalte im FK-62-Sollschema (AG3-117) existiert. Eine im Mapping genannte Ziel-Spalte, die nicht im FK-62-Sollschema existiert, ist ein Fehler (FAIL-CLOSED).
4. **Source-Owner-Klassen-Pruefung (§2.1.3):** der Source-Owner wird je KPI gegen die laut FK-61 §61.2-§61.11 zustaendige Quellklasse geprueft, **nicht** pauschal gegen AG3-081. Negativtest: eine KPI der Klasse 2/3 ohne den zugehoerigen AG3-081-EventType/-Payload schlaegt fehl; eine KPI der Klasse 1/4/5 erfordert keinen AG3-081-Event und wird gegen ihre jeweils benannte FK-61-Quelle geprueft; ein leerer `collection_point.hook_or_event` ist immer ein Fehler; ein `KpiDefinition` mit leerer `decision_question` ist unzulaessig (FK-60 §60.2 P1).
5. Die angereicherten Event-Payload-Ziele sind konsistent mit AG3-081 (kein doppelter Feldname-Satz). Der Test nagelt die kanonischen Wire-Keys fest: `integrity_gate_result.blocked_dimensions`, `are_gate_result.total_requirements`, `are_gate_result.covered_requirements` (FK-61 §61.12.2) und ihre Ziel-Spalten (§2.1.2).
6. `llm_response_time_p50` ist als AKTIV-KPI registriert und mappt auf `fact_pool_period.response_time_p50_ms`; **keine P95-KPI** ist registriert (Test belegt die Abwesenheit; FK-60/§62.2.3 INVENTAR).
7. Die AG3-038-Contract-Test-Familie ist **erweitert** (nicht ersetzt) und gruen; der bestehende `tests/unit/kpi_analytics/test_catalog.py` ist von SKELETON/leer auf COMPLETE/40 umgestellt.
8. Alle neuen KPI-IDs/Feldnamen/Enum-Werte englisch (ARCH-55).
9. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates (GAC-1 conformance); Coverage >= 85 %.

## 4. Definition of Done
- AK 1–9 erfuellt; QA-Gate ist die giftige Codex-Review (alleiniges Code-Gate) **PASS** + die Standard-Pflichtbefehle + Jenkins + Sonar. Vorgesehen fuer Implementierung nach Codex-Spec-Review + User-Go-Ahead.

## 5. Guardrail-Referenzen
- **FAIL CLOSED:** keine KPI ohne FK-61-Source-Owner (§2.1.3); KPIs der Klasse 2/3 ohne den zugehoerigen AG3-081-EventType/-Payload sind Fehler; keine KPI ohne Entscheidungsfrage; keine Mapping-Ziel-Spalte ausserhalb des FK-62-Sollschemas (AG3-117).
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** FK-60 ist die KPI-ID-Wahrheit, FK-61 die Mapping-Wahrheit, FK-62 das Spalten-Sollschema; kein paralleler Definitions-Satz, keine zweite KPI-Wahrheit.
- **TYPISIERT STATT STRINGS:** KPIs als `KpiDefinition`-Instanzen, Mapping als typisierte Ziel-Fact-Spalten-Zuordnung.
- **ZERO DEBT:** der Skeleton wird real auf 40 KPIs gehoben (kein „follow-up"-Docstring mehr); kein TODO-Rest; P95 sauber als INVENTAR ausgewiesen.
- **ARCH-55:** alle KPI-IDs/Feldnamen/Enum-Werte englisch.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Die Typ-Infrastruktur (`catalog.py:15-170`) ist fertig — nur **Population + Status-Wechsel auf COMPLETE** + Ersatz des Skeleton-Docstrings; kein neues Katalog-Modell bauen. Die 40 IDs/Domaenen/Koernungen stehen in §2.1.1 und FK-60 §60.4 (vor Implementierung erneut gegen FK-60 verifizieren).
- Den FK-61-Mapping-Vertrag (Source-Event/Payload + Prozesspunkt + Ziel-Fact-Spalte) je KPI aus FK-61 §61.2-§61.11 ablesen; die Ziel-Spalte als typisierte Zuordnung modellieren (kein loser String-Satz neben dem Katalog).
- Ziel-Spalten muessen gegen das **von AG3-117 gelieferte** FK-62-Sollschema aufloesen (depends_on) — der fail-closed-Test (AC3) ist erst gegen die FK-62-Spalten gruen.
- Feldnamen-Konsolidierung mit AG3-081 (eine ARE-/Integrity-Payload-Wahrheit, kanonische Wire-Keys aus FK-61 §61.12.2).
- P95 NICHT registrieren (INVENTAR). Keine Fuelllogik (AG3-082).
- `tests/unit/kpi_analytics/test_catalog.py` von SKELETON/leer auf COMPLETE/40 umstellen (beabsichtigter Bruch).
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Test-Namen der exakten 40-AKTIV-ID-Pruefung + des fail-closed-Ziel-Spalten-Tests + der Source-Owner-Klassen-Negativtests.

## 7. Vorbedingungen
- **depends_on AG3-117** — die FK-62-Spalten muessen als fail-closed-Aufloesungsziel existieren (AC3). Ohne sie kann der Mapping-Ziel-Spalten-Test nicht gruen werden.
- **unblocks: keine** (additiver Abschluss der Sequenz; AG3-118 ersetzt zusammen mit AG3-116/117 das superseded AG3-083).
- **Cross-cutting (doc-only, nicht hier editieren):** `var/concept-gap-analysis/_STORY_INDEX.md` + AG3-082 `status.yaml` (`unblocks: [AG3-083]`) zeigen die alte 082↔083-Reihenfolge falsch herum; da 082/084 `completed`, ist das nur Bookkeeping — Routing an die Owner als Doc-Bereinigung mit Verweis auf AG3-116/117/118.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
