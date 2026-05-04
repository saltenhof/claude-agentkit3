---
concept_id: FK-20
title: Workflow-Engine und State Machine
module: workflow-engine
domain: pipeline-framework
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: workflow-engine
  - scope: phase-model
  - scope: feedback-loop
  - scope: escalation-and-pause
  - scope: recovery
  - scope: scheduling
defers_to:
  - target: FK-02
    scope: domain-model
    reason: Story-Lifecycle-Zustande und Enums sind im Domaenenmodell definiert
  - target: FK-25
    scope: escalation-classification
    reason: Eskalationsklassen (Klasse 1-4) und Mandatsklassifikation in FK-25 normiert
  - target: FK-59
    scope: story-contract-classification
    reason: "`mode`/`execution_route` ist eine Vertragsachse aus FK-59"
  - target: FK-39
    scope: phase-state-persistence
    reason: Phase-State-Modell, PhaseEnvelope, PhasePayload, PhaseMemory, AttemptRecord, PauseReason-Enum liegen in FK-39
  - target: FK-45
    scope: phase-runner-cli
    reason: CLI-Aufruf, Phasen-Dispatch und Phase-Transition-Enforcement liegen in FK-45
  - target: FK-38
    scope: feedback-mechanism
    reason: Maengelliste-Format und QA-Subflow-Feedback-Mechanik liegen in FK-38
  - target: FK-35
    scope: governance-observation
    reason: Governance-Beobachtung und Eskalationsmechanik liegen in FK-35
  - target: FK-53
    scope: story-reset
    reason: StoryResetService-Mechanik liegt in FK-53
  - target: FK-54
    scope: story-split
    reason: Scope-Explosion-Pfad und StorySplitService liegen in FK-54
  - target: FK-22
    scope: scope-overlap
    reason: Preflight-Scope-Overlap-Check liegt in FK-22 §22.3.1
supersedes: []
superseded_by:
tags: [state-machine, phase-runner, pipeline, feedback-loop, orchestration]
prose_anchor_policy: strict
formal_refs:
  - formal.story-workflow.state-machine
  - formal.story-workflow.commands
  - formal.story-workflow.events
  - formal.story-workflow.invariants
  - formal.story-workflow.scenarios
  - formal.story-reset.invariants
glossary:
  exported_terms:
    - id: edge-rule
      definition: >
        Gerichtete Kante zwischen zwei Knoten in einer FlowDefinition.
        Definiert Quelle, Ziel, optionale Guard-Bedingung und Prioritaet.
        Nur die erste passende Kante nach Prioritaet wird bei einer
        Fallunterscheidung ausgefuehrt.
    - id: execution-policy
      definition: >
        Wiederholungs- und Skip-Semantik eines Knotens in der
        Prozess-DSL. Erlaubte Werte: ALWAYS, ONCE_PER_RUN,
        ONCE_PER_STORY, UNTIL_SUCCESS, SKIP_AFTER_SUCCESS. Steuert
        zusammen mit dem persistierten Execution-Ledger, ob ein Knoten
        bei erneutem Durchlauf erneut ausgefuehrt wird.
      values: [ALWAYS, ONCE_PER_RUN, ONCE_PER_STORY, UNTIL_SUCCESS, SKIP_AFTER_SUCCESS]
    - id: flow-definition
      definition: >
        Vollstaendiger Ablaufvertrag einer Pipeline, Phase oder
        Komponente in der hierarchischen Prozess-DSL. Enthaelt
        flow_id, level (pipeline | phase | component), owner,
        Knoten (NodeDefinition), Kanten (EdgeRule) und Hooks.
        Modelliert Kontrollfluss ohne Fachinhalt.
    - id: node-definition
      definition: >
        Knoten im Ablaufgraph einer FlowDefinition. Traegt node_id,
        kind (step | gate | yield | branch | subflow), handler_ref,
        ExecutionPolicy und OverridePolicy. Atomare Ausfuehrungseinheit
        der hierarchischen Prozess-DSL.
    - id: phase-transition
      definition: >
        Gesteuerter Wechsel von einer Pipeline-Phase in eine andere.
        Wird ausschliesslich von der Engine nach Graphen- und
        Status-Validierung sowie semantischen Preconditions ausgefuehrt
        (Phase-Transition-Enforcement, FK-45). Unerlaubte Uebergaenge
        fuehren unmittelbar zu ESCALATED.
    - id: retry-policy
      definition: >
        Begrenzung und Ziel von Wiederholungen fuer einen Knoten oder
        eine Rueckkante. Enthaelt max_attempts, backtrack_target und
        cooldown_policy. Wird zusammen mit dem persistierten Zaehler im
        Phase-State ausgewertet; nie ad hoc im Handler.
---

# 20 — Workflow-Engine und State Machine

<!-- PROSE-FORMAL: formal.story-workflow.state-machine, formal.story-workflow.commands, formal.story-workflow.events, formal.story-workflow.invariants, formal.story-workflow.scenarios, formal.story-reset.invariants -->

## 20.1 Grundprinzip

Die Pipeline-Orchestrierung folgt einem zentralen Grundsatz des FK
(FK-05-002): **Kein Agent entscheidet über den Ablauf; der Ablauf
entscheidet, wann welcher Agent arbeiten darf.**

Technisch bedeutet das: Der Phase Runner ist ein deterministisches
Python-Skript, das den Story-Lifecycle als State Machine steuert.
Er wird vom Orchestrator-Agent über die CLI aufgerufen, aber der
Orchestrator hat keinen Einfluss auf die Phasenlogik selbst. Der
Phase Runner entscheidet über Phasenwechsel, Feedback-Loops und
Eskalation.

### 20.1.1 Komponentenschnitt

Im fachlichen Komponentenmodell aus FK-01 ist die Workflow-Engine die
Top-Level-Komponente `PipelineEngine`. Der Phase Runner ist ihre
deterministische Laufzeitimplementierung.

| Ebene | Zugehoerigkeit | Verantwortung |
|-------|----------------|---------------|
| `PipelineEngine` | Top-Level-Komponente | State Machine, Transition-Guards, Feedback-/Review-Loops, Eskalation |
| `SetupPhase`, `ExplorationPhase`, `ImplementationPhase`, `ClosurePhase` | Subkomponenten der `PipelineEngine` | Innere Fachlogik je Phase. Output-QA wird intern aus `ExplorationPhase` (Exit-Gate, FK-23 §23.5) und `ImplementationPhase` (QA-Subflow, FK-27) gegen die Capability `VerifySystem` aufgerufen — kein eigenstaendiger `VerifyPhase`-Top-Knoten. |
| `PreflightChecker`, `ModeResolver` | Subkomponenten von `SetupPhase` | Vorbedingungen und Modusermittlung |
| `StructuralChecker`, `PolicyEngine` | Subkomponenten der Capability `VerifySystem` (BC verify-system) | Layer-1-Pruefung und finale Aggregation des QA-Subflows |
| `IntegrityGate` | Sub von `agentkit.governance.integrity_gate` (BC governance-and-guards); wird von `ClosurePhase` aufgerufen | Vorbedingung fuer Merge/Abschluss |

**Abgrenzung:** Der vollstaendige Story-Reset ist **keine**
Subkomponente der `PipelineEngine`. Er ist eine separate
Top-Level-Komponente `StoryResetService`, weil er keinen normalen
Story-Run fortsetzt, sondern eine menschlich autorisierte
Recovery-Operation ausserhalb des Pipeline-Kontrollflusses ist.

Dasselbe gilt fuer `StorySplitService`: Auch ein Story-Split ist
keine normale Phasenfortsetzung, sondern eine administrative
Operation ausserhalb des Pipeline-Kontrollflusses. Er beendet bei
Scope-Explosion die ueberdehnte Ausgangs-Story kontrolliert und legt
deren Nachfolger an.

### 20.1.2 Einheitliche Prozess-DSL

AK3 verwendet fuer die Ablaufmodellierung **eine einzige hierarchische
Prozess-DSL**. Dieselben Sprachkonstrukte gelten fuer die komplette
Pipeline, fuer einzelne Phasen, fuer fachliche Komponenten und fuer
deren Subschritte. Es gibt **kein zweites Kontrollflussmodell** auf
Komponentenebene.

**Abgrenzung:** Die in FK-28 definierte Request-DSL bleibt eine
fachspezifische Nachforderungssprache fuer Reviewer. Sie ist **nicht**
Teil der hier beschriebenen Kontrollfluss-DSL.

| Ebene | DSL-Sicht | Typischer Owner | Zweck |
|-------|-----------|-----------------|-------|
| Pipeline | `FlowDefinition(level="pipeline")` | `PipelineEngine` | Gesamtablauf einer Story |
| Phase | `FlowDefinition(level="phase")` | `SetupPhase`, `ImplementationPhase`, ... | Ablauf innerhalb einer Phase |
| Komponente | `FlowDefinition(level="component")` | `StageRegistry`, `Installer`, `GuardSystem`, ... | Innere Kontrolllogik einer Komponente (auch `VerifySystem`-QA-Subflow) |
| Subschritt | `NodeDefinition(kind="step")` oder `subflow` | jeweilige Komponente | Atomarer oder zusammengesetzter Ausfuehrungsschritt |

Die DSL modelliert **Kontrollfluss**, nicht Fachinhalt. Fachlogik,
I/O, Artefaktproduktion und Seiteneffekte bleiben in den
Schritt-Handlern der jeweiligen Komponente implementiert. Die DSL
beschreibt dagegen:

- Reihenfolge
- Fallunterscheidungen
- Wiederholungen und Rueckspruenge
- Gates und Yield-Points
- Once-only-/Until-success-Semantik
- manuelle oder orchestratorseitige Overrides

### 20.1.3 Kernkonstrukte der Prozess-DSL

| Konstrukt | Bedeutung | Typische Felder |
|-----------|-----------|-----------------|
| `FlowDefinition` | Vollstaendiger Ablaufvertrag einer Pipeline, Phase oder Komponente | `flow_id`, `level`, `owner`, `nodes`, `edges`, `hooks` |
| `NodeDefinition` | Knoten im Ablaufgraph | `node_id`, `kind`, `handler_ref`, `execution_policy`, `override_policy` |
| `EdgeRule` | Gerichtete Kante zwischen zwei Knoten | `source`, `target`, `when`, `priority`, `resume_policy` |
| `Guard` | Seiteneffektfreie Vorbedingung / Entscheidungsbedingung | `name`, `reads`, `predicate` |
| `Gate` | Mehrstufiger Pruefpunkt mit Aggregationsregel | `id`, `stages`, `final_aggregation`, `max_remediation_rounds` |
| `YieldPoint` | Typisierte Pause mit Resume-Triggern | `status`, `resume_triggers`, `required_artifacts` |
| `ExecutionPolicy` | Wiederholungs- und Skip-Semantik eines Knotens | `ALWAYS`, `ONCE_PER_RUN`, `ONCE_PER_STORY`, `UNTIL_SUCCESS`, `SKIP_AFTER_SUCCESS` |
| `RetryPolicy` | Begrenzung und Ziel von Wiederholungen | `max_attempts`, `backtrack_target`, `cooldown_policy` |
| `OverridePolicy` | Erlaubte manuelle Eingriffe | `allow_skip`, `allow_force_pass`, `allow_jump`, `allow_truncate` |

**Node-Klassen:** Die DSL verwendet auf allen Ebenen dieselben
Knotentypen:

| `kind` | Semantik |
|--------|----------|
| `step` | Atomarer Ausfuehrungsschritt mit konkretem Handler |
| `gate` | Qualitaets-/Freigabepunkt mit Stage-Aggregation |
| `yield` | Pause bis externer Trigger / Mensch / Orchestrator resumiert |
| `branch` | Fallunterscheidung; ausgehende Kanten werden ueber Guards gewaehlt |
| `subflow` | Eingebetteter Ablauf, der wieder dieselbe DSL benutzt |

**Normative Regel:** Komponenten modellieren ihre Subschritte als
`subflow` + `step`-Kombinationen. Imperative Einzelschritt-Logik in
beliebigen Python-Dateien ohne expliziten DSL-Vertrag ist fuer
nichttriviale Ablaufteile nicht zulaessig.

### 20.1.4 Fallunterscheidung, Wiederholung und Ruecksprung

Die DSL muss dieselben generischen Ablaufmuster auf allen Ebenen
abbilden koennen:

| Muster | Normative Modellierung |
|--------|------------------------|
| Fallunterscheidung | `branch`-Node oder mehrere `EdgeRule`s mit Guards; erste passende Kante gewinnt nach `priority` |
| Wiederholung | Explizite Rueckkante auf frueheren `node_id` + `RetryPolicy` |
| Gezielter Ruecksprung | Ruecksprung erfolgt immer auf **explizite** `node_id`s, nie auf implizite "minus 2 Schritte" ohne DSL-Kante |
| Remediation-Loop | Rueckkante + `max_attempts` + persistierter Zaehler im Laufzeitstate |
| Einmalige Schritte | `ExecutionPolicy = ONCE_PER_RUN` oder `ONCE_PER_STORY` |
| Nur bis Erfolg wiederholen | `ExecutionPolicy = UNTIL_SUCCESS` |
| Nach Erfolg ueberspringen | `ExecutionPolicy = SKIP_AFTER_SUCCESS` |

Damit gilt auch fuer Rueckspruenge aus spaeteren Phasen oder
Komponenten: Wenn der Ablauf erneut vorwaerts durchlaufen wird,
entscheidet **nicht** der Handler ad hoc, welche Schritte erneut
laufen, sondern die DSL zusammen mit dem persistierten
Execution-Ledger.

### 20.1.5 Overrides und manuelle Eingriffe

Overrides sind ein normierter Teil der Ablaufsteuerung und werden
nicht als ad-hoc-Sonderlogik in einzelnen Komponenten modelliert.

| Override | Semantik |
|----------|----------|
| `skip_node` | Knoten wird fuer diesen Run bewusst uebergangen |
| `force_gate_pass` / `force_gate_fail` | Gate-Entscheidung wird manuell gesetzt |
| `jump_to` | Ausfuehrung springt auf einen expliziten `node_id` |
| `truncate_flow` | Restlicher Teil eines Subflows wird bewusst abgeschnitten |
| `freeze_retries` | Weitere Rueckspruenge / Wiederholungen werden fuer diesen Ast unterbunden |

**Regeln:**

1. Overrides duerfen nur durch Mensch oder Orchestrator via CLI
   beantragt werden, nie durch Worker.
2. Jeder Override wird als auditierbarer Override-Record persistiert
   und von der Engine ausgewertet.
3. Ob ein Override zulaessig ist, entscheidet die `OverridePolicy`
   des betroffenen Knotens oder Flows.
4. Auch ein Override mutiert den Zustand nicht direkt; die Engine
   wendet ihn deterministisch bei der naechsten Auswertung an.

**Abgrenzung zum Story-Reset:** Ein vollstaendiger Story-Reset ist
kein Override. Er ersetzt keinen Knotenentscheid und springt nicht im
laufenden Flow, sondern beendet die korrupt gewordene Umsetzung
administrativ und schafft einen neuen sauberen Startzustand.

### 20.1.6 Evolution der bestehenden Workflow-DSL

Die bereits implementierte Workflow-DSL unter
`agentkit.pipeline_engine.flow_orchestrator` ist die **erste Auspraegung** der
hierarchischen Prozess-DSL und wird nicht verworfen, sondern
verallgemeinert.

| Heutiger Begriff | Zielbegriff in der Einheits-DSL | Rolle |
|------------------|----------------------------------|-------|
| `WorkflowDefinition` | `FlowDefinition` | Ablaufvertrag auf beliebiger Ebene |
| `PhaseDefinition` | `NodeDefinition(kind="subflow")` oder phasenbezogene Spezialisierung | Zusammengesetzter Knoten |
| `TransitionRule` | `EdgeRule` | Kante im Ablaufgraph |
| `GuardFn` | `Guard` | Bedingung |
| `Gate` | `Gate` | unveraendert, aber nicht mehr nur phasenbezogen |
| `YieldPoint` | `YieldPoint` | unveraendert, aber auf allen Ebenen nutzbar |

**Konsequenz fuer AK3:** Die Pipeline bleibt phasenorientiert
modelliert. Komponenten fuehren jedoch **dieselbe** Sprache fuer ihre
eigenen Subschritte. Dadurch werden Kontrollfluss-Semantik, Override-
Verhalten und Wiederholungslogik systemweit vereinheitlicht.

### 20.1.7 Ausfuehrungsvertrag fuer Knoten

Die Einheits-DSL definiert den Kontrollfluss. Damit Komponenten
andockbar bleiben, ohne die Engine zu unterlaufen, gilt fuer alle
ausfuehrbaren Knoten ein gemeinsamer Handler-Vertrag.

| Vertragsteil | Bedeutung |
|--------------|-----------|
| `StepExecutionContext` | Immutable Laufzeitansicht auf `project_key`, `story_id`, `run_id`, `flow_id`, `node_id`, `StoryContext`, `PhaseState`, aktive Overrides und lesbare Artefakt-Handles |
| `StepHandler` | Deterministische oder agentische Implementierung eines `step`-Knotens; fuehrt Fachlogik aus, mutiert aber den globalen State nicht direkt |
| `StepResult` | Rueckgabe eines Knotens: `outcome`, `produced_artifacts`, `emitted_events`, `requested_yield`, `diagnostics` |
| `SubflowProvider` | Liefert fuer `subflow`-Knoten die untergeordnete `FlowDefinition` plus Handler-Registry |
| `GateRunner` | Fuehrt `gate`-Knoten aus und aggregiert Stage-Ergebnisse gemaess Gate-Vertrag |

**Normative Regeln:**

1. Schritt-Handler schreiben den globalen Ablaufstate nicht direkt.
   Sie liefern `StepResult`; die Engine wendet daraus den
   Zustandsuebergang an.
2. Rueckspruenge, Wiederholungen, Skips und Overrides duerfen nicht
   im Handler versteckt implementiert werden; sie muessen ueber die
   DSL-Kanten, Policies und Override-Records sichtbar sein.
3. Ein `subflow`-Knoten darf nur ueber einen `SubflowProvider` neue
   Knoten einbringen. Dynamisch zusammengebaute implizite Python-Loops
   ausserhalb der DSL sind nicht zulaessig.
4. Agentische Schritte sind erlaubt, aber nur als Handler eines
   expliziten `step`-Knotens. Auch sie sind an `ExecutionPolicy`,
   `RetryPolicy` und `OverridePolicy` gebunden.

**Folge fuer die Komponentenmodellierung:** Jede nichttriviale
Komponente liefert kuenftig mindestens:

- eine `FlowDefinition` fuer ihren internen Ablauf
- eine Handler-Registry fuer ihre `step`-Knoten
- einen klaren Satz lesbarer Inputs und produzierter Artefakte

Damit werden Komponenten zu expliziten, auditierbaren
Ausfuehrungseinheiten derselben Sprache, statt ihre innere
Kontrolllogik in frei formulierten Python-Dateien zu verstecken.

## 20.2 Phasenmodell

### 20.2.1 Vier Phasen mit QA-Subflow

| Phase | Typ | Zweck | Akteur |
|-------|-----|-------|--------|
| `setup` | Deterministisch | Preflight, Worktree, Context, Guards, Mode-Routing | Pipeline-Skript |
| `exploration` | Agent-gesteuert | Entwurfsartefakt erzeugen, Dokumententreue pruefen; Exit-Gate ruft Capability `VerifySystem` (FK-23 §23.5) | Worker-Agent + LLM-Evaluator |
| `implementation` | Agent-gesteuert + Subflow | Code/Konzept/Research umsetzen; vor Phasenabschluss laeuft der QA-Subflow gegen die Capability `VerifySystem` (4-Schichten-QA, FK-27) inklusive Remediation-Loop | Worker-Agent + Pipeline-Skripte + LLM-Evaluator + Adversarial Agent |
| `closure` | Deterministisch | Integrity-Gate, Merge, Issue-Close, Metriken, Postflight | Pipeline-Skript |

> **[Entscheidung 2026-05-01]** Die vormalige Top-Phase `verify` entfaellt. Output-QA ist kein eigenstaendiger Phasenknoten mehr, sondern interner Subflow innerhalb `implementation` (analog zum Exit-Gate der `exploration`). Die Faehigkeit `VerifySystem` bleibt als Bounded-Context-Capability bestehen und wird sowohl von `ExplorationPhase` als auch von `ImplementationPhase` aufgerufen. Siehe `concept/_meta/bc-cut-decisions.md` "Verify als Capability (Variante Y)".

### 20.2.1a StoryResetService

Der `StoryResetService` ist die administrative Recovery-Komponente fuer
Faelle, in denen ein eskalierter Story-Run nicht mehr ueber den
normalen Workflow repariert oder weitergefuehrt werden kann.

| Aspekt | Regel |
|--------|-------|
| Ausloeser | nur ausdruecklicher menschlicher CLI-Befehl |
| Erlaubender Vorzustand | typischerweise `ESCALATED`, nie automatischer Trigger |
| Initiator | Mensch; Orchestrator darf nur empfehlen oder dokumentieren |
| Wirkung | Purge von Runtime-State, Read Models, Analytics-Ableitungen, story-bezogenen Sperren und ephemeren Arbeitsartefakten |
| Ergebnis | Story verbleibt als fachliche Arbeitseinheit, aber die bisherige korrupt gewordene Umsetzung verschwindet vollstaendig |

**Normative Regel:** `PipelineEngine` darf niemals selbststaendig einen
vollstaendigen Story-Reset ausfuehren. Sie darf hoechstens in einen
eskalierten Zustand uebergehen und damit den Menschen zu einer
Entscheidung zwingen.

### 20.2.2 State Machine

```mermaid
stateDiagram-v2
    [*] --> setup

    setup --> ABBRUCH : Preflight FAIL
    setup --> exploration : Exploration Mode
    setup --> implementation : Execution Mode

    state exploration {
        [*] --> entwurf_erstellen
        entwurf_erstellen --> selbst_konformitaet : Worker prüft selbst
        selbst_konformitaet --> doc_fidelity_check : Unabhängige Prüfung (LLM)
        doc_fidelity_check --> ESKALATION_DOC : FAIL
        doc_fidelity_check --> design_review : PASS
        design_review --> premise_challenge
        premise_challenge --> trigger_eval
        trigger_eval --> design_challenge : Trigger vorhanden
        trigger_eval --> aggregation : Kein Trigger
        design_challenge --> aggregation
        aggregation --> mensch_pause : Klasse 1/3/4 (FK-25)
        aggregation --> feindesign : Klasse 2 (FK-25)
        aggregation --> remediation : Review-Findings remediable
        feindesign --> design_review
        remediation --> entwurf_erstellen
        mensch_pause --> design_review : Resume nach Klärung
        aggregation --> entwurf_freeze : PASS ohne Findings
        entwurf_freeze --> [*]
    }

    exploration --> implementation : Exploration-Exit-Gate vollständig bestanden

    state implementation {
        [*] --> worker_running
        worker_running --> qa_subflow : Handover erzeugt
        worker_running --> BLOCKED_EXIT : Worker meldet BLOCKED

        state qa_subflow {
            [*] --> schicht_1 : Deterministische Checks (Skripte)
            schicht_1 --> schicht_2 : PASS
            schicht_1 --> FEEDBACK_INT : FAIL
            schicht_2 --> schicht_3 : PASS (LLM-Bewertungen via Skript, kein Dateisystem)
            schicht_2 --> FEEDBACK_INT : FAIL
            schicht_3 --> schicht_4 : keine Befunde (Adversarial Agent, mit Dateisystem)
            schicht_3 --> FEEDBACK_INT : Befunde
            schicht_4 --> qa_pass : PASS (Policy-Evaluation)
            schicht_4 --> FEEDBACK_INT : FAIL
            FEEDBACK_INT --> remediation : feedback_rounds < max
            remediation --> worker_running
            FEEDBACK_INT --> ESC_MAX : feedback_rounds >= max
            qa_pass --> [*]
        }
    }

    implementation --> closure : QA-Subflow PASS
    implementation --> ESKALATION_BLOCKED : Worker BLOCKED (unloesbarer Constraint)
    implementation --> ESKALATION_MAX : Max Runden erschoepft (QA-Subflow)
    implementation --> [*] : ESCALATED (Impact-Violation)
    implementation --> [*] : ESCALATED (Dokumententreue Ebene 3 FAIL)

    state closure {
        [*] --> integrity_gate
        integrity_gate --> ESKALATION_INT : FAIL
        integrity_gate --> merge
        merge --> ESKALATION_MERGE : Merge-Konflikt
        merge --> issue_close
        issue_close --> metrics
        metrics --> postflight
        postflight --> [*]
        note right of postflight : VektorDB-Sync async (Fire-and-Forget)
    }

    closure --> [*] : Story abgeschlossen
```

> [Terminologie-Hinweis 2026-04-09] **ABBRUCH in Diagrammen = `status: ESCALATED` im State-Modell:** Die Mermaid-Diagramme verwenden `ABBRUCH` und `ABORT` als Beschriftung für den Preflight-FAIL-Terminalknoten. Im v3-Zustandsmodell entspricht dies `status: ESCALATED` mit `escalation_reason: "preflight_fail"`. Es gibt keinen separaten Status `ABBRUCH` — der Begriff ist ausschließlich eine Darstellungshilfe in den Diagrammen.

> [Korrektur 2026-04-09] **Kein Phasen-Ruecksprung in die Exploration:**
> Die ursprueengliche Transition `verify --> exploration : Impact-Violation
> (Exploration Mode)` wurde entfernt. Impact-Violation im QA-Subflow
> bedeutet Implementierungsversagen und fuehrt zu `status: ESCALATED`.
> Es gibt keinen automatischen Ruecksprung von Implementation oder
> ihrem QA-Subflow in die Exploration-Phase. Der Mensch entscheidet
> nach Eskalation ueber naechste Schritte (ggf. neue Exploration mit
> neuem Mandat als neuer Pipeline-Lauf). Exploration-interne
> Remediation (max 3 Runden) bleibt davon unberuehrt.

> [Entscheidung 2026-05-01] **`verify` als Top-Phase entfaellt:**
> Die ehemaligen Phasen-Transitionen `implementation -> verify` und
> `verify -> closure` existieren nicht mehr. Implementation enthaelt
> intern den vollstaendigen QA-Subflow (Schicht 1-4 plus
> Remediation-Loop) gegen die Capability `VerifySystem`. Der Uebergang
> `implementation -> closure` erfolgt erst, wenn Implementation den
> QA-Subflow mit `qa_cycle_status = pass` abgeschlossen hat. Der
> ehemalige Remediation-Phasenwechsel `verify -> implementation` ist
> jetzt ein Subflow-interner Loop und triggert keinen Top-Phase-Wechsel
> mehr.

> [Korrektur 2026-04-09] **Exploration-Exit-Gate:** Die Transition
> `exploration --> implementation` erfordert den vollständigen Ablauf
> gemäß FK-23 und FK-25: Dokumententreue, Design-Review,
> Prämissen-Challenge, optionale Design-Challenge, H1-Aggregation,
> H2-Nachklassifikation und ggf. Feindesign-Subprozess. Erst wenn
> der Draft alle Prüfungen bestanden hat, eingefroren wurde und
> `payload.gate_status: APPROVED` erreicht ist, darf die
> Implementation-Phase betreten werden.

### 20.2.3 Abweichende Pfade nach Story-Typ

Die State Machine gilt in voller Ausprägung nur für
**implementierende Story-Typen** (Implementation, Bugfix).
Konzept- und Research-Stories nehmen Abkürzungen:

```mermaid
flowchart TD
    START(["Story freigegeben"]) --> PREFLIGHT["Preflight"]
    PREFLIGHT -->|FAIL| ABORT(["Abbruch"])
    PREFLIGHT -->|PASS| TYP{"Story-Typ?"}

    TYP -->|"Implementation / Bugfix"| FULL["Volle Pipeline<br/>(Setup → Exploration? →<br/>Implementation inkl. QA-Subflow →<br/>Closure)"]

    TYP -->|"Concept"| CONCEPT["Konzept-Pfad:<br/>Worker erstellt Dokument<br/>→ VektorDB-Abgleich<br/>→ Pflicht-Feedback (2 LLMs)<br/>→ QA prüft Einarbeitung<br/>→ Leichtgewichtige Checks<br/>→ Closure (ohne Integrity-Gate)"]

    TYP -->|"Research"| RESEARCH["Research-Pfad:<br/>Skill laden<br/>→ Strukturierte Recherche<br/>→ Leichtgewichtige Checks<br/>→ Closure (ohne Integrity-Gate)"]

    FULL --> DONE(["Done"])
    CONCEPT --> DONE
    RESEARCH --> DONE
```

**Was Konzept- und Research-Stories NICHT durchlaufen:**
- Keine Modus-Ermittlung (Execution/Exploration)
- Kein Worktree/Branch (arbeiten direkt auf Main — AI-Augmented-Modus)
- Kein 4-Schichten-QA-Subflow innerhalb Implementation
- Kein Integrity-Gate
- Kein Adversarial Testing

**Was Konzept-Stories zusätzlich durchlaufen:**
- VektorDB-Abgleich auf Überschneidungen mit bestehenden Konzepten
- Pflicht-Feedback-Loop mit 2 verschiedenen LLMs (FK-02 §02.2.4)
- QA-Prüfung der Feedback-Einarbeitung

> **[Entscheidung 2026-04-08]** Element 16 — PhaseState-Restructuring: Ownership-Trennung in StoryContext (langlebige Story-Semantik), PhaseStateCore (aktueller Laufzeitstatus), PhasePayload (diskriminierte Union pro Phase), RuntimeMetadata (nicht-fachliche Loader-/Guard-Infos). `mode`, `story_type` → raus aus PhaseState, rein in StoryContext. QA-Zyklus-Felder → VerifyState. Exploration-Gate-Felder → ExplorationState. Closure-Substates → ClosureState. Detailkonzept ist in FK-39 ausgearbeitet.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 16.

> **[Ergänzung 2026-04-09]** Das Detailkonzept zu Element 16 liegt vollständig vor (Designwizard R1+R2 vom 2026-04-09). Die ausgearbeiteten Entscheidungen sind in **FK-39 (Phase-State-Persistenz)** eingetragen: PhaseEnvelope + RuntimeMetadata (FK-39 §39.3), AttemptRecord-Typisierung (FK-39 §39.4), PhaseMemory mit Carry-Forward (FK-39 §39.5), PauseReason StrEnum (FK-39 §39.2.2), PhasePayload Discriminated Union mit ExplorationPayload, VerifyPayload, ClosurePayload (FK-37 §37.1, FK-23 §23.5, FK-29 §29.1.0).

## 20.3 Phase-State-Persistenz

> Phase-State-Modell, PhaseEnvelope, PhasePayload (discriminated union),
> PhaseMemory (carry-forward), AttemptRecord, PauseReason und das
> Lese-/Schreibprotokoll sind in **FK-39 (Phase-State-Persistenz und
> Phase-Envelope-Modell)** normiert.

## 20.4 Phase Runner: CLI-Schnittstelle

> CLI-Aufrufkonvention (`agentkit run-phase ...`), Phasen-Dispatch,
> Phase-Transition-Enforcement (Graphen- und Status-Validierung,
> semantische Preconditions, Remediation-Pfad mit Guard-Check vor
> Inkrement) und die Tabelle "Phasen-Ergebnisse und Orchestrator-Reaktion"
> sind in **FK-45 (Phase Runner CLI und Phase-Transition-Enforcement)**
> normiert.

## 20.5 Feedback-Loop

### 20.5.1 Mechanismus

Wenn der QA-Subflow innerhalb der Implementation-Phase scheitert,
loopt die Engine intern: der Remediation-Worker laeuft als
naechster Subflow-Schritt **innerhalb derselben Implementation-Phase**
und erhaelt eine strukturierte Maengelliste als Input. Es gibt
keinen Phasen-Wechsel mehr — Remediation ist eine interne
Subflow-Iteration, keine Top-Phase-Transition.

> [Entscheidung 2026-05-01] Die fruehere Phasen-Wechsel-Logik
> `verify (FAILED) -> implementation (IN_PROGRESS)` mit Inkrement von
> `memory.verify.feedback_rounds` beim Phasenuebergang entfaellt. Der
> Inkrement-Schritt bleibt erhalten, ist aber jetzt eine interne
> Subflow-Iteration in `implementation`. Die Implementation-Phase
> verlaesst den Worker-Run-Knoten erst, wenn der QA-Subflow
> `qa_cycle_status = pass` erreicht oder eskaliert.

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant PR as Phase Runner (Implementation)
    participant V as VerifySystem (Capability)
    participant W as Worker (Remediation)

    O->>PR: run-phase implementation --story ODIN-042 (qa_subflow active)
    PR->>V: run_qa_subflow(qa_context=IMPLEMENTATION_INITIAL)
    V-->>PR: PolicyVerdict: FAILED (findings)

    Note over PR: QA-Subflow-Loop (intern, kein Phase-Wechsel) [Entscheidung 2026-05-01]
    Note over PR: 1. Prueft Guard: memory.implementation.qa_feedback_rounds < max (VOR Inkrement)
    alt Guard bestanden (aktueller Wert < max)
        Note over PR: 2. Inkrementiert memory.implementation.qa_feedback_rounds (0->1, 1->2, 2->3)
        Note over PR: 3. save_phase_state() — persistiert Inkrement VOR Worker-Spawn
        PR-->>O: phase-state: phase=implementation, status=IN_PROGRESS, agents_to_spawn=[remediation_worker]
        O->>W: Spawnt Remediation-Worker mit Maengelliste
        W-->>O: Fixes committed
        O->>PR: run-phase implementation --story ODIN-042 (resume qa_subflow)
        PR->>V: run_qa_subflow(qa_context=IMPLEMENTATION_REMEDIATION)
        V-->>PR: PolicyVerdict: PASS oder erneut FAILED
        PR-->>O: phase-state: COMPLETED (PASS) oder erneut Loop
    else Guard abgelehnt (aktueller Wert >= max)
        Note over PR: Guard FAIL -> ESCALATED (max_rounds_exceeded)
        PR-->>O: phase-state: ESCALATED, escalation_reason=max_rounds_exceeded
    end
```

> [Entscheidung 2026-05-01] **Sequenzdiagramm aktualisiert:**
> Die fruehere Phasen-Wechsel-Logik (`verify (FAILED) ->
> implementation (IN_PROGRESS) -> verify`) entfaellt mit dem Cut
> der Top-Phase `verify`. Das jetzt geltende Modell ist
> Subflow-intern in der Implementation-Phase:
> 1. QA-Subflow liefert FAILED (mit aktuellem, nicht-inkrementiertem
>    `memory.implementation.qa_feedback_rounds`-Wert)
> 2. Engine prueft Guard: `memory.implementation.qa_feedback_rounds
>    < policy.max_feedback_rounds` (Pre-Check VOR Inkrement)
> 3. Guard bestanden -> Engine inkrementiert
>    `memory.implementation.qa_feedback_rounds` (NACH Guard-Check)
>    und persistiert via `save_phase_state()` VOR Spawn des
>    Remediation-Workers
> 4. Orchestrator setzt den `agents_to_spawn`-Auftrag um —
>    Implementation bleibt aktive Phase, kein Phasen-Wechsel
> 5. Remediation-Worker laeuft mit Remediation-Prompt
> 6. Engine ruft `VerifySystem.run_qa_subflow` erneut auf
>    (qa_context = IMPLEMENTATION_REMEDIATION)
> 7. Implementation-Phase beendet erst nach `qa_cycle_status = pass`
>    oder Eskalation
>
> Der Zaehler `memory.implementation.qa_feedback_rounds`
> (vormals `memory.verify.feedback_rounds`) wird per Carry-Forward
> in `PhaseMemory` mitgefuehrt, weil mehrere Subflow-Iterationen
> ueber Crash-Recovery hinweg konsistent sein muessen
> (FK-39 §39.5).

> [Korrektur 2026-04-09] **Ownership-Klarstellung Guard-Check
> und Inkrement:** Guard-Prüfung (`feedback_rounds < max`),
> Inkrement (`feedback_rounds++`) und Persistierung
> (`save_phase_state()`) sind ausschließlich Aufgaben des
> **Phase Runner (Engine)**, nicht des Orchestrators. Der
> Orchestrator liest den Phase-State und reagiert darauf (z.B.
> ruft `run-phase implementation` auf), aber er mutiert den
> State nie direkt. Dieses Prinzip ist in FK-39 §39.6 normativ
> festgelegt ("Nur der Phase Runner schreibt") und folgt aus
> dem Determinismus-Grundsatz (§20.1): Ablaufsteuerung,
> Guard-Logik und State-Mutationen laufen deterministisch im
> Phase Runner — der Orchestrator ist Konsument, nicht Produzent
> des Phase-State.

### 20.5.2 Mängelliste

Format und Felder der Mängelliste (`feedback.json`) sind in
**FK-38 §38.1.2** normiert. Der Remediation-Worker (FK-26 §26.2.3)
erhält diese Datei als Input.

### 20.5.3 Konfiguration

| Parameter | Default | Config-Pfad |
|-----------|---------|-------------|
| Max Feedback-Runden | 3 | `policy.max_feedback_rounds` |

Nach Erreichen des Limits: Pipeline stoppt, Story bleibt
"In Progress", Eskalation an Mensch.

## 20.6 Eskalation

> **[Entscheidung 2026-04-08, aktualisiert 2026-04-09]** Die ursprünglich 11 Eskalations-Trigger wurden auf 12 Einträge erweitert (Ergänzung: Design-Review-Gate FAIL, Impact-Violation Exploration Mode, Governance-Incident als PAUSED-Trigger). FK-20 §20.6.1 und FK-35 §35.4.2 sind normativ. Kein Trigger ist redundant.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 17.

### 20.6.1 Eskalations- und Pause-Punkte

Die folgende Tabelle listet alle Auslöser, die die Pipeline stoppen. Spalte „Status" zeigt, ob der Zustand `ESCALATED` (dauerhafter Stopp, erfordert manuellen Reset) oder `PAUSED` (temporär, Resume nach Klärung) ist.

| Auslöser | Phase | Status | Reaktion |
|----------|-------|--------|---------|
| Preflight FAIL | setup | ESCALATED (`escalation_reason: "preflight_fail"`) | Story startet nicht. Kein automatischer Remediation-Pfad. Mensch muss Voraussetzungen klären. |
| Dokumententreue Ebene 2 FAIL (Entwurfstreue) | exploration | ESCALATED (`escalation_reason: "doc_fidelity_fail"`) | Pipeline wird eskaliert. Mensch muss Konflikt mit Architektur klären. [Korrektur 2026-04-09: War fälschlich als PAUSED dokumentiert.] |
| Design-Review-Gate FAIL non-remediable oder Rundenlimit überschritten | exploration | ESCALATED (`escalation_reason: "design_review_rejected"`) | `gate_status: REJECTED` → Pipeline eskaliert. Mensch muss Entwurf klären oder Story neu aufsetzen. [Entscheidung 2026-04-09: Terminalpfad gemäß FK-23 §23.5 Stufe 2c.] |
| Dokumententreue Ebene 3 FAIL (Umsetzungstreue) | implementation (QA-Subflow) | ESCALATED (`escalation_reason: "doc_fidelity_fail"`) | Pipeline wird eskaliert. Worker hat vom Konzept abgewichen, Mensch entscheidet. [Korrektur 2026-04-09: War faelschlich als PAUSED dokumentiert.] [Entscheidung 2026-05-01: Phase ist `implementation` — QA-Subflow statt eigene Verify-Phase.] |
| Impact-Violation (Execution Mode) | implementation (QA-Subflow) | ESCALATED (`escalation_reason: "impact_violation"`) | Issue-Metadaten waren falsch deklariert. Mensch entscheidet ueber naechste Schritte. [Entscheidung 2026-05-01: Phase ist `implementation` — QA-Subflow.] |
| Impact-Violation (Exploration Mode) | implementation (QA-Subflow) | ESCALATED (`escalation_reason: "impact_violation"`) | Kein automatischer Ruecksprung in Exploration. Mensch entscheidet (ggf. neue Exploration mit neuem Mandat). [Korrektur 2026-04-09: War faelschlich als Ruecksprung dokumentiert.] [Entscheidung 2026-05-01: Phase ist `implementation` — QA-Subflow.] |
| Worker BLOCKED (unloesbarer Constraint) | implementation | ESCALATED (`escalation_reason: "worker_blocked"`) | Worker hat ueber `worker-manifest.json` unloesbaren Constraint gemeldet (z.B. Hook-Barriere, fehlende Dependency). Mensch loest externen Constraint. |
| Max Feedback-Runden erschoepft (QA-Subflow) | implementation | ESCALATED (`escalation_reason: "max_rounds_exceeded"`) | Pipeline stoppt. Mensch muss entscheiden: Story anpassen, Anforderungen lockern, oder manuell fixen. [Entscheidung 2026-05-01: Phase ist `implementation` — Feedback-Runden zaehlen den QA-Subflow-Loop.] |
| Integrity-Gate FAIL | closure | ESCALATED (`escalation_reason: "integrity_fail"`) | Pipeline stoppt. Mensch prüft Audit-Log (`integrity-violations.log`). |
| Merge-Konflikt | closure | ESCALATED (`escalation_reason: "merge_fail"`) | Pipeline stoppt. Worker muss rebasen oder Mensch löst Konflikt. |
| Scope-Explosion (Klasse 3) | exploration | PAUSED (`pause_reason` durch H2-Routing) | Mensch prueft Split-Befund. Standardpfad: `agentkit split-story` statt Weiterarbeit im selben Story-Vertrag. |
| Governance-Beobachtung: kritischer Incident | jede | **PAUSED** (`pause_reason: GOVERNANCE_INCIDENT`) | Pipeline pausiert sofort — kein ESCALATED. Mensch muss intervenieren, dann Resume via `agentkit resume`. Siehe FK-39 §39.2.2. |
| Governance-Beobachtung: harter Verstoß (Secrets, Governance-Manipulation) | jede | ESCALATED (`escalation_reason: "governance_violation"`) | Sofortiger dauerhafter Stopp, kein LLM-Adjudication nötig. |

### 20.6.2 Eskalationsverhalten (einheitlich)

Bei jeder **ESCALATED**-Eskalation (nicht PAUSED — `GOVERNANCE_INCIDENT` führt zu PAUSED, siehe FK-39 §39.2.2) gilt dasselbe Verhalten (FK-05-218 bis FK-05-222):

1. Story bleibt im GitHub-Status "In Progress"
2. Phase-State wird auf `status: ESCALATED` gesetzt
3. Orchestrator stoppt die Bearbeitung dieser Story
4. Orchestrator nimmt keine weiteren Aktionen für diese Story vor
5. Mensch muss aktiv intervenieren
6. Erst nach menschlicher Intervention kann die Story wieder
   in die Pipeline eingespeist werden

**PAUSED vs. ESCALATED:** Pause-Zustände (`PAUSED` mit einem
PauseReason) sind vorübergehend — Resume nach Klärung via
`agentkit resume`. ESCALATED ist dauerhafter Stopp der aktuellen
Iteration — Ursache muss behoben werden, bevor ein neuer Run
gestartet wird. Definition der drei PauseReason-Werte und
der Resume-Trigger in **FK-39 §39.2.2**.

| Status | PauseReason / Ausloeser | Phase | Bedeutung | Resume |
|--------|----------------------|-------|-----------|--------|
| `PAUSED` | `AWAITING_DESIGN_REVIEW` | exploration | Entwurfsartefakt wartet auf Design-Review. Pipeline pausiert, bis Review-Ergebnis vorliegt. | `agentkit resume --story {id}` (nach Review-Abschluss) |
| `PAUSED` | `AWAITING_DESIGN_CHALLENGE` | exploration | Design-Review hat Einwaende erhoben. Pipeline pausiert, bis Challenge-Prozess abgeschlossen. | `agentkit resume --story {id}` (nach Challenge-Klaerung) |
| `PAUSED` | `GOVERNANCE_INCIDENT` | jede | Governance-Observer hat kritischen Incident erkannt. Pipeline pausiert sofort, Mensch muss intervenieren. | `agentkit resume --story {id}` (nach Incident-Klaerung) |
| `ESCALATED` | Preflight FAIL, Worker BLOCKED, Integrity-Gate FAIL, Max Runden im QA-Subflow, Merge-Konflikt, Gate-FAIL nach max Runden | setup, implementation, closure | Pipeline ist dauerhaft gestoppt fuer diese Iteration. Mensch muss Ursache klaeren und ggf. neuen Run starten. | `agentkit reset-escalation --story {id}` -> neuer Run |

**Technisch:** Der Phase-State mit `status: ESCALATED` oder `PAUSED`
verhindert, dass der Orchestrator die nächste Phase aufruft.

> **[Entscheidung 2026-04-08]** Element 7 — CrashScenario / CRASH_SCENARIO_CATALOG entfaellt als eigene Runtime-Datenstruktur in v3. Die Recovery-Logik (§20.7) existiert separat und bleibt bestehen. Die Szenario-Informationen bleiben in den Konzeptdokumenten (hier §20.7.1).
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 7.

## 20.7 Recovery

### 20.7.1 Szenarien

| Szenario | Phase-State | Recovery |
|----------|------------|---------|
| Agent-Session crashed mitten in Implementation | `phase: implementation, status: IN_PROGRESS` | Neuer Run mit neuer `run_id`. Worktree existiert noch, Commits sind da. Orchestrator spawnt neuen Worker, der die Arbeit fortsetzt. |
| Phase Runner crashed mitten im QA-Subflow | `phase: implementation, status: IN_PROGRESS, payload.qa_cycle_status: awaiting_qa` | `run-phase implementation` erneut aufrufen — Engine setzt den QA-Subflow am letzten persistierten `qa_cycle_status` fort. Schicht 1 hat bereits `structural.json` geschrieben (idempotent). Fortschritt wird aus vorhandenen Artefakten rekonstruiert. [Entscheidung 2026-04-09: `verify_layer` entfernt — ephemerer Fortschritt, nicht durable.] [Entscheidung 2026-05-01: Phase ist `implementation` — QA-Subflow.] |
| Closure crashed nach Merge aber vor Issue-Close | `payload.progress: {merge_done: true, issue_closed: false}` | `run-phase closure` erneut aufrufen. Merge wird übersprungen (bereits gemergt). Issue-Close wird ausgeführt. [Entscheidung 2026-04-09: `closure_substates` → `payload.progress` (ClosurePayload).] |
| Mensch will eskalierten Run fortsetzen | `status: ESCALATED` | Mensch setzt Phase-State zurück: `agentkit reset-escalation --story {story_id}`. Dann neuer Run. |

### 20.7.2 Run-ID und Retry

Jeder Pipeline-Durchlauf bekommt eine eigene `run_id` (UUID).
Bei Recovery (neuer Versuch nach Crash) wird eine neue `run_id`
erzeugt. Die alte `run_id` bleibt in der Telemetrie erhalten
für Forensik.

**Kein automatischer Retry.** Der Phase Runner versucht nicht
selbststaendig, eine gescheiterte Phase zu wiederholen. Recovery
ist immer eine bewusste Entscheidung — entweder des Orchestrators
(bei QA-Subflow-Failure -> Subflow-internem Feedback-Loop, §20.5)
oder des Menschen (bei Eskalation).

> **[Entscheidung 2026-04-08]** Element 8 — Scheduling Policies (3 Klassen) entfallen als Runtime-Datenstrukturen in v3. Die Scheduling-Informationen bleiben in der Konzeptdokumentation (hier §20.8). Reines Doku-Artefakt ohne Verhalten.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 8.

## 20.8 Scheduling und Priorisierung

### 20.8.1 Kein automatisches Scheduling

AgentKit hat keinen Scheduler. Der Orchestrator-Agent entscheidet,
welche Story als nächstes bearbeitet wird, indem er das GitHub
Project Board liest und eine freigegebene Story auswählt. Das ist
eine Agent-Entscheidung, die im Orchestrator-Prompt beschrieben
wird, kein deterministischer Mechanismus.

### 20.8.2 Orchestrator-Vertrag: ExecutionPlanning vor Story-Start

**Normative Regel (FK-70 §70.8):** `PipelineEngine` MUSS
`ExecutionPlanning.evaluate_scheduling` vor jedem Story-Start aufrufen.
`PipelineEngine` greift nicht selbststaendig in den Backlog; sie konsumiert
ausschliesslich die Top-Surface von `ExecutionPlanning` und ist
transport-agnostisch gegenueber der Scheduling-Logik.

`ExecutionPlanning.evaluate_scheduling` prueft Abhaengigkeiten,
Bereitschaftsstatus und Scheduling-Policy und liefert das Ergebnis zurueck
(bereit / blockiert / defer). Erst bei `READY` startet `PipelineEngine`
den Setup-Lauf fuer die Story.

Querverweise: FK-70 §70.8 (ExecutionPlanning-Top-Surface).

### 20.8.3 Parallelisierung

Mehrere Stories können parallel bearbeitet werden (FK-10 §10.5.1):
- Jede Implementation/Bugfix-Story hat eigenen Worktree, eigene Telemetrie, eigene Locks. Concept/Research-Stories arbeiten direkt auf main (kein Worktree/Branch, §20.2.3).
- Der Orchestrator kann mehrere Worker-Agents parallel spawnen
- Der Phase Runner arbeitet pro Story sequentiell

**Pipeline-übergreifende Koordination via Scope-Overlap-Check.**
Wenn zwei Stories denselben Code-Bereich betreffen, erkennt der
Preflight-Scope-Overlap-Check (FK-22 §22.3.1, Check 9) dies
vor dem Start der zweiten Story. Die Story bleibt im Backlog
bis die parallele Story gemergt ist. Zusätzlich greift beim Merge
die FF-only-Prüfung als zweite Verteidigungslinie.

---

*FK-Referenzen: FK-05-001/002 (feste Phasenfolge, Ablauf entscheidet),
FK-05-007 bis FK-05-010 (Prozessschwere nach Story-Typ),
FK-05-037 bis FK-05-057 (Story-Bearbeitung, Typ-Routing),
FK-05-209 bis FK-05-214 (Policy-Evaluation, Feedback-Loop),
FK-05-215 bis FK-05-232 (Closure-Sequenz, Eskalation),
FK-06-040 bis FK-06-055 (Execution/Exploration Mode)*

**Querverweise:**
- FK-39 — Phase-State-Persistenz: PhaseEnvelope, PhasePayload (discriminated union), PhaseMemory (carry-forward), AttemptRecord, PauseReason-Enum, Lese-/Schreibprotokoll
- FK-45 — Phase Runner CLI: `agentkit run-phase`, Phasen-Dispatch, Phase-Transition-Enforcement, Orchestrator-Reaktionstabelle
- FK-38 — QA-Subflow-Feedback und Dokumententreue-Schleife: Maengelliste-Format, Mandatory-Target-Rueckkopplung, Ebene 3 und 4
- FK-35 — Integrity-Gate, Governance-Beobachtung und Eskalation
- FK-23 — Modusermittlung und Exploration: ExplorationPayload, gate_status, Design-Review-Gate
- FK-37 — QA-Subflow-Context: verify_context als Subflow-internes Diskriminator-Feld, integration_stabilization-Vertragsprofil
- FK-29 — Closure-Sequence: ClosurePayload, ClosureProgress, Substate-Recovery
- FK-53 — StoryResetService: Vollständiger Story-Reset-Pfad
- FK-54 — StorySplitService: Scope-Explosion und Successor-Stories
