OVERALL CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: WEAK**

- ERROR: Transition-Owner ist unscharf bzw. falsch geschnitten. Die Story fordert `PHASE_TRANSITION_GRAPH` als “Single source im Phase-Runner/`pipeline_engine`” (`stories/AG3-060.../story.md:29`), aber der reale FK-45-Eintrittspfad sitzt bereits in `control_plane/dispatch.py` und nutzt workflow-spezifische Kanten/Guards (`src/agentkit/control_plane/dispatch.py:306`, `src/agentkit/control_plane/dispatch.py:393`). Die tatsächlichen Kanten sind story-typ-spezifisch (`src/agentkit/process/language/definitions.py:93`, `:116`, `:134`, `:151`).  
  Fix: Story muss den Owner klar setzen: entweder Graph/Funktion als shared FK-45-Helper, den `control_plane.dispatch` konsumiert, oder explizit aus `WorkflowDefinition` ableiten. Kein statischer zweiter Graph, der `setup -> exploration` global erlaubt.

- ERROR: ESCALATED-Semantik ist nicht ausreichend spezifiziert. FK-45 und Story verlangen bei ungültigem Übergang ESCALATED (`concept/technical-design/45_phase_runner_cli.md:151`, `stories/.../story.md:31`, `:46`), real liefert der Dispatch vor Engine-Eintritt `status="rejected"` ohne Dispatch (`src/agentkit/control_plane/dispatch.py:549`).  
  Fix: AC muss festlegen, ob AG3-060 die bestehende Dispatch-Contract-Semantik auf ESCALATED ändert, ob ein `PhaseState`/`AttemptRecord` persistiert wird, und welche Tests den neuen Contract beweisen.

**AC-Schaerfe: FAIL**

- ERROR: AC 4/5 testen nur den abstrakten Graphen, aber nicht die workflow-spezifischen Guards/Edge-Ordering-Regeln. Bestehender Dispatch spiegelt “first passing edge wins” (`src/agentkit/control_plane/dispatch.py:430`) und darf z. B. für Bugfix/Concept/Research kein `setup -> exploration` zulassen (`src/agentkit/process/language/definitions.py:116`, `:134`, `:151`).  
  Fix: AC ergänzen: `setup -> exploration` ist nur bei Implementation+Exploration-Mode zulässig; Bugfix/Concept/Research müssen fail-closed/rejected/escalated bleiben. Edge-ordering von `_first_passing_edge` muss regression-getestet werden.

- WARNING: `OverrideType`-Owner ist offen formuliert: “Owner in `core_types` (oder `process/language`)” (`stories/.../story.md:27`). Das widerspricht dem eigenen SSOT-Ziel (`stories/.../story.md:56`).  
  Fix: Einen Owner festlegen, z. B. `core_types`, und Re-Exports/Imports explizit benennen.

**Klarheit: WEAK**

- WARNING: Ist-Zustand-Anchor ist teilweise falsch/irreführend. Die Story nennt `_check_preconditions` in `pipeline_engine/engine.py:192-303` (`stories/.../story.md:18`), aber dort existiert `_evaluate_transitions` und `_can_enter_phase`, keine `_check_preconditions` (`src/agentkit/pipeline_engine/engine.py:192`, `src/agentkit/pipeline_engine/engine.py:209`).  
  Fix: Anchor korrigieren und den realen Dispatch-Pfad `control_plane/dispatch.py:_enforce_transition` aufnehmen.

- NIT: `OverridePolicy` wird in der Ist-Zustand-Beschreibung nur mit drei Booleans genannt (`stories/.../story.md:17`), real existieren sechs (`src/agentkit/process/language/model.py:83`).  
  Fix: Liste vollständig machen oder explizit “u. a.” schreiben.

**Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Die Story behauptet “keine Doppel-Implementierung” (`stories/.../story.md:31`, `:62`), fordert aber gleichzeitig einen neuen `PHASE_TRANSITION_GRAPH` als Single Source im `pipeline_engine`, während `WorkflowDefinition`/`dispatch._enforce_transition` schon die operative Transition-Wahrheit tragen (`src/agentkit/control_plane/dispatch.py:417`, `src/agentkit/process/language/model.py:227`).  
  Fix: Graph darf nicht unabhängig gepflegt werden. Entweder aus `workflow.get_transitions_from(...)` ableiten oder als reine Phase-Superset-Prüfung vor der bestehenden workflow-spezifischen Prüfung deklarieren.

**Must-Fix**

1. Transition-Owner und Einbaupunkt korrigieren: `control_plane.dispatch`/Phase-Runner realistisch einbeziehen.
2. ESCALATED-vs-`rejected`-Contract entscheiden und in Scope/AC/Testpflicht konkretisieren.
3. Statischen `PHASE_TRANSITION_GRAPH` gegen workflow-spezifische Kanten absichern oder daraus ableiten.
4. `OverrideType`-Owner eindeutig festlegen.
5. Falschen `_check_preconditions`-Anchor und unvollständige `OverridePolicy`-Beschreibung korrigieren.
