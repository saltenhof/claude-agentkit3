# AG3-001: Sparring Runde 1 — Architektur-Validierung

**Datum:** 2026-04-07
**Teilnehmer:** Claude (Opus 4.6), ChatGPT, Grok, Qwen
**Methodik:** 1 Runde unabhaengige Bewertung + Claude-Synthese

---

## Konvergenz (alle 3 LLMs einig)

### K1: Fluent Builder + Frozen IR

Alle drei empfehlen einen Fluent Builder als Authoring-Frontend ueber einem
immutablen Datenmodell (frozen dataclasses / Pydantic). Builder ist mutable,
`WorkflowDefinition` ist frozen. PhaseBuilder als scoped Sub-Builder.

**Entscheidung: Uebernommen.**

### K2: Einheitliche Guard-Signatur

Alle drei empfehlen `(ctx: StoryContext, state: PhaseState) -> GuardResult`.
Kein Signatur-Zoo. Context als read-only Facade.

ChatGPT ergaenzt: `@guard`-Decorator mit `reads={}`-Sets als Dokumentation.
Qwen ergaenzt: Lazy-Loading im Context fuer Artefakt-Zugriffe.

**Entscheidung: Einheitliche Signatur. `reads`-Sets als optionales Decorator-Attribut
(Dokumentation, nicht enforced). Lazy-Loading im Context fuer Artefakte.**

### K3: Compiler/Validator fuer Mixin-Komposition

Alle drei sagen: Freie Kombination ohne Validierung fuehrt zu Inkonsistenz.
ChatGPT: WorkflowFragments mit `requires/provides/forbids`.
Grok: Factory-Funktionen + Validator.
Qwen: Invariant-basierter Validator bei `.build()`.

**Entscheidung: WorkflowFragments mit requires/provides/forbids (ChatGPT).
`compose_workflow(name, *fragments)` als einziger Einstiegspunkt.
Compiler prueft Invarianten vor Rueckgabe.**

### K4: Hybride Persistenz

Alle drei empfehlen: Atomarer Current-State + append-only Historie.
`context.json` (langlebig) + `phase-state.json` (aktuell) +
`phase-runs/<phase>/attempt-NNN.json` (immutable).

**Entscheidung: Uebernommen. Atomarer Write via temp + os.replace() + fsync.**

---

## Divergenz

### D1: `transitions`-Library

| LLM | Position |
|-----|---------|
| ChatGPT | Nicht im Kern, optional als Adapter fuer Diagramme |
| Grok | Verwenden als Kern (HierarchicalGraphMachine) |
| Qwen | Gar nicht, eigener typisierter Graph |

**Analyse:** Grok steht allein. Die Gegenargumente ueberwiegen:
- `transitions` generiert Methoden dynamisch → kollidiert mit mypy strict
- Die DSL modelliert nur Topologie, kein FSM-Interpreter noetig
- Externe Library wird zum "Model" wenn man nicht aufpasst (ChatGPT)
- Bei 5-7 Phasen ist der Graph trivial genug fuer Eigenbau (Qwen)

**Entscheidung: Kein `transitions` im Kern. Eigener typisierter Graph.
Optional: `transitions`-Adapter fuer Mermaid/GraphViz-Export als
Extra-Dependency (`pip install agentkit[workflow-diagrams]`).**

### D2: Gate-Interface

| LLM | Position |
|-----|---------|
| ChatGPT | GateSpec → GateEvent-Stream → GateExecutionReport |
| Grok | Synchrones Protokoll: gate.execute() → GateResult |
| Qwen | Callback-basiert: on_progress(stage, status, evidence) |

**Analyse:** ChatGPTs Modell ist das sauberste fuer eine fail-closed Pipeline:
- Events sind append-only → Audit-Trail
- Teilergebnisse werden geschrieben, nicht zurueckgerufen
- Human-Approval-Stages erzeugen Yields, keine blockierenden Waits
- Groks synchrones Modell bricht bei mehrstufigen Gates mit Yield
- Qwens Callbacks sind mutable und nicht persistierbar

**Entscheidung: GateSpec als DSL-Vertrag, GateEvent als append-only Audit,
GateExecutionReport als aggregierte Sicht. GateRunner-Protocol in der
Engine-Schicht, nicht in der DSL.**

### D3: Property-based Testing

| LLM | Position |
|-----|---------|
| ChatGPT | Ja, auf kompilierter IR |
| Grok | Overkill, exhaustive Unit-Tests reichen |
| Qwen | Ja, mit Hypothesis |

**Analyse:** Bei 4 Story-Typen × je 5-7 Phasen × Guards × Modes ist der
State-Space klein genug fuer exhaustive Tests, ABER: Property-based Testing
deckt Invarianten ab, die bei manuellen Tests leicht vergessen werden
(z.B. "von jedem nicht-terminalen State existiert ein Pfad zum Endzustand").

**Entscheidung: Beides. Exhaustive Tests fuer die 4 konkreten Workflows
(alle gueltigen + ungueltigen Transitions). Property-based Tests fuer
harte Graph-Invarianten (Erreichbarkeit, Zyklenfreiheit, Yield-Vollstaendigkeit).**

---

## Zusammenfassung der Entscheidungen

| # | Frage | Entscheidung |
|---|-------|-------------|
| 1 | Builder-API | Fluent Builder + frozen IR (Konsens) |
| 2 | `transitions` | Nicht im Kern, optionaler Adapter (2:1) |
| 3 | Guard-Signatur | Einheitlich `(ctx, state) -> GuardResult` (Konsens) |
| 4 | Gate-Interface | GateSpec/GateEvent/Report (ChatGPT, bestaetigt) |
| 5 | Mixin-Komposition | WorkflowFragments + Compiler (ChatGPT, bestaetigt) |
| 6 | Persistenz | Hybrid: context.json + phase-state.json + attempts (Konsens) |
| 7 | Testbarkeit | Property-based + exhaustive + Snapshots + Kernel (2:1) |
