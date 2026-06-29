---
concept_id: FK-45
title: Phase Runner Service mit Recovery-CLI
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
    reason: ImplementationPayload (verify_context, qa_cycle_status) und Subflow-interne verify_context-Auswertung liegen in FK-37
  - target: FK-29
    scope: closure-precondition
    reason: Closure-Precondition (Implementation COMPLETED, inkl. QA-Subflow PASS) und ClosurePayload liegen in FK-29
  - target: FK-26
    scope: worker-blocked
    reason: worker-manifest.json und Worker-Blocked-Erkennung liegen in FK-26
  - target: FK-02
    scope: domain-model
    reason: Story-Lifecycle-Status-Werte und Phase-Enum liegen im Domänenmodell
  - target: FK-59
    scope: story-contract-classification
    reason: "`mode`/`execution_route`-Vertragsachse"
  - target: FK-91
    scope: api-call-parameters
    reason: Normative Aufruf-Parameter (story_id, phase, mode, op_id) fuer den Service-API-Eintrittspunkt liegen in FK-91 §91.1a
supersedes: []
superseded_by:
tags: [phase-runner, api, cli, state-machine, pipeline, orchestration]
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
glossary:
  exported_terms:
    - id: node-execution
      definition: >
        Einzelner deterministischer Ausfuehrungsschritt eines Knotens
        (NodeDefinition) innerhalb einer FlowDefinition. Der Phase
        Runner dispatcht den passenden StepHandler, empfaengt ein
        StepResult und wendet den Zustandsuebergang an. NodeExecution
        ist immer durch ExecutionPolicy, RetryPolicy und OverridePolicy
        begrenzt.
  internal_terms:
    - id: phase-transition-enforcement
      reason: >
        Interner Validierungsschritt in run_phase(), der Graphen-
        und Status-Validierung sowie semantische Preconditions vor dem
        Phase-Dispatch prueft. Implementierungsdetail des Phase Runners;
        der exportierte Begriff ist phase-transition (FK-20).
---

# 45 — Phase Runner Service mit Recovery-CLI

<!-- PROSE-FORMAL: formal.setup-preflight.entities, formal.setup-preflight.state-machine, formal.setup-preflight.invariants, formal.setup-preflight.scenarios, formal.implementation.state-machine, formal.implementation.commands, formal.implementation.events, formal.implementation.scenarios, formal.verify.state-machine, formal.verify.commands, formal.verify.events, formal.verify.scenarios, formal.story-workflow.commands -->

## 45.1 Service-API-Eintrittspunkt und Phasen-Dispatch

Der Standard-Eintrittspunkt fuer den Phase Runner ist die
Control-Plane-API (FK-91 §91.1a). Agents und der Orchestrator-Skill
verwenden ausschliesslich diese API. Die normative
Aufruf-Parameterdefinition (story_id, phase, mode, op_id) liegt
in FK-91 §91.1a als Schema-Owner.

### 45.1.1 Service-API-Aufruf (Standard)

```
POST /v1/story-runs/{run_id}/phases/{phase}/start
Body: { "story_id": "ODIN-042", "mode": "execution" }
```

Der Orchestrator-Skill ruft den Phase Runner fuer jede Phase
einzeln ueber die Control-Plane-API auf. Der Phase Runner fuehrt
die Phase aus, aktualisiert den Phase-State und gibt eine normierte
Antwort zurueck. Der Orchestrator liest den Phase-State und
entscheidet, was als naechstes passiert.

### 45.1.2 Interner Phasen-Dispatch

```python
def run_phase(phase: str, story_id: str, config: PipelineConfig) -> PhaseState:
    # Intern arbeitet run_phase() mit PhaseEnvelope (state + runtime);
    # der Rueckgabewert PhaseState ist envelope.state (persistierbarer Teil).
    envelope = load_or_create_phase_state(story_id)  # gibt PhaseEnvelope zurueck
    # Handler bekommen nur envelope.state (PhaseState), nicht den Envelope
    match phase:
        case "setup":
            return _phase_setup(envelope.state, story_id, config)
        case "exploration":
            return _phase_exploration(envelope.state, story_id, config)
        case "implementation":
            return _phase_implementation(envelope.state, story_id, config)
        case "closure":
            return _phase_closure(envelope.state, story_id, config)
        case _:
            raise ValueError(f"Unknown phase: {phase}")
```

> Der QA-Subflow
> laeuft als interner Bestandteil von `_phase_implementation()` gegen
> die Capability `VerifySystem` (FK-27, BC verify-system). Vier
> Top-Phasen: `setup`, `exploration`, `implementation`, `closure`.
> Siehe `concept/_meta/bc-cut-decisions.md` "Verify als Capability
> (Variante Y)".

**Hinweis:** Vor dem Dispatch greift die
Phase-Transition-Enforcement (§45.2). `_phase_implementation()`
wertet zusaetzlich `payload.verify_context` (auf
`ImplementationPayload`) aus, um die QA-Tiefe des Subflows zu
bestimmen: Bei `POST_REMEDIATION` laufen die Checks auf Basis der
Remediation-Ergebnisse, bei `POST_IMPLEMENTATION` der volle
4-Schichten-QA-Subflow.
`verify_context`
ist kein Top-Level-Feld mehr, sondern Teil des
`ImplementationPayload` (vormals `VerifyPayload`; siehe FK-39 §39.2,
PhasePayload). `_phase_implementation()` erkennt zudem
`status: BLOCKED` im `worker-manifest.json` und setzt den
Phase-Status auf ESCALATED mit
`escalation_reason: "worker_blocked"`. Siehe FK-39 §39.2 fuer die
Felddefinitionen, DK-02 §Verify-Kontext fuer die
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
4. **Status-Pruefung der Vorphase:** Die Vorphase muss COMPLETED
   sein. Ausnahmen:
   - **QA-Subflow-Resume**: Resume derselben Phase
     `implementation` mit aktivem QA-Subflow (z.B. nach
     Phase-Runner-Crash mitten im Subflow) wird bereits in
     Schritt 2 behandelt — kein Phasenuebergang. Der
     Subflow-interne Remediation-Loop ist Subflow-intern und
     erzeugt keinen Top-Phasen-Wechsel.
     Der Zaehler heisst `memory.implementation.qa_feedback_rounds`.
     Inkrement und Guard-Check finden zu Beginn der
     Subflow-Iteration statt, nicht beim Phasenuebergang.
   - **Resume-Pfad**: `PAUSED` -> Fortsetzung derselben Phase
     (wird bereits in Schritt 2 behandelt, kein Phasenuebergang).
   - `ESCALATED` ist ein **Endzustand** — keine weitere Transition
     erlaubt. Mensch muss erst `reset-escalation` ausfuehren.
   - Von `implementation` zu `closure` ausschliesslich bei
     COMPLETED. Implementation kann nur dann COMPLETED erreichen,
     wenn der QA-Subflow `qa_cycle_status = pass` erreicht hat.
5. **Erstaufruf ohne State-Datei:** Existiert keine
   `phase-state.json`, darf ausschließlich `setup` aufgerufen
   werden. Jede andere Phase → PIPELINE_ERROR.

**Semantische Preconditions (zusätzlich zum Graphen):**

Der Graph allein reicht nicht aus. Modusabhängige Bedingungen
werden nach der Graphen-Validierung geprüft:

- `mode="exploration"` + `phase="implementation"` +
  **Transition von `exploration`** (erster Eintritt):
  `payload.gate_status` muss `APPROVED` sein.
  Ohne bestandenes Exploration-Gate wird die
  Implementation-Phase nicht betreten. Defense-in-Depth: Diese
  Pruefung ergaenzt den bestehenden Guard im QA-Subflow innerhalb
  `_phase_implementation()`, der als zweite Verteidigungslinie
  erhalten bleibt.
  **Nicht bei
  Subflow-interner Remediation:** Innerhalb des QA-Subflows (interner
  Remediation-Loop) wird `payload.gate_status` NICHT erneut geprueft.
  Das Gate wurde bereits beim ersten Eintritt in die
  Implementation-Phase bestanden und liegt in der History. Eine
  erneute Pruefung waere semantisch falsch, da der
  ExplorationPayload nach dem Phasenwechsel zu Implementation nicht
  mehr aktiv ist und der Subflow-Loop kein Phasenwechsel ist.

> In v3 wird `ExplorationPayload.gate_status == ExplorationGateStatus.APPROVED` geprueft. Der Guard `exploration_gate_approved` liest diesen Wert aus dem Payload der aktuellen Phase. Siehe FK-23 §23.5.0.

- `phase="closure"`:
  - Bei Implementation/Bugfix-Stories: Implementation muss mit
    Status COMPLETED abgeschlossen sein. Implementation erreicht
    COMPLETED nur, wenn der QA-Subflow innerhalb der
    Implementation-Phase mit `qa_cycle_status = pass` abgeschlossen
    wurde. Ohne abgeschlossene Implementation-Phase darf Closure
    nicht starten.
  - Bei Concept/Research-Stories: Keine QA-Subflow-Precondition —
    diese Stories haben keinen QA-Subflow (FK-20 §20.2.3).

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

            # Status-Pruefung der Vorphase. Der QA-Subflow-Remediation-Loop
            # ist Subflow-intern in `implementation` und erzeugt keinen
            # Phasenuebergang; Inkrement und Guard-Check fuer
            # `memory.implementation.qa_feedback_rounds` finden zu Beginn
            # der naechsten Subflow-Iteration in `_phase_implementation()`
            # statt, nicht hier in der Phasen-Transition.
            if from_status != "COMPLETED":
                # Normale Vorwaerts-Transition: nur aus COMPLETED
                ...

        # Semantische Preconditions
        # gate_status-Check nur
        # bei exploration -> implementation (erster Eintritt). Subflow-interne
        # Remediation-Iterationen innerhalb derselben Implementation-Phase
        # erzeugen keinen Phasenuebergang und werden in Schritt 2 abgefangen.
        is_first_entry = (from_phase == "exploration")
        if phase == "implementation" and persisted.get("mode") == "exploration" and is_first_entry:
            payload = persisted.get("payload", {})
            gate = payload.get("gate_status", "PENDING")
            if gate != "APPROVED":
                # PIPELINE_ERROR: Gate nicht bestanden
                ...
        # In v3 wird ExplorationPayload.gate_status == ExplorationGateStatus.APPROVED geprueft.
        # Der Guard exploration_gate_approved liest diesen Wert aus dem Payload der aktuellen Phase.
        if phase == "closure":
            # Implementation muss COMPLETED sein (inkl. QA-Subflow PASS)
            ...
    else:
        # Keine State-Datei: nur setup erlaubt
        if phase != "setup":
            # PIPELINE_ERROR
            ...
    # --- Ende Transition-Enforcement ---

    # load_or_create_phase_state() gibt PhaseEnvelope zurueck.
    # Liest hier den BEREITS PERSISTIERTEN State. Subflow-interne Inkremente
    # von memory.implementation.qa_feedback_rounds erfolgen waehrend
    # _phase_implementation() (Subflow-Loop), nicht hier; der Persistenz-Punkt
    # liegt in der Subflow-Iteration und wird hier korrekt zurueckgelesen.
    envelope = load_or_create_phase_state(story_id)
    # Dispatch zur Phase-Funktion (Handler bekommt envelope.state) ...
```

**Nicht blockierte Pfade:**

- PAUSED -> Resume derselben Phase (z.B. Exploration wird nach
  Design-Review-Completion erneut aufgerufen)
- Resume `implementation` mit aktivem QA-Subflow nach Crash —
  Subflow setzt am letzten persistierten `qa_cycle_status` fort
  (kein Phasenwechsel, FK-20 §20.7)

Impact-Violation fuehrt zu `status: ESCALATED`, nicht zu
einem Ruecksprung in die Exploration-Phase. Remediation laeuft
Subflow-intern in `implementation` (FK-20 §20.5).

Referenz: DK-02 §Phase-Transition-Enforcement, FK-23 §23.4
(Exploration-Gate-Semantik).

## 45.3 Phasen-Ergebnisse und Orchestrator-Reaktion

| Phase | Ergebnis im Phase-State | Orchestrator reagiert |
|-------|------------------------|----------------------|
| `setup` COMPLETED | `mode: execution` oder `exploration`, `agents_to_spawn: [worker]` | Spawnt Worker (oder Exploration-Worker bei Exploration Mode) |
| `setup` ESCALATED | `escalation_reason: "preflight_fail"`, `errors: [...]` | Eskalation an Mensch — Preflight-Checks fehlgeschlagen, kein automatischer Remediation-Pfad (FK-20 §20.6.1). |
| `exploration` COMPLETED | `agents_to_spawn: [worker]` | Spawnt Implementation-Worker |
| `exploration` PAUSED | `pause_reason: "awaiting_design_review"` oder `"awaiting_design_challenge"` | Orchestrator wartet auf externe Klärung (Design-Review bzw. Design-Challenge). Resume nach Abschluss via `POST /phases/exploration/start` (Service-Resume) oder Operator-CLI `agentkit resume` (§45.4). |
| `exploration` ESCALATED | `escalation_reason: "doc_fidelity_fail"` oder `"design_review_rejected"` | Eskalation an Mensch. Auslöser: (1) Dokumententreue FAIL (doc_fidelity_fail), (2) Design-Review FAIL non-remediable oder Rundenlimit überschritten (gate_status = REJECTED → design_review_rejected). |
| `implementation` COMPLETED (QA-Subflow PASS) | `agents_to_spawn: []`, `payload.qa_cycle_status: pass` | Startet `POST /phases/closure/start`. Implementation kann COMPLETED nur erreichen, wenn der interne QA-Subflow `qa_cycle_status = pass` erreicht. |
| `implementation` mit QA-Subflow im Remediation-Loop | `payload.qa_cycle_status: awaiting_remediation`, `agents_to_spawn: [remediation_worker]` | Subflow-intern: QA-Subflow lieferte FAIL mit verbleibenden Runden. Phase Runner inkrementiert `memory.implementation.qa_feedback_rounds` nach Guard-Check (Pre-Check VOR Inkrement) und persistiert via `save_phase_state()`. Orchestrator spawnt Remediation-Worker. Nach Worker-Abschluss erneut `POST /phases/implementation/start` — der Subflow setzt mit `verify_context = POST_REMEDIATION` fort, kein Phasenwechsel. |
| `implementation` ESCALATED (Worker BLOCKED) | `escalation_reason: "worker_blocked"`, Blocker-Details aus `worker-manifest.json` | Eskalation an Mensch. Worker hat unloesbaren Constraint gemeldet (z.B. Hook-Barriere, fehlende Dependency). |
| `implementation` ESCALATED (QA-Subflow) | `escalation_reason: "max_rounds_exceeded"` / `"doc_fidelity_fail"` / `"impact_violation"`, `payload.qa_cycle_status: escalated` | Eskalation an Mensch. Ausloeser im QA-Subflow: (1) Max Feedback-Runden erschoepft, (2) Dokumententreue Ebene 3 FAIL (Umsetzungstreue), (3) Impact-Violation (Issue-Metadaten falsch deklariert). |
| `closure` COMPLETED | `payload.progress: {alle true}` | Story ist Done |
| `closure` ESCALATED | `escalation_reason: "integrity_fail"` oder `"merge_fail"` | Eskalation an Mensch. |

## 45.4 Operator-Recovery-CLI (Spezialfall)

Die CLI `agentkit run-phase ...` ist **kein Standard-Aufrufweg**.
Sie ist ausschliesslich fuer menschliche Operator-Recovery-Szenarien
vorgesehen, in denen kein Orchestrator-Agent verfuegbar ist oder
ein defekter Run manuell weitergeschrieben werden muss.

**Erlaubte CLI-Recovery-Befehle:**

```bash
# Nur als Operator-Recovery, nicht als normaler Aufrufweg
agentkit run-phase {phase} --story {story_id} [--config {path}]
agentkit resume --story {story_id}
agentkit reset-escalation --story {story_id}
agentkit cleanup --story {story_id}
```

**Unveraenderlich CLI-basiert (kein Service-Aequivalent):**

| Befehl | Grund |
|--------|-------|
| `agentkit-hook-claude` / `agentkit-hook-codex` | Harness-Hooks sind OS-Prozesse mit stdin/stdout-Pipes — unausweichlich CLI (FK-30 §30.3.1) |
| `agentkit register-project` / `agentkit verify-project` | Einmaliges Operator-Bootstrap/Setup (FK-50) |
| `agentkit reset-story`, `agentkit split-story`, `agentkit exit-story` | Operator-Notfallpfade (FK-53, FK-54, FK-58) |

**Normative Regel:** Kein Agent darf die CLI direkt aufrufen.
Agents greifen ausschliesslich ueber den `Project Edge Client`
gegen die Control-Plane-API (FK-91 §91.1a) zu.
Die CLI ist menschlicher und administrativer Adapterpfad (FK-91 §91.1).
