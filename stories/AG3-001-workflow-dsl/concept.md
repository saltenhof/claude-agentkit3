# AG3-001: Workflow-DSL fuer die 5-Phasen-Pipeline

## Status

Entwurf -- bereit fuer Multi-LLM-Sparring

---

## Problemstellung

AgentKit v2 hat die gesamte Orchestrierungslogik in einer ~7.800-Zeilen-Datei (`phase_runner.py`). Das erzeugt vier zusammenhaengende Architekturprobleme:

1. **Workflow-Wissen und Ausfuehrungslogik sind vermischt.** Welche Transitions erlaubt sind und welche Guards gelten, steht in denselben Funktionen wie Artefakte laden, Evaluator konfigurieren, Bundles bauen und Telemetrie schreiben. Die Topologie ist nicht unabhaengig von der Ausfuehrung les- und testbar.

2. **Recovery-Regeln sind implizit.** Rehydration, Resume-Bedingungen und Fail-Closed-Semantik sind nicht als Architekturvertrag modelliert, sondern als verstreute Fallback-Logik im Code. Mehrere reale Bugs (z.B. `mode`-Verlust bei `phase-state.json`-Reset) sind direkte Folge.

3. **Story-Typ-Unterschiede werden ueber if/else-Branches im Hauptpfad abgebildet.** Jeder neue Story-Typ oder jede neue Variante (concept, research, bugfix) erfordert wachsende Sonderfall-Branches statt isolierter Workflow-Definitionen.

4. **Vertraege sind an mehreren Stellen gleichzeitig wahr, aber an keiner Stelle autoritativ.** Transition-Graph und Enforcement-Logik driften auseinander. Neue QA-Bausteine existieren in Tests/Helpern, aber nicht im Produktionspfad.

---

## Loesung: Programmatische Workflow-DSL

Die Loesung ist eine **Python Builder-API** (nicht YAML), die den Story-Lifecycle als typsicheres Workflow-Modell beschreibt.

### Kerneigenschaften

- **Python-Code, keine Konfiguration.** Guards sind Funktionsreferenzen, mypy prueft Signaturen, IDE bietet Autocomplete. Kein Turing-in-YAML-Risiko, keine zweite Sprache.
- **Leichtgewichtige State-Machine-Library (`transitions`) als Kern.** ~1500 Zeilen, keine Dependencies, MIT-Lizenz. Liefert Transition-Validierung, hierarchische Zustaende, Guard-Evaluation, State-Callbacks und Graph-Export.
- **DSL modelliert NUR Topologie.** States, Transitions, Guards, Gates, Yields, Hooks, Recovery-Regeln. Keine Prompt-Inhalte, keine GitHub-Details, keine Installer-Logik.
- **Ausfuehrungslogik bleibt in typisierten Phase-Handlern.** Die ~7.500 Zeilen Handler-Code (Artefakte laden, Evaluator konfigurieren, Bundles bauen) wandern in Phase-Handler mit explizitem Lifecycle, nicht in die DSL.

### Beispiel

```python
implementation_workflow = (
    Workflow("implementation")
    .phase("setup")
        .guard(preflight_passed)
        .on_complete(route_by_mode)
    .phase("exploration")
        .gate(exploration_exit_gate)
        .yield_to("orchestrator", on="awaiting_design_review")
        .yield_to("orchestrator", on="awaiting_design_challenge")
        .max_remediation_rounds(2)
    .phase("implementation")
        .precondition(exploration_gate_approved, when=mode_is_exploration)
        .on_blocked("escalate_worker_blocked")
    .phase("verify")
        .context_routing(
            post_exploration="structural_only",
            post_implementation="full_qa",
        )
        .max_feedback_rounds(3)
    .phase("closure")
        .precondition(verify_completed)
        .substates(["integrity", "merge", "close_issue", "metrics", "postflight"])
)
```

---

## Architekturentscheidungen (konvergiert im Multi-LLM-Sparring)

Die folgenden Entscheidungen wurden im Vorkonzept durch Claude, ChatGPT und Qwen erarbeitet und sind konvergiert.

### K1: Fail-closed, keine Compensation -- Eskalation statt Rollback

AgentKit ist fundamental fail-closed. Bei Inkonsistenz, Policy-Verstoss oder unloeslichem Constraint wird **eskaliert**, nicht kompensiert. Automatischer Rollback wuerde Telemetrie- und Audit-Traces verwaessern, KI-Artefakte in inkonsistenten Zwischenzustaenden belassen und das Governance-Prinzip "niemals stillschweigend fortfahren" untergraben.

Die DSL modelliert keine Compensation-Semantik, sondern explizite Eskalationspfade, Quarantaene-Zustaende und Human-Override-Vertraege. Technisches Cleanup (Locks loesen, temp Files aufraeumen, Worker-Prozesse terminieren) ist erlaubt, aber das ist Betriebshygiene, keine Workflow-Compensation.

Empirischer Beleg: REF-042 (Worker-Runaway) -- Worker bekommt BLOCKED-Exit, Phase wird ESCALATED, Mensch interveniert.

### K2: ORCHESTRATOR_REACTION_REGISTRY als Migrationskeim

Die bestehende `ORCHESTRATOR_REACTION_REGISTRY` -- eine Tabelle `(phase, status) -> suggested_reaction` -- ist der natuerliche Ausgangspunkt fuer die DSL-Migration. Sie ist bereits deklarativ genug, um die heutige Laufzeitsemantik sichtbar zu machen.

Bei AgentKit v3 (Greenfield) ist dies weniger direkt relevant, bleibt aber als Architekturprinzip bestehen: Workflows werden aus beobachteten Produktionspfaden abgeleitet, nicht aus Architektur-Aesthetik entworfen.

### K3: Yield-Punkte fuer Orchestrator-Kontrolluebergabe

Die DSL muss explizite Yield-Punkte modellieren -- kooperative Kontrolluebergabe zwischen Pipeline und Orchestrator. Die Exploration-Phase hat PAUSED/Resume-Zyklen, die der Orchestrator steuert (Agent spawnen, auf Completion warten, `run_phase()` erneut aufrufen).

```python
.phase("exploration")
    .yield_to("orchestrator",
        on="awaiting_design_review",
        resume_triggers=["agent_completed", "timeout_24h"],
        required_artifacts=["design-review-preliminary.json"],
        resume_mode="same_phase_reentry",
        timeout_policy="escalate_after_24h",
    )
```

Interpreter-Verhalten: Phase ausfuehren bis Yield-Punkt, strukturiertes `YieldResult` zurueckgeben, keine interne Warte-/Retry-Logik. Orchestrator uebernimmt, Resume erfolgt gegen persistierten `attempt_id` und `resume_input_contract`.

### K4: Hooks =/= Guards -- klare Trennung

Hooks (Branch-Guard, Orchestrator-Guard, Health-Monitor) sind ein paralleles Enforcement-Layer und duerfen NICHT als DSL-Guards modelliert werden.

- **DSL-Guards** beantworten: "Darf der Workflow fachlich fortschreiten?" (Zustandsevaluation, Artefaktpruefung)
- **Hooks** beantworten: "Darf diese Operation unter System-/Policy-/Safety-Regeln ausgefuehrt werden?" (Querschnittsthemen)

Die DSL definiert Einschubpunkte fuer Hooks (`pre_transition`, `post_transition`, `on_yield`, `on_escalate`), nicht die Hook-Logik selbst.

### V1: Gates als First-Class-Objekte

Gates sind nicht einfach boolesche Guards, sondern mehrstufige Entscheidungsprozesse mit eigener Identitaet. Jedes Gate hat Stages (mit Actor, Evidenz, Outcomes), Remediation-Regeln und eine deterministische Aggregation.

DSL definiert den Gate-Vertrag (Stufen, Actors, Evidenz, Outcomes). Ein separates Gate-Subsystem fuehrt aus (Evaluator-Runner, Challenger-Runner, Human-Approval-Mechanik). DSL owns contract, Gate engine owns execution.

### V2: Attempt-basierte Phase-Runs

Nicht nur ein Snapshot pro Phase, sondern mehrere Attempts (`phase-runs/verify/attempt-001.json`, `attempt-002.json`). Jeder Attempt enthaelt: Eintrittsgrund, Guard-Evaluations, Evidenz-Referenzen, Outcome, Folge-Transition. `phase-state.json` bleibt die aktuelle Sicht; die Attempts sind die autoritative Historie.

Die bestehende Artefakt-Invalidierung (stale/-Mechanik) wird auf `attempt_id` konsolidiert.

### V3: Kompilierte DSL mit Validierung

Die DSL wird in ein validiertes, typisiertes Modell kompiliert. Validatoren pruefen: unerreichbare States, widerspruechliche Transitionen, unvollstaendige Resume-Pfade, fehlende Artefakt-/Evidenzvertraege, Story-Typ-Varianten ohne vollstaendige Ableitung.

### V4: Kompositionelle Story-Typ-Workflows (base + mixins)

Story-Typ-Varianten per Komposition, nicht per Kopie:

- `base_workflow` -- gemeinsame Phasen
- `code_change_mixin` -- Worktree, Branch, Verify mit 4 QA-Schichten
- `verify_with_remediation_mixin` -- Feedback-Loop
- `human_gate_mixin` -- Human-Approval-Yield-Points

Dann: `implementation = base + code_change + verify_with_remediation`.

### V5: Phase-Handler-Lifecycle (on_enter/on_progress/on_exit/on_resume)

`phase_runner.py` wird zur Handler-Registry mit explizitem Lifecycle:

- `on_enter(ctx, state)` -- Initialisierung, Precondition-Check
- `on_progress(ctx, state)` -- Fortschrittsreporting, Heartbeats
- `on_exit(ctx, state)` -- Snapshot schreiben, Artefakte validieren
- `on_resume(ctx, state)` -- Rehydration, Yield-Contract pruefen

---

## Offene Fragen fuer Sparring

Die folgenden Fragen sollen mit ChatGPT, Grok und Qwen diskutiert werden, um das Feinkonzept vorzubereiten.

### 1. Builder-API Design

Wie sieht die konkrete Python-API aus? Drei Kandidaten stehen zur Diskussion:

- **Fluent Builder**: `Workflow("impl").phase("setup").guard(f).phase("verify")...` -- kompakt, aber Methoden-Ketten koennen bei komplexen Workflows unuebersichtlich werden.
- **Deklarative Klassen**: Jede Phase ist eine eigene Klasse mit expliziten Attributen -- mehr Boilerplate, aber bessere IDE-Unterstuetzung und klarere Struktur.
- **Decorator-basiert**: `@phase("setup")` auf Handler-Funktionen -- bindet Topologie an Ausfuehrung, was der Trennung widerspricht.

Welcher Ansatz skaliert am besten fuer 4-5 Story-Typen mit je 3-7 Phasen und unterschiedlichen Gate-/Yield-Konfigurationen?

### 2. `transitions`-Library

Ist `transitions` die richtige Wahl, oder gibt es bessere leichtgewichtige Alternativen fuer Python 3.11+? Bewertungskriterien:

- Hierarchische Zustaende (Composite States)
- Typisierbarkeit (mypy-kompatibel)
- Minimalismus (keine eigene Runtime/Infrastruktur)
- Aktive Wartung und Stabilitaet
- Graph-Export (Mermaid, GraphViz)

### 3. Guard-Signatur

Einheitliche Signatur `(ctx: StoryContext, state: PhaseState) -> GuardResult` oder differenzierte Signaturen je nach Guard-Typ?

- Einheitlich: einfacher, weniger Typen, aber Guards brauchen oft nur einen Teil des Kontexts.
- Differenziert: `@guard(source="phase_snapshot", phase="exploration")` -- praeziser, aber mehr Signatur-Varianten.
- Wie handhabt man Guards, die mehrere Quellen brauchen (Context + Artifact + Snapshot)?

### 4. Gate-Subsystem

Wie grenzt sich das Gate-Execution-Subsystem von der DSL ab? Konkret:

- DSL definiert Gate-Vertrag (Stages, Actors, Evidenz, Outcomes, Remediation-Regeln).
- Gate Engine fuehrt aus (Evaluator-Runner, Challenger-Runner, Human-Approval).
- Wo liegt die Schnittstelle? Ist es ein `GateExecutor`-Protokoll? Ein Event-basiertes Interface?
- Wie meldet die Gate Engine Teilergebnisse zurueck (Stage 1 bestanden, Stage 2 laeuft)?

### 5. Mixin-Komposition

Wie verhindert man inkonsistente Workflows bei freier Mixin-Kombination?

- `base + code_change + verify_with_remediation` ist sinnvoll.
- `base + human_gate` ohne `verify` koennte inkonsistent sein.
- Braucht es einen Compiler/Validator, der Mixin-Kombinationen gegen Invarianten prueft?
- Oder reichen Unit-Tests auf den konkreten Story-Typ-Workflows?

### 6. Persistenz

Wie wird der Workflow-State persistiert?

- Snapshot pro Transition? Delta-basiert? Event-Sourcing-artig?
- `phase-state.json` als aktueller State, `phase-runs/<phase>/attempt-NNN.json` als Historie -- reicht das?
- Wie wird atomare Persistenz sichergestellt (kein korrupter State bei Crash)?
- Zusammenspiel mit `context.json` (langlebig) vs. `phase-state.json` (fluechtig)?

### 7. Testbarkeit

Wie testet man den Workflow-Graphen selbst (nicht die Handler)?

- Property-based Testing fuer Transitions (z.B. "von jedem nicht-terminalen State ist mindestens ein Pfad zum Endzustand erreichbar")?
- Snapshot-Tests fuer den kompilierten Graphen (Regression bei Topologie-Aenderungen)?
- Wie testet man Guard-Interaktionen (Guard A + Guard B zusammen)?
- Wie testet man Yield/Resume-Zyklen isoliert?

---

## Scope

### IM Scope

- States, Transitions und der Workflow-Graph
- Guards und Preconditions (Signaturen, Quellen, Evaluation)
- Gates als First-Class-Objekte (Stages, Actors, Evidenz, Outcomes)
- Yield-Punkte und Resume-Contracts
- Hook-Einschubpunkte (pre/post_transition, on_yield, on_escalate)
- Recovery- und Rehydration-Regeln
- Story-Typ-Varianten und Mixin-Komposition
- Workflow-Validierung und -Kompilierung
- Zustandsmodell (StoryContext vs. PhaseState vs. PhaseSnapshot)

### NICHT im Scope

- Phase-Handler-Logik (was in on_enter/on_exit konkret passiert)
- Prompt-Inhalte und Prompt-Komposition
- GitHub-spezifische Details (Issue-API, Project-Board-Felder)
- Installer-/Upgrade-Logik
- Telemetry-Payloads im Detail
- CLI-Entrypoints

---

## Zielstruktur im Code

```
src/agentkit/pipeline/
    state.py          # PhaseState, Workflow-State-Modelle
    routing.py        # Story-Typ -> Workflow-Aufloesung
    engine.py         # Interpreter/Executor
    workflow/
        model.py      # DSL-Datenmodell (Workflow, Phase, Transition, Guard, Gate)
        builder.py    # Fluent Builder-API
        guards.py     # Guard-Definitionen
        gates.py      # Gate-Subsystem
        recovery.py   # Rehydration-/Recovery-Regeln
        validators.py # Workflow-Graph-Validierung
```
