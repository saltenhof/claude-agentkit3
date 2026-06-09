# AG3-108: Check-Outcome-Metriken (story_metrics `check_ref`/Outcome + ProjectionFilter + Population)

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** `story-closure` (`closure/post_merge_finalization` — Schema-Owner + Writer der Closure-Metriken, FK-29 §29.6) + `telemetry-and-events` (`ProjectionFilter`/`read_projection`).
**Quell-Konzepte (autoritativ):**
- `FK-69 §69.8` — Telemetrie-/Read-Model-Tabellen rund um story-closure (autoritativ fuer die **exakte** Tabellen-/Spaltenform der Check-Outcome-Erfassung).
- `FK-29 §29.6` — `PostMergeFinalization` ist Schema-Owner + alleiniger Writer fuer `story_metrics` (belegt in `closure/phase.py:994`).
- `FK-41 §41.3.2` — `check_ref`-Semantik = Referenz auf `fc_check_proposals.check_id` (bereits real fuer `fc_patterns.check_ref`, `sqlite_store.py:899`).
- Herkunft: D6-Entscheidung (PO 2026-06-09, `_OPEN_DECISIONS.md`); buendelt die No-Owner-Gaps **CP2/CP3/CP4** aus AG3-078. **Zweck:** Datenunterbau, damit der Failure-Corpus-/Check-Factory-Lernloop die **Check-Effektivitaet** messen kann (heute `FailureCorpus.report_effectiveness` = `NotImplementedError`).

---

## 1. Kontext / Ist-Zustand (belegt)
- **`story_metrics` ist EINE Zeile pro Run, ohne Check-Bezug:** `StoryMetricsRecord` (`closure/post_merge_finalization/records.py:11-31`) traegt `qa_rounds`/`final_status`/`llm_roles` etc., aber **kein** `check_ref`/Check-Outcome. Tabelle `story_metrics` PK `(project_key, run_id)` (`state_backend/sqlite_store.py:320-345`; Postgres `upsert_story_metrics_row`/INSERT `postgres_store.py:2600-2652` + `postgres_schema.sql`). Writer = `build_story_metrics_record` (`metrics.py:23`) ueber `PostMergeFinalization` (`closure/phase.py:994/1010`, FK-29 §29.6). **=> Per-Check-Granularitaet passt NICHT in die Ein-Zeile-pro-Run-Tabelle.**
- **`ProjectionFilter` kennt kein `check_ref`/`since_days`:** Felder sind `project_key/story_id/run_id/attempt_no/stage_id` (`telemetry/projection_accessor.py:120-140`); `read_projection` (`:329`) wendet nur gesetzte Felder als WHERE an.
- **`check_ref`-Semantik existiert bereits** in der Failure-Corpus-Domaene: FK auf `fc_check_proposals(check_id)` (`fc_patterns.check_ref`, FK-41 §41.3.2; `sqlite_store.py:894-899`). Diese Semantik wird wiederverwendet, **nicht** neu erfunden.
- **Heute keine Check-Outcome-Erfassung aus echten Laeufen:** es gibt keine Quelle, die pro Story-Run festhaelt, welche Checks gefeuert / uebersteuert / sauber durchgelaufen sind. Folge: der Lernloop (`FailureCorpus.report_effectiveness`, `failure_corpus/top.py` = `NotImplementedError`) ist **blind**.

## 2. Scope

### 2.1 In Scope
1. **Per-Check-Outcome-Projektion (Schema, BEIDE Stores) — Form gemaess FK-69 §69.8:** eine Erfassung, die pro Story-Run **je Check** das Outcome traegt: `check_ref` (FK auf `fc_check_proposals.check_id`) + Outcome-Klassifikation **triggered / overridden / clean-run** (typisiert, kein Free-String) + Schluessel `project_key/story_id/run_id` (+ ggf. `node_id`/`stage_id`/`decided_at` gemaess FK-69 §69.8).
   - **Modell-Entscheidung (verbindlich pruefen):** Da `story_metrics` eine Zeile pro Run ist, gehoeren Per-Check-Outcomes in eine **eigene Projektion** (z. B. `story_check_outcomes`, PK `(project_key, run_id, check_ref)`), **nicht** als Spalten an `story_metrics`. **Die exakte Tabellen-/Spaltenform ist FK-69 §69.8 zu entnehmen.** Wenn FK-69 §69.8 die Per-Check-Granularitaet (eigene Tabelle vs. Aggregat-Spalten an story_metrics) **nicht eindeutig** vorgibt: **STOPP + melden** (kein Raten, kein zweites Schema neben der Konzeptvorgabe).
   - Umsetzung in `sqlite_store.py` + `postgres_schema.sql` + `postgres_store.py` (upsert/load) + typisierter Record + Payload + `ProjectionKind`-Registrierung; `SCHEMA_VERSION` (state_backend/config.py) bumpen.
2. **`ProjectionFilter` erweitern (telemetry):** `check_ref: str | None = None` + `since_days: int | None = None` ergaenzen (`projection_accessor.py:120-140`); `read_projection` wendet sie als WHERE an — `check_ref` als Gleichheit, `since_days` als Zeitfenster (`<zeitspalte> >= now - since_days`, deterministische, UTC-basierte Grenze). Docstring + Contract/Golden-Tests nachziehen.
3. **Outcome-Population aus ECHTEN verify/closure-Laeufen (CP4):** `PostMergeFinalization` (alleiniger Writer, FK-29 §29.6) befuellt die Per-Check-Outcome-Projektion aus den **realen** Check-Ergebnissen des QA-Subflows + Override-Records des Runs — **nicht** synthetisiert, **keine** zweite Wahrheit. Quelle: die im Run real vorliegenden Verify-Stage-Ergebnisse + `override_records` (`sqlite_store.py:347`).
4. **Tests:** Schema-Roundtrip beide Stores; `ProjectionFilter.check_ref`/`since_days`-Filterung (inkl. Zeitfenster-Grenzfall); Population aus realistischen Run-Artefakten (triggered/overridden/clean je ein Fall); Invarianten (jede erfasste Check-Outcome-Zeile hat gueltigen `check_ref`); fail-closed bei fehlendem `project_key`.

### 2.2 Out of Scope (mit Owner)
- **Lern-/Auswertungslogik** (`report_effectiveness`, Pattern-Promotion/Check-Ableitung **auf Basis** dieser Daten) — **AG3-078** (Failure-Corpus/Check-Factory). Diese Story liefert nur das **Daten-Substrat**, nicht den Regelkreis.
- **KPI-/Dashboard-Sichten** ueber die Check-Outcomes — KPI-Welle (FK-63/FK-72).
- **`check_ref`-FK-Semantik in der Failure-Corpus-Domaene** (`fc_patterns`/`fc_check_proposals`) — bestehend, unveraendert wiederverwendet.
- **Skill-/Experiment-Attribution** (`skill_name`/`experiment_tag`) — AG3-081/083/AG3-095-Umfeld; nicht Teil dieser Story.

## 3. Akzeptanzkriterien
1. Eine Per-Check-Outcome-Projektion existiert in **beiden** Stores in der von **FK-69 §69.8** vorgegebenen Form; Insert/Read-Roundtrip pro Store (Test). Jede Zeile traegt `check_ref` (FK `fc_check_proposals.check_id`) + typisiertes Outcome (triggered/overridden/clean-run) + `project_key/story_id/run_id`.
2. `ProjectionFilter` traegt `check_ref` + `since_days`; `read_projection` filtert deterministisch danach (Test: `check_ref`-Gleichheit; `since_days`-Zeitfenster inkl. Grenzfall „genau an der Grenze").
3. `PostMergeFinalization` befuellt die Outcomes aus **echten** Run-Daten (Verify-Stage-Ergebnisse + `override_records`), nicht synthetisiert; alleiniger Writer (Test mit realistischen Run-Artefakten: je ein triggered/overridden/clean-Fall → erwartete Zeilen).
4. Invariante: jede Outcome-Zeile hat einen gueltigen `check_ref`; fehlender `project_key` → fail-closed (Test).
5. `since_days`-Fenster ist UTC-deterministisch (kein `now()`-Nichtdeterminismus im Test — Zeit injizierbar/parametrisiert).
6. ARCH-55 (englische Spalten/Enum-Werte/Keys); Schema-Aenderung in **beiden** Stores + Contract/Golden-Tests nachgezogen + `SCHEMA_VERSION` gebumpt.
7. **Pflichtbefehle gruen:** scoped pytest (`tests/unit/closure`, `tests/unit/telemetry`, `tests/unit/state_backend`, `tests/contract`, `-n0`) + `pytest --collect-only -q tests` (0 Importfehler) + broad `pytest tests/unit tests/contract -q -n0` (0 failed); `mypy src` (+`--platform linux`); `ruff`; GAC-1 (Exit 0); Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–7 erfuellt; Codex-Review PASS; Commit auf `main` erst nach explizitem PO-Go.

## 5. Guardrail-Referenzen
- **SINGLE SOURCE OF TRUTH:** `PostMergeFinalization` ist alleiniger Writer (FK-29 §29.6); keine zweite Check-Outcome-Wahrheit neben der Projektion.
- **FIX THE MODEL:** Per-Check-Granularitaet in eine eigene, FK-69-§69.8-konforme Projektion (nicht in die Ein-Zeile-pro-Run-`story_metrics` quetschen); `check_ref`-Semantik aus FK-41 §41.3.2 wiederverwenden.
- **FAIL-CLOSED:** unklare Konzeptvorgabe (FK-69 §69.8 zur Granularitaet) → STOPP + melden, nicht raten; fehlender `project_key` → Fehler.
- **TYPISIERT STATT STRINGS:** Outcome-Klassifikation als Enum (triggered/overridden/clean-run), nicht Free-String.
- **ZERO DEBT:** beide Stores zusammen, Population aus echten Laeufen (kein Synthese-Platzhalter), Contract/Golden gezogen.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Zuerst FK-69 §69.8 lesen** und die exakte Tabellen-/Spaltenform daraus uebernehmen. Gibt FK-69 §69.8 die Per-Check-Granularitaet nicht her → STOPP + als offene Konzeptfrage melden (nicht selbst ein Schema erfinden).
- Schema-Aenderungen IMMER in beiden Stores (`sqlite_store.py` + `postgres_schema.sql`/`postgres_store.py`) + `ProjectionKind` + Contract/Golden-Tests + `SCHEMA_VERSION`-Bump.
- `check_ref` ist FK auf `fc_check_proposals(check_id)` (FK-41 §41.3.2) — Semantik nicht neu erfinden.
- Population NUR ueber den `PostMergeFinalization`-Writer; Lese-Zugriff der spaeteren Konsumenten ueber `ProjectionFilter`/`read_projection`.
- AK2/`.mcp.json` nicht anfassen; `concept/**`/`stories/**` nicht im Code-Commit.
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Test-Namen (Schema-Roundtrip beide Stores, check_ref/since_days-Filter, Population triggered/overridden/clean).

---

## Globale Akzeptanzkriterien (verbindlich)
- **GAC-1:** `scripts/ci/check_architecture_conformance.py` mit **0 Errors** (Exit 0) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Architektur-Guardrails `guardrails/architecture-guardrails.md` eingehalten; Konflikt = hart stoppen und melden.
