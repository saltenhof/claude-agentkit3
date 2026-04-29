---
concept_id: FK-45
title: Phase Runner CLI und Phase-Transition-Enforcement
module: phase-runner-cli
domain: pipeline-framework
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: phase-runner-cli
  - scope: phase-dispatch
  - scope: phase-transition-enforcement
defers_to:
  - target: FK-20
    scope: workflow-engine
    reason: Engine-Mechanik, Feedback-Loop und Eskalationssemantik liegen in FK-20
  - target: FK-39
    scope: phase-state-persistence
    reason: Phase-State-Modell, PhaseEnvelope, PhaseMemory und AttemptRecord liegen in FK-39
  - target: FK-23
    scope: exploration-gate
    reason: Exploration-Gate-Semantik und ExplorationPayload liegen in FK-23
  - target: FK-37
    scope: verify-context
    reason: VerifyPayload und verify_context-Auswertung liegen in FK-37
  - target: FK-29
    scope: closure-precondition
    reason: Closure-Precondition (Verify COMPLETED) und ClosurePayload liegen in FK-29
  - target: FK-26
    scope: worker-blocked
    reason: worker-manifest.json und Worker-Blocked-Erkennung liegen in FK-26
  - target: FK-02
    scope: domain-model
    reason: Story-Lifecycle-Status-Werte und Phase-Enum liegen im Domänenmodell
  - target: FK-59
    scope: story-contract-classification
    reason: "`mode`/`execution_route`-Vertragsachse"
supersedes: []
superseded_by:
tags: [phase-runner, cli, state-machine, pipeline, orchestration]
prose_anchor_policy: strict
formal_refs:
  - formal.setup-preflight.entities
  - formal.setup-preflight.state-machine
  - formal.setup-preflight.invariants
  - formal.setup-preflight.scenarios
  - formal.implementation.state-machine
  - formal.implementation.commands
  - formal.implementation.events
  - formal.implementation.scenarios
  - formal.verify.state-machine
  - formal.verify.commands
  - formal.verify.events
  - formal.verify.scenarios
  - formal.story-workflow.commands
---

# 45 — Phase Runner CLI und Phase-Transition-Enforcement

<!-- PROSE-FORMAL: formal.setup-preflight.entities, formal.setup-preflight.state-machine, formal.setup-preflight.invariants, formal.setup-preflight.scenarios, formal.implementation.state-machine, formal.implementation.commands, formal.implementation.events, formal.implementation.scenarios, formal.verify.state-machine, formal.verify.commands, formal.verify.events, formal.verify.scenarios, formal.story-workflow.commands -->

## 45.1 Aufrufkonvention und Phasen-Dispatch

### 45.1.1 Aufrufkonvention

```bash
agentkit run-phase {phase} --story {story_id} [--config {path}]
```

Der Orchestrator-Skill ruft den Phase Runner für jede Phase
einzeln auf. Der Phase Runner führt die Phase aus, aktualisiert
den Phase-State und beendet sich. Der Orchestrator liest dann
den Phase-State und entscheidet, was als nächstes passiert.

### 45.1.2 Phasen-Dispatch

```python
def run_phase(phase: str, story_id: str, config: PipelineConfig) -> PhaseState:
    # Intern arbeitet run_phase() mit PhaseEnvelope (state + runtime);
    # der Rückgabewert PhaseState ist envelope.state (persistierbarer Teil).
    envelope = load_or_create_phase_state(story_id)  # gibt PhaseEnvelope zurück
    # Handler bekommen nur envelope.state (PhaseState), nicht den Envelope
    match phase:
        case "setup":
            return _phase_setup(envelope.state, story_id, config)
        case "exploration":
            return _phase_exploration(envelope.state, story_id, config)
        case "implementation":
            return _phase_implementation(envelope.state, story_id, config)
        case "verify":
            return _phase_verify(envelope.state, story_id, config)
        case "closure":
            return _phase_closure(envelope.state, story_id, config)
        case _:
            raise ValueError(f"Unknown phase: {phase}")
```

**Hinweis:** Vor dem Dispatch greift die
Phase-Transition-Enforcement (§45.2). `_phase_verify()`
wertet zusätzlich `payload.verify_context` aus, um die
QA-Tiefe zu bestimmen: Bei `POST_REMEDIATION` laufen die
Checks auf Basis der Remediation-Ergebnisse, bei
`POST_IMPLEMENTATION` die volle 4-Schichten-QA.
[Entscheidung 2026-04-09] `verify_context` ist kein
Top-Level-Feld mehr, sondern Teil des `VerifyPayload`
(siehe FK-39 §39.2, PhasePayload). `_phase_implementation()`
erkennt `status: BLOCKED` im `worker-manifest.json` und
setzt den Phase-Status auf ESCALATED mit
`escalation_reason: "worker_blocked"`. Siehe FK-39 §39.2 für
die Felddefinitionen, DK-02 §Verify-Kontext für die
Entscheidungsregeln.

## 45.2 Phase-Transition-Enforcement

`run_phase()` prüft bei jedem Aufruf den Phasenübergang gegen
den bestehenden `PHASE_TRANSITION_GRAPH`, bevor die Phase-Funktion
dispatched wird. Die Validierung ist fail-closed: ein ungültiger
Übergang führt zu ESCALATED, die Phase wird nicht betreten.

**Ablauf der Transition-Validierung:**

1. `run_phase()` liest das `phase`-Feld aus der persistierten
   `phase-state.json` als `from_phase` und das `status`-Feld
   als `from_status`.
2. **Resume derselben Phase:** Wenn `from_phase == to_phase`
   (z.B. Exploration nach PAUSED — awaiting_design_review),
   ist das kein Phasenübergang. Der Transition-Graph wird
   nicht konsultiert, der Aufruf wird durchgelassen.
3. **Graphen-Enforcement:** Bei `from_phase != to_phase` wird
   `is_valid_phase_transition(from_phase, to_phase)` aufgerufen.
   Ist der Übergang nicht im Graphen → PIPELINE_ERROR, Status
   ESCALATED.
4. **Status-Prüfung der Vorphase:** Die Vorphase muss COMPLETED
   sein. Ausnahmen:
   - **Remediation-Pfad** (`verify` → `implementation`): auch bei
     `from_status: FAILED` erlaubt, sofern
     `memory.verify.feedback_rounds < policy.max_feedback_rounds`.
     Verify hat FAIL zurückgeliefert, der Remediation-Worker
     bessert die Implementation nach. [Entscheidung 2026-04-09]
   - **Resume-Pfad**: `PAUSED` → Fortsetzung derselben Phase
     (wird bereits in Schritt 2 behandelt, kein Phasenübergang).
   - `ESCALATED` ist ein **Endzustand** — keine weitere Transition
     erlaubt. Mensch muss erst `reset-escalation` ausführen.
   - Von `verify` zu `closure` ausschließlich bei COMPLETED.
   [Korrektur 2026-04-09: `exploration` aus der Ausnahmeliste
   entfernt — kein Rücksprung von verify zu exploration, siehe
   Entscheidung 2026-04-09 in FK-20 §20.2.2.]
5. **Erstaufruf ohne State-Datei:** Existiert keine
   `phase-state.json`, darf ausschließlich `setup` aufgerufen
   werden. Jede andere Phase → PIPELINE_ERROR.

**Semantische Preconditions (zusätzlich zum Graphen):**

Der Graph allein reicht nicht aus. Modusabhängige Bedingungen
werden nach der Graphen-Validierung geprüft:

- `mode="exploration"` + `phase="implementation"` +
  **Transition von `exploration`** (erster Eintritt):
  `payload.gate_status` muss `APPROVED` sein
  [Entscheidung 2026-04-09: Feld in ExplorationPayload verschoben].
  Ohne bestandenes Exploration-Gate wird die
  Implementation-Phase nicht betreten. Defense-in-Depth: Diese
  Prüfung ergänzt den bestehenden Guard in `_phase_verify()`,
  der als zweite Verteidigungslinie erhalten bleibt.
  [Entscheidung 2026-04-09] **Nicht bei Remediation:** Bei der
  Transition `verify → implementation` (Remediation-Pfad) wird
  `payload.gate_status` NICHT erneut geprüft. Das Gate wurde
  bereits beim ersten Eintritt in die Implementation-Phase
  bestanden und liegt in der History. Eine erneute Prüfung wäre
  semantisch falsch, da der ExplorationPayload nach dem
  Phasenwechsel zu Implementation nicht mehr aktiv ist.

> **[Entscheidung 2026-04-09]** Der Gate-String `"approved_for_implementation"` ist ein v2-Artefakt. In v3 wird `ExplorationPayload.gate_status == ExplorationGateStatus.APPROVED` geprüft. Der Guard `exploration_gate_approved` liest diesen Wert aus dem Payload der aktuellen Phase. Siehe FK-23 §23.5.0.

- `phase="closure"`:
  - Bei Implementation/Bugfix-Stories: Verify muss mit Status COMPLETED
    abgeschlossen sein. Ohne abgeschlossene Verify-Phase darf
    Closure nicht starten.
  - Bei Concept/Research-Stories: Keine Verify-Precondition — diese
    Stories haben keine Verify-Phase (FK-20 §20.2.3).

  > [Korrektur 2026-04-09: Closure-Precondition Story-Type-abhängig — Concept/Research haben keine Verify-Phase (FK-20 §20.2.3).]

**Diagnostische Fehlermeldungen:**

Jede Ablehnung enthält: `from_phase`, `to_phase`, `from_status`,
die erlaubten Übergänge und bei semantischen Preconditions den
aktuellen Wert des fehlenden Feldes. Der Orchestrator und der
menschliche Reviewer können aus der Meldung ablesen, was falsch
ist und welcher Schritt als nächstes korrekt wäre.

```python
# Pseudocode — Transition-Enforcement in run_phase()
def run_phase(phase: str, story_id: str, config: PipelineConfig) -> PhaseState:
    if phase not in _VALID_PHASES:
        raise ValueError(...)

    # --- Transition-Enforcement ---
    ps_path = qa_dir / "phase-state.json"

    if ps_path.exists():
        persisted = json.loads(ps_path.read_text(encoding="utf-8"))
        from_phase = persisted.get("phase", "")
        from_status = persisted.get("status", "")

        # Resume derselben Phase ist kein Übergang
        if from_phase != phase:
            if not is_valid_phase_transition(from_phase, phase):
                # PIPELINE_ERROR: ungültiger Übergang
                ...

            # Status-Prüfung der Vorphase [Entscheidung 2026-04-09]
            is_remediation = (from_phase == "verify" and phase == "implementation")
            if is_remediation:
                # Remediation-Pfad: FAILED erlaubt (Verify hat FAIL geliefert)
                # [Entscheidung 2026-04-09] Guard-Check VOR Inkrement:
                # feedback_rounds enthält den aktuellen Wert (noch nicht inkrementiert).
                # Prüfung bei 0, 1, 2 → allow (3 zulässige Runden).
                # Prüfung bei 3 → deny (max erreicht).
                # Inkrement erfolgt NACH bestandenem Guard, VOR der Transition.
                memory = persisted.get("memory", {})
                rounds = memory.get("verify", {}).get("feedback_rounds", 0)
                max_rounds = config.policy.max_feedback_rounds
                if from_status != "FAILED" or rounds >= max_rounds:
                    # PIPELINE_ERROR: kein gültiger Remediation-Übergang
                    ...
                # Guard bestanden → Inkrement JETZT (nach Check, vor Transition)
                memory["verify"]["feedback_rounds"] = rounds + 1
                # [Korrektur 2026-04-09] Persistierung VOR Transition —
                # ohne diesen Schritt würde load_or_create_phase_state()
                # den Inkrement überschreiben.
                save_phase_state(story_id, persisted)
            elif from_status != "COMPLETED":
                # Normale Vorwärts-Transition: nur aus COMPLETED
                ...

        # Semantische Preconditions [Entscheidung 2026-04-09: Payload-Pfad]
        # [Entscheidung 2026-04-09] gate_status-Check nur bei exploration→implementation
        # (erster Eintritt), NICHT bei verify→implementation (Remediation).
        is_first_entry = (from_phase == "exploration")
        if phase == "implementation" and persisted.get("mode") == "exploration" and is_first_entry:
            payload = persisted.get("payload", {})
            gate = payload.get("gate_status", "PENDING")
            if gate != "APPROVED":
                # PIPELINE_ERROR: Gate nicht bestanden
                ...
        # [Entscheidung 2026-04-09] Der Gate-String "approved_for_implementation" ist ein v2-Artefakt.
        # In v3 wird ExplorationPayload.gate_status == ExplorationGateStatus.APPROVED geprüft.
        # Der Guard exploration_gate_approved liest diesen Wert aus dem Payload der aktuellen Phase.
        if phase == "closure":
            # Verify muss COMPLETED sein
            ...
    else:
        # Keine State-Datei: nur setup erlaubt
        if phase != "setup":
            # PIPELINE_ERROR
            ...
    # --- Ende Transition-Enforcement ---

    # [Korrektur 2026-04-09] load_or_create_phase_state() gibt PhaseEnvelope zurück.
    # Liest hier den BEREITS PERSISTIERTEN State (inkl. ggf. inkrementiertem
    # feedback_rounds). Im Remediation-Pfad wurde save_phase_state()
    # oben bereits aufgerufen — der Inkrement ist auf Platte und wird
    # hier korrekt zurückgelesen. Kein Datenverlust.
    envelope = load_or_create_phase_state(story_id)
    # Dispatch zur Phase-Funktion (Handler bekommt envelope.state) ...
```

**Nicht blockierte Pfade:**

- PAUSED→Resume derselben Phase (z.B. Exploration wird nach
  Design-Review-Completion erneut aufgerufen)
- Verify→Implementation (Remediation nach Verify-FAIL)

[Korrektur 2026-04-09] Der Pfad Verify→Exploration
(Impact-Violation im Exploration Mode) wurde entfernt.
Impact-Violation führt zu `status: ESCALATED`, nicht zu einem
Rücksprung in die Exploration-Phase. Siehe Entscheidung
2026-04-09 in FK-20 §20.2.2.

Referenz: DK-02 §Phase-Transition-Enforcement, FK-23 §23.4
(Exploration-Gate-Semantik).

## 45.3 Phasen-Ergebnisse und Orchestrator-Reaktion

| Phase | Ergebnis im Phase-State | Orchestrator reagiert |
|-------|------------------------|----------------------|
| `setup` COMPLETED | `mode: execution` oder `exploration`, `agents_to_spawn: [worker]` | Spawnt Worker (oder Exploration-Worker bei Exploration Mode) |
| `setup` ESCALATED | `escalation_reason: "preflight_fail"`, `errors: [...]` | Eskalation an Mensch — Preflight-Checks fehlgeschlagen, kein automatischer Remediation-Pfad (FK-20 §20.6.1). |
| `exploration` COMPLETED | `agents_to_spawn: [worker]` | Spawnt Implementation-Worker |
| `exploration` PAUSED | `pause_reason: "awaiting_design_review"` oder `"awaiting_design_challenge"` | Orchestrator wartet auf externe Klärung (Design-Review bzw. Design-Challenge). Resume nach Abschluss via `agentkit resume`. [Entscheidung 2026-04-09: PAUSED-Ergebnis ergänzt — Exploration nutzt PAUSED zentral für Design-Review und Design-Challenge.] |
| `exploration` ESCALATED | `escalation_reason: "doc_fidelity_fail"` oder `"design_review_rejected"` | Eskalation an Mensch. Auslöser: (1) Dokumententreue FAIL (doc_fidelity_fail), (2) Design-Review FAIL non-remediable oder Rundenlimit überschritten (gate_status = REJECTED → design_review_rejected). [Entscheidung 2026-04-09: Design-Review-Terminalpfad gemäß FK-23 §23.5 Stufe 2c ergänzt; `errors`-Feld durch `escalation_reason` ersetzt für Konsistenz mit anderen ESCALATED-Zeilen.] |
| `implementation` COMPLETED | `agents_to_spawn: []` | Ruft `run-phase verify` auf |
| `implementation` ESCALATED | `escalation_reason: "worker_blocked"`, Blocker-Details aus `worker-manifest.json` | Eskalation an Mensch. Worker hat unlösbaren Constraint gemeldet (z.B. Hook-Barriere, fehlende Dependency). |
| `verify` COMPLETED | `status: COMPLETED` | Ruft `run-phase closure` auf |
| `verify` FAILED | `status: FAILED`, `agents_to_spawn: []` | [Korrektur 2026-04-09] Verify liefert FAILED mit aktuellem (nicht-inkrementiertem) `memory.verify.feedback_rounds`. Orchestrator ruft `run-phase implementation` auf — der **Phase Runner (Engine)** prüft dabei den Guard (Pre-Check VOR Inkrement), inkrementiert `feedback_rounds` nach bestandenem Guard, persistiert via `save_phase_state()` und führt die Transition `verify → implementation` aus. Verify selbst spawnt keinen Agent — der Remediation-Worker wird in der Implementation-Phase gespawnt (nach dem Phasenwechsel). Implementation-Phase liefert `agents_to_spawn: [remediation_worker]`. Nach Abschluss: `run-phase verify` (normaler Vorwärts-Übergang implementation→verify). |
| `verify` ESCALATED | `escalation_reason: "max_rounds_exceeded"` / `"doc_fidelity_fail"` / `"impact_violation"` | Eskalation an Mensch. Auslöser: (1) Max Feedback-Runden erschöpft, (2) Dokumententreue Ebene 3 FAIL (Umsetzungstreue), (3) Impact-Violation (Issue-Metadaten falsch deklariert). [Entscheidung 2026-04-09: Beschreibung um Dokumententreue-FAIL und Impact-Violation erweitert — waren in FK-20 §20.6.1 dokumentiert, fehlten in der Übersichtstabelle.] |
| `closure` COMPLETED | `payload.progress: {alle true}` | Story ist Done |
| `closure` ESCALATED | `escalation_reason: "integrity_fail"` oder `"merge_fail"` | Eskalation an Mensch. [Korrektur 2026-04-09: `errors`-Feld durch `escalation_reason` ersetzt für Konsistenz mit anderen ESCALATED-Zeilen.] |
