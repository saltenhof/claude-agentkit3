---
concept_id: FK-02
title: "Domänenmodell, Zustände und Artefakte"
module: domain-model
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: domain-model
defers_to:
  - target: FK-67
    scope: artefakt-envelope
    reason: Artefaktklassen, Envelope, Lock-Record und Stage-Registry sind in FK-67 normiert
supersedes: []
superseded_by:
tags: [domaenenmodell, zustaende, artefakte, lock-record, stage-registry]
formal_scope: prose-only
---

# 02 — Domänenmodell, Zustände und Artefakte

## 2.1 Kanonische Begriffe

Dieses Kapitel definiert die Begriffe, die im gesamten Feinkonzept
verwendet werden. Jeder Begriff hat eine exakte technische Bedeutung.

| Begriff | Definition | Technische Repräsentation |
|---------|-----------|--------------------------|
| **Story** | Kleinste planbare Arbeitseinheit. Entspricht einem GitHub Issue mit AgentKit Custom Fields. | GitHub Issue + Project Item |
| **Projekt** | Ein registriertes Zielprojekt, gegen das eine zentrale AgentKit-Installation arbeitet. | Projektregistrierung + lokale Projektkonfiguration |
| **Project-Key** | Mandanten-Schlüssel eines registrierten Projekts. Alle kanonischen Runtime- und Analytics-Records sind daran gebunden. | String, systemweit eindeutig |
| **Story-ID** | Eindeutiger Identifikator einer Story. Format: `{PREFIX}-{NNN}`, z.B. `ODIN-042`. | String, Regex: `[A-Z][A-Z0-9]+(?:-[A-Z][A-Z0-9]+)*-\d+` |
| **Story-Typ** | Klassifikation der Story. Bestimmt den Pipeline-Pfad. | Enum: `implementation`, `bugfix`, `concept`, `research` |
| **Story-Größe** | Geschätzter Umfang. Beeinflusst Review-Häufigkeit. | Enum: `XS`, `S`, `M`, `L`, `XL` |
| **Run** | Eine Ausführung der Pipeline für eine Story. Eine Story kann mehrere Runs haben (bei Retry/Rework). | `run_id` (UUID), erzeugt beim Setup. Technischer Ausführungsschlüssel neben `story_id`. |
| **Phase** | Ein Abschnitt des Pipeline-Ablaufs. | Enum: `setup`, `exploration`, `implementation`, `verify`, `closure` |
| **Stage** | Ein Prüfschritt innerhalb einer Phase. Typisiert mit Schicht, Story-Typ-Geltung und Blocking-Modus. | Typisiertes Objekt in Stage-Registry (siehe 2.9) |
| **Flow** | Hierarchisch interpretierbarer Ablaufvertrag. Kann Pipeline, Phase oder Komponente beschreiben. | `FlowDefinition` der Prozess-DSL |
| **Node / Schritt** | Atomarer oder zusammengesetzter Kontrollfluss-Knoten innerhalb eines Flows. | `NodeDefinition(kind="step" \| "gate" \| "yield" \| "branch" \| "subflow")` |
| **Guard** | Permanenter Hook-basierter Schutzmechanismus. Blockiert verbotene Aktionen. | Python-Skript, PreToolUse-Hook, exit(0)/exit(2) |
| **Gate** | Einmaliger oder mehrstufiger Prüfpunkt innerhalb eines Flows. Blockiert bei Failure den Fortschritt. | `Gate`-Knoten der Prozess-DSL + deterministischer Gate-Runner |
| **Execution Policy** | Regel, ob ein Schritt immer, nur einmal oder nur bis zum Erfolg ausgeführt werden darf. | Enum auf `NodeDefinition` |
| **Override** | Expliziter, auditierbarer Eingriff von Mensch/Orchestrator in den Ablauf. | Override-Record / CLI-Kommando, durch Engine ausgewertet |
| **Artefakt** | Maschinenlesbares Ergebnis eines Pipeline-Schritts. | Strukturierter Record im zentralen State-Backend; optional als JSON exportierbar |
| **Incident** | Einzelbeobachtung eines Agent-Fehlverhaltens. | JSONL-Eintrag in Failure Corpus |
| **Pattern** | Wiederkehrendes Muster über mehrere Incidents. | JSONL-Eintrag in Failure Corpus |
| **Check** | Deterministischer Guard, abgeleitet aus einem Pattern. | Python-Skript, registriert in Stage-Registry |
| **Entwurfsartefakt** | Kompakter Change-Frame mit 7 Bestandteilen. Entsteht in der Exploration-Phase. | JSON-Datei, validiert gegen Schema |
| **Handover-Paket** | Strukturierte Übergabe vom Worker an die Verify-Phase. | JSON-Datei, validiert gegen Schema |
| **Worker-Manifest** | Technische Deklaration der Worker-Ergebnisse. | JSON-Datei (`worker-manifest.json`) |
| **Protocol** | Menschenlesbares Protokoll der Story-Bearbeitung. | Markdown-Datei (`protocol.md`) |
| **Mängelliste** | Strukturierte Liste von Befunden aus der Verify-Phase. | JSON-Array mit Check-Ergebnissen |
| **Eskalation** | Pipeline-Stopp mit menschlicher Intervention. Story bleibt "In Progress". | Kein technisches Objekt; Pipeline-Halt + opake Meldung |

## 2.2 Zustandsmodelle

### 2.2.1 Story-Zustände (GitHub Project Board)

Vier Zustände im GitHub Project Board. Nur diese sind extern sichtbar.

```mermaid
stateDiagram-v2
    [*] --> Backlog : Issue erstellt
    Backlog --> Freigegeben : Mensch gibt frei
    Freigegeben --> InProgress : Pipeline startet
    InProgress --> Done : Closure PASS
    InProgress --> Cancelled : offizieller Story-Split
    InProgress --> Backlog : Ablehnung / Rework
    Done --> [*]
    Cancelled --> [*]
```

**Technische Umsetzung:** Das `Status`-Feld ist ein Single-Select
Custom Field im GitHub Project V2. Werte: `Backlog`, `Freigegeben`,
`In Progress`, `Done`, `Cancelled`. Änderungen erfolgen via
GraphQL-Mutation:

```graphql
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId
    itemId: $itemId
    fieldId: $statusFieldId
    value: { singleSelectOptionId: $optionId }
  }) { projectV2Item { id } }
}
```

### 2.2.2 Interne Pipeline-Zustände

Interne Zustände ändern den GitHub-Status NICHT. Die Story bleibt
"In Progress", solange kein offizieller administrativer Pfad
(`StorySplitService`, `StoryResetService`) ausgefuehrt wird. Interne
Zustände leben im zentralen State-Backend und in der Telemetrie.

```mermaid
stateDiagram-v2
    state "In Progress (GitHub)" as IP {
        [*] --> setup
        setup --> exploration : Exploration Mode
        setup --> implementation : Execution Mode
        exploration --> implementation : Dokumententreue PASS
        exploration --> ESKALATION : Dokumententreue FAIL
        implementation --> verify
        verify --> implementation : FAIL (Feedback-Loop, max N Runden)
        verify --> closure : PASS
        closure --> [*] : Integrity-Gate PASS + Postflight
        closure --> ESKALATION : Integrity-Gate FAIL
    }
```

**Normative Auslegung:** Die sichtbare State Machine ist die
Pipeline-Ebene eines groesseren hierarchischen Ablaufmodells. Dieselben
Konstrukte (Guards, Gates, Yield-Points, Rueckspruenge, Execution
Policies, Overrides) gelten auch innerhalb von Phasen und Komponenten.
Die Pipeline ist also kein Sonderfall, sondern die oberste
`FlowDefinition` des Systems.

> **[Entscheidung 2026-04-08]** Element 3 — NON_DETERMINISTIC_PHASE Konstanten entfallen in v3. Stattdessen `requires_llm: bool` pro Phase in der Phase-Config.
> Element 16 — PhaseState wird in v3 nach Ownership getrennt: StoryContext (langlebige Story-Semantik), PhaseStateCore (aktueller Laufzeitstatus), PhasePayload (diskriminierte Union pro Phase), RuntimeMetadata (nicht-fachliche Loader-/Guard-Infos). `mode`, `story_type` raus aus PhaseState, rein in StoryContext.
> Die fachliche Ausmodellierung steht jetzt in FK-17, die relationale Abbildung in FK-18.

**Pipeline-State-Record:** zentrale Runtime-Projektion
(`phase_state_projection`) im State-Backend.

> **[Hinweis 2026-04-08]** Das folgende JSON-Beispiel ist nur noch ein
> Legacy-Uebergangsbild fuer die fachliche Idee. Autoritativ sind jetzt
> FK-17 (Attributvertraege) und FK-18 (relationale Abbildung).

```json
{
  "schema_version": "3.0",
  "project_key": "odin-trading",
  "story_id": "PROJ-042",
  "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "phase": "verify",
  "status": "IN_PROGRESS",
  "started_at": "2026-03-16T14:00:00+01:00",
  "finished_at": "2026-03-16T14:23:01+01:00",
  "attempt": 2,
  "mode": "exploration",
  "verify_result": "RUN_SEMANTIC",
  "exploration_gate_status": "approved_for_implementation",
  "exploration_review_round": 0,
  "closure_completed": false,
  "closure_substates": {
    "integrity_gate_passed": false,
    "merge_completed": false,
    "issue_closed": false,
    "metrics_written": false,
    "postflight_passed": false
  },
  "feedback_rounds": 1,
  "max_feedback_rounds": 3,
  "agents_to_spawn": [],
  "errors": [],
  "warnings": [],
  "producer": { "type": "script", "name": "run-phase" }
}
```

**Neue Felder (REF-034):**

| Feld | Typ | Gültig in Phase | Bedeutung |
|------|-----|-----------------|-----------|
| `exploration_gate_status` | String | `exploration` | Fortschritt durch das Drei-Stufen-Gate am Ende der Exploration. Muss `"approved_for_implementation"` sein bevor Verify läuft. Gültige Werte: `""`, `"doc_compliance_passed"`, `"design_review_passed"`, `"design_review_failed"`, `"approved_for_implementation"` |
| `exploration_review_round` | Integer | `exploration` | Zähler für Design-Review-Remediation-Runden. Max 2 Runden, dann Eskalation. |

**Entfernt (REF-034):** `verify_result = "STRUCTURAL_ONLY_PASS"` ist kein gültiger Wert mehr.
Exploration-mode Stories durchlaufen nach der Implementation die volle 4-Schichten-Verify.

**Mandantenregel:** `story_id` ist kein systemweit ausreichender
Schlüssel. Kanonische Records im State-Backend werden immer mindestens
unter `(project_key, story_id, run_id?)` geführt.

### 2.2.2a Flow-Ausfuehrung, Node-Ledger und Overrides

Die Einheits-DSL aus FK-20 braucht einen kanonischen Laufzeitzustand,
damit `ExecutionPolicy`, Rueckspruenge und Overrides nicht implizit in
Handlern versteckt werden. Dieser Zustand gehoert fachlich zum
`PhaseStateStore`.

**Normative Aufteilung:**

- `StoryContext`: langlebige Story-Semantik wie `story_type`, `mode`,
  Konzept-Referenzen und Scope
- `PhaseStateCore`: aktueller Top-Level-Phasenstatus der Pipeline
- `FlowExecution`: aktueller Ausfuehrungszustand eines konkreten
  `FlowDefinition`-Versuchs
- `NodeExecution`: persistierte Node-Historie pro `node_id`
- `AttemptRecord`: append-only Historie eines Phasenversuchs
- `OverrideRecord`: auditierbarer Eingriff von Mensch/Orchestrator

```python
@dataclass(frozen=True)
class FlowExecution:
    project_key: str
    story_id: str
    run_id: str
    flow_id: str
    level: str              # pipeline | phase | component
    owner: str              # PipelineEngine, Installer, StageRegistry, ...
    parent_flow_id: str | None
    status: str             # READY | IN_PROGRESS | YIELDED | COMPLETED | FAILED | ABORTED
    current_node_id: str | None
    attempt_no: int
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class NodeExecution:
    project_key: str
    story_id: str
    run_id: str
    flow_id: str
    node_id: str
    attempt_no: int
    outcome: str               # PASS | FAIL | SKIP | YIELD | BACKTRACK
    started_at: datetime
    finished_at: datetime | None
    resume_trigger: str | None
    backtrack_target: str | None


@dataclass(frozen=True)
class AttemptRecord:
    project_key: str
    story_id: str
    run_id: str
    phase: str
    attempt_no: int
    outcome: str               # COMPLETED | FAILED | ESCALATED | YIELDED | BLOCKED | SKIPPED
    failure_cause: str | None
    started_at: datetime
    ended_at: datetime


@dataclass(frozen=True)
class OverrideRecord:
    override_id: str
    project_key: str
    story_id: str
    run_id: str
    flow_id: str
    target_node_id: str | None
    override_type: str         # skip_node | force_gate_pass | force_gate_fail | jump_to | truncate_flow | freeze_retries
    actor_type: str            # human | orchestrator
    actor_id: str
    reason: str
    created_at: datetime
    consumed_at: datetime | None
```

**Semantik:**

1. `ExecutionPolicy` wird ausschliesslich gegen `NodeExecution`
   ausgewertet.
2. Rueckspruenge erhoehen `attempt_no` des betroffenen Flows, loeschen
   aber keine Historie.
3. Ein `subflow` erzeugt einen eigenen `FlowExecution`-Record mit
   `parent_flow_id`, nicht bloss einen Flag im Elternflow.
4. Overrides werden nie inline ausgefuehrt, sondern als
   `OverrideRecord` persistiert und erst bei der naechsten
   Engine-Auswertung konsumiert.
5. `story_id` allein reicht auch fuer diese Records nicht; der Scope
   ist immer mindestens `(project_key, story_id, run_id, flow_id)`.

### 2.2.3 Verify-Schicht-Zustände (implementierende Stories)

Die vollständige Verify-Pipeline mit vier Schichten gilt **nur für
implementierende Story-Typen** (Implementation, Bugfix). Jede
Schicht kann PASS oder FAIL ergeben.

```mermaid
flowchart TD
    S1["Schicht 1:<br/>Deterministische Checks"] -->|PASS| S2
    S1 -->|FAIL| FB["Feedback an Worker"]

    S2["Schicht 2: LLM-Bewertungen"] -->|PASS| S3
    S2 -->|FAIL| FB

    S2A["QA-Review<br/>(12 Checks, LLM A)"] --> S2G{Gate}
    S2B["Semantic Review<br/>(LLM B)"] --> S2G
    S2 -.-> S2A
    S2 -.-> S2B

    S3["Schicht 3:<br/>Adversarial Testing"] -->|keine Befunde| S4
    S3 -->|Befunde| FB

    S4["Schicht 4:<br/>Policy-Evaluation"] -->|PASS| DONE["Verify bestanden"]
    S4 -->|FAIL| FB

    style FB fill:#f8d7da,stroke:#dc3545
    style DONE fill:#d4edda,stroke:#28a745
```

**Zustandspersistenz:** Jede Schicht schreibt ihr Ergebnis als
separaten Artefakt-Record in das State-Backend; daraus können bei
Bedarf JSON-Exporte erzeugt werden:

| Schicht | Kanonischer Record | Optionale Materialisierung | Producer |
|---------|--------------------|---------------------------|----------|
| 1 | `ArtifactRecord(kind="structural")` | `structural.json` | `qa-structural-check` |
| 2 | `ArtifactRecord(kind="qa_review")` | `qa_review.json` | `qa-llm-review` |
| 2 | `ArtifactRecord(kind="semantic_review")` | `semantic_review.json` | `qa-semantic-review` |
| 3 | `ArtifactRecord(kind="adversarial")` | `adversarial.json` | `qa-adversarial` |
| 4 | Policy-/Verify-Decision-Record | `policy.json` / Legacy-Export `decision.json` | `qa-policy-engine` |

### 2.2.4 Abweichende Abläufe nach Story-Typ

Nicht alle Story-Typen durchlaufen die vollständige Pipeline.
Die vier Schichten der Verify-Phase (2.2.3) sind der Ablauf für
implementierende Stories. Research- und Konzept-Stories nehmen
grundlegend andere Wege.

**Research-Stories** produzieren ein strukturiertes Rechercheergebnis,
keinen Code. Sie durchlaufen:
- Preflight-Gates (wie alle Stories)
- Skill-gesteuerte Recherche (kein Worktree, kein Branch)
- Leichtgewichtige Qualitätsprüfung (Struktur, Quellenvielfalt,
  Bewertungskriterien)
- Kein Exploration/Execution-Routing, keine Verify-Pipeline,
  kein Integrity-Gate

**Konzept-Stories** produzieren ein Konzeptdokument, keinen Code.
Sie durchlaufen:
- Preflight-Gates
- Konzepterstellung durch Worker-Agent
- VektorDB-Abgleich auf Überschneidungen mit bestehenden Konzepten
- **Pflicht-Feedback-Loop mit zwei LLMs** (siehe unten)
- Leichtgewichtige Qualitätsprüfung (Struktur, Vollständigkeit,
  Feedback-Einarbeitung)
- Kein Exploration/Execution-Routing, keine vollständige Verify-Pipeline,
  kein Integrity-Gate

#### Konzept-Story: Pflicht-Feedback-Loop

Konzept-Stories müssen vor Abschluss einen strukturierten
Feedback-Zyklus durchlaufen. Dieser ist nicht optional.

```mermaid
flowchart TD
    KONZEPT["Worker erstellt<br/>Konzeptdokument"] --> SPARRING

    subgraph SPARRING ["Pflicht-Feedback (2 LLMs)"]
        SEND_A["Konzept an LLM A<br/>(z.B. ChatGPT)"] --> FB_A["Feedback A<br/>(vollständig geloggt)"]
        SEND_B["Konzept an LLM B<br/>(z.B. Gemini)"] --> FB_B["Feedback B<br/>(vollständig geloggt)"]
    end

    FB_A --> EINARBEITUNG["Worker arbeitet<br/>Feedback ein oder<br/>begründet Ablehnung"]
    FB_B --> EINARBEITUNG

    EINARBEITUNG --> QA_CHECK{"QA-Agent prüft:<br/>Einarbeitung erfolgt<br/>oder begründet<br/>abgelehnt?"}

    QA_CHECK -->|ja| DONE["Konzept abgeschlossen"]
    QA_CHECK -->|nein| REWORK["Nacharbeit"] --> EINARBEITUNG

    style SPARRING fill:#e8f4f8,stroke:#17a2b8
```

**Regeln:**

| Regel | Beschreibung |
|-------|-------------|
| Pflicht-LLMs | Mindestens 2 verschiedene LLM-Familien (konfiguriert in `llm_roles`) |
| Vollständiges Logging | Prompt und Response beider LLM-Calls werden vollständig in der Telemetrie protokolliert (nicht nur Aufrufzähler) |
| Keine blinde Übernahme | Es besteht keine Pflicht, alles einzuarbeiten — LLMs können auch Unsinn liefern |
| Begründungspflicht | Jeder Feedback-Punkt, der nicht eingearbeitet wird, muss im Konzeptdokument mit Begründung dokumentiert werden |
| QA-Prüfung | Ein QA-Agent (oder LLM-Bewertungsfunktion) prüft, ob zu jedem Feedback-Punkt eine Einarbeitung oder eine nachvollziehbare Begründung der Ablehnung vorliegt |
| Telemetrie-Nachweis | Die Telemetrie muss die Feedback-Calls vollständig protokollieren. Der Nachweis wird von der leichtgewichtigen QA-Prüfung (nicht vom Integrity-Gate, das Konzept-Stories nicht durchlaufen) ausgewertet. |

**Abgrenzung zum Verify-Prozess:** Dieser Feedback-Loop ist bewusst
leichtgewichtig. Er ersetzt nicht die 4-Schichten-Verify-Pipeline
der implementierenden Stories, sondern stellt sicher, dass Konzepte
mit Architektenbrille (bestehende Architektur, Systembestand) und
Business-Stakeholder-Brille (fachliche Korrektheit) gegengeprüft
werden, bevor sie zur Grundlage von Umsetzungs-Stories werden.

### 2.2.5 Failure-Corpus-Zustände

Der Failure Corpus hat ein eigenes Zustandsmodell für seine drei
Artefakttypen. Details in Kapitel 41, hier das Zustandsmodell als
Teil des Domänenmodells.

```mermaid
stateDiagram-v2
    state "Incident" as INC {
        [*] --> erfasst
        erfasst --> klassifiziert : LLM-Adjudication
        klassifiziert --> [*]
    }

    state "Pattern" as PAT {
        [*] --> candidate : Clustering schlägt vor
        candidate --> confirmed : Mensch bestätigt
        candidate --> rejected : Mensch verwirft
        confirmed --> [*]
    }

    state "Check" as CHK {
        [*] --> draft : LLM erzeugt Proposal
        draft --> approved : Mensch gibt frei
        draft --> rejected_chk : Mensch verwirft
        approved --> active : Worker implementiert
        active --> tuned : Wirksamkeitsreview
        active --> retired : Auto-Deaktivierung (90d, >3 FP)
        tuned --> active
        tuned --> retired
    }

    INC --> PAT : Promotion (3x/30d, 1x kritisch, 2x+checkbar)
    PAT --> CHK : Check-Ableitung (6-Schritt-Prozess)
```

## 2.3 Identifikatoren und Korrelation

### 2.3.1 ID-Schema

| Entität | Format | Beispiel | Erzeugung |
|---------|--------|----------|-----------|
| Story-ID | `{PREFIX}-{NNN}` | `ODIN-042` | GitHub Issue Nummer + Projektprefix |
| Run-ID | UUID v4 | `a1b2c3d4-e5f6-...` | Phase Runner beim Setup |
| Issue-Nummer | Integer | `42` | GitHub (auto-increment) |
| Branch-Name | `story/{story_id}` | `story/ODIN-042` | Worktree-Setup |
| Story-Verzeichnis | `{story_id}_{slug}` | `ODIN-042_implement-broker-api` | Context-Berechnung |
| Story-Paket | `{story_id}_{slug}` | `ODIN-042_implement-broker-api` | Story-Export |
| Artefakt-Referenz | `artifact_id` | `art-structural-001` | Artifact Manager |
| Lock-Record | `(project_key, story_id, run_id, lock_type)` | `(odin, ODIN-042, run-123, qa_artifact_write)` | Pipeline-Skripte |
| Adversarial-Sandbox | `_temp/adversarial/{story_id}/` | `_temp/adversarial/ODIN-042/` | Phase Runner |
| Incident-ID | `FC-{YYYY}-{NNNN}` | `FC-2026-0017` | Failure Corpus |
| Pattern-ID | `FP-{NNNN}` | `FP-0003` | Failure Corpus |
| Check-ID | `CHK-{NNNN}` | `CHK-0012` | Failure Corpus |
| Checkpoint-Name | `cp_{nn}_{name}` | `cp_04_github_fields` | Installer |

### 2.3.2 Korrelation

Alle Artefakte und Events werden über zwei Schlüssel korreliert:

- **`story_id`** — fachlicher Schlüssel. Identifiziert die Story
  über alle Runs hinweg. Pflichtfeld in jedem Telemetrie-Event,
  jedem QA-Artefakt-Envelope, Teil des Branch-Namens, des
  Verzeichnisnamens und der zentralen Runtime-/Telemetry-Records.

- **`run_id`** — technischer Ausführungsschlüssel. Identifiziert
  einen einzelnen Pipeline-Durchlauf. Wird beim Setup als UUID
  erzeugt und in alle Events und Artefakte dieses Durchlaufs
  geschrieben. Ermöglicht:
  - Klare Trennung bei Retry/Rework (welche Events gehören zu
    welchem Versuch)
  - Recovery nach Absturz (Run-ID identifiziert den unterbrochenen
    Lauf)
  - Incident-Korrelation (welcher Run hat den Incident ausgelöst)
  - Forensik (alle Aktionen eines Laufs isoliert abrufbar)

Eine Story kann mehrere Runs haben. Ein Run gehört immer zu genau
einer Story.

## 2.4 Artefaktklassen und Ownership

> Artefaktklassen (Worker / QA / Pipeline / Telemetrie / Governance /
> Entwurf / Handover / Adversarial-Sandbox) und ihre Ownership-Regeln
> sind in **FK-67 §67.1** normiert. Die Producer-Registry liegt in
> **FK-67 §67.2**.

## 2.5 Artefakt-Envelope-Schema

> Artefakt-Envelope (Pflichtfelder, LLM-Status-Mapping
> PASS/PASS_WITH_CONCERNS/FAIL → PASS/WARN/FAIL, Producer-Registry)
> ist in **FK-67 §67.2** normiert.

## 2.6 Fachliche Invarianten (technisch durchgesetzt)

| Invariante | Durchsetzung | Mechanismus |
|------------|-------------|-------------|
| Ein Agent kann nicht entscheiden, was implementiert wird | Preflight prüft `Status == "Approved"` | `preflight.py` |
| Alle Änderungen auf Story-Branch isoliert | Branch-Guard blockiert Main-Operationen | `branch_guard.py` Hook |
| Orchestrator implementiert nicht | Orchestrator-Guard blockiert Codebase-Zugriff | `orchestrator_guard.py` Hook |
| Worker kann QA nicht manipulieren | Lock-Record-Mechanismus + CCAG blockiert Sub-Agents (siehe 2.7) | Lock-Record + CCAG-Regeln |
| LLM bewertet, Pipeline entscheidet | LLM-Antwort wird geparst; Pipeline wertet Status-Feld aus | `llm_evaluator.py` |
| Kein Issue-Close ohne Merge | Closure führt Merge vor Close durch | `closure.py` |
| Kein Issue-Close ohne Integrity-Gate | Integrity-Hook fängt `gh issue close` ab | `integrity.py` Hook |
| Multi-LLM ist Pflicht | Integrity-Gate prüft Telemetrie-Nachweise für alle Pflicht-Reviewer | `integrity.py` |
| Fehlende Felder → Exploration Mode | Mode-Router behandelt fehlendes Feld als Exploration-Kriterium | `mode_router.py` |
| GitHub-Felder sind Eingabe, nicht operative Wahrheit | Nach Setup wird `StoryContext` als autoritativer Snapshot im State-Backend persistiert. Optional kann daraus ein `context.json` exportiert werden. Ab da liest die Pipeline den Snapshot, nicht mehr GitHub. Enums validiert, Referenzen aufgelöst, abgeleitete Flags berechnet. | `context.py` → `story_contexts` / optional `context.json` |
| Maximal 2 LLM-Aufrufe pro Check | LLM-Evaluator begrenzt Retry auf 1 | `llm_evaluator.py` |
| Konzept-Feedback ist Pflicht | Telemetrie + QA-Agent prüfen Feedback-Einarbeitung | Konzept-Feedback-Loop (2.2.4) |
| Adversarial Agent schreibt nicht direkt ins Repo | Tests nur in Sandbox, Promotion durch Pipeline-Skript | Adversarial-Sandbox + Promotion-Skript |

## 2.7 Lock-Mechanismus für QA-Artefaktschutz

> Lock-Record-Mechanismus (Prinzip, qa_artifact_write_lock-Record,
> Lebenszyklus, PID-/TTL-basierte Stale-Erkennung, Sub-Agent-Scoping,
> CCAG-Regel) ist in **FK-67 §67.3** normiert.

## 2.9 Typisierte Stage-Registry

> Typisierte Stage-Registry (StageDefinition-Datamodell mit
> id/layer/kind/applies_to/blocking/trust_class/producer und
> Standard-Stages) ist in **FK-67 §67.4** normiert.

## 2.10 Aufgelöste Konflikte: Bestandscode vs. Fachkonzept

An mehreren Stellen implementiert der bestehende Code Funktionalität,
die im Fachkonzept nicht beschrieben ist oder ihm widerspricht. Diese
Konflikte wurden analysiert und entschieden.

### K-01: Meta-QA als eigenständige Phase → ENTFÄLLT

**Bestandscode:** Phase Runner hat `meta_qa` als 6. Phase nach Closure
mit eigenem Prompt und Agent-Spawn.

**FK-Aussage (6.6):** "Diese Beobachtung ist kein eigenständiger Agent,
sondern eine in die bestehende Infrastruktur eingebettete
Governance-Schicht." Prozessüberwachung erfolgt über Hooks und
Phasen-Skripte, nicht als separater Agent.

**Kernproblem:** Ein Agent, der den Orchestrator überwachen soll, wird
vom Orchestrator selbst gespawnt. Das funktioniert in der Praxis nicht,
weil der Orchestrator seine eigene Überwachung kontrolliert.

**Entscheidung:** Meta-QA als eigenständige Phase wird entfernt.
Die Prozessüberwachung wird stattdessen über zwei FK-konforme
Mechanismen umgesetzt:

1. **Hook-basierte Echtzeit-Sensorik** (FK 6.6): Hooks überwachen
   auch den Orchestrator — jede Aktion wird normalisiert, akkumuliert,
   bei Schwellenüberschreitung als Incident-Kandidat behandelt. Der
   Orchestrator kann seine eigenen Hooks nicht umgehen.
2. **Phasen-Skript-basierte Anomalie-Erkennung** (FK 6.6): Skripte
   prüfen Phasenfortschritt, Retry-Loops, Stagnation. Diese laufen
   unabhängig vom Orchestrator.

Was aus dem bestehenden Meta-QA-Code sinnvoll ist (Artefakt-
Vollständigkeitsprüfung, Prozess-Konsistenz), wird in die
Postflight-Gates (bereits im FK vorgesehen) und in die Governance-
Beobachtung (FK 6.6) überführt.

**Konsequenz für Pipeline-Phasen:** 5 statt 6 Phasen.
`setup → exploration? → implementation → verify → closure`

### K-02: Shadow Mode → ENTFERNT

**Bestandscode:** `shadow` Config-Sektion mit `enabled`,
`required_stories`, `cutover_timeout_weeks`.

**Entscheidung:** Komplett entfernen. Shadow Mode ist kein Teil
des Zielbilds. Die Config-Sektion, der zugehörige Code und die
Pydantic-Modelle werden gelöscht.

### K-03: E2E-Assertion-Engine → ZURÜCKBAUEN auf FK-Umfang

**Bestandscode:** Eigenständiges Subsystem mit Trust-Klassen-Registry,
Checker-Plugins, Scaffold, Assertion-Governance (manual_budget_percent).

**Kernproblem:** Die Engine hat die Frage "Wer erstellt wann die
Assertions?" nicht beantwortet:

- **Zum Zeitpunkt der Story-Erstellung** steht die konkrete
  Architektur und Umsetzung oft noch nicht fest. Deterministische
  Checks, die von der Lösungsarchitektur abhängen (Tabellennamen,
  API-Endpunkte, Spaltenstrukturen), können zu diesem Zeitpunkt
  nicht erstellt werden.
- **Was möglich ist:** Allgemeine Systemprüfungen (System fährt
  hoch, Smoketest möglich) und begrenzt domänenspezifische Checks
  aus Akzeptanzkriterien (fachliche Zustände abfragen).
- **Was nicht möglich ist:** Tiefe technische Assertions, die
  Implementierungsdetails voraussetzen.

**Entscheidung:** Die E2E-Assertion-Engine wird auf den FK-Umfang
zurückgebaut:

1. **Trust-Klassen (FK 7.2) bleiben.** Das Konzept A/B/C ist
   fachlich fundiert und wird in der Verify-Pipeline (Schicht 1)
   bei der Bewertung von Evidence angewendet.
2. **Allgemeine System-Assertions bleiben.** Systemstart, Health-
   Check, Smoketest — diese können vorab definiert werden.
3. **Die Checker-Registry und das Plugin-System werden vereinfacht.**
   Kein aufwändiges Scaffold, keine Assertion-Governance mit
   Budget-Prozent. Stattdessen: Structural Checks (Schicht 1)
   prüfen die allgemeinen Assertions als Teil des regulären
   Check-Katalogs.
4. **Story-spezifische fachliche Assertions** werden nicht vorab
   definiert, sondern entstehen als Teil der Verify-Phase
   (Schicht 2: LLM-Bewertung prüft Akzeptanzkriterien,
   Schicht 3: Adversarial Agent schreibt gezielte Tests).

**Konsequenz:** `assertion_governance` Config-Sektion wird
vereinfacht. `e2e_assertions` Feature-Flag bleibt, steuert aber
nur noch die allgemeinen System-Assertions, nicht ein eigenständiges
Subsystem.

---

*FK-Referenzen: FK-05-001 bis FK-05-010 (Zustände, Typen),
FK-05-041 bis FK-05-051 (Konzept/Research-Pfade),
FK-05-058 bis FK-05-069 (Preflight), FK-06-029 bis FK-06-034
(Artefaktschutz), FK-06-071 bis FK-06-094 (Integrity-Gate),
FK-08-001 bis FK-08-005 (Telemetrie-Grundlagen)*
