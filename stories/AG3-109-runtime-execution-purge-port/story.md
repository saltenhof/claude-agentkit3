# AG3-109: Runtime-Execution-Purge-Port (koordiniert, je Owner dediziert)

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** Per-Entitaet-Purge in den jeweiligen Owner-BCs (`pipeline-framework`: FlowExecution/NodeExecution/AttemptRecord; `governance-and-guards`: OverrideRecord/GuardDecision; `telemetry-and-events`: PhaseState-Projektion/ExecutionEvent; `artifacts`: umsetzungsgebundene ArtifactRecord) + **ein koordinierender `RuntimeExecutionPurgePort`** an der State-Backend-/Persistenz-Grenze (wo `purge_run` heute schon lebt). Konsument: `story-lifecycle` (`StoryResetService`, AG3-071) — hier **nicht** gebaut.
**Quell-Konzepte (autoritativ):**
- `FK-53 §53.6.2` — Entitaeten, die ein Reset **vollstaendig entfernt** (`FlowExecution`, `NodeExecution`, `AttemptRecord`, `OverrideRecord`, `GuardDecision`, `PhaseState`, umsetzungsgebundene `ArtifactRecord`, `ExecutionEvent`, …).
- `FK-53 §53.7.5` — Reset-Schritt 5 „Operativen Runtime-State purgen"; Regel: kein verbleibendes Objekt darf einen spaeteren Neustart/Resume/Guard-Entscheid beeinflussen.
- `FK-53 §53.9.1` — Idempotenz: loeschen-wenn-vorhanden / ignorieren-wenn-weg / hart fehlschlagen nur bei echten Infra-/Berechtigungsproblemen.
- `FK-53 §53.10` — Service-Vertrag inkl. `verify_reset_clean_state(reset_id)`.
- `FK-18` — relationale Purge-Domaenen/Tabellenfamilien (normativ fuer die exakte Tabellenmenge).
- Herkunft: D3-Entscheidung (PO 2026-06-09, `_OPEN_DECISIONS.md`); No-Owner-Gap aus AG3-071-Remediation (`_CROSS_STORY_PREREQS.md`).

> **PO-Designentscheidung (D3):** Der Runtime-Execution-Purge wird **je Owner-BC dediziert** ausgefuehrt; der Reset-Service ruft sie **koordiniert** ueber einen schmalen Port auf. **Kein** zentraler „God-Purge", der direkt in fremde BC-Stores greift.

---

## 1. Kontext / Ist-Zustand (belegt)
- **FK-53 spezifiziert den Purge fachlich vollstaendig** (§53.6.2 Entitaetenliste, §53.7.5 Purge-Schritt + Regel, §53.9.1 Idempotenz, §53.10 `verify_reset_clean_state`). **Nicht** spezifiziert ist die **Realisierungsform** (zentral vs. per-Owner) — das ist der D3-Nachzug (siehe Konzept-Nachzug-Aufgabe).
- **Per-Projektion-`purge_run` existiert bereits** mehrfach in `state_backend/store/projection_repositories.py` (z. B. `:75/:113/:149/:176/:196/:581/:825/:889/:1005`) — aber laut Cross-Story-Befund decken die bestehenden Purges **Read-Models/Analytics** ab (AG3-081/082-Umfeld), **nicht** die kanonische Loeschung der **Runtime-Execution-Kernentitaeten** `FlowExecution/NodeExecution/AttemptRecord/OverrideRecord/GuardDecision/PhaseState/ExecutionEvent`.
- **`PurgeResult`** (typisiertes Ergebnis) existiert bereits (`telemetry/projection_accessor.py:148`).
- **Kein koordinierender Port:** es gibt heute keine kanonische Operation, die — von `(project_key, story_id, run_id)` ausgehend — die Runtime-Execution-Owner-Purges gebuendelt ausloest und ein Gesamt-Ergebnis liefert. AG3-071 (`StoryResetService` §53.7.5, Welle 4) konsumiert sie fail-closed → ohne diese Story ist Reset nicht sauber lieferbar.

## 2. Scope

### 2.1 In Scope
1. **Per-Owner-Purge der Runtime-Execution-Kernentitaeten** (je am Owner-Repository/Store, **beide** Stores, idempotent gem. §53.9.1): `FlowExecution`, `NodeExecution`/`NodeExecutionLedger`, `AttemptRecord`, `OverrideRecord`, `GuardDecision`, kanonischer `PhaseState`, `ExecutionEvent`, umsetzungsgebundene `ArtifactRecord` — soweit nicht bereits durch ein bestehendes `purge_run` abgedeckt (Bestehendes wiederverwenden, Fehlendes ergaenzen; **kein** Duplikat). Exakte Tabellenmenge gem. **FK-18** / FK-53 §53.6.2.
2. **Koordinierender `RuntimeExecutionPurgePort`** an der Persistenz-/State-Backend-Grenze: nimmt `(project_key, story_id, run_id)`, ruft die Per-Owner-Purges der Runtime-Execution-Domaene **gebuendelt** auf und liefert ein typisiertes `PurgeResult` (Zeilen je Domaene). **Kein** direkter Cross-BC-Loeschzugriff — der Port orchestriert die Owner-Operationen.
3. **Idempotenz (§53.9.1):** jeder Per-Owner-Purge ist konvergent (loeschen-wenn-vorhanden, ignorieren-wenn-weg); harter Fehler nur bei echten Infra-/Berechtigungsproblemen. Mehrfacher Aufruf mit derselben `(project_key, run_id)` ist sicher (Resume-faehig).
4. **`verify`-Unterstuetzung (§53.8/§53.10):** eine Pruefoperation, die fail-closed bestaetigt, dass fuer den `run_id` **kein** Runtime-Execution-Residuum der o. g. Entitaeten verbleibt (Baustein fuer `verify_reset_clean_state`).
5. **Tests:** Roundtrip je Entitaet (anlegen → purge → weg) in **beiden** Stores; Idempotenz (zweiter Purge = 0 zusaetzliche Loeschungen, kein Fehler); Port-Fan-out (ein Aufruf entfernt alle Runtime-Execution-Domaenen, `PurgeResult`-Zaehler stimmen); Negativpfad (fehlender `project_key` → fail-closed); verify-Pruefung positiv (sauber) + negativ (Residuum erkannt).

### 2.2 Out of Scope (mit Owner)
- **`StoryResetService`-Flow selbst** (Fence/Quiesce/Audit/Resume, §53.7.1-4/§53.9) — **AG3-071** (story-lifecycle). Diese Story liefert nur den Purge-Port, den AG3-071 in §53.7.5 aufruft.
- **Read-Models-/Analytics-Purge** (FK-69-Read-Models, `fact_story`, §53.7.6) — bestehende `purge_run`-Pfade / AG3-081/082-Umfeld; hier nur die Runtime-Execution-Domaene.
- **Worktree-/Branch-Behandlung** (§53.7.8) + ephemere Arbeitsoberflaechen (§53.7.7) — story_context_manager / WorktreeManager-Konsolidierung (D11/AG3-104-Umfeld).
- **FK-18-Tabellen-Normalisierung** — bestehend; hier konsumiert, nicht neu definiert.
- **Locks/Leases-Quiescing** (§53.7.3) — Operator-/Reset-Service-Mechanik (AG3-071/AG3-076); der Port purgt nur persistente Runtime-Execution-Objekte.

## 3. Akzeptanzkriterien
1. Fuer jede Runtime-Execution-Kernentitaet (§53.6.2: FlowExecution/NodeExecution/AttemptRecord/OverrideRecord/GuardDecision/PhaseState/ExecutionEvent/umsetzungsgebundene ArtifactRecord) existiert eine Per-Owner-Purge-Operation in **beiden** Stores; Roundtrip-Test (anlegen→purge→weg) je Store.
2. `RuntimeExecutionPurgePort` purgt von `(project_key, story_id, run_id)` ausgehend alle Runtime-Execution-Domaenen gebuendelt und liefert ein typisiertes `PurgeResult` mit Zeilen je Domaene (Test).
3. Idempotenz (§53.9.1): zweiter Purge-Aufruf liefert 0 zusaetzliche Loeschungen ohne Fehler; harter Fehler nur bei Infra/Berechtigung (Test).
4. **Regel §53.7.5 bewiesen:** nach Purge gibt es fuer den `run_id` kein Objekt der o. g. Entitaeten mehr, das einen Neustart/Resume/Guard-Entscheid beeinflussen koennte (verify-Pruefung positiv; Negativtest mit kuenstlichem Residuum schlaegt fail-closed an).
5. **Kein God-Purge:** der Port ruft die Owner-Operationen auf; kein direkter SQL-/Store-Zugriff des Ports in fremde BC-Tabellen ausserhalb der jeweiligen Owner-Repository-API (Review/Architektur-Assertion; GAC-1 ohne neue Boundary-Verletzung).
6. ARCH-55; Schema-/Purge-Pfade in **beiden** Stores; Contract/Golden-Tests nachgezogen; `SCHEMA_VERSION` nur falls Schemaaenderung noetig.
7. **Pflichtbefehle gruen:** scoped pytest (`tests/unit/state_backend`, `tests/unit/pipeline_engine`, `tests/unit/governance`, `tests/contract`, `-n0`) + `pytest --collect-only -q tests` (0 Importfehler) + broad `pytest tests/unit tests/contract -q -n0` (0 failed); `mypy src` (+`--platform linux`); `ruff`; GAC-1 (Exit 0); Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–7 erfuellt; Codex-Review PASS; Commit auf `main` erst nach explizitem PO-Go.

## 5. Guardrail-Referenzen
- **FIX THE MODEL / BC-OWNERSHIP:** jede Entitaet wird von ihrem Owner-BC gepurgt; der Port koordiniert nur — keine zweite Loesch-Wahrheit, kein Cross-BC-Direktzugriff.
- **FAIL-CLOSED (§53.9.1):** harter Fehler nur bei echten Infra-/Berechtigungsproblemen; sonst konvergent; verify schlaegt bei Residuum an.
- **SINGLE SOURCE OF TRUTH:** bestehende `purge_run`-Operationen wiederverwenden, nichts duplizieren.
- **ZERO DEBT:** beide Stores zusammen; alle §53.6.2-Runtime-Execution-Entitaeten abgedeckt; keine stille Restmenge.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Erst pruefen, welche `purge_run`/Purge-Pfade real existieren** (`state_backend/store/projection_repositories.py`) und welche §53.6.2-Entitaeten noch KEINEN Purge haben — nur Fehlendes ergaenzen, Bestehendes wiederverwenden.
- Tabellenmenge gegen **FK-18** + FK-53 §53.6.2 abgleichen; bei Unklarheit melden, nicht raten.
- Der Port orchestriert Owner-Operationen — **kein** direkter Fremd-Store-Zugriff (Importrichtung/BC-Grenzen beachten; GAC-1).
- AK2/`.mcp.json` nicht anfassen; `concept/**`/`stories/**` nicht im Code-Commit.
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Test-Namen (Per-Entitaet-Roundtrip beide Stores, Port-Fan-out, Idempotenz, verify positiv/negativ).

---

## Globale Akzeptanzkriterien (verbindlich)
- **GAC-1:** `scripts/ci/check_architecture_conformance.py` mit **0 Errors** (Exit 0) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Architektur-Guardrails `guardrails/architecture-guardrails.md` eingehalten; Konflikt = hart stoppen und melden.
