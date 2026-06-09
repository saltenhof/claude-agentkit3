# AG3-107: `PhaseStatus.BLOCKED` aus der Live-Status-Achse entfernen (Precondition-Fail → `FAILED`)

**Typ:** Implementation (Achsen-Vermischung beseitigen)
**Groesse:** M
**Bounded Context:** `pipeline-framework` (`pipeline_engine`) + `bootstrap` (Composition-Root-Residue). Beruehrt die Phasen-Zustandsmaschine → broad Verify Pflicht.
**Quell-Konzepte (autoritativ):**
- `FK-39 §39.2.1` — Live-`PhaseStatus` (nach D1: `PENDING, IN_PROGRESS, COMPLETED, FAILED, ESCALATED, PAUSED` — **kein** `BLOCKED`).
- `FK-39 §39.4.2/§39.4.3` — `AttemptOutcome.BLOCKED` + `FailureCause.PRECONDITION_FAILED` bleiben (Audit-Achse, unveraendert).

> **Herkunft + Korrektur:** PO-Entscheidung D1 (2026-06-09). **Wichtige Richtigstellung gegenueber der Erstfassung** (Codex-Review `job-d2ccdbc3`): `PhaseStatus.BLOCKED` wird **nicht** beim Worker-Blocked gesetzt — Worker-Blocked ist laut FK-26 §26.x / FK-45 §45 bereits `ESCALATED` (via `worker-manifest.json` → `HandlerResult(status=PhaseStatus.ESCALATED)`, `src/agentkit/implementation/phase.py:407`) und bleibt **unangetastet**. `BLOCKED` ist real der Live-Status fuer **„Vorbedingung zum Phaseneintritt fehlgeschlagen"**. Diese Story entfernt nur diesen einen Live-Status; „blocked" lebt weiter auf der Audit-Achse.

---

## 1. Kontext / Ist-Zustand (belegt)
- `PhaseStatus` (Code) traegt 7 Werte inkl. `BLOCKED` (`src/agentkit/pipeline_engine/phase_executor/models.py:37-44`); FK-39 §39.2.1 kennt `BLOCKED` **nicht** als Live-Status.
- **Einzige Setz-Stelle = Precondition-Fail:** `engine.py:1056-1061` — wenn `_can_enter_phase(...)` `False` liefert, wird `status=PhaseStatus.BLOCKED` gesetzt (`pause_reason=None`, `escalation_reason=None`, `errors=failure_reasons`). Der zugehoerige AttemptRecord traegt bereits **direkt** `outcome=AttemptOutcome.BLOCKED` + `failure_cause=FailureCause.PRECONDITION_FAILED` (`engine.py:1069-1074`) — **unabhaengig** vom Live-Status.
- **Status→x-Maps** (greifen nur, wenn ein Handler terminal `BLOCKED` zurueckgibt — passiert real nicht, da Worker-Blocked = ESCALATED): `_engine_status_for` `BLOCKED→"blocked"` (`engine.py:728`), `_outcome_for_terminal` `BLOCKED→AttemptOutcome.BLOCKED` (`engine.py:737`), `_failure_cause_for_terminal` `BLOCKED→FailureCause.WORKER_BLOCKED` (`engine.py:745-746`).
- **Residue-Set:** `composition_root.py:1479` fuehrt `PhaseStatus.BLOCKED` als terminal/nicht-frisch.
- **Audit-Achse korrekt + bleibt:** `AttemptOutcome.BLOCKED` (FK-39 §39.4.2) + `FailureCause.PRECONDITION_FAILED` (§39.4.3) sind die richtigen Traeger der „precondition-blocked"-Information.

## 2. Scope
### 2.1 In Scope
1. **`PhaseStatus.BLOCKED` aus dem Live-Enum entfernen** (`phase_executor/models.py:44`).
2. **Precondition-Fail-Setz-Stelle umbiegen (`engine.py:1061`):** Live-`status = FAILED` statt `BLOCKED`. Der AttemptRecord bleibt **unveraendert** `outcome=AttemptOutcome.BLOCKED` + `failure_cause=FailureCause.PRECONDITION_FAILED` (`engine.py:1073-1074`) — die „blocked"-Info bleibt also auf der Audit-Achse erhalten, nur der Live-Status wird FAILED.
3. **Status→x-Maps bereinigen:** die `PhaseStatus.BLOCKED`-Eintraege aus `_engine_status_for` (`:728`), `_outcome_for_terminal` (`:737`) und `_failure_cause_for_terminal` (`:745-746`) entfernen (sie sind nach Wegfall des Live-`BLOCKED` tot; die `.get(...)`-Defaults bleiben).
4. **Residue-Set bereinigen:** `PhaseStatus.BLOCKED` aus `composition_root.py:1479` entfernen — der Precondition-Fail endet jetzt als `FAILED` und ist damit schon terminal abgedeckt (Verhalten unveraendert).
5. **Worker-Blocked NICHT anfassen:** `implementation/phase.py:407` (`HandlerResult.ESCALATED`) und alle ESCALATED-Pfade bleiben unveraendert.
6. **Negativpfad-/Übergangs-Tests** an der Zustandsmaschine.

### 2.2 Out of Scope (mit Owner)
- `AttemptOutcome.BLOCKED` / `FailureCause.PRECONDITION_FAILED` / `WORKER_BLOCKED` aendern — bleiben (Audit-Achse).
- Worker-Blocked-Semantik (ist bereits ESCALATED) — unberuehrt.
- `PENDING`-Konzept-Nachzug (FK-39 §39.2.1 / FK-91 §91.5 / frontend-events) — separat erledigt (D1).
- Andere `PhaseStatus`-Werte / PAUSE-Semantik — unberuehrt.

## 3. Akzeptanzkriterien
1. `PhaseStatus` hat **6** Werte, `BLOCKED` ist entfernt (`models.py`); **kein** Produktionscode referenziert `PhaseStatus.BLOCKED` mehr (grep + `mypy` sauber).
2. Precondition-Fail (`_can_enter_phase` false) setzt Live-`status = FAILED` (Test gegen `engine.py`-Pfad).
3. Der AttemptRecord des Precondition-Fail traegt unveraendert `outcome=AttemptOutcome.BLOCKED` + `failure_cause=FailureCause.PRECONDITION_FAILED` (Test) — Audit-Information erhalten.
4. Die bereinigten Maps liefern keine `PhaseStatus.BLOCKED`-Verzweigung mehr; Verhalten fuer alle real auftretenden terminalen Status (FAILED/ESCALATED) unveraendert (Test).
5. Setup-Residue-Erkennung unveraendert (Precondition-Fail endet terminal als FAILED; kein Regress, Test).
6. Worker-Blocked bleibt `ESCALATED` (Regressionstest gegen `implementation/phase.py`-Pfad — beweist, dass diese Story den Worker-Pfad nicht beruehrt).
7. ARCH-55; `mypy src` (+ `--platform linux`) sauber (Enum-Entfernung zieht keine offenen `match`/Vergleiche nach sich).
8. **Pflichtbefehle gruen:** scoped pytest (`tests/unit/pipeline_engine`, `tests/unit/bootstrap`, betroffene Pfade) + `pytest --collect-only -q tests` (0 Importfehler) + **broad** `pytest tests/unit tests/contract -q -n0` (0 failed); `mypy src` (+linux); `ruff`; GAC-1 (Exit 0); Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–8 erfuellt; Codex-Review PASS; Commit auf `main` erst nach explizitem PO-Go.

## 5. Guardrail-Referenzen
- **FIX THE MODEL:** „blocked" lebt auf der Audit-Achse (`AttemptOutcome.BLOCKED`/`FailureCause.PRECONDITION_FAILED`), nicht im Live-Status — keine zweite Wahrheit.
- **FAIL-CLOSED:** Precondition-Fail bleibt terminal (FAILED); kein stiller Erfolg.
- **ZERO DEBT:** vollstaendige Enum-Entfernung inkl. aller Map-/Residue-Stellen, keine Restreferenz.
- **KEIN SCOPE-CREEP:** Worker-Blocked (ESCALATED, FK-26/FK-45) wird nicht angefasst.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Blast-Radius = Zustandsmaschine → **broad** `pytest tests/unit tests/contract` + `--collect-only` Pflicht (Lehre aus AG3-059).
- Vor dem Entfernen ALLE Referenzen suchen: `PhaseStatus.BLOCKED`, `"blocked"`-Mappings, `match`/`if` ueber `PhaseStatus`; Tests anpassen (u. a. `tests/unit/story/test_models.py`).
- **Nicht** verwechseln: Precondition-Fail (`engine.py:1061`, diese Story) vs. Worker-Manifest-Blocked (`implementation/phase.py:407`, = ESCALATED, NICHT anfassen).
- AK2/`.mcp.json` nicht anfassen; `concept/**`/`stories/**` nicht im Code-Commit.
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Test-Namen (precondition→FAILED + AttemptOutcome.BLOCKED erhalten, worker-blocked weiter ESCALATED, Residue unveraendert).

---

## Globale Akzeptanzkriterien (verbindlich)
- **GAC-1:** `scripts/ci/check_architecture_conformance.py` mit **0 Errors** (Exit 0).
- **GAC-2:** Architektur-Guardrails `guardrails/architecture-guardrails.md` eingehalten.
