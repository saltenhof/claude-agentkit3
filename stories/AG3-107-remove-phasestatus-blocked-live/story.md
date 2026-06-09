# AG3-107: `PhaseStatus.BLOCKED` aus der Live-Status-Achse entfernen

**Typ:** Implementation (Bugfix-nah: Achsen-Vermischung beseitigen)
**Groesse:** M
**Bounded Context:** `pipeline-framework` (`pipeline_engine`) + `bootstrap` (Composition-Root-Residue). Beruehrt die Phasen-Zustandsmaschine.
**Quell-Konzepte (autoritativ):**
- `FK-39 §39.2.1` — Live-`PhaseStatus` (nach D1: `PENDING, IN_PROGRESS, COMPLETED, FAILED, ESCALATED, PAUSED` — **kein** `BLOCKED`).
- `FK-39 §39.4.2/§39.4.3` — `AttemptOutcome.BLOCKED` + `FailureCause.WORKER_BLOCKED` bleiben (Audit-Achse, unveraendert).

> **Herkunft:** PO-Entscheidung D1 (2026-06-09). `BLOCKED` ist im Konzept nie ein Live-Status gewesen; im Code ist es eine Achsen-Vermischung — der Code setzt einen Live-Status `BLOCKED`, nur um ihn sofort in das Audit-Outcome `AttemptOutcome.BLOCKED`/`FailureCause.WORKER_BLOCKED` zu uebersetzen. „Fix the Model": `BLOCKED` lebt auf der Audit-Achse, nicht im Live-Status.

---

## 1. Kontext / Ist-Zustand (belegt)
- `PhaseStatus` (Code) traegt 7 Werte inkl. `BLOCKED` (`src/agentkit/pipeline_engine/phase_executor/models.py:37-44`); FK-39 §39.2.1 kennt es **nicht** als Live-Status.
- `PhaseStatus.BLOCKED` wird an **einer** Stelle gesetzt: `src/agentkit/pipeline_engine/engine.py:1061` (Worker-blocked-Ergebnis, `pause_reason=None`, `escalation_reason=None`).
- Es wird sofort uebersetzt: final_status-String `"blocked"` (`engine.py:728`), `AttemptOutcome.BLOCKED` (`engine.py:737`), `FailureCause.WORKER_BLOCKED` (`engine.py:745`).
- Als „terminal/nicht-frisch" behandelt im Setup-Residue-Set (`src/agentkit/bootstrap/composition_root.py:1479`).
- `AttemptOutcome.BLOCKED` (`models.py` / FK-39 §39.4.2) und `FailureCause.WORKER_BLOCKED` (§39.4.3) sind die **richtigen**, konzept-sanktionierten Traeger der „blocked"-Information.

## 2. Scope
### 2.1 In Scope
1. **`PhaseStatus.BLOCKED` aus dem Live-Enum entfernen** (`phase_executor/models.py`).
2. **Setz-Stelle umbiegen (`engine.py:1061`):** Der Worker-blocked-Ausgang setzt als **Live-Status** kuenftig `FAILED` (terminaler Fehler), **nicht** `BLOCKED`.
3. **Audit-Achse erhalten:** Der AttemptRecord traegt weiterhin `outcome = AttemptOutcome.BLOCKED` und `failure_cause = FailureCause.WORKER_BLOCKED`. Die Ableitung erfolgt aus einem **typisierten Worker-blocked-Signal** des Handler-/Phasen-Ergebnisses (z. B. ein dediziertes Result-Feld/Marker), **nicht** mehr aus dem (jetzt entfernten) Live-Status `BLOCKED`.
4. **Map-Stellen bereinigen:** `engine.py:728` (final_status-Map: `"blocked"` nur noch aus dem Worker-blocked-Signal, nicht aus Live-Status), `engine.py:737/745` (outcome/failure_cause aus dem Signal); `composition_root.py:1479` (Residue-Set: `BLOCKED` entfaellt — der Worker-blocked-Ausgang ist jetzt `FAILED` und damit schon abgedeckt).
5. **Negativpfad-/Übergangs-Tests** an der Zustandsmaschine: Worker-blocked → Live-Status `FAILED` **und** AttemptRecord `outcome=BLOCKED`/`failure_cause=WORKER_BLOCKED`; final_status-String korrekt; Residue-Verhalten unveraendert (FAILED ist terminal).

### 2.2 Out of Scope (mit Owner)
- `AttemptOutcome.BLOCKED` / `FailureCause.WORKER_BLOCKED` aendern — bleiben (Audit-Achse).
- `PENDING`-Konzept-Nachzug (FK-39 §39.2.1) — bereits via D1 doc-only erledigt.
- Andere `PhaseStatus`-Werte / die PAUSE-Semantik — unberuehrt.

## 3. Akzeptanzkriterien
1. `PhaseStatus` hat **6** Werte, `BLOCKED` ist entfernt (`models.py`); kein Produktionscode referenziert `PhaseStatus.BLOCKED` mehr (grep/mypy sauber).
2. Worker-blocked-Ausgang setzt Live-`status = FAILED` (`engine.py`-Pfad, Test).
3. Der zugehoerige AttemptRecord traegt weiterhin `outcome = AttemptOutcome.BLOCKED` und `failure_cause = FailureCause.WORKER_BLOCKED`, abgeleitet aus dem Worker-blocked-Signal (Test).
4. final_status-/outcome-/failure_cause-Maps liefern fuer den Worker-blocked-Fall unveraenderte Audit-Ergebnisse, ohne Live-Status `BLOCKED` (Test).
5. Setup-Residue-Erkennung verhaelt sich unveraendert (Worker-blocked endet terminal als FAILED; kein Regress, Test).
6. ARCH-55; `mypy src` (+ `--platform linux`) sauber (Enum-Entfernung zieht keine ungefangenen `match`/Vergleiche nach sich).
7. **Pflichtbefehle gruen:** scoped pytest (`tests/unit/pipeline_engine`, `tests/unit/bootstrap` bzw. betroffene Pfade) + `pytest --collect-only -q tests` (0 Importfehler) + broad `pytest tests/unit tests/contract -q -n0` (0 failed); `mypy src` (+linux); `ruff`; GAC-1 (Exit 0); Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–7 erfuellt; Codex-Review PASS; Commit auf `main` erst nach explizitem PO-Go.

## 5. Guardrail-Referenzen
- **FIX THE MODEL:** „blocked" lebt auf der Audit-Achse (`AttemptOutcome`/`FailureCause`), nicht im Live-Status — keine zweite Wahrheit.
- **FAIL-CLOSED:** Worker-blocked bleibt terminal (FAILED); kein stiller Erfolg.
- **TYPISIERT STATT STRINGS:** Worker-blocked-Signal typisiert, nicht ueber den Live-Status-Umweg.
- **ARCH-55 / ZERO DEBT:** vollstaendige Enum-Entfernung inkl. aller Map-/Lese-Stellen, keine Restreferenz.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Blast-Radius ist die Zustandsmaschine — **broad** `pytest tests/unit tests/contract` + `--collect-only` Pflicht (Lehre aus AG3-059).
- Vor dem Entfernen alle Referenzen suchen: `PhaseStatus.BLOCKED`, `"blocked"`-Mappings, `match`/`if`-Verzweigungen ueber `PhaseStatus`.
- AK2/`.mcp.json` nicht anfassen; `concept/**`/`stories/**` nicht im Code-Commit.
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Test-Namen (worker-blocked→FAILED+AttemptOutcome.BLOCKED, Residue unveraendert).

---

## Globale Akzeptanzkriterien (verbindlich)
- **GAC-1:** `scripts/ci/check_architecture_conformance.py` mit **0 Errors** (Exit 0).
- **GAC-2:** Architektur-Guardrails `guardrails/architecture-guardrails.md` eingehalten.
