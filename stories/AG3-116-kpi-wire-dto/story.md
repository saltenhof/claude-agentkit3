# AG3-116: KPI-Wire-DTO (Anti-Corruption-Layer am KPI-HTTP-Rand)

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** `kpi-and-dashboard` / KPI-API-Rand (BC16) + Frontend-Analytics-Slice (Konsument). Einfuehrung eines stabilen, typisierten **Wire-DTO** am KPI-HTTP-Rand zwischen den internen Fact-Records und der oeffentlichen JSON-Wire-Wahrheit — ein bewusster Anti-Corruption-Layer, damit interne/DB-Umbenennungen nie wieder bis in den Browser durchschlagen.
**Quell-Konzepte (autoritativ):**
- `FK-62 §62.2.1-§62.2.5` (`concept/technical-design/62_kpi_aggregation.md`) — Sollstand-Spaltennamen der fuenf Fact-Tabellen; die FK-62-Namen (`pipeline_mode`, `opened_at`, `closed_at`, `qa_round_count`, `adversarial_findings_count`, `are_gate_passed`, `guard_key`, `pool_key`, `new_incident_count`, `patterns_total_count`, `patterns_with_active_check`) sind die **stabile Wire-Vertragswahrheit** dieser Story.
- `FK-63 §63.4` — KPI-API/Read-Contract (Dimension-Reads + Comparison-Period), an dem die Routen haengen.
- `concept/technical-design/01_systemkontext_und_architekturprinzipien.md` — Trust Boundaries / Seiteneffekte und Mapping an den Raendern (ACL-Prinzip).

---

## 1. Kontext / Ist-Zustand (belegt)

Der KPI-Read-Pfad serialisiert heute die **rohen Pydantic-Fact-Records verbatim** auf die Wire — es gibt **kein DTO, kein Feld-Remapping**:

- `src/agentkit/kpi_analytics/http/routes.py:461` — `"rows": [row.model_dump(mode="json") for row in view.rows]`; Comparison-Rows analog `:469` (`row.model_dump(mode="json") for row in view.comparison_rows`). Die Hilfsmethode `_build_kpi_payload` (`routes.py:445-471`) ist der einzige Serialisierungspunkt; ihr Docstring (`:451-456`) benennt das „dump typed rows to plain dicts here" explizit als HTTP-Edge-Muster.
- Die Rows sind die typisierte Union `DashboardFactRow = FactStory | FactGuardPeriod | FactPoolPeriod | FactPipelinePeriod | FactCorpusPeriod` (`src/agentkit/kpi_analytics/views.py:27`), getragen von `DashboardView.rows`/`.comparison_rows` (`views.py:84-85`).
- Konsequenz: **DB-Spaltenname == Pydantic-Feldname == oeffentlicher Wire-Key == Frontend-Property** in einer ungebrochenen Kette. Beleg fuer das 1:1-Durchschlagen bis in den Browser:
  - Frontend-Wire-Typen spiegeln die Record-Felder exakt: `frontend/prototype/src/foundation/bff/client.ts:251` `WireFactStory` (u. a. `story_mode:256`, `started_at:257`, `qa_rounds:259`, `adversarial_findings:262`, `are_gate_status:269`, `agentkit_version:270`, `agentkit_commit:271`), `WireFactGuardPeriod:275` (`guard_id:277`, `period_end:279`), `WireFactPoolPeriod:285` (`llm_role:287`, `period_end:289`, `token_input_total:291`), `WireFactPipelinePeriod:297` (`period_end:300`, `stories_completed:301`, `avg_qa_rounds:303`), `WireFactCorpusPeriod:308` (`period_end:311`, `incidents_recorded:312`, `patterns_promoted:313`, `checks_approved:314`); Union `WireFactRow:319-323`.
  - Direkte UI-Bindings auf dieselben Keys: `frontend/prototype/src/contexts/kpi_analytics/AnalyticsSlot.tsx:139` (`r.qa_rounds`), `:145` (`r.adversarial_findings`), `:174` (`r.started_at`), `:733-735` (`r.incidents_recorded`/`r.patterns_promoted`/`r.checks_approved`), `:782-785` (`r.guard_id`), `:813-816` (`r.llm_role`), `:819` (`r.token_input_total + r.token_output_total`), `:849` (`r.stories_completed`), `:852` (`r.stories_escalated`). Fixtures pinnen dieselben Keys, u. a. `__tests__/realShapes.fixture.ts:286` (`stories_escalated`).
- **Das ist das architektonische Anti-Pattern**: kein Anti-Corruption-Layer am Trust-Boundary-Rand. Eine reine DB-/Record-Umbenennung (wie sie FK-62 fuer AG3-117 vorsieht) leckt heute ungebremst bis in den Browser — die Wire-Contract-Aenderung ist „hard-to-reverse", weil sie zwei bereits ausgelieferte, gruene Stories (AG3-084 API, AG3-094 Frontend) trifft.
- Es gibt bereits ein etabliertes DTO-Muster am selben Rand: `_handle_design_tokens` (`routes.py:473-484`) serialisiert den typisierten `DesignSystem`-Owner ueber ein eigenes typisiertes Modell (`DesignTokens`, `views.py`) — nicht roh aus der Domaene. Dieselbe Disziplin fehlt den Fact-Rows.

## 2. Scope

### 2.1 In Scope
1. **Typisiertes Wire-DTO je Fact-Dimension** in `kpi_analytics` (ARCH-55-englisch): ein bewusster, versionierbarer Wire-Vertrag (z. B. `WireKpiStoryRow`/`WireKpiGuardRow`/`WireKpiPoolRow`/`WireKpiPipelineRow`/`WireKpiCorpusRow` als typisierte Pydantic-Modelle), der die internen Fact-Records (`DashboardFactRow`-Union, `views.py:27`) auf den stabilen Wire-Vertrag abbildet. Das DTO ist die **einzige** Quelle der Wire-Keys; die rohen Records verlassen den Prozess nicht mehr.
2. **Bewusstes Mapping (kein roher `model_dump`)** in `_build_kpi_payload` (`routes.py:445-471`): sowohl `rows` (`:461`) als auch `comparison_rows` (`:469`) werden ueber das DTO-Mapping erzeugt. Das Mapping ist eine deklarative, getestete Zuordnung interner Feldname → stabiler Wire-Key.
3. **Wire-Vertrag = FK-62-benannte Projektion der HEUTE verfuegbaren Felder je Dimension (Entscheidung gesperrt).** Der Wire exponiert pro Dimension genau die **FK-62-Namen derjenigen Felder, die in den heutigen Fact-Records bereits existieren** — also die FK-62-Umbenennungen der vorhandenen Spalten plus die unveraenderten vorhandenen Spalten: `pipeline_mode`, `opened_at`, `closed_at`, `qa_round_count`, `adversarial_findings_count`, `are_gate_passed`, `guard_key`, `pool_key`, `story_count_closed`, `qa_round_avg`, `new_incident_count`, `patterns_total_count`, `patterns_with_active_check`, sowie unveraenderte Bestandsspalten (`invocation_count`, `violation_count`, `call_count`, `period_start`, …). Das DTO bildet die **heutigen** internen Feldnamen (`story_mode`, `started_at`, `completed_at`, `qa_rounds`, `adversarial_findings`, `are_gate_status`, `guard_id`, `llm_role`, `incidents_recorded`, `patterns_promoted`, `checks_approved`, `stories_completed`→`story_count_closed`, `avg_qa_rounds`→`qa_round_avg`) **jetzt** auf diese FK-62-Wire-Keys ab — damit ist diese Story lieferbar **vor** der Schema-Umbenennung (AG3-117), und nach AG3-117 wird das Mapping zur Identitaet. **Abgrenzung (kein Widerspruch):** Die ~54 erst durch AG3-117 angelegten und durch AG3-082 befuellten NEUEN FK-62-Spalten (z. B. `story_count`, `period_grain`, `processing_time_ms`, `integrity_gate_block_count`, …) sind zum AG3-116-Zeitpunkt **NICHT** auf der Wire — es gibt heute keine Quell-Record-Felder dafuer. Sie treten dem Wire-Vertrag bei, sobald sie real produziert werden (inkrementelle DTO-Erweiterung in/nach AG3-117, nicht diese Story). AG3-116 exponiert also den **heute aufloesbaren** FK-62-benannten Teilsatz, nicht den vollen FK-62-Sollsatz.
4. **Felder, die FK-62 fallen laesst, werden NICHT auf der Wire exponiert (sauberer Schnitt jetzt, kein Uebergangsballast).** Die Felder ohne FK-62-Aequivalent — `token_input_total`, `token_output_total`, `avg_latency_ms`, `agentkit_version`, `agentkit_commit`, `period_end`, `stories_escalated` — erscheinen **nicht** im DTO/auf der Wire. Damit die ausgelieferte UI dabei nicht bricht, wird in **dieser** Story jede UI-Abhaengigkeit auf diese to-be-dropped-Felder entfernt:
   - **Gerenderte Drops (UI-Logikaenderung noetig):** `AnalyticsSlot.tsx:819` rendert die Pool-Metrik „Tokens" aus `r.token_input_total + r.token_output_total` — FK-62 `fact_pool_period` hat **keine** Token-Spalten; die Token-Metrik wird aus dem Pool-Panel entfernt (FK-62 bietet `call_count` als Pool-Metrik). `AnalyticsSlot.tsx:852` rendert „eskaliert" aus `r.stories_escalated` — FK-62 `fact_pipeline_period` hat **kein** `stories_escalated`; die „eskaliert"-Metrik wird aus dem Pipeline-Panel entfernt. (`AnalyticsSlot.tsx:849` `r.stories_completed` bleibt — es ist der **semantische Rename** `stories_completed → story_count_closed`, also Umbenennung des gelesenen Keys, kein Drop.)
   - **Nicht gerenderte Drops (nur Typ-Bereinigung):** `agentkit_version`/`agentkit_commit` (`WireFactStory:270-271`), `avg_latency_ms` (`WireFactPoolPeriod:293`), `period_end` (`WireFactGuardPeriod:279`/`WireFactPoolPeriod:289`/`WireFactPipelinePeriod:300`/`WireFactCorpusPeriod:311`), `avg_phase_implementation_ms` (`WireFactPipelinePeriod:304`) werden in keiner UI-Bindung gerendert (Grep belegt: nur in den Typdefinitionen) und entfallen ersatzlos aus den `WireFact*`-Typen.
   So liest die UI nach AG3-116 ausschliesslich FK-62-geformte Keys, und AG3-117 kann das Frontend wahrheitsgemaess unangetastet lassen.
5. **Frontend-Konsum auf den DTO-Vertrag umstellen**: `client.ts` `WireFact*`-Typen (`:251-323`) und `AnalyticsSlot.tsx`-Bindings (siehe §1) lesen ausschliesslich die FK-62-geformten DTO-Wire-Keys; die unter §2.1.4 gelisteten gedroppten Felder werden aus `WireFact*` und den UI-Bindungen entfernt. Keine zweite Frontend-Wire-Wahrheit; die TS-Typen spiegeln genau den DTO-Vertrag.
6. **Diese Story aendert KEINE DB-Spalte und KEIN Fact-Record-Feld** — ausschliesslich das HTTP-Edge-Mapping (Backend) + den Frontend-Konsum. `fact_store/models.py`, die DDLs und die `fact_repository.py`-Mapper bleiben unangetastet (das ist AG3-117).
7. **Versionierungs-/Stabilitaetsnotiz**: der DTO-Vertrag wird per Contract-Test festgenagelt, sodass ein kuenftiger interner Rename (AG3-117) den Wire-Vertrag **nicht** veraendert (das DTO-Mapping wird dort zur Identitaet, siehe AG3-117 §2.1).

### 2.2 Out of Scope (mit Owner)
- **Fact-Spalten-Reconciliation nach FK-62 (Renames/Adds/Drops, alle Truth-Locations, Backend-Reader)** — **AG3-117** (`unblocks` dieser Story). Diese Story bereitet den Schutzschild (DTO) vor; AG3-117 fuehrt die internen Renames durch, ohne den Wire-Vertrag zu beruehren.
- **KPI-Katalog-Population (40 KPIs) + FK-61-Mapping** — **AG3-118**.
- **Neue KPI-Felder/Spalten, P95-Aktivierung, Aggregations-/Fuelllogik** — **AG3-117/AG3-118 bzw. AG3-082** (bereits `completed`). Keine neuen Wire-Felder ueber den heutigen Bestand hinaus.
- **`/api/live/stories` / SSE-Pfad** — unveraendert (AG3-094, `completed`); diese Story beruehrt nur den Fact-Dimension-Read-Payload.

## 3. Akzeptanzkriterien
1. Der KPI-Dimension-Read-Payload (`rows` **und** `comparison_rows`) wird ausschliesslich vom typisierten Wire-DTO erzeugt; in `routes.py:461`/`:469` steht **kein** roher `row.model_dump(mode="json")` der Fact-Records mehr (Struktur-/Code-Test belegt das Mapping; das DesignTokens-Edge-Muster bleibt unberuehrt).
2. Ein **Contract-Test** nagelt die stabilen Wire-Keys je Dimension fest (die FK-62-benannte Projektion der **heute verfuegbaren** Felder als Vertragswahrheit; die erst durch AG3-117/AG3-082 entstehenden neuen FK-62-Spalten sind hier noch **nicht** Teil des Vertrags): `fact_story`-Dimension traegt `pipeline_mode`/`opened_at`/`closed_at`/`qa_round_count`/`adversarial_findings_count`/`are_gate_passed` usw.; `guards`→`guard_key`, `pools`→`pool_key`, `corpus`→`new_incident_count`/`patterns_total_count`/`patterns_with_active_check`. Der Test prueft die **exakte** Key-Menge je Dimension (nicht nur Praesenz) — exakt = der heute aufloesbare FK-62-benannte Teilsatz — und belegt insbesondere, dass die FK-62-gedroppten Felder (`token_input_total`/`token_output_total`/`avg_latency_ms`/`agentkit_version`/`agentkit_commit`/`period_end`/`stories_escalated`) **nicht** im Wire-Vertrag vorkommen.
3. Das DTO mappt die **heutigen** internen Record-Feldnamen korrekt auf die FK-62-Wire-Keys (Unit-Test: ein `FactStory(story_mode=..., started_at=..., are_gate_status=...)` ergibt einen DTO mit `pipeline_mode`/`opened_at`/`are_gate_passed`); das Mapping ist deklarativ und vollstaendig (jedes wire-sichtbare FK-62-Feld hat genau einen Quell-Record-Feldnamen; die FK-62-gedroppten Record-Felder werden bewusst **nicht** durchgereicht).
4. Das Frontend konsumiert ausschliesslich die FK-62-geformten DTO-Wire-Keys: `client.ts` `WireFact*` und `AnalyticsSlot.tsx`-Bindings sind auf die neuen Keys umgestellt, **und** jede Abhaengigkeit auf die FK-62-gedroppten Felder ist entfernt (Pool-„Tokens"-Metrik `AnalyticsSlot.tsx:819` und Pipeline-„eskaliert"-Metrik `:852` entfallen; die nicht gerenderten gedroppten Felder verschwinden aus `WireFact*`). Frontend-Build + Frontend-Tests/Fixtures (inkl. der KPI-Shape-/View-Tests) gruen.
5. **End-to-End gegen echtes Backend (Frontend-Abnahme-Haertekriterium, analog AG3-094):** Die Analytics-Dimensionen rendern weiterhin gegen die **reale** AG3-084-KPI-Surface ueber den neuen DTO-Vertrag — belegt durch einen echten End-to-End-Lauf ohne Stub an der Backend-/BFF-/DB-Grenze (Muster: `frontend/prototype/src/__tests__/e2e/realBackend.test.ts`). Kein „DTO gebaut, aber nicht verdrahtet".
6. **Keine zweite Wahrheit / kein Drift:** Es existiert genau ein Wire-Vertrag (DTO); die Frontend-TS-Typen spiegeln ihn 1:1 (ein Mismatch FE↔DTO ist Test rot). Die internen Fact-Records bleiben unveraendert (Diff zeigt keine Aenderung an `fact_store/models.py`/DDLs/Mappern).
7. Alle neuen Wire-Keys/DTO-Feldnamen/Typbezeichner englisch (ARCH-55).
8. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage >= 85 %. Zusaetzlich (Frontend-TS): Build + Frontend-Test-/Lint-Lauf gruen.

## 4. Definition of Done
- AK 1–8 erfuellt; QA-Gate ist die giftige Codex-Review (alleiniges Code-Gate) **PASS** + die Standard-Pflichtbefehle + Jenkins + Sonar. Diese Story ist fuer Implementierung nach Codex-Spec-Review + User-Go-Ahead vorgesehen (kein reines „nur autorisiert/reviewt").
- Hinweis (autorisiert durch User): diese Story **oeffnet bewusst** AG3-084-Eigentum (`http/routes.py`) und den AG3-094-Frontend-Pfad (`client.ts`, `AnalyticsSlot.tsx`) — die Cross-Story-Edits sind fuer AG3-116 freigegeben.

## 5. Guardrail-Referenzen
- **FIX THE MODEL / Anti-Corruption-Layer:** der Trust-Boundary-Rand bekommt ein bewusstes Mapping; DB-/Record-Wahrheit und oeffentliche Wire-Wahrheit werden entkoppelt (Architekturprinzip FK-01). Kein roher Domaenen-Dump mehr auf die Wire.
- **SINGLE SOURCE OF TRUTH:** genau ein Wire-Vertrag (DTO); das Frontend haelt keine zweite Wire-Wahrheit, sondern spiegelt das DTO.
- **TYPISIERT STATT STRINGS:** DTO als typisierte Pydantic-Modelle, nicht als ad-hoc dicts; Wire-Keys per Contract-Test gepinnt.
- **ZERO DEBT / FAIL-CLOSED:** kein stiller Drop — die FK-62-gedroppten Felder werden in **dieser** Story sauber aus Wire **und** UI entfernt (statt sie als Uebergangsballast mitzuschleppen), sodass die ausgelieferte UI nicht durch ein spaeteres `undefined` bricht; ein FE↔DTO-Mismatch ist Test rot, nicht stilles `undefined`.
- **ARCH-55:** alle Wire-Keys/DTO-Feldnamen englisch; deutsche UI-Label bleiben Lokalisierung.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Der einzige Serialisierungspunkt ist `_build_kpi_payload` (`routes.py:445-471`). Beide Listen (`rows:461`, `comparison_rows:469`) ueber das DTO-Mapping fuehren; das DesignTokens-Edge (`routes.py:473-484`) ist bereits korrekt und bleibt unangetastet.
- Wire-Vertrag = **FK-62-benannte Projektion der heute verfuegbaren Felder je Dimension** (gesperrte Entscheidung). Das DTO mappt die heutigen Record-Felder (`fact_store/models.py:25-120`) jetzt auf die FK-62-Keys; **keine** DB-/Record-Aenderung in dieser Story (das ist AG3-117). Die erst durch AG3-117/AG3-082 entstehenden neuen FK-62-Spalten sind zum 116-Zeitpunkt **nicht** auf der Wire (keine Quelle) und kommen inkrementell hinzu, sobald produziert. So bleibt die Story vor dem Rename lieferbar.
- FK-62-gedroppte Felder (`token_input_total`/`token_output_total`/`avg_latency_ms`/`agentkit_version`/`agentkit_commit`/`period_end`/`stories_escalated`) **nicht** auf die Wire legen. Die UI von diesen Feldern entkoppeln: gerenderte Drops `AnalyticsSlot.tsx:819` (Pool-„Tokens" entfernen) und `:852` (Pipeline-„eskaliert" entfernen); nicht gerenderte Drops nur aus den `WireFact*`-Typen streichen. **Achtung Rename, kein Drop:** `stories_completed`→`story_count_closed` (`AnalyticsSlot.tsx:849`) und `avg_qa_rounds`→`qa_round_avg` bleiben als umbenannte Keys erhalten.
- Frontend: `client.ts` `WireFact*` (`:251-323`) + `AnalyticsSlot.tsx`-Bindings auf die DTO-Keys umstellen; FE-Tests/Fixtures (`__tests__/realShapes.fixture.ts`, `views.test.tsx`, `e2e/kpiSse.test.ts`, `e2e/realBackend.test.ts`) mitziehen.
- E2E-Abnahme gegen echtes Backend (Muster `__tests__/e2e/realBackend.test.ts`), kein Mock an der Backend-/DB-Grenze.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Frontend-Build/-Tests, Test-Namen des Wire-Key-Contract-Tests + des Real-Backend-E2E.

## 7. Vorbedingungen
- **depends_on AG3-084** (`completed` 2026-06-15) — die fuenf KPI-Read-Endpoints (`GET /v1/projects/{key}/kpi/{stories|guards|pools|pipeline|corpus}`) und `_build_kpi_payload` existieren und sind der Edit-Punkt dieser Story.
- **unblocks AG3-117** — die Fact-Spalten-Reconciliation laeuft erst, wenn das DTO den Wire-Vertrag schuetzt; danach wird das DTO-Mapping fuer die umbenannten Keys zur Identitaet.
- **Cross-cutting (doc-only, nicht hier editieren):** `var/concept-gap-analysis/_STORY_INDEX.md` und die AG3-082-Metadaten (`stories/AG3-082-kpi-refresh-worker/status.yaml:11-12` `unblocks: [AG3-083]`) zeigen die alte 082↔083-Reihenfolge falsch herum. Da AG3-082/084 bereits `completed` sind, ist das nur noch Bookkeeping — Routing an die jeweiligen Owner als reine Doc-Bereinigung, mit Verweis auf die neuen IDs (AG3-116/117/118 ersetzen das superseded AG3-083).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
