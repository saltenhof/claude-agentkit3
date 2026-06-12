# AG3-115: Create-Time-Conflict-Adjudicator — LLM-Konfliktbewertung (FK-21 §21.4.1 Schritt 3) im pre-story Create-Scope

**Typ:** Implementation (mit FK-21-Konzept-Klarstellung via Approval-Flow, falls noetig)
**Groesse:** L
**Bounded Context:** `story-creation` (Owner der Anlage-Reconciliation) + Konsum der LLM-Evaluations-/Transport-Mechanik (`verify-system` Kap. 11 `StructuredEvaluator` / FK-65 LLM-Transport). Liefert den **Create-Time-Conflict-Adjudicator** als getypten Port, den AG3-114 verdrahtet.

**Quell-Konzepte (autoritativ):**
- `FK-21 §21.4.1 Schritt 3` — **LLM-Konfliktbewertung** bei Über-Schwellwert-Treffern: `evaluator.evaluate(role="story_creation_review", prompt_template="prompts/vectordb-conflict.md", context={new_story, candidates}, expected_checks=["conflict_assessment"], story_id=…, run_id=…)` → PASS (kein Konflikt) / FAIL (Duplikat/Überschneidung). **Die hier übergebenen `story_id`/`run_id` setzen eine bereits existierende Story voraus — die zur Anlage-Zeit nicht existiert. Diese Spannung ist der Kern dieser Story** (s. §1.1).
- `FK-21 §21.4.2 / §21.4.3` — Abgleich-Protokollierung (`total_hits`/`above_threshold`/`sent_to_llm`/`llm_conflicts`/…); VectorDB ist Pflicht, fail-closed bei Ausfall.
- `Kap. 11` (`StructuredEvaluator`) + `Kap. 13.5` (Zweistufiger VectorDB-Abgleich) — die Evaluator-/Zwei-Stufen-Mechanik.
- `FK-65` — LLM-Transport/Dialogue-Runner (der reale LLM-Aufruf-Pfad).

---

## 1. Ist-Zustand (belegt)

- **Stufe 1 (Similarity-Suche + Schwellenwert) existiert real:** der Reconciler fährt `story_search` + Threshold-Filter (`story_creation/vectordb_reconciliation.py`); AG3-114 ruft `reconcile_only(...)` und produziert die `ReconciliationEvidence`.
- **Stufe 2 (LLM-Konfliktbewertung) hat KEINEN create-time-Owner:** der einzige `StructuredEvaluator` ist **execution-scoped** — sein `PromptRuntimeMaterializer` verlangt eine lebende `StoryContext` (`story_id`, `project_root`), ein Story-Arbeitsverzeichnis und einen aufloesbaren **Run-Pin** (`resolve_run_scope` → non-None `run_id`; `ensure_run_pin`). Zur Anlage-Zeit existiert **nichts davon** (die Story wird gerade erst angelegt). Belegt durch die AG3-114-R1-Investigation + FK-21 §21.4.1 Schritt 3 (das `story_id`/`run_id` übergibt).
- **AG3-114 fail-closet heute auf Stufe 2:** `runtime_factory.FailClosedConflictEvaluator` wirft `ConflictAdjudicationUnavailableError` (→ Wire-Code `conflict_adjudication_unavailable`) für **jeden** Über-Schwellwert-Treffer. No-Conflict-Anlage funktioniert; Konflikt-Anlage ist blockiert, bis dieser Adjudicator existiert.
- **Der Konflikt-Prompt ist konzeptverankert:** `prompts/vectordb-conflict.md` (FK-21 §21.4.1 Schritt 3) ist die Bewertungsvorlage.

### 1.1 Zentrale Spannung + konzepttreue Auflösung (verbindlich)

FK-21 §21.4.1 Schritt 3 übergibt `story_id`/`run_id` an den Evaluator — das passt zum **execution-scoped** `StructuredEvaluator`, **nicht** zum Anlage-Zeitpunkt (pre-story). Die Konfliktbewertung **gatet** die Anlage; sie kann also **nicht** voraussetzen, dass die Story (mit `story_id`/`run_id`/Story-Dir/Run-Pin) bereits existiert. **Auflösung dieser Story:** ein **create-scope** Adjudicator-Pfad, der die LLM-Konfliktbewertung über `{new_story, candidates}` fährt, **ohne** `StoryContext`/`story_id`/`run_id`/Story-Dir/Run-Pin (ephemerer/provisorischer Kontext). Falls FK-21 §21.4.1 Schritt 3 dafür eine **Klarstellung** braucht (create-time evaluator scope ≠ execution-time), ist diese als kleines Konzept-Delta **via Codex-Approval-Flow** zu machen (kein stiller Konzept-Edit) — die Substitutions-/Evaluations-Pflicht bleibt, nur der Scope wird präzisiert.

**Konzept-Konflikt-Check:** Wenn sich beim Bauen zeigt, dass FK-21 / Kap. 11 / Kap. 13.5 den create-time-Pfad **anders** vorsehen (z. B. provisorische ID-Allokation vor der Bewertung), **stoppe und melde** — implementiere keine Abweichung eigenmächtig.

## 2. Scope

### 2.1 In Scope

1. **FK-21-Konzept-Klarstellung (falls noetig, ZUERST, via Approval-Flow):** in FK-21 §21.4.1 Schritt 3 (und ggf. Kap. 11/13.5) den **create-time conflict-assessment scope** präzisieren: die Bewertung läuft pre-story ohne `story_id`/`run_id`/Story-Dir/Run-Pin; der Evaluator-Aufruf an dieser Stelle nutzt einen create-scope/ephemeren Kontext. Ablauf: **Codex absegnen (write=false) → Edit `concept/…` → Codex re-review → GAC-1/Concept-Gates grün.** Nur falls der reale Code-Pfad eine Konzept-Anpassung erzwingt; sonst entfällt dieser Schritt (Begründung im Bericht).
2. **Create-Time-Conflict-Adjudicator (Owner = story-creation, Mechanik-Konsum = verify-system/FK-65):** ein getypter Adjudicator, der
   - die **Über-Schwellwert-Kandidaten** (Top-N, `vectordb.max_llm_candidates`) + die **neue Story-Beschreibung** entgegennimmt,
   - die **LLM-Konfliktbewertung** über `prompts/vectordb-conflict.md` + den realen LLM-Transport (FK-65) fährt,
   - ein getyptes Verdikt **PASS (kein Konflikt)** / **FAIL (Konflikt: Duplikat/Überschneidung)** zurückgibt (FK-21 §21.4.1 Schritt 3),
   - **ohne** `StoryContext`/`story_id`/`run_id`/Story-Dir/Run-Pin auskommt (create-scope; ephemerer Kontext statt execution-scope-Materialisierung).
   Wenn der bestehende `StructuredEvaluator` für einen create-scope-Pfad **parametrisierbar** ist (ohne den execution-scope zu schwächen), wiederverwenden; sonst ein dedizierter create-scope-Evaluator-Pfad, der dieselbe LLM-Transport-Mechanik nutzt (keine zweite LLM-Aufruf-Wahrheit).
3. **Port für AG3-114:** der Adjudicator implementiert genau die Evaluator-Schnittstelle, die AG3-114s `runtime_factory` erwartet (der Slot, den heute `FailClosedConflictEvaluator` belegt), sodass AG3-114 den realen Adjudicator injizieren kann. **Das Verdrahten in AG3-114 ist NICHT Teil dieser Story** (AG3-114-Resume), nur der bereitgestellte, getestete Port.
4. **Protokollierung (FK-21 §21.4.2):** der Abgleich liefert die §21.4.2-Zähler (`total_hits`/`above_threshold`/`sent_to_llm`/`llm_conflicts`/`threshold_used`/`search_mode`) in einer Form, die in die `ReconciliationEvidence`/das Abgleich-Protokoll passt (Owner-treu; kein neues Schatten-Schema).
5. **Fail-closed (FK-21 §21.4.3-Geist, getrennte Ursachen):** LLM-Transport/Adjudicator nicht verfügbar → fail-closed, **mit wahrheitsgemäßem, vom VectorDB-Outage unterscheidbarem Fehler** (nicht `vectordb_unavailable` umdeuten). Kein Dummy-Verdikt, kein „im Zweifel PASS".
6. **Tests (real, kein Stub der Evaluations-Mechanik):** PASS- und FAIL-Verdikt aus realistischen Kandidaten/new_story-Eingaben über den realen Evaluator-/Transport-Pfad (Fake nur an der LLM-Hub-/Modell-Grenze); Konflikt-erkannt-Fall; fail-closed bei LLM-Ausfall; create-scope ohne Story-Kontext (Negativbeweis: kein `story_id`/`run_id`/Run-Pin nötig).

### 2.2 Out of Scope (mit Owner)

- **Verdrahtung in AG3-114** (`runtime_factory` `FailClosedConflictEvaluator` → realer Adjudicator) + AG3-114-DoD/Konflikt-Pfad — **AG3-114-Resume**. Diese Story liefert nur den getesteten Port.
- **Stufe 1 (Similarity-Suche + Threshold)** + `reconcile_only` + `ReconciliationEvidence`-Modell — bestehend (AG3-068/AG3-114). Unverändert konsumiert.
- **Der execution-scoped `StructuredEvaluator`** (QA-/Review-Pfad mit Story-Kontext) — bleibt unangetastet; create-scope darf ihn nicht schwächen.
- **Story-Anlage-Mechanik selbst** (`create_story`/Route/`ProjectEdgeClient`) — AG3-114/Story-Service.
- **AK2 / `.mcp.json` / `resources/skill_bundles/`** — nicht anfassen.

## 3. Akzeptanzkriterien

1. **Konzept-Klarstellung (falls vorgenommen) via Approval-Flow:** FK-21 §21.4.1 Schritt 3 (und ggf. Kap. 11/13.5) präzisieren den create-time conflict-assessment scope (pre-story, kein `story_id`/`run_id`); Codex absegnen → Edit → re-review; GAC-1/Concept-Gates grün. Falls keine Konzept-Anpassung nötig war: explizite Begründung im Bericht.
2. **Adjudicator existiert + ist create-scope:** liefert PASS/FAIL über `{new_story, candidates}` + `prompts/vectordb-conflict.md` + realen LLM-Transport, **ohne** `StoryContext`/`story_id`/`run_id`/Story-Dir/Run-Pin. Test: Aufruf gelingt ohne jeden Story-Kontext.
3. **Verdikt-Korrektheit:** ein klarer Konflikt-Kandidat → FAIL (`conflict_assessment`); kein/aufgelöster Konflikt → PASS. Test je Verdikt aus realistischen Eingaben.
4. **Port-Kompatibilität zu AG3-114:** der Adjudicator implementiert die Evaluator-Schnittstelle, die AG3-114s `runtime_factory` injiziert (denselben Slot wie `FailClosedConflictEvaluator`). Test: Substituierbarkeit gegen die AG3-114-Reconciler-Erwartung (ohne AG3-114 zu verändern).
5. **Protokollierung:** die §21.4.2-Zähler werden owner-treu geliefert (in `ReconciliationEvidence`/Abgleich-Protokoll), kein neues Schatten-Schema. Test.
6. **Fail-closed + wahrheitsgemäßer Fehler:** LLM-Transport-Ausfall → fail-closed mit einem von `vectordb_unavailable` **unterscheidbaren** Fehler; kein Dummy-PASS. Test.
7. **Keine Schwächung des execution-scope-Evaluators:** der bestehende QA-/Review-Evaluator-Pfad bleibt unverändert (Review/Test). Kein zweiter LLM-Aufruf-Pfad neben FK-65.
8. **Pflichtbefehle grün:** scoped pytest (`tests/unit/story_creation`, `tests/unit/verify_system`, `tests/contract`, ggf. `tests/integration/...`, `-n0`) + `pytest --collect-only -q tests` (0 Importfehler) + broad `pytest tests/unit tests/contract -q -n0` (0 failed); `mypy src` (+`--platform linux`); `ruff`; GAC-1; Concept-Gates; Coverage >= 85 %.

## 4. Definition of Done

- AK 1–8 erfüllt; Codex-Review PASS (Codex ist das alleinige Review-Gate).
- AG3-114 wird entblockt: der getestete Create-Time-Conflict-Adjudicator-Port existiert; AG3-114-Resume verdrahtet ihn (`FailClosedConflictEvaluator` → realer Adjudicator) und schließt seine FK-21-§21.4-Zwei-Stufen-Reconciliation + die offenen R2-Findings.
- Commit/Push erst nach grünem Review (Orchestrator-Policy). `.mcp.json` nicht mitcommitten.

## 5. Guardrail-Referenzen

- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** EINE LLM-Aufruf-Mechanik (FK-65); kein zweiter Evaluations-Pfad. Der create-scope-Adjudicator ist die konzepttreue create-time-Variante der FK-21-§21.4.1-Schritt-3-Bewertung, kein Parallel-Pfad.
- **FAIL-CLOSED / NO ERROR BYPASSING:** LLM-Ausfall → fail-closed, wahrheitsgemäßer Fehler (nicht `vectordb_unavailable` umdeuten); kein Dummy-Verdikt, kein „im Zweifel PASS".
- **KONZEPT-APPROVAL:** FK-21-Klarstellung NUR über den Codex-Absegnungs-Flow.
- **TYPISIERT STATT STRINGS:** getyptes Verdikt (PASS/FAIL + `conflict_assessment`), getypter Port; §21.4.2-Zähler getypt.
- **ARCH-55:** englische Bezeichner/Wire-Keys.
- **ZERO DEBT:** nach dieser Story ist die FK-21-§21.4.1-Schritt-3-Bewertung create-time real verfügbar; AG3-114s Konflikt-Pfad nicht mehr dauerhaft fail-closed-blockiert.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Erst die Spannung verstehen (§1.1):** prüfe FK-21 §21.4.1 Schritt 3 + Kap. 11 (`StructuredEvaluator`/`PromptRuntimeMaterializer`) + Kap. 13.5 via die `agentkit3-concepts` MCP. Kläre, ob der bestehende Evaluator für einen create-scope-Pfad parametrisierbar ist (ohne execution-scope zu schwächen) oder ein dedizierter create-scope-Pfad nötig ist. Bei Konzept-Konflikt: STOPP + melden.
- **Konzept-Delta nur falls erzwungen + via Approval-Flow** (Codex absegnen → Edit → re-review). Keine stillen `concept/`-Edits.
- **EINE LLM-Mechanik:** den realen FK-65-Transport/Dialogue-Runner nutzen; den Konflikt-Prompt `prompts/vectordb-conflict.md` verwenden; keinen zweiten LLM-Pfad bauen.
- **Den execution-scoped Evaluator NICHT schwächen** (QA-/Review-Pfad bleibt). Den AG3-114-`runtime_factory`/`create_story`-Pfad NICHT verändern (das ist AG3-114-Resume) — nur den Port bereitstellen, den AG3-114 injizieren kann.
- **Fakes nur an der LLM-Hub-/Modell-Grenze**; Evaluator-/Transport-/Reconciler-Collaborators real.
- AK2 / `.mcp.json` / `skill_bundles/` nicht anfassen. Kein Commit ohne Orchestrator-Auftrag.
- „done" nur mit Beleg: Diff, grüne Pflichtbefehle, Test-Namen (PASS/FAIL-Verdikt, Konflikt-erkannt, create-scope ohne Story-Kontext, Port-Kompatibilität, fail-closed-LLM-Ausfall, §21.4.2-Zähler), ggf. Konzept-Approval-Beleg.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusätzlich gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md`:
- **GAC-1:** `scripts/ci/check_architecture_conformance.py` mit **0 Errors** (`PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`).
- **GAC-2:** Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN); Konflikt = hart stoppen und melden.
