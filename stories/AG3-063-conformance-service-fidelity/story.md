# AG3-063: ConformanceService (4 Fidelity-Ebenen, konsolidierender Einstieg) + Manifest-Index-Consumer + Size-Control

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `verify-system` / Dokumententreue (BC3) — der gemeinsame Conformance-Service, der alle vier Fidelity-Ebenen ueber **eine** `check_fidelity(level, …)`-Funktion bedient, statt verteilter Ad-hoc-Loesungen.
**Quell-Konzepte (autoritativ):**
- `FK-32 §32.1/§32.2` — `ConformanceService` (Subkomponente von VerifySystem, `agentkit.verify_system.conformance_service`) mit vier Fidelity-Ebenen: Zieltreue (`goal`), Entwurfstreue (`design`), Umsetzungstreue (`impl`), Rueckkopplungstreue (`feedback`); exportierte Glossarterme `fidelity-level` (Werte `goal`/`design`/`impl`/`feedback`) und `conformance-verdict` (Werte `PASS`/`PASS_WITH_CONCERNS`/`FAIL`)
- `FK-32 §32.3` — gemeinsames technisches Pattern: ein `check_fidelity` fuer alle vier Ebenen (5 Schritte inkl. **Schritt 5 Telemetrie-Event**, `concept/technical-design/32_dokumententreue_conformance_service.md:123-135`)
- `FK-32 §32.4/§32.4.3/§32.4.4` — Referenzdokument-Identifikation + Manifest-Index; **kuratierte** Datei `_guardrails/manifest-index.json`, **kein automatisches Scanning**, Pflege obliegt dem Menschen (`32_dokumententreue_conformance_service.md:260-271`)
- `FK-32 §32.4b` — 3-Tier-Prompt-Groessenkontrolle (`FILE_UPLOAD_THRESHOLD_BYTES` 50 KB / `HARD_LIMIT_BYTES` 500 KB; Tier 3 ≥ 500 KB → sofortiges FAIL ohne LLM-Aufruf; kein Trunkieren)
- `FK-32 §32.5.3/§32.6.4` — ebenenspezifisches FAIL-Verhalten (Zieltreue-FAIL → Story-Ueberarbeitung; Entwurfstreue-FAIL → ESCALATED)
- `FK-32 §32.10` — Telemetrie: `llm_call`-Event mit `role: doc_fidelity`, `source_component: conformance_service` (`32_dokumententreue_conformance_service.md:518-534`); Integrity-Gate prueft die Anwesenheit je relevanter Ebene
- `formal.conformance.events` — normative Event-Trias `conformance.event.assessment.started` / `conformance.event.level.evaluated` / `conformance.event.assessment.completed` mit Pflicht-Payloads (`concept/formal-spec/conformance/events.md:24-52`); FK-91-API-Event-Namen `conformance_assessment_started`/`conformance_level_evaluated`/`conformance_assessment_completed` (`concept/technical-design/91_api_event_katalog.md:252-254`)

---

## 1. Kontext / Ist-Zustand (belegt)

Es gibt **keinen** gemeinsamen `ConformanceService`; nur zwei der vier Ebenen sind punktuell und verteilt umgesetzt, **nicht** im gemeinsamen `ConformanceService` konsolidiert. Belegt (`var/concept-gap-analysis/gap-fk-26-35.md:282-301`):

- `src/agentkit/verify_system/doc_fidelity/__init__.py` ist eine **leere Datei (0 Bytes / 0 Zeilen)**. Grep `ConformanceService|class.*Conformance|FidelityLevel|check_fidelity` **im Produktionscode unter `src/agentkit/`** → 0 Treffer (`gap-fk-26-35.md:282-283`). **Hinweis zur Praezision:** `FidelityResult` darf nicht naiv repo-weit gegrept werden — ein verwandter, aber anderer Typ `DocFidelityResult` existiert bereits (`src/agentkit/exploration/review/doc_fidelity.py:41`); er ist das Ebene-2-Exploration-Ergebnis, **nicht** der gemeinsame `FidelityResult` aus FK-32 §32.1.
- **Ebene 2 (Entwurfstreue, nach Exploration)** existiert bereits — aber **nicht im gemeinsamen `ConformanceService`**: als Stage 1 des Exploration-Exit-Gates, `DocFidelityChecker.check(change_frame)` (`src/agentkit/exploration/review/doc_fidelity.py:59-119`), produktiv gewired ueber `build_exploration_review` (`src/agentkit/bootstrap/composition_root.py:217-247`, Konstruktion `:242-247`). Stage 1 ruft denselben Layer-2-`StructuredEvaluator` mit Rolle `DOC_FIDELITY` (`doc_fidelity.py:100-105`) und stoppt das Gate bei FAIL hart auf REJECTED (`src/agentkit/exploration/review/review.py:136-147`).
- **Ebene 3 (Umsetzungstreue)** existiert als Layer-2-LLM-Check `doc_fidelity` (`verify_system/llm_evaluator/*`, Rolle `doc_fidelity`; `core_types/qa_artifact_names.py:36/76/89` — `DOC_FIDELITY_FILE`/`DOC_FIDELITY_STAGE`/`DOC_FIDELITY_PRODUCER`).
- **Ebene 4 (Rueckkopplungstreue)** existiert als nicht-blockierender Closure-**Seam**, **nicht** als produktiver Evaluator: das Protocol `DocFidelityFeedbackPort` (`src/agentkit/closure/post_merge_finalization/finalization.py:53-69`) und die produktive Port-Implementierung `ProductiveDocFidelityFeedbackPort` (`src/agentkit/closure/runtime_ports.py:197-218`, gewired `composition_root.py:2165-2175`). Diese Implementierung hat **keinen produktiven Evaluator-Callable**, sondern emittiert pro Lauf einen verpflichtenden **Warning** (`runtime_ports.py:213-218`): der Schritt ist MANDATORY, aber NON-BLOCKING; der produktive Ebene-4-Evaluator (`feedback_fidelity`, FK-38 §38.3.1) ist Eigentum **AG3-067** (siehe Out of Scope).
- **Ebene 1 (Zieltreue, Story-Erstellung)** fehlt vollstaendig.
- **Manifest-Index-Consumer** fehlt: Grep `manifest.index|manifest-index|identify_references` unter `src/agentkit/` → 0 Treffer (`gap-fk-26-35.md:296-301`). Damit fehlt die Quelle der Referenzdokumente fuer alle Ebenen. (Der Index selbst ist eine **kuratierte** Zielprojekt-Datei, keine Runtime-Generierung — FK-32 §32.4.4.)
- **3-Tier-Groessenkontrolle** fehlt: Grep `FILE_UPLOAD_THRESHOLD|HARD_LIMIT_BYTES|conformance.hard_limit` → 0 Treffer. (Abzugrenzen vom Layer-2-`BUNDLE_TOKEN_LIMIT`-Verfahren aus FK-37 — das ist ein anderer Mechanismus, FK-32 §32.4b.5.)
- **Telemetrie/Conformance-Events** fehlen: kein `source_component: conformance_service`-`llm_call`-Event (FK-32 §32.10) und keine Emission der formalen Event-Trias (`formal.conformance.events`).

**Konfliktcheck (Kontext-Sinnhaftigkeit) — NICHT parallel neu bauen, sondern konsolidieren:** Ebene 2 (Exploration-`DocFidelityChecker`), Ebene 3 (Layer-2-`doc_fidelity`-Reviewer) und Ebene 4 (Closure-`DocFidelityFeedbackPort`) sind **bereits gebaut**. Diese Story darf sie **nicht** doppeln oder durch eine zweite Wahrheit ersetzen, sondern muss den gemeinsamen `ConformanceService.check_fidelity(level, …)` so schneiden, dass die vorhandenen Mechaniken **dahinter** konsolidiert werden (gemeinsames Pattern, FK-32 §32.3). Insbesondere darf **kein** zweiter Design-Fidelity-Einstieg neben dem Exploration-Stage-1-Pfad entstehen: der vorhandene `DocFidelityChecker.check()` muss an `ConformanceService.check_fidelity(level=design, …)` delegieren oder durch ihn abgeloest werden, ohne den alten Einstieg parallel zu lassen. Die FK-37/FK-38-Naming-Drift (`VerifyContext`→`QaContext`, `ContextBundle`→`ReviewBundle`) ist bekannt (bc-cut-decisions) und in AG3-101 doc-only; hier keine FK-Prosa aendern. Die 3-Tier-Groessenkontrolle (§32.4b) ist ausdruecklich **getrennt** vom FK-37-Packing (AG3-067) — nicht vermischen.

## 2. Scope

### 2.1 In Scope
1. **`conformance_service`-Modul** unter `verify_system/conformance_service/` (loest den `verify_system/doc_fidelity/__init__.py`-Leerstub ab; kein toter Stub bleibt) mit:
   - `FidelityLevel` (StrEnum, 4 Werte: `goal`/`design`/`impl`/`feedback`, englisch) gem. FK-32 §32.1.
   - `FidelityResult` (Pydantic v2, frozen) inkl. `conformance-verdict`-Feld (Werte `PASS`/`PASS_WITH_CONCERNS`/`FAIL`, englisch).
   - `ConformanceService.check_fidelity(level: FidelityLevel, …) -> FidelityResult` als **ein** gemeinsamer Einstieg fuer alle vier Ebenen (FK-32 §32.3), mit den fuenf Schritten inkl. Telemetrie (In-Scope 6).
2. **Ebene 1 neu implementieren, Ebene 2 konsolidieren**:
   - **Ebene 1 (Zieltreue, `goal`, Story-Erstellung)** ist **neu** als ebenenspezifische Auswertung hinter `check_fidelity` (FK-32 §32.5).
   - **Ebene 2 (Entwurfstreue, `design`, nach Exploration)** wird **konsolidiert**, **nicht** parallel neu gebaut: der vorhandene `DocFidelityChecker.check()` (`exploration/review/doc_fidelity.py:84-119`) wird auf `ConformanceService.check_fidelity(level=design, …)` umgestellt (Delegation oder Abl_oesung), sodass kein zweiter Design-Fidelity-Einstieg bestehen bleibt. Der Exploration-Stage-1-Pfad (`review.py:136-147`) behaelt seine binaere REJECTED-Wirkung; die Auswertungslogik liegt aber hinter `check_fidelity`.
3. **Ebenen 3 + 4 konsolidieren**: die vorhandenen Mechaniken (Layer-2-`doc_fidelity`-Reviewer; Closure-`DocFidelityFeedbackPort`) hinter `check_fidelity(impl/feedback)` einordnen, **ohne** ihre produktive Wirkung zu doppeln (kein zweiter `doc_fidelity`-Reviewer, kein zweiter Feedback-Schreibpfad). Fuer Ebene 4 liefert AG3-063 nur die `check_fidelity(level=feedback)`-Fassade; der produktive `feedback_fidelity`-Evaluator und die post-merge-Mandatory-Rueckkopplung bleiben **AG3-067** (FK-38 §38.3.1). Der heute verpflichtende Warning-Seam (`ProductiveDocFidelityFeedbackPort`, `runtime_ports.py:197-218`) wird **nicht** in dieser Story zum produktiven Evaluator — er bleibt Closure-Seam, bis AG3-067 den Evaluator liefert.
4. **Manifest-Index-Consumer** (FK-32 §32.4/§32.4.3): `identify_references(level, context)` **liest und validiert** den **kuratierten** Index `_guardrails/manifest-index.json` und matcht Referenzdokumente anhand Story-Metadaten (Modul/Typ) + Tags (Matching-Regel §32.4.3). Deterministisch, fail-closed bei fehlendem/kaputtem Index (kein stilles „keine Referenzen"). **Kein Runtime-Schreibpfad waehrend des Assessments** (FK-32 §32.4.4: Index ist kuratiert, Pflege obliegt dem Menschen). Ein optionaler initialer Index-Erzeuger gehoert zum Installer/Admin (Out of Scope, separater Owner) — der ConformanceService ist reiner **read/validate/resolve-Consumer**.
5. **3-Tier-Prompt-Groessenkontrolle** (FK-32 §32.4b): benannte Konstanten `FILE_UPLOAD_THRESHOLD_BYTES = 50 KB`, `HARD_LIMIT_BYTES = 500 KB`; Tier 1 (< 50 KB inline), Tier 2 (50–500 KB Datei-Upload via `merge_paths`, Cleanup im `finally`), Tier 3 (≥ 500 KB) → **sofortiges FAIL ohne LLM-Aufruf, kein Trunkieren**. Schwellwerte konfigurierbar (`conformance.file_upload_threshold`/`conformance.hard_limit`, FK-32 §32.4b.3).
6. **Telemetrie + Conformance-Events** (FK-32 §32.10, `formal.conformance.events`, FK-91 §91): `check_fidelity` Schritt 5 emittiert je Lauf
   - das `llm_call`-Event mit `source_component: conformance_service`, `role: doc_fidelity`, `level`, `status` (FK-32 §32.10 / `32_dokumententreue_conformance_service.md:518-534`), **und**
   - die formale Event-Trias `conformance.event.assessment.started` (Payload `assessment_id`/`level`/`story_id`/`run_id`), `conformance.event.level.evaluated` (`assessment_id`/`level`/`status`/`reason`), `conformance.event.assessment.completed` (`assessment_id`/`level`/`status`/`references_used`) gem. `formal.conformance.events:24-52`, projiziert auf die FK-91-API-Event-Namen `conformance_assessment_started`/`conformance_level_evaluated`/`conformance_assessment_completed` (`91_api_event_katalog.md:252-254`). Tier-3-Blockade emittiert ebenfalls die `level.evaluated`/`completed`-Events mit `status: FAIL`, aber **kein** `llm_call` (kein LLM-Aufruf erfolgt).
7. **Ebenenspezifisches FAIL-Verhalten** (FK-32 §32.5.3/§32.6.4): Zieltreue-FAIL → typisiertes Story-Ueberarbeitungssignal; Entwurfstreue-FAIL → Eskalation (`status: ESCALATED`). Typisiert, kein String-Flag.
8. **Negativpfade** als Tests: jede Ebene FAIL → korrektes ebenenspezifisches Verhalten; Tier-3-Input → FAIL ohne LLM-Aufruf; fehlender/kaputter Manifest-Index → fail-closed; Event-Payload-Contract gegen `formal.conformance.events`.

### 2.2 Out of Scope (mit Owner)
- **Produktiver post-merge `feedback_fidelity`-Evaluator (Ebene 4) + Mandatory-Target-Rueckkopplung, Section-aware Packing / `BUNDLE_TOKEN_LIMIT` / `ContextBundle` / ContextSufficiencyBuilder** — **AG3-067** (FK-37 §37.1-§37.3, FK-38 §38.3/§38.1.4). AG3-063 liefert nur die `check_fidelity(level=feedback)`-Fassade; der Warning-Seam (`runtime_ports.py:197-218`) bleibt unveraendert, bis AG3-067 den Evaluator liefert. §32.4b grenzt die Conformance-Groessenkontrolle ausdruecklich vom FK-37-Packing ab.
- **EvidenceAssembler/BundleManifest** — **AG3-061** (FK-28); der Conformance-Service konsumiert ggf. das Manifest, baut es nicht.
- **Stage-Registry-Eintraege fuer die Conformance-Stages (Trust/Producer/Override)** — **AG3-064** (FK-33). Hier nur der Service, nicht die Stage-Registrierung; insb. die Integrity-Gate-Pruefung, dass je Ebene ein `doc_fidelity`-`llm_call` vorliegt (FK-32 §32.10 / FK-35), bleibt Owner der Verify/Closure-Stage-Welt (AG3-064/Integrity-Gate) — AG3-063 **emittiert** die Events, registriert/prueft sie aber nicht.
- **Initialer Manifest-Index-Erzeuger (Installer/Admin-Indexer)** — Installer/Admin-Owner (AG3-006-Welle Installer). AG3-063 ist read/validate-Consumer der kuratierten Datei, kein Generator.
- **FK-37/FK-38-Prosa-Nachzug (Naming)** — doc-only AG3-101.

## 3. Akzeptanzkriterien
1. `FidelityLevel` hat **genau 4 englische Werte** (`goal`/`design`/`impl`/`feedback`); `FidelityResult` traegt das `conformance-verdict`-Feld (englische Werte `PASS`/`PASS_WITH_CONCERNS`/`FAIL`); `ConformanceService.check_fidelity(level, …)` ist der einzige gemeinsame Einstieg (Test: alle vier Level laufen ueber dieselbe Funktion).
2. Ebene 1 (Zieltreue) ist **neu** real ausgewertet und liefert `FidelityResult` mit `conformance-verdict` (je ein PASS- und ein FAIL-Test); Ebene 2 (Entwurfstreue) liefert ebenfalls real (PASS/FAIL-Test) **ueber `check_fidelity(level=design)`**, nicht ueber einen separaten Einstieg.
3. **Konsolidierung statt zweiter Wahrheit:** Der vorhandene Exploration-`DocFidelityChecker.check()` (`exploration/review/doc_fidelity.py:84-119`) delegiert an `check_fidelity(level=design)` bzw. ist durch ihn abgeloest — es bleibt **kein** paralleler Design-Fidelity-Einstieg (Test/Assertion: Stage 1 des Exploration-Gates fuehrt zu genau einem Auswertungspfad). Ebenen 3 + 4 sind hinter `check_fidelity` eingeordnet, **ohne** die vorhandenen Layer-2-/Closure-Mechaniken zu doppeln (Assertion: kein zweiter `doc_fidelity`-Reviewer, kein zweiter Feedback-Schreibpfad; der Ebene-4-Warning-Seam bleibt AG3-067-Owner).
4. Manifest-Index-Consumer **liest und validiert** Referenzdokumente aus dem **kuratierten** `_guardrails/manifest-index.json` (Matching aus Story-Metadaten + Tags, §32.4.3); fehlender/kaputter Index → fail-closed (zwei Tests). **Kein Runtime-Schreibpfad waehrend des Assessments** (Assertion: `check_fidelity` schreibt den Index nicht).
5. 3-Tier-Groessenkontrolle: < 50 KB inline, 50–500 KB Upload-Pfad (`merge_paths`, Cleanup im `finally`), ≥ 500 KB → **FAIL ohne LLM-Aufruf** und ohne Trunkierung (drei Tests; Tier-3-Test prueft, dass kein LLM-Call erfolgt).
6. Ebenenspezifisches FAIL-Verhalten: Zieltreue-FAIL erzeugt das typisierte Story-Ueberarbeitungssignal, Entwurfstreue-FAIL setzt ESCALATED (zwei Tests, typisiert).
7. **Telemetrie/Events:** `check_fidelity` emittiert je Lauf das `llm_call`-Event (`source_component: conformance_service`, `role: doc_fidelity`, `level`, `status`) **und** die formale Event-Trias `assessment.started`/`level.evaluated`/`assessment.completed` mit den Pflicht-Payloads aus `formal.conformance.events:24-52` (Contract-Test gegen die formale Spec mit exakten Payload-Keys; FK-91-Namen `conformance_assessment_*`). Tier-3-Blockade emittiert `level.evaluated`/`completed` mit `status: FAIL`, aber **kein** `llm_call` (Assertion im Tier-3-Test).
8. `verify_system/doc_fidelity/__init__.py`-Leerstub ist abgeloest bzw. der neue Service ist sauber unter `verify_system/conformance_service/` registriert/exportiert; kein toter Stub bleibt.
9. **Pflichtbefehle gruen:**
   - pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates (`scripts/ci/check_concept_frontmatter.py`, `scripts/ci/compile_formal_specs.py`); Coverage ≥ 85 %.
   - **Remote-Gates** vor „fertig" (`AGENTS.md:31-53`): Jenkins gruen und Sonar-Quality-Gate gruen via `scripts/ci/check_remote_gates.ps1`; strikte Sonar-Metriken `violations=0`, `critical_violations=0`, `security_hotspots=0`. Repo-Zustand nie mit rotem Jenkins/Sonar-Gate hinterlassen.

## 4. Definition of Done
- AK 1–9 erfuellt; giftige Codex-Review PASS; Implementierung/Commit erst nach Execution-Plan-Freigabe; Remote-Gates (Jenkins/Sonar) gruen.

## 5. Guardrail-Referenzen
- **FAIL CLOSED:** Tier-3-Input → FAIL ohne LLM-Call (kein Trunkieren); fehlender/kaputter Manifest-Index → fail-closed; Entwurfstreue-FAIL → ESCALATED.
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** ein `check_fidelity` fuer alle Ebenen (kein viertes Ad-hoc-Muster); vorhandene Ebenen 2/3/4 werden **konsolidiert, nicht dupliziert** (kein zweiter Design-Fidelity-Einstieg, kein zweiter Reviewer/Feedback-Pfad); der **kuratierte** `manifest-index.json` ist der eine Referenzdokument-Owner und wird zur Assessment-Zeit nur gelesen/validiert.
- **TYPISIERT STATT STRINGS:** `FidelityLevel`-Enum, `FidelityResult`-Modell, typisiertes FAIL-Verhalten; Event-Payloads gegen die formale Spec.
- **ARCH-55:** alle Identifier/Enum-Werte/Wire-Keys/Event-Keys/Dateinamen englisch.
- **ZERO DEBT:** alle vier Ebenen real bedient bzw. konsolidiert; keine Ebene als „spaeter"; 3-Tier vollstaendig; Telemetrie real emittiert, nicht angedeutet.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Konsolidieren, nicht doppeln:** Ebene 2 (`exploration/review/doc_fidelity.py:84-119`, gewired `composition_root.py:217-247`), Ebene 3 (`llm_evaluator` `doc_fidelity`-Reviewer, `core_types/qa_artifact_names.py:36/76/89`) und Ebene 4 (`closure/post_merge_finalization/finalization.py:53-69` Protocol + `closure/runtime_ports.py:197-218` Warning-Port) sind **bereits gebaut** — hinter `check_fidelity` konsolidieren, NICHT parallel ersetzen. Der vorhandene Design-Fidelity-Einstieg (`DocFidelityChecker.check()`) muss an `check_fidelity(level=design)` delegieren/abgeloest werden; kein zweiter Einstieg.
- **Ebene 4 nicht ueberziehen:** AG3-063 liefert nur die `check_fidelity(level=feedback)`-Fassade. Der produktive `feedback_fidelity`-Evaluator + Mandatory-Rueckkopplung sind **AG3-067** (FK-38 §38.3.1). Der heute verpflichtende Warning-Seam (`runtime_ports.py:197-218`) bleibt unveraendert. Wenn die Konsolidierung in die post-merge-Mandatory-Rueckkopplung hineinragt: Grenze ziehen und melden, nicht beide Seiten hier bauen.
- **Telemetrie ist Pflichtteil des Cuts:** `check_fidelity` Schritt 5 (FK-32 §32.10) emittiert das `llm_call`-Event **und** die formale Event-Trias (`formal.conformance.events:24-52`); Contract-Test mit exakten Payload-Keys. Die Integrity-Gate-**Pruefung** dieser Events bleibt Owner der Stage/Closure-Welt (AG3-064/Integrity-Gate) — hier nur emittieren.
- **Manifest-Index ist kuratiert:** read/validate/resolve-Consumer, **kein** Runtime-Schreibpfad waehrend des Assessments (FK-32 §32.4.4). Initiale Index-Erzeugung ist Installer/Admin (Out of Scope).
- §32.4b-Groessenkontrolle NICHT mit FK-37-`BUNDLE_TOKEN_LIMIT`/Section-aware-Packing (AG3-067) vermischen — andere Konstanten, anderer Mechanismus (§32.4b.5).
- FK-37/FK-38-Naming-Drift (`VerifyContext`/`ContextBundle`) ist bewusst superseded (bc-cut-decisions); **keine** Konzept-Prosa hier aendern — das ist doc-only AG3-101.
- **Grep-Praezision:** `FidelityResult` nicht repo-weit als „0 Treffer" behaupten — `DocFidelityResult` (`exploration/review/doc_fidelity.py:41`) existiert und ist ein anderer Typ. Suchscope auf `src/agentkit/` + den gemeinsamen `FidelityResult`-Typ praezisieren.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle inkl. Remote-Gates, Testnamen (4 Level ueber denselben Einstieg, Ebene-2-Delegation, Indexer read/validate + fail-closed, 3-Tier inkl. no-LLM-call, Event-Contract, ebenenspezifisches FAIL).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
