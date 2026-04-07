# AG3-001: Workflow-DSL fuer die 5-Phasen-Pipeline

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** Keine (Greenfield — nutzt Foundation-Layer aus Iteration 1)
**Quell-Konzept:** `_temp/konzept-workflow-dsl-state-architecture.md`, `concept.md` (diese Story)

---

## Kontext

AgentKit v3 braucht einen Workflow-Kern, der den Story-Lifecycle als typsicheres
Modell beschreibt. In v2 lag die gesamte Orchestrierungslogik in `phase_runner.py`
(~7.800 Zeilen) — Topologie und Ausfuehrungslogik vermischt, Recovery implizit,
Story-Typ-Unterschiede als if/else-Branches. Die Workflow-DSL trennt das:

- **DSL**: Was ist erlaubt? (States, Transitions, Guards, Gates, Yields)
- **Phase-Handler**: Was passiert konkret? (Artefakte, Evaluatoren, Telemetrie)

Die DSL ist Python-Code mit Builder-API, keine YAML-Konfiguration.
Guards sind Funktionsreferenzen, mypy prueft Signaturen.

---

## Scope

### In Scope

- Workflow-Datenmodell: `WorkflowDefinition`, `PhaseDefinition`, `TransitionRule`
- Builder-API: Fluent Builder zum Konstruieren von Workflows
- Guards: Typisierte Guard-Funktionen mit `GuardResult` (PASS/FAIL + Reason)
- Gates: First-Class-Objekte mit Stages, Actors, Evidenz, Outcomes, Remediation
- Yield-Punkte: `YieldPoint` mit Resume-Triggers und Resume-Input-Contract
- Hook-Einschubpunkte: `pre_transition`, `post_transition`, `on_yield`, `on_escalate`
- Story-Typ-Workflows: Konkrete Workflow-Definitionen fuer implementation, bugfix, concept, research
- Workflow-Validierung: Compiler prueft Erreichbarkeit, Transition-Konsistenz, Resume-Vollstaendigkeit
- Recovery-Regeln: Rehydration-Contract (welche Felder aus welcher Quelle)

### Out of Scope

- Phase-Handler-Implementierung (was on_enter/on_exit konkret tut)
- Pipeline-Engine/Interpreter (Ausfuehrung von Workflows)
- Prompt-Komposition, GitHub-Integration, Installer
- Telemetrie-Payloads
- CLI-Entrypoints

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|-------------|--------------|
| `src/agentkit/pipeline/__init__.py` | Modifiziert | Re-Exports der Workflow-API |
| `src/agentkit/pipeline/workflow/__init__.py` | Neu | Package-Init mit Public API |
| `src/agentkit/pipeline/workflow/model.py` | Neu | Datenmodell: WorkflowDefinition, PhaseDefinition, TransitionRule, YieldPoint, HookPoints |
| `src/agentkit/pipeline/workflow/builder.py` | Neu | Fluent Builder-API zum Konstruieren von Workflows |
| `src/agentkit/pipeline/workflow/guards.py` | Neu | GuardResult, Guard-Protokoll, Guard-Dekorator, konkrete Guards |
| `src/agentkit/pipeline/workflow/gates.py` | Neu | Gate, GateStage, GateResult — Gate-Vertrag (nicht Execution) |
| `src/agentkit/pipeline/workflow/recovery.py` | Neu | RehydrationRule, RecoveryContract — welche Felder aus welcher Quelle |
| `src/agentkit/pipeline/workflow/validators.py` | Neu | WorkflowValidator — Erreichbarkeit, Konsistenz, Resume-Vollstaendigkeit |
| `src/agentkit/pipeline/workflow/definitions.py` | Neu | Konkrete Workflows: implementation, bugfix, concept, research |
| `tests/unit/pipeline/workflow/test_model.py` | Neu | Unit-Tests fuer Datenmodell |
| `tests/unit/pipeline/workflow/test_builder.py` | Neu | Unit-Tests fuer Builder-API |
| `tests/unit/pipeline/workflow/test_guards.py` | Neu | Unit-Tests fuer Guards inkl. Negativpfade |
| `tests/unit/pipeline/workflow/test_gates.py` | Neu | Unit-Tests fuer Gate-Vertraege |
| `tests/unit/pipeline/workflow/test_validators.py` | Neu | Unit-Tests fuer Workflow-Validierung |
| `tests/unit/pipeline/workflow/test_definitions.py` | Neu | Unit-Tests fuer die 4 konkreten Workflows |
| `tests/unit/pipeline/workflow/test_transitions.py` | Neu | Uebergangsgraph vollstaendig verprobt (gueltige + ungueltige) |
| `tests/unit/pipeline/workflow/test_recovery.py` | Neu | Recovery/Rehydration-Tests |

---

## Akzeptanzkriterien

### Datenmodell

1. `WorkflowDefinition` enthaelt: `name: str`, `phases: list[PhaseDefinition]`, `transitions: list[TransitionRule]`, `hooks: HookPoints`. Es ist ein immutables Datenobjekt (frozen).
2. `PhaseDefinition` enthaelt: `name: str`, `guards: list[Guard]`, `gates: list[Gate]`, `yield_points: list[YieldPoint]`, `preconditions: list[Precondition]`, `max_remediation_rounds: int | None`, `substates: list[str]`.
3. `TransitionRule` enthaelt: `source: str`, `target: str`, `guard: Guard | None`, `resume_policy: str | None`. Transitions mit identischem `(source, target)` aber unterschiedlichen Guards sind erlaubt (erster passender Guard gewinnt).
4. `YieldPoint` enthaelt: `status: str` (z.B. "awaiting_design_review"), `resume_triggers: list[str]`, `required_artifacts: list[str]`, `timeout_policy: str | None`.
5. `HookPoints` enthaelt: `pre_transition: list[str]`, `post_transition: list[str]`, `on_yield: list[str]`, `on_escalate: list[str]`. Hook-Namen sind Strings (Referenzen auf externe Hook-Implementierungen).

### Guards

6. `GuardResult` ist ein Ergebnisobjekt mit `passed: bool` und `reason: str | None`. Konstruktion ueber `GuardResult.PASS()` und `GuardResult.FAIL(reason="...")`.
7. Guards sind Callables mit Signatur `(ctx: StoryContext, state: PhaseState) -> GuardResult`. Sie sind seiteneffektfrei — sie lesen und evaluieren, schreiben aber keinen State.
8. Ein `@guard`-Dekorator existiert, der Metadaten (Name, Beschreibung) an die Guard-Funktion bindet.
9. Mindestens diese Guards sind implementiert: `preflight_passed`, `exploration_gate_approved`, `verify_completed`, `mode_is_exploration`.

### Gates

10. `Gate` enthaelt: `id: str`, `stages: list[GateStage]`, `max_remediation_rounds: int`, `on_max_exceeded: str` (z.B. "escalate"), `final_aggregation: str` (z.B. "deterministic").
11. `GateStage` enthaelt: `name: str`, `actor: str`, `evidence: list[str]`, `outcomes: list[str]`, `condition: Guard | None` (optionale Vorbedingung fuer die Stage), `risk_triggers: list[str]`.
12. Die Gate-Datenstruktur definiert den **Vertrag**, nicht die Ausfuehrung. Es gibt keinen `GateExecutor` in dieser Story.

### Builder-API

13. Der Builder erzeugt ein `WorkflowDefinition` ueber eine Fluent-API: `Workflow("name").phase("setup").guard(f).phase("verify").transition("setup", "verify")...build()`.
14. `.build()` gibt ein immutables `WorkflowDefinition` zurueck. Mehrfaches `.build()` auf demselben Builder erzeugt unabhaengige Instanzen.
15. Der Builder validiert bei `.build()`: Alle Transition-Quellen und -Ziele muessen als Phasen definiert sein.
16. Der Builder unterstuetzt: `.phase()`, `.guard()`, `.gate()`, `.yield_to()`, `.precondition()`, `.transition()`, `.hooks()`, `.max_remediation_rounds()`, `.substates()`.

### Story-Typ-Workflows

17. Fuer jeden der 4 Story-Typen (implementation, bugfix, concept, research) existiert eine konkrete `WorkflowDefinition`.
18. `resolve_workflow(story_type: StoryType) -> WorkflowDefinition` gibt den passenden Workflow zurueck.
19. Der Implementation-Workflow enthaelt mindestens: setup, exploration, implementation, verify, closure — mit Guards fuer mode-abhaengiges Exploration-Routing und Yield-Punkten fuer Design-Review.
20. Der Bugfix-Workflow ueberspringt Exploration (kein `mode_is_exploration`-Guard, keine Exploration-Yields).

### Workflow-Validierung

21. `WorkflowValidator.validate(workflow)` gibt `list[ValidationError]` zurueck.
22. Validiert wird: (a) Jeder Transition-Source und -Target existiert als Phase, (b) von der ersten Phase ist jede andere Phase erreichbar, (c) mindestens eine Transition fuehrt zur letzten Phase, (d) kein Yield-Punkt ohne mindestens einen Resume-Trigger.
23. Ein Workflow mit unerreichbaren Phasen erzeugt einen `ValidationError`.

### Uebergangsgraph (Pipeline-Robustheitstest-Standard)

24. Fuer jeden der 4 Story-Typ-Workflows: Jede gueltige Transition wird in einem Test ausgefuehrt und bestaetigt.
25. Fuer jeden der 4 Story-Typ-Workflows: Jede ungueltige Transition (z.B. setup -> closure direkt) wird in einem Test versucht und die Ablehnung bestaetigt.
26. Fuer jede Phase mit Preconditions: Ein Test beweist, dass die Phase bei verletzter Precondition ablehnt.

### Recovery

27. `RecoveryContract` definiert fuer jedes semantische Feld (mode, story_type, etc.) die Rehydration-Reihenfolge: (1) expliziter Parameter, (2) context.json, (3) letzter Snapshot, (4) definierter Default.
28. Fehlende autoritative Quelle fuer ein semantisches Feld ist ein harter Fehler (kein stiller Fallback auf "wahrscheinlich execution").

### Qualitaet

29. Alle Module bestehen `ruff check` und `mypy --strict` ohne Fehler.
30. `from __future__ import annotations` in jedem Modul.
31. Google-style Docstrings auf allen public Funktionen und Klassen.

---

## Technische Details

### Abhaengigkeiten

- Foundation-Layer: `agentkit.story` (StoryType, StoryMode, StoryContext, PhaseState, PhaseStatus)
- Foundation-Layer: `agentkit.exceptions` (WorkflowError, TransitionError, GuardError, GateError)
- Externe Library: `transitions` (leichtgewichtige State-Machine, wird in pyproject.toml ergaenzt)

### Offene Designfragen (im Sparring zu klaeren)

Siehe `concept.md` Abschnitt "Offene Fragen fuer Sparring" — 7 Fragen zu Builder-API-Design,
`transitions`-Library-Wahl, Guard-Signatur, Gate-Subsystem-Grenze, Mixin-Komposition,
Persistenz und Testbarkeit.
