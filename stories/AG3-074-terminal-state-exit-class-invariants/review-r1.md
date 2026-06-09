OVERALL CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: WEAK**
- **ERROR**: `Cancelled` wird in der Story zu eng gefasst. FK-59 verbietet nur `Cancelled` als Ergebnis normaler Closure-Semantik (`concept/technical-design/59_story_contract_axes_and_combination_matrix.md:255-257`). Die Story fordert aber, `Cancelled` duerfe nur ueber Split/Reset/Exit-Records entstehen (`stories/AG3-074-terminal-state-exit-class-invariants/story.md:36`, `:59`). Das kollidiert mit dem bestehenden `cancel_story`-Pfad: `Backlog|Approved -> Cancelled` ist frontend-driven erlaubt (`src/agentkit/story_context_manager/service.py:80-85`, `:594-649`; HTTP-Route `src/agentkit/story_context_manager/http/routes.py:217-224`, `:409-426`).  
  **Fix**: #4 auf den Closure-Pfad begrenzen: normale Closure/`complete_story()` darf nur `Done` erzeugen. Bestehende administrative Cancel-Pfade entweder explizit aus AG3-074 ausnehmen oder separaten Owner/Record-Pfad definieren.

- **WARNING**: Reset-Zwischenstati sind widerspruechlich spezifiziert. Scope verlangt Mapping inkl. `RESETTING`/`RESET_FAILED` (`story.md:33`), AC1 relativiert mit “falls vorhanden” (`story.md:55`). Im realen `StoryStatus` existieren diese Werte nicht (`src/agentkit/story_context_manager/story_model.py:34-46`); FK-53 fuehrt sie konzeptionell als Reset-Status (`concept/technical-design/53_story_reset_service_recovery_flow.md:191-193`, `:322`).  
  **Fix**: Entweder AG3-071 als harte Dependency aufnehmen und den Typ-Schnitt fuer Reset-Stati definieren, oder die Tests fuer diese Werte explizit future-/conditional halten.

**AC-Schaerfe: WEAK**
- **ERROR**: AC5 ist in der aktuellen Form nicht eindeutig testbar ohne bestehende Cancel-Funktionalitaet zu brechen (`story.md:59`; `service.py:640-649`).  
  **Fix**: AC5 als Test gegen `ClosurePhaseHandler -> _transition_story_done() -> complete_story()` formulieren (`src/agentkit/closure/phase.py:326-332`, `:1082-1097`), nicht als globale “nur Split/Reset/Exit setzen Cancelled”-Regel.

- **WARNING**: AC6 ist zu offen: “ueberall dort verfuegbar, wo ... gebraucht wird (z. B. KPI/Dashboard)” (`story.md:45`) definiert keine konkrete Schnittstelle. Der aktuelle Dashboard-Lesepfad hat eigene Lifecycle-Mapping-Logik und defaultet unbekannte Werte auf `Cancelled` (`src/agentkit/kpi_analytics/dashboard/service.py:48-83`).  
  **Fix**: Konkrete Consumer benennen oder AC6 auf eine klar importierbare Ableitungs-/Read-Funktion beschraenken; Dashboard/KPI-Anpassung als eigener AC nur mit konkretem Modul/Verhalten.

**Klarheit: WEAK**
- **WARNING**: “abgeleitet aus `StoryStatus`” und gleichzeitig Reset-Stati abdecken ist typfachlich unklar (`story.md:33`, `:55`; `story_model.py:34-46`).  
  **Fix**: Signatur festlegen, z. B. `derive_terminal_state(status: StoryStatus) -> TerminalState`; falls Reset-Stati einbezogen werden sollen, separaten typisierten Input/Adapter benennen.

**Kontext-Sinnhaftigkeit: FAIL**
- **ERROR**: Die Story haelt den AG3-073-Split meist sauber (`story.md:47-52`, `:79`), verletzt ihn aber bei #4 durch implizite Orchestrierungs-/Producer-Aussage “nur ueber Split/Reset/Exit-Records” (`story.md:36`, `:59`). AG3-074 soll Achse + Constraints liefern; AG3-073 besitzt Story-Exit-Orchestration, FK-58 defers `exit_class` an FK-59 (`concept/technical-design/58_story_exit_human_takeover_handoff.md:13-16`) und beschreibt den Exit-Pfad separat (`:177-188`).  
  **Fix**: AG3-074 auf `terminal_state`/`exit_class`-Typen, Ableitung und Constraint-Funktion reduzieren; Producer-/Orchestrierungspfade nur als Konsumenten/Out-of-Scope referenzieren.

Gepruefte Ist-Zustand-Anker: `StoryStatus` existiert wie behauptet (`story_model.py:34-46`), `terminal_state` ist nur lokale `PhaseState`-Variable (`pipeline_engine/engine.py:751`, `:785`), `exit_class|ExitClass` hat keine Python-Treffer unter `src/agentkit`, die Implementation-Contract-Restriktion existiert (`story_context_manager/models.py:402-426`), `_TERMINAL_STATUSES` ist nur Done/Cancelled (`service.py:91-93`), und die sechs FK-59-Testnamen haben keine Treffer unter `tests/`.

**Must-Fix**
1. #4/AC5 so umformulieren, dass nur normale Closure nicht nach `Cancelled` gehen darf; bestehender `cancel_story`-Pfad darf nicht unbeabsichtigt verboten werden.
2. Reset-Stati-Umgang entscheiden: AG3-071-Dependency + Typ-Schnitt oder conditional/future-compatible ohne Pflicht-Test.
3. AC6 konkretisieren oder aus dem Scope nehmen; keine offene “ueberall wo gebraucht”-Anforderung.
4. AG3-074 konsequent als Achsen-/Constraint-Owner halten; keine Producer-/Exit-Orchestrierung in diese Story ziehen.
