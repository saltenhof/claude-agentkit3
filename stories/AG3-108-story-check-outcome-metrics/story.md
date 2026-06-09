# AG3-108: Per-Check-Outcome-Read-Model (verify-system-emittiert) + Telemetrie-Filter + Closure-Aggregation

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** **`verify-system`** (Owner + Emitter der Per-Check-Outcome-Wahrheit zur QA-Zeit; FK-69/FK-33 owns die QA-Read-Models) + **`telemetry-and-events`** (`ProjectionFilter`/`read_projection`, `ProjectionKind`) + **`story-closure`** (nur **Aggregation**, kein Erzeuger) + Konzept **FK-69** (Read-Model-Definition via Approval-Flow).
**Quell-Konzepte (autoritativ):**
- `FK-69` — QA-Telemetrie-Read-Models; QA-Read-Models (`qa_stage_results`/`qa_findings`) werden von **verify-system** geschrieben, nur `story_metrics` von closure (`69_qa_telemetrie_aggregation_dashboard.md:177`). **Hier neu zu definieren:** ein Per-Check-Outcome-Read-Model.
- `FK-33` — `QaStageResult`/`QaFinding`/`StageDefinition`-Schemas gehoeren verify-system (`33_…:133`).
- Herkunft: D6-Entscheidung (PO 2026-06-09) + Codex-Review `job-74f78cbe` (CHANGES): die closure-zentrierte Erstfassung lag auf drei falschen Annahmen — neu geschnitten.

> **Korrektur-Historie (Review job-74f78cbe):** (1) FK-69 §69.8 definiert **kein** Per-Check-Read-Model (nur run-level `story_metrics`); (2) `fc_check_proposals.check_id` (`CHK-NNNN`, Vorschlaege) ist der **falsche** Identifier — ausgefuehrte Checks tragen `check_id`/`stage_id` (`artifact.protocol`, `qa_review`, `ac_fulfilled`, `impl_fidelity`); (3) Per-Check-Outcomes liegen zur Closure-Zeit **nicht** vor (clean/PASS + Override-Bezug werden nicht persistiert). **Owner ist verify-system, nicht closure.**

---

## 1. Kontext / Ist-Zustand (belegt)
- **FK-69 definiert run-level `story_metrics`, kein Per-Check-Read-Model** (`69_…:299/306-338`). `ProjectionKind` = genau die FK-69-Tabellen (`telemetry/projection_accessor.py:56`); ein Per-Check-Kind existiert nicht.
- **QA-Read-Models gehoeren verify-system:** `qa_stage_results`/`qa_findings` werden von verify-system geschrieben (FK-69:177, FK-33:133); nur `story_metrics` von closure. Die Per-Check-Outcome-Wahrheit gehoert damit zu verify-system, nicht closure.
- **Clean/PASS-Checks werden NICHT persistiert:** `qa_findings` haelt nur Findings, Status hart `REPORTED` (`verify_system/qa_read_models.py:79`); Policy-Layer-Artefakte serialisieren nur `findings`+Metadaten (`policy_engine/projections.py:38`); der LLM-Evaluator aggregiert volle Antworten zu Findings+Hash und **verwirft PASS-Checks** aus dem Laufzeitmodell (`llm_evaluator/structured_evaluator.py:448`). => „clean" ist heute nicht ableitbar.
- **Overrides tragen keinen Check-Bezug:** `OverrideRecord` hat `target_node_id`/`override_type`/Actor/reason/Timestamps, aber **kein** `check_id`/`check_ref` (`phase_state_store/models.py:58`). => „overridden pro Check" ist heute nicht bestimmbar.
- **Ausgefuehrte Checks identifizieren sich ueber `check_id`/`stage_id`** (`verify_system/stage_registry/data.py:67`, `llm_evaluator/structured_evaluator.py:143`), z. B. `artifact.protocol`/`branch.story`/`qa_review`/`ac_fulfilled`/`impl_fidelity` — **nicht** ueber `fc_check_proposals.check_id` (das sind `CHK-NNNN`-Vorschlaege, CheckFactory nicht gebaut, `failure_corpus/check_proposal.py:92`, `top.py:159`).
- **`ProjectionFilter`** hat kein `check_id`/`since_days` (`telemetry/projection_accessor.py:120-140`). **`report_effectiveness`** = `NotImplementedError` (Konsument, AG3-078).

## 2. Scope

### 2.1 In Scope
1. **FK-69-Konzept-Eintrag (Approval-Flow, ZUERST):** in FK-69 ein **Per-Check-Outcome-Read-Model** definieren (z. B. `qa_check_outcomes`), **Owner verify-system**: Key `(project_key, run_id, check_id)` (+ `story_id`, `attempt_no`/`stage_id` soweit sinnvoll), Outcome-Enum **triggered | clean | overridden**, `occurred_at` (UTC), optional `check_proposal_ref` (FK auf `fc_check_proposals.check_id` **nur**, wenn der Check tatsaechlich aus einem Proposal stammt), Override-Korrelation. Ablauf strikt: **Codex absegnen (write=false) → Edit `concept/…` → Codex re-review → GAC-1/Concept-Gates grün.** Erst danach Code.
2. **verify-system emittiert das Per-Check-Ergebnis zur QA-Zeit:** fuer **jeden ausgefuehrten Check** (nicht nur Findings) eine Zeile mit `check_id` + `status` (triggered = Finding erzeugt / clean = PASS / overridden = per Override aufgehoben) + `occurred_at`. **PASS/clean-Checks werden persistiert** (heute verworfen). `check_id` = ausgefuehrter Check (`stage_id`/Finding-`check_id`), NICHT `fc_check_proposals`.
3. **Override→Check-Korrelation:** der Override-Pfad bekommt einen `check_id`-Bezug (am `OverrideRecord` oder ueber eine Korrelations-Zeile), damit „overridden" deterministisch pro Check bestimmbar ist.
4. **Read-Model-Schema in BEIDEN Stores** (`sqlite_store.py` + `postgres_schema.sql`/`postgres_store.py`) + `ProjectionKind`-Registrierung + typisierter Record/Payload + `SCHEMA_VERSION`-Bump; Contract/Golden-Tests.
5. **`ProjectionFilter` erweitern (telemetry):** `check_id: str | None` + `since_days: int | None`; `read_projection` filtert deterministisch (Gleichheit `check_id`; `since_days` als UTC-Zeitfenster `occurred_at >= now - since_days`). Welche Zeitspalte gilt, ist pro Projektion eindeutig (hier `occurred_at`).
6. **closure aggregiert nur:** falls closure-seitige Roll-ups noetig sind, lesen sie das verify-system-Read-Model; closure **erzeugt** keine Per-Check-Wahrheit (keine Rekonstruktion aus Aggregaten).
7. **Tests:** Emission je Outcome (triggered/clean/overridden) aus realistischen QA-Run-Artefakten; clean/PASS wird persistiert; Override→check_id-Korrelation; Schema-Roundtrip beide Stores; `ProjectionFilter.check_id`/`since_days` (inkl. Fenster-Grenzfall, Zeit injizierbar); Invariante (jede Zeile hat gueltigen `check_id`); fail-closed bei fehlendem `project_key`.

### 2.2 Out of Scope (mit Owner)
- **Lern-/Auswertungslogik** (`report_effectiveness`, Pattern-Promotion/Check-Ableitung **auf Basis** dieser Daten) — **AG3-078**. Diese Story liefert nur das Daten-Substrat.
- **CheckFactory / `fc_check_proposals`-Befuellung** (`CHK-NNNN`) — AG3-078; hier nur optionaler `check_proposal_ref`.
- **KPI-/Dashboard-Sichten** ueber die Check-Outcomes — KPI-Welle (FK-63/FK-72).
- **Skill-/Experiment-Attribution** — AG3-081/083/AG3-095-Umfeld.

## 3. Akzeptanzkriterien
1. **FK-69 definiert** das Per-Check-Outcome-Read-Model (Owner verify-system, Key/Outcome-Enum/`occurred_at`/optional `check_proposal_ref`); der Konzept-Eintrag ist via Approval-Flow (Codex absegnen → Edit → re-review) erfolgt, GAC-1/Concept-Gates grün.
2. verify-system emittiert zur QA-Zeit fuer **jeden** ausgefuehrten Check eine Outcome-Zeile (triggered/clean/overridden) mit `check_id` + `occurred_at`; clean/PASS wird persistiert (Test mit realistischen QA-Run-Artefakten je Outcome).
3. `check_id` ist der **ausgefuehrte** Check (`stage_id`/Finding-`check_id`), nicht `fc_check_proposals.check_id`; `check_proposal_ref` ist optional und nur gesetzt, wenn der Check aus einem Proposal stammt (Test/Review).
4. Override→Check-Korrelation: ein per Override aufgehobener Check ist deterministisch als `overridden` mit korrektem `check_id` erkennbar (Test).
5. Read-Model existiert in **beiden** Stores; Insert/Read-Roundtrip; `ProjectionKind` registriert; `SCHEMA_VERSION` gebumpt; Contract/Golden gezogen.
6. `ProjectionFilter.check_id`/`since_days` filtern deterministisch (Test: `check_id`-Gleichheit; `since_days`-UTC-Fenster inkl. Grenzfall; Zeit injizierbar; negatives/0 definiert).
7. closure erzeugt keine Per-Check-Wahrheit (Review/Architektur-Assertion: closure liest nur, schreibt das Read-Model nicht).
8. ARCH-55; Invariante gueltiger `check_id`; fail-closed bei fehlendem `project_key`.
9. **Pflichtbefehle gruen:** scoped pytest (`tests/unit/verify_system`, `tests/unit/telemetry`, `tests/unit/state_backend`, `tests/unit/closure`, `tests/contract`, `-n0`) + `pytest --collect-only -q tests` (0 Importfehler) + broad `pytest tests/unit tests/contract -q -n0` (0 failed); `mypy src` (+`--platform linux`); `ruff`; GAC-1; Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–9 erfuellt; Codex-Review PASS; Konzept-Eintrag (AK1) via Approval-Flow; Commit auf `main` erst nach explizitem PO-Go.

## 5. Guardrail-Referenzen
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** Per-Check-Outcome-Wahrheit liegt beim **Erzeuger verify-system** (der die Checks ausfuehrt), nicht bei closure — keine zweite Wahrheit, keine Aggregat-Rekonstruktion.
- **TYPISIERT STATT STRINGS:** Outcome-Enum (triggered/clean/overridden); `check_id` als ausgefuehrter-Check-Identifier; `check_proposal_ref` getrennt + optional.
- **FAIL-CLOSED:** fehlender `project_key` → Fehler; clean/overridden werden **erfasst**, nicht geraten.
- **KONZEPT-APPROVAL:** FK-69-Read-Model-Definition NUR ueber den Codex-Absegnungs-Flow (kein stiller Konzept-Edit).
- **ZERO DEBT:** beide Stores; clean/PASS real persistiert; Override-Korrelation real; CheckFactory nicht vorausgesetzt.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Reihenfolge:** zuerst FK-69-Read-Model via Approval-Flow definieren (Codex absegnen → Edit → re-review), dann Code. Ohne den Konzept-Eintrag NICHT implementieren.
- `check_id` = ausgefuehrter Check (`stage_id`/Finding-`check_id`, `data.py:67`/`structured_evaluator.py:143`), **nicht** `fc_check_proposals.check_id`.
- verify-system muss clean/PASS-Checks erfassen (heute verworfen, `structured_evaluator.py:448`); Override braucht `check_id`-Bezug (`OverrideRecord` hat heute keinen).
- Schema in beiden Stores + `ProjectionKind` + `SCHEMA_VERSION` + Contract/Golden.
- AK2/`.mcp.json` nicht anfassen; im Code-Commit kein `concept/**`/`stories/**` (der Konzept-Edit ist ein eigener, approval-geführter Schritt).
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Test-Namen (Emission triggered/clean/overridden, Override-Korrelation, Schema-Roundtrip beide Stores, ProjectionFilter check_id/since_days).

---

## Globale Akzeptanzkriterien (verbindlich)
- **GAC-1:** `scripts/ci/check_architecture_conformance.py` mit **0 Errors** (Exit 0).
- **GAC-2:** Architektur-Guardrails `guardrails/architecture-guardrails.md` eingehalten; Konflikt = hart stoppen und melden.
