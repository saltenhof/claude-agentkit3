# AG3-074: Ergebnisachse `terminal_state` + exit_class-Invarianten + Pflichttests

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** `story-lifecycle` (BC `story-contracts`, alleiniger Owner FK-59 der Vertragsachsen-Matrix) — die konsolidierte **Ergebnisachse** einer Story und die harten Gueltigkeits-/Ungueltigkeits-Invarianten zwischen den Achsen. **Diese Story besitzt ausschliesslich die Achsen-Typen, die Ableitungsfunktion und die Constraint-Funktion — keine Producer-, Status-Mutations- oder Orchestrierungslogik** (siehe §2.2).

**Quell-Konzepte (autoritativ):**
- `FK-59 §59.6.1` — konsolidierte Ergebnisachse `terminal_state` mit genau drei Werten: `Open` (Sammelkategorie aller nicht-terminalen Stories), `Done` (erfolgreich geliefert), `Cancelled` (administrativ beendet; **nie** durch normale Closure, §59.8 #4)
- `FK-59 §59.6.2` — `exit_class` ist **keine** freie Vertragsachse; nur unter `terminal_state=Cancelled` zulaessig; dokumentiert in offiziellen Exit-/Split-/Reset-Records; Beispiele `scope_split`, `viability_handoff`
- `FK-59 §59.8` — harte Ungueltigkeiten (fail-closed), insbesondere #2 (`Done` + `exit_class != null`) und #3 (`terminal_state != Cancelled` + `exit_class != null`); ferner #4 (`Cancelled` als Ergebnis **normaler Closure-Semantik**)
- `FK-59 §59.11` — kanonischer Persistenzschnitt: `exit_class` nur in offiziellen Exit-/Split-/Reset-Records, nicht als freies Story-Hauptfeld
- `FK-59 §59.12` — sechs namentlich mandatierte Pflichttests

---

## 1. Kontext / Ist-Zustand (belegt)

Die persistenten Vertragsachsen sind sauber, die **Ergebnisachse fehlt** und die `exit_class`-Invarianten sind ungebaut:

- `src/agentkit/story_context_manager/story_model.py:34-46` — `StoryStatus = Backlog|Approved|In Progress|Done|Cancelled` (StrEnum, Wire-Encoding mit Leerzeichen, z. B. `"In Progress"`). Das ist die **GitHub-/Board-Statusachse**, **nicht** die FK-59-konsolidierte Ergebnisachse: es gibt **kein** `Open` (im Code mappen drei Nicht-terminal-Werte Backlog/Approved/In Progress auf „nicht terminal"), und `terminal_state` existiert nicht als eigener Typ.
- `src/agentkit/pipeline_engine/engine.py:751` — der einzige `terminal_state`-Treffer ist eine **lokale** `PhaseState`-Variable, kein Story-Ergebnisachsen-Feld (NICHT mit der Story-Achse verwechseln).
- Grep `exit_class|ExitClass` ueber `src/agentkit` → **kein Modell, keine Validierung, keine Constraint**. Damit sind §59.8 #2/#3 unimplementiert.
- `src/agentkit/story_context_manager/models.py:402-426` — die `implementation_contract`-Restriktion (§59.8 #1) ist im Code durchgesetzt (`ValueError`, wenn `implementation_contract` nicht im erlaubten Profil-Set des `story_type` liegt); die konzeptmandatierten Tests (§59.12) existieren aber nicht (Grep der sechs Namen ueber `tests/` → No files found).
- `src/agentkit/story_context_manager/service.py:91-93` — `_TERMINAL_STATUSES = {Done, Cancelled}` existiert als Status-Begriff, ist aber NICHT die konsolidierte `terminal_state`-Achse (kein `Open`, kein `exit_class`-Bezug).

Reale Anknuepfungspunkte (FIX-THE-MODEL): die Ergebnisachse ist **abgeleitet** aus dem vorhandenen `StoryStatus` (Done→Done, Cancelled→Cancelled, alles andere→Open) — eine reine, typisierte Funktion ohne I/O. Es darf **keine** zweite persistente Statusachse neben `StoryStatus` entstehen (SINGLE SOURCE OF TRUTH).

Kontext-Konflikt-Check (Achsen sauber trennen):
- `terminal_state` ist **nicht** identisch mit `StoryStatus`. `StoryStatus` bleibt die Wire-/Board-Achse (mit `Backlog`/`Approved`/`In Progress`); `terminal_state` ist die konsolidierte Ergebnis-Sicht (`Open|Done|Cancelled`). `Open` ist eine Sammelkategorie, kein eigener administrativer Endzustand.
- **Reset-Zwischenstati sind heute KEINE `StoryStatus`-Werte.** Die in FK-53 §53.x konzeptionell gefuehrten administrativen Reset-Stati `RESETTING`/`RESET_FAILED` (`concept/technical-design/53_story_reset_service_recovery_flow.md`) existieren im realen `StoryStatus`-Enum (`story_model.py:34-46`) **nicht**; ihr Typ-Schnitt (ob als eigene `StoryStatus`-Member oder als separate administrative Achse) ist **AG3-071-Owner** (siehe §2.2) und in dieser Story **nicht** gebaut. AG3-071 hat zudem entschieden, dass der Reset-Pfad **kein** `Cancelled` und **kein** `exit_class` setzt (`stories/AG3-071-story-reset-service/story.md:92`) — Reset bleibt restartbar, also nicht-terminal. Folge fuer diese Story: die Ableitungsfunktion `derive_terminal_state(StoryStatus)` arbeitet **ausschliesslich** auf den realen `StoryStatus`-Membern; sie ist so geschnitten (`else → Open`), dass jeder kuenftige nicht-terminale Status (inkl. `RESETTING`/`RESET_FAILED`, falls AG3-071 sie spaeter als `StoryStatus`-Member einfuehrt) **automatisch** auf `Open` faellt. Ein Pflichttest gegen heute nicht existierende Enum-Werte wird **nicht** gefordert (kein Test gegen Phantom-Member); die Future-Kompatibilitaet wird ueber die `else → Open`-Erschoepfungsregel + einen typisierten Erschoepfungstest (jeder reale `StoryStatus`-Member ist abgedeckt, kein `else`-Loch) belegt.

## 2. Scope

### 2.1 In Scope
1. **`terminal_state`-Ergebnisachse (§59.6.1)** als typisierte Enum mit genau `Open|Done|Cancelled` (englisch). Bereitgestellt wird **eine reine, typisierte Ableitungsfunktion mit fester Signatur** `derive_terminal_state(status: StoryStatus) -> TerminalState` (kein I/O, keine zweite persistente Statusachse): `Done→Done`, `Cancelled→Cancelled`, **alle uebrigen realen `StoryStatus`-Member** (Backlog/Approved/In Progress) `→Open`. Die Funktion ist ueber alle realen `StoryStatus`-Member **erschoepfend** (keine `else`-Luecke); kuenftige nicht-terminale Member fallen automatisch auf `Open` (siehe §1 Kontext-Konflikt-Check). **Reset-Zwischenstati werden hier NICHT als neue Enum-Member eingefuehrt** (AG3-071-Owner).
2. **`exit_class`-Modell (§59.6.2/§59.11)** als typisierte Enum/StrEnum mit mindestens `scope_split`, `viability_handoff` (erweiterbar fuer weitere offizielle Abbruchklassen). `exit_class` wird **nur** in offiziellen Exit-/Split-Records gefuehrt, **nicht** als freies Story-Hauptfeld. (Diese Story liefert nur den **Typ**; das Setzen/Persistieren des Werts ist Producer-Sache, §2.2.)
3. **Fail-closed Constraint-Funktion (§59.8 #2/#3)** als **eine** zentrale, typisierte Validierungsfunktion mit fester Signatur (z. B. `validate_exit_class_constraints(terminal_state: TerminalState, exit_class: ExitClass | None) -> None`, raise on violation): (#2) `terminal_state=Done` + `exit_class != null` → unzulaessig; (#3) `terminal_state != Cancelled` + `exit_class != null` → unzulaessig (deckt u. a. `Open` + `exit_class` ab). Diese Funktion ist der gemeinsame Validierungs-Owner, den die `exit_class`-Producer (AG3-072/073) **konsumieren** koennen — sie wird hier gebaut, nicht von ihnen aufgerufen-erzwungen.
4. **#4-Constraint auf die normale Closure-Semantik begrenzt (§59.8 #4):** Diese Story stellt — als Achsen-/Invarianten-Owner — sicher, dass **die normale Closure** (`complete_story()`, aufgerufen aus dem Closure-Pfad) die Story-Ergebnisachse **ausschliesslich** auf `Done` fuehrt und **nie** auf `Cancelled`. Der Schutz ist als **Test gegen den realen Closure-Pfad** formuliert: `ClosurePhaseHandler` → `_transition_story_done()` → `complete_story()` erzeugt nur `Done` (`src/agentkit/closure/phase.py:326-334`, `:1082-1097`; `complete_story` `src/agentkit/story_context_manager/service.py:737-761`, einziger `In Progress -> Done`-Pfad). **Ausdruecklich KEINE globale Regel „nur Split/Reset/Exit duerfen `Cancelled` setzen"** — das waere eine Producer-/Orchestrierungs-Aussage und liegt ausserhalb dieser Story. Insbesondere bleibt der bestehende administrative Frontend-`cancel_story`-Pfad (`Backlog|Approved -> Cancelled`, `service.py:594-652`; Route `src/agentkit/story_context_manager/http/routes.py`) **unberuehrt und erlaubt** — er ist **kein** „normaler Closure"-Pfad und wird durch #4 **nicht** verboten. Die administrative `In Progress -> Cancelled`-Story-Exit-Transition ist AG3-073-Owner (§2.2).
5. **Die sechs mandatierten Pflichttests (§59.12)** mit exakt diesen Namen:
   - `test_implementation_contract_only_allowed_for_implementation`
   - `test_exit_class_only_allowed_when_terminal_state_cancelled`
   - `test_operating_mode_is_runtime_derived_not_story_persisted`
   - `test_binding_invalid_is_not_free_ai_augmented`
   - `test_integration_stabilization_is_not_third_operating_mode`
   - `test_phase_state_mode_is_execution_route_alias`
   Jeder Test prueft die in §59.8/§59.5 beschriebene Invariante real gegen den Produktivcode (kein Platzhalter, kein Skip). `test_implementation_contract_only_allowed_for_implementation` prueft die vorhandene Restriktion (`models.py:402-426`); die `operating_mode`/`binding_invalid`/`integration_stabilization`/`phase_state_mode`-Tests pruefen den vorhandenen Resolution-/Routing-Code (siehe §2.2), bauen ihn aber nicht neu.
6. **Eine importierbare, typisierte Read-/Ableitungs-Schnittstelle** statt einer offenen „ueberall verfuegbar"-Forderung: `derive_terminal_state(...)` (#1) ist die **einzige** kanonische Ableitung der Story-Ergebnis-Sicht und liegt im `story-contracts`-BC, ohne `StoryStatus` zu duplizieren. **Konkreter benannter (optionaler) Consumer-Hinweis, nicht in Scope dieser Story:** der KPI-/Dashboard-Lesepfad (`src/agentkit/kpi_analytics/dashboard/service.py:48-83`) fuehrt **heute** eine eigene `lifecycle_status → Kanban-Spalte`-Mapping-Logik mit Default-auf-`Cancelled` fuer unbekannte Werte; eine **Umstellung dieses Lesepfads auf `derive_terminal_state`** ist **nicht** Teil dieser Story (eigener Owner: KPI/Dashboard-Stories AG3-082/AG3-084, FK-60/FK-64) und wird nur als kuenftiger Consumer der hier gebauten Funktion benannt — diese Story liefert die importierbare Funktion, nicht die Consumer-Umbauten.

### 2.2 Out of Scope (mit Owner aus `_STORY_INDEX.md`)
- **`exit_class=viability_handoff`-Producer (Exit-Record/Dossier/`exit_gate`) + administrative `In Progress -> Cancelled`-Story-Exit-Transition + Run-Terminalitaet** — **AG3-073** (FK-58). AG3-073 **setzt** `Cancelled` administrativ ueber eine eigene gegatete `StoryService`-Transition und setzt `exit_class=viability_handoff` am Exit-Record; diese Story liefert nur die Achse + Constraint und **konsumiert** nichts davon. (AG3-073 §2.2 weist die konsolidierte Ergebnisachse + §59.8-Invarianten — inkl. #4 — ausdruecklich dieser Story zu.)
- **`exit_class=scope_split`-Producer (Split-Record), Ausgangs-Story `Cancelled`** — **AG3-072** (FK-54). AG3-072 setzt `Cancelled` + fuehrt `scope_split`; diese Story liefert Typ + Constraint.
- **Reset-Record/`reset_id` + Reset-Zwischenstati (`RESETTING`/`RESET_FAILED`)-Typ-Schnitt** — **AG3-071** (FK-53). AG3-071 hat entschieden, dass der Reset-Pfad **kein** `Cancelled`/`exit_class` setzt und restartbar bleibt (`stories/AG3-071-story-reset-service/story.md:60,:92`). Diese Story fuehrt die Reset-Stati daher **nicht** als `StoryStatus`/`terminal_state`-Member ein; falls AG3-071 sie als nicht-terminale `StoryStatus`-Member nachzieht, fallen sie ueber die `else → Open`-Regel automatisch auf `Open` (kein Eingriff hier noetig). **Reset ist heute KEIN `exit_class`-Producer** — FK-59 §59.6.2 nennt „Reset-Record" generisch als zulaessigen Trager; ein realer Reset-`exit_class`-Producer existiert in keiner Story.
- **`operating_mode`/`binding_invalid`-Resolution-Logik** — bereits vorhanden (`src/agentkit/control_plane/runtime.py:1977-1986` `_resolve_operating_mode`); diese Story **testet** nur die Invarianten (§59.12 `test_operating_mode_is_runtime_derived_not_story_persisted` / `test_binding_invalid_is_not_free_ai_augmented`), baut die Resolution nicht neu.
- **`execution_route`/`mode`/`fast`-Determination** — AG3-057/AG3-018 (vorhanden); §59.12 `test_phase_state_mode_is_execution_route_alias` testet die nicht-fast Standard-Familie gegen den vorhandenen Code (`mode` als `execution`/`exploration`-Alias; `fast` ist **kein** `execution_route`-Wert, FK-24 §24.3.2).
- **`integration_stabilization`-Maschinerie** — AG3-069 (FK-05); §59.12 `test_integration_stabilization_is_not_third_operating_mode` testet nur, dass es **kein** dritter Betriebsmodus ist (§59.8 #7), baut die Maschinerie nicht.

## 3. Akzeptanzkriterien
1. `terminal_state` existiert als typisierte Enum `Open|Done|Cancelled` und wird ueber die reine Funktion `derive_terminal_state(status: StoryStatus) -> TerminalState` **abgeleitet** (keine zweite persistente Statusachse). Test: `Done→Done`, `Cancelled→Cancelled`, jeder andere reale `StoryStatus`-Member (Backlog/Approved/In Progress) `→Open`; **Erschoepfungstest**: jeder Member von `StoryStatus` ist abgedeckt, es gibt keine `else`-Luecke (kuenftige nicht-terminale Member faellen damit garantiert auf `Open`). **Kein** Test gegen heute nicht existierende `RESETTING`/`RESET_FAILED`-Werte (AG3-071-Owner).
2. `exit_class` existiert als typisierte Enum mit mindestens `scope_split`/`viability_handoff`; es ist **kein** freies Story-Hauptfeld (Test/Assertion: das `Story`-/Vertragsmodell traegt kein `exit_class`-Feld — der Typ ist nur fuer offizielle Records vorgesehen).
3. Constraint #2 (`Done` + `exit_class`) ist ueber `validate_exit_class_constraints(...)` fail-closed unzulaessig (Negativtest: Aufruf mit `Done` + beliebiger `exit_class` → raise).
4. Constraint #3 (`!= Cancelled` + `exit_class`) ist fail-closed unzulaessig (Negativtest, u. a. `Open` + `exit_class` → raise; Positivtest: `Cancelled` + `exit_class` → kein raise; `Cancelled`/`Open`/`Done` + `None` → kein raise).
5. **#4 (auf normale Closure begrenzt):** der reale Closure-Pfad fuehrt die Ergebnisachse nur auf `Done`, nie auf `Cancelled` (Test gegen `ClosurePhaseHandler` → `_transition_story_done()` → `complete_story()`: nach Closure ist `derive_terminal_state(story.status) == Done`). **Abgrenzungs-/Regressionstest:** der bestehende administrative `cancel_story`-Pfad (`Backlog|Approved -> Cancelled`, `service.py:594-652`) bleibt erlaubt und wird durch diese Story **nicht** verboten (Test: `cancel_story` aus `Backlog`/`Approved` bleibt erfolgreich; `derive_terminal_state == Cancelled` ist dort ein **gueltiges** Ergebnis, weil es **kein** normaler Closure-Pfad ist). **Keine** globale „nur Split/Reset/Exit setzen Cancelled"-Assertion.
6. Alle sechs §59.12-Tests existieren **mit exakt den vorgegebenen Namen**, sind gruen und pruefen die jeweilige Invariante real (kein Skip, kein Stub).
7. Die Constraint-Validierung ist **eine** gemeinsame, typisierte Funktion mit fester Signatur, die von den `exit_class`-Producern (AG3-072/073) konsumiert werden kann (Test, der die Funktion direkt verprobt — Positiv + #2/#3-Negativ).
8. `derive_terminal_state` ist eine importierbare, reine Funktion im `story-contracts`-BC (Test: direkter Import + Aufruf, kein I/O, keine `StoryStatus`-Duplikation). Eine Umstellung des KPI-/Dashboard-Lesepfads ist **nicht** Teil dieser Story (Owner AG3-082/AG3-084).
9. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–9 erfuellt; giftige Codex-Review PASS; (Implementierung/Commit erst nach Execution-Plan-Freigabe — diese Story wird zunaechst nur autorisiert/reviewt).

## 5. Guardrail-Referenzen
- **FAIL-CLOSED:** jede ungueltige Achsenkombination (#2/#3) wird hart abgelehnt; kein grosszuegiges Tolerieren von `exit_class` ausserhalb `Cancelled`. #4 ist fail-closed **fuer die normale Closure** (Closure → nie `Cancelled`), ohne den administrativen `cancel_story`-Pfad zu brechen.
- **FIX-THE-MODEL / SINGLE SOURCE OF TRUTH:** `terminal_state` **abgeleitet** aus dem einen `StoryStatus`-Owner ueber die feste Signatur `derive_terminal_state(StoryStatus) -> TerminalState` — keine zweite persistente Statusachse; `exit_class` nur als Typ fuer offizielle Records (kein freies Hauptfeld, kein zweites exit_class-Modell neben den Producern).
- **SAUBERER STORY-CUT:** diese Story ist **Achsen- + Constraint-Owner**, **kein** Producer/Orchestrator. Status-Mutationen (`Cancelled`/`Done`-Setzen), Exit-/Split-/Reset-Records und Run-Terminalitaet liegen bei AG3-071/072/073 (§2.2). #4 ist als Closure-Pfad-Test formuliert, nicht als Producer-Regel.
- **TYPISIERT STATT STRINGS:** `terminal_state`/`exit_class` als Enums; die Invarianten als typisierte Constraint-Funktion, nicht als String-Vergleichskaskade.
- **ZERO DEBT:** die sechs Pflichttests sind real und gruen, nicht als TODO/Skip; die Ableitungs-/Constraint-Funktion ist real und importierbar.
- **ARCH-55:** alle Enum-Werte/Feldnamen/Funktions-/Testnamen englisch.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Kritische Anknuepfungspunkte (alle mit verifizierter Zeile, volle Pfade):
  - `src/agentkit/story_context_manager/story_model.py:34-46` (`StoryStatus` — **Quelle** der Ableitung, NICHT duplizieren, NICHT erweitern).
  - `src/agentkit/story_context_manager/service.py:91-93` (`_TERMINAL_STATUSES` — vorhandener Status-Begriff, aber **nicht** die konsolidierte Achse), `service.py:737-761` (`complete_story` — einziger `In Progress -> Done`-Pfad, Ziel des #4-Closure-Tests), `service.py:594-652` (`cancel_story` — administrativer `Backlog|Approved -> Cancelled`-Pfad, der durch #4 **nicht** verboten wird).
  - `src/agentkit/closure/phase.py:326-334` und `:1082-1097` (`ClosurePhaseHandler`-Step-4 → `_transition_story_done` → `complete_story`) — der reale Closure-Pfad fuer den #4-Test (AC5).
  - `src/agentkit/story_context_manager/models.py:402-426` (vorhandene `implementation_contract`-Restriktion — `test_implementation_contract_only_allowed_for_implementation` testet diese).
  - `src/agentkit/control_plane/runtime.py:1977-1986` (`_resolve_operating_mode` — operating_mode/binding_invalid; die `operating_mode`/`binding_invalid`-Tests pruefen diesen vorhandenen Code, bauen ihn nicht neu).
  - `src/agentkit/pipeline_engine/engine.py:751` (lokale `terminal_state`-`PhaseState`-Variable — NICHT die Story-Achse).
  - `src/agentkit/kpi_analytics/dashboard/service.py:48-83` (eigener Lifecycle→Spalte-Lesepfad mit Default-auf-`Cancelled`) — nur als kuenftiger Consumer der hier gebauten Funktion genannt; **Umbau nicht in dieser Story** (Owner AG3-082/AG3-084).
- Fallstrick: `terminal_state != StoryStatus`. `Open` ist eine Sammelkategorie, kein eigener administrativer Endzustand. Keine zweite persistente Achse anlegen, kein neuer `StoryStatus`-Member.
- Fallstrick: `RESETTING`/`RESET_FAILED` existieren **nicht** als reale `StoryStatus`-Werte (AG3-071-Owner). **Kein** Pflichttest gegen diese Phantom-Member; Future-Kompatibilitaet ueber die `else → Open`-Erschoepfungsregel + Erschoepfungstest belegen.
- Fallstrick: #4 ist **kein** globaler „nur Split/Reset/Exit setzen Cancelled"-Guard. Es ist ein Test gegen den **normalen Closure-Pfad** (Closure → nur `Done`); der administrative `cancel_story`-Pfad bleibt erlaubt; die administrative `In Progress -> Cancelled`-Story-Exit-Transition ist AG3-073-Owner.
- Fallstrick: die `exit_class`-Werte werden von AG3-072/073 **gesetzt**; diese Story liefert nur Typ + Constraint-Funktion, nicht die Producer. Reset (AG3-071) ist **kein** `exit_class`-Producer. Constraint-Funktion so schneiden, dass die Producer sie konsumieren koennen.
- Fallstrick: die sechs Testnamen sind **wortgleich** zu uebernehmen (§59.12), inkl. `test_phase_state_mode_is_execution_route_alias` (deckt nur die nicht-fast Standard-Familie; `fast` ist kein execution_route-Wert — FK-24 §24.3.2).
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, die sechs §59.12-Testnamen + die #2/#3-Negativtests + der #4-Closure-Test (AC5) + der `cancel_story`-Abgrenzungstest.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
