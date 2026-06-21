---
concept_id: FK-39
title: Phase-State-Persistenz und Phase-Envelope-Modell
module: phase-state-persistence
domain: pipeline-framework
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: phase-envelope
  - scope: phase-state-projection
  - scope: phase-payload
  - scope: phase-memory
  - scope: attempt-record
  - scope: pause-reason
defers_to:
  - target: FK-20
    scope: workflow-engine
    reason: Phase-Runner und Engine-Mechanik liegen in FK-20; FK-39 ist die State-Schicht darunter
  - target: FK-45
    scope: phase-runner-cli
    reason: CLI-Dispatch und Phase-Transition-Enforcement liegen in FK-45
  - target: FK-23
    scope: exploration-payload
    reason: ExplorationPayload und ExplorationPhaseMemory werden in FK-23 fachlich verfeinert
  - target: FK-37
    scope: verify-context
    reason: verify_context-Semantik (Subflow-internes Diskriminator-Feld der Implementation-Phase) liegt in FK-37
  - target: FK-29
    scope: closure-payload
    reason: ClosurePayload und ClosureProgress liegen in FK-29
  - target: FK-59
    scope: story-contract-classification
    reason: "`mode`/`execution_route` ist eine Vertragsachse aus FK-59"
  - target: FK-10
    scope: state-backend
    reason: State-Backend-Persistenz und phase_state_projection-Mechanik in FK-10 §10.5
  - target: FK-02
    scope: domain-model
    reason: Story-Lifecycle-Zustände und kanonische Enums liegen im Domänenmodell
  - target: FK-71
    scope: artefakt-envelope
    reason: phase-state.json wird als Pipeline-Artefakt mit Envelope-Schema materialisiert (FK-71)
supersedes: []
superseded_by:
tags: [state-machine, phase-runner, persistenz, runtime-state, state-backend]
prose_anchor_policy: strict
formal_refs:
  - formal.implementation.entities
  - formal.implementation.invariants
  - formal.verify.entities
  - formal.story-workflow.invariants
glossary:
  exported_terms:
    - id: attempt-record
      definition: >
        Durables Fehlerartefakt, das durable Fehlerinformationen eines
        einzelnen Phase-Ausfuehrungsversuchs erfasst. Ueberlebt Crashes
        und Phase-Transitionen. Wird vom Phase Runner erzeugt und ist
        die kanonische Quelle fuer Retry-Entscheidungen und
        Post-Mortem-Analyse.
    - id: pause-reason
      definition: >
        StrEnum mit drei Werten, das den Grund eines PAUSED-Zustands
        beschreibt. AWAITING_DESIGN_REVIEW: Entwurfsartefakt wartet auf
        Design-Review. AWAITING_DESIGN_CHALLENGE: Design-Challenge-
        Prozess laeuft. GOVERNANCE_INCIDENT: Governance-Observer hat
        kritischen Incident erkannt. Jeder andere Wert ist ungueltig.
      values: [AWAITING_DESIGN_REVIEW, AWAITING_DESIGN_CHALLENGE, GOVERNANCE_INCIDENT]
    - id: phase-envelope
      definition: >
        Frozen Dataclass als Laufzeit-Container fuer eine Phase-
        Ausfuehrung. Enthaelt state (PhaseState, wird persistiert) und
        runtime (RuntimeMetadata, ephemer). Wird nie als Ganzes
        persistiert; nur der state-Teil wird als phase_state_projection
        geschrieben.
    - id: phase-memory
      definition: >
        Phasenuebergreifende Zaehler, die per Carry-Forward ueber
        Phase-Transitionen und Subflow-Iterationen mitgefuehrt werden.
        Enthaelt exploration.review_rounds und
        implementation.qa_feedback_rounds. Wird ausschliesslich von der
        Engine inkrementiert, nie von Phase-Handlern.
    - id: phase-payload
      definition: >
        Discriminated union im PhaseState, gesteuert ueber payload.type.
        Enthaelt phase-spezifische Durable Contract Fields. Typen:
        ExplorationPayload (gate_status), ImplementationPayload
        (qa_cycle_status, verify_context, qa_feedback_rounds),
        ClosurePayload (progress). Setup hat kein Payload (null).
    - id: phase-state-core
      definition: >
        Pflicht-Kernteil des persistierten PhaseState. Enthaelt
        story_id, run_id, phase, status, mode, story_type, attempt,
        Zeitstempel, pause_reason, escalation_reason, agents_to_spawn,
        errors, warnings und producer. Wird als phase_state_projection
        im State-Backend persistiert.
  internal_terms:
    - id: runtime-metadata
      reason: >
        Ephemore Laufzeitdaten (nur PhaseOrigin: NEW | LOADED), die
        ausschliesslich in-memory existieren und nie auf Platte
        geschrieben werden. Kein Vertragsinhalt fuer andere BCs.
---

# 39 — Phase-State-Persistenz und Phase-Envelope-Modell

<!-- PROSE-FORMAL: formal.implementation.entities, formal.implementation.invariants, formal.verify.entities, formal.story-workflow.invariants -->

## 39.1 Vierschichtiges State-Modell [Entscheidung 2026-04-09]

Der Phase-State folgt einer vierschichtigen Architektur. Die
oberste Schicht (`PhaseEnvelope`) ist ein frozen Dataclass, der
**nie als Ganzes persistiert** wird. Nur die `state`-Schicht wird
als `phase_state_projection` im State-Backend persistiert; ein
`phase-state.json` ist nur ihr materialisierter Export. Die
`runtime`-Schicht ist ephemer und existiert ausschließlich im Speicher
des laufenden Phase-Runner-Prozesses.

```
PhaseEnvelope (frozen dataclass, nie persistiert als Ganzes)
├── state: PhaseState          ← wird als `phase_state_projection` persistiert
│   ├── PhaseStateCore          (story_id, phase, status, pause_reason, …)
│   ├── payload: PhasePayload   (discriminated union, phase-spezifische Durable Fields)
│   └── memory: PhaseMemory     (phasenübergreifende Zähler, carry-forward)
└── runtime: RuntimeMetadata    ← ephemer, NICHT persistiert
    └── origin: PhaseOrigin     (NEW | LOADED)
```

> [Korrektur 2026-04-09: RuntimeMetadata enthält ausschliesslich origin: PhaseOrigin — guard_failure/retry_count/elapsed_seconds entfernt.]

**Persistierung:** Nur `PhaseState` (= `PhaseStateCore` +
`payload` + `memory`) wird zentral als `phase_state_projection`
persistiert. Ein `_temp/qa/{story_id}/phase-state.json` ist nur ein
Export dieser Projektion. `RuntimeMetadata` wird **nie** auf Platte
oder in den Store geschrieben — sie existiert nur in-memory für die
Dauer eines `run-phase`-Aufrufs.

**Normative Leseregel:** Alle spaeteren Verweise in diesem Dokument
auf `phase-state.json` meinen den Export der kanonischen
`phase_state_projection`, nicht eine eigenstaendige Wahrheit.

**Abgrenzung ephemer vs. durable:** Durable Fehlerinformation
(die einen Crash überleben muss) wird über `AttemptRecord` erfasst
(siehe §39.4).

> [Korrektur 2026-04-09: RuntimeMetadata enthält ausschliesslich origin: PhaseOrigin — guard_failure/retry_count/elapsed_seconds entfernt.]

### 39.1.1 Phase-State-Datei (phase-state.json)

> **[Hinweis 2026-04-08, aktualisiert 2026-04-09]** Dieses Beispiel zeigt die aktualisierte v3-Struktur. Das Detailkonzept ist ausgearbeitet (§39.1ff., 2026-04-09). Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 16.

```json
{
  "schema_version": "4.0",
  "story_id": "ODIN-042",
  "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "phase": "implementation",
  "status": "IN_PROGRESS",
  "mode": "exploration",
  "story_type": "implementation",
  "attempt": 2,
  "started_at": "2026-03-17T10:00:00+01:00",
  "phase_entered_at": "2026-03-17T11:00:00+01:00",
  "pause_reason": null,
  "escalation_reason": null,
  "agents_to_spawn": [
    {
      "type": "adversarial",
      "prompt_file": "prompts/adversarial-testing.md",
      "model": "opus"
    }
  ],
  "errors": [],
  "warnings": [],
  "producer": { "type": "script", "name": "run-phase" },

  "payload": {
    "type": "implementation",
    "qa_cycle_status": "awaiting_qa",
    "verify_context": "POST_IMPLEMENTATION"
  },

  "memory": {
    "exploration": {
      "review_rounds": 0
    },
    "implementation": {
      "qa_feedback_rounds": 1
    }
  }
}
```

[Entscheidung 2026-04-09] Gegenueber dem frueheren flachen v2-Modell
(schema_version 3.0) wurden folgende Felder in die richtige Schicht
ueberfuehrt:
- `verify_context` -> `payload.verify_context` (jetzt Teil des
  `ImplementationPayload`, vormals `VerifyPayload` der entfallenen
  Top-Phase `verify`)
- `feedback_rounds` -> `memory.implementation.qa_feedback_rounds`
  (PhaseMemory; vormals `memory.verify.feedback_rounds`)
- `verify_layer` -> entfernt (ephemerer Fortschritt, nicht durable;
  wird bei Resume aus den vorhandenen Artefakten rekonstruiert)
- `closure_substates` -> `payload.progress` (ClosurePayload)
- `exploration_gate_status` -> `payload.gate_status` (ExplorationPayload)
- `exploration_review_round` -> `memory.exploration.review_rounds` (PhaseMemory)

[Korrektur 2026-04-09] Im JSON-Beispiel oben wurde `"verify_context":
"post_implementation"` (lowercase v2-String) auf `"POST_IMPLEMENTATION"`
korrigiert. Korrekte Serialisierung des `VerifyContext`-StrEnum ist
Uppercase (`POST_IMPLEMENTATION`, `POST_REMEDIATION`).

> **[Entscheidung 2026-05-01]** Die Top-Phase `verify` und der Payload-
> Typ `VerifyPayload` entfallen. Output-QA ist ein interner Subflow
> innerhalb der `implementation`-Phase (analog zum Exit-Gate der
> `exploration`-Phase, FK-23 §23.5). Die ehemaligen `VerifyPayload`-
> Felder (`verify_context`) und der ehemalige Verify-Remediation-
> Zaehler (`memory.verify.feedback_rounds`) werden in
> `ImplementationPayload` bzw. `memory.implementation.qa_feedback_rounds`
> gefuehrt. Siehe `concept/_meta/bc-cut-decisions.md` "Verify als
> Capability (Variante Y)".

## 39.2 Schlüsselfelder nach Schicht [Entscheidung 2026-04-09]

> **[Hinweis 2026-04-08, aktualisiert 2026-04-09]** Diese Feldliste zeigt die v3-Schichtstruktur. Das Detailkonzept ist ausgearbeitet (§39.1ff., 2026-04-09). Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 16.

### 39.2.1 PhaseStateCore (immer vorhanden)

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `schema_version` | String | Versionsnummer des State-Schemas (aktuell `"4.0"`) |
| `story_id` | String | Eindeutige Story-ID (z.B. `"ODIN-042"`) |
| `run_id` | String (UUID) | Eindeutige ID des aktuellen Pipeline-Durchlaufs |
| `phase` | Enum | Aktuelle Phase: setup, exploration, implementation, closure. [Entscheidung 2026-05-01: `verify` entfaellt als Top-Phase — QA-Subflow laeuft intern in `implementation`.] |
| `status` | Enum | PENDING, IN_PROGRESS, COMPLETED, FAILED, ESCALATED, PAUSED. `PENDING` = Phase angelegt, aber noch nicht gestartet (Pre-Dispatch). |
| `mode` | Enum | execution, exploration, fast. Für die nicht-fast Standard-Familie (`execution`/`exploration`, nach Mode-Routing gesetzt) ist `mode` fachlich der Wire-Name der Intra-Run-Achse `execution_route` gemaess FK-59/FK-24 §24.3.2, **nicht** `operating_mode`. `fast` (AG3-018, FK-24 §24.3.3/§24.3.4) ist ein gleichrangiger Story-Modus und **kein** `execution_route`-Wert: `mode` ist seit der Entkopplung in FK-24 §24.3.2 nicht mehr blosser `execution_route`-Alias. `fast` ist mit `exploration` wechselseitig ausschliessend. Für Concept/Research-Stories immer `"execution"` — diese Story-Typen unterstützen weder Exploration- noch Fast-Mode; der Phase Runner setzt `mode = "execution"` ohne Mode-Routing-Prüfung. |
| `story_type` | Enum | implementation, bugfix, concept, research |
| `attempt` | Integer | Aktueller Durchlauf (beginnt bei 1) |
| `started_at` | ISO-8601 | Zeitstempel des Pipeline-Starts |
| `phase_entered_at` | ISO-8601 | Zeitstempel des Eintritts in die aktuelle Phase |
| `pause_reason` | PauseReason \| null | Grund bei `status: PAUSED`. Erlaubte Werte: siehe PauseReason-StrEnum unten. Wire-Format (in `phase-state.json`): serialisierter StrEnum-Wert in Lowercase (`"awaiting_design_review"`, `"awaiting_design_challenge"`, `"governance_incident"`). Enum-Member-Namen (`AWAITING_DESIGN_REVIEW` etc.) sind nur in Python-Code zu verwenden. [Entscheidung 2026-04-09] |
| `escalation_reason` | String \| null | REF-042: Grund bei `status: ESCALATED`. Werte: `"worker_blocked"`, `"max_rounds_exceeded"`, `"preflight_fail"`, `"integrity_fail"`, `"merge_fail"`, `"doc_fidelity_fail"`, `"impact_violation"`, `"design_review_rejected"`, `"governance_violation"`. [Entscheidung 2026-04-09: `doc_fidelity_fail` und `impact_violation` ergänzt — waren in FK-20 §20.6.1 beschrieben, fehlten aber in der Werte-Liste.] [Entscheidung 2026-04-09: `design_review_rejected` ergänzt — Exploration Design-Review FAIL non-remediable oder Rundenlimit überschritten.] [Korrektur 2026-04-09: `governance_violation` ergänzt — Governance-Beobachtung harter Verstoß (Secrets, Governance-Manipulation), führt zu sofortigem ESCALATED-Stopp (FK-20 §20.6.1).] |
| `agents_to_spawn` | Array | Agents, die der Orchestrator als nächstes spawnen soll |
| `errors` | Array | Fehlerliste des aktuellen Durchlaufs |
| `warnings` | Array | Warnungen des aktuellen Durchlaufs |
| `producer` | Object | Identifikation des schreibenden Prozesses |

> [Hinweis 2026-04-09, konsolidiert 2026-04-19, praezisiert 2026-06-03: `mode` und `story_type` sind in StoryContext (context.json) die primäre Quelle (Element 16). `mode` ist fuer die nicht-fast Standard-Familie der Wire-Name der fachlichen Achse `execution_route` gemaess FK-59; seit der Entkopplung in FK-24 §24.3.2 traegt `mode` zusaetzlich den gleichrangigen Story-Modus `fast` (AG3-018), der **kein** `execution_route`-Wert ist. PhaseStateCore enthält sie als denormalisierte Kopie — der Phase Runner liest sie aus phase-state.json ohne separaten context.json-Load. Keine inhaltliche Abweichung von Element 16.]

> **[Entscheidung 2026-04-09]** Die Felder `feedback_rounds`, `max_feedback_rounds`, `exploration_gate_status`, `verify_context`, `verify_layer`, `closure_substates` aus der v2-Tabelle entfallen aus dem flachen `PhaseStateCore`. Sie werden in die neue Schichtstruktur ueberfuehrt: `ExplorationPayload.gate_status`, `ImplementationPayload.verify_context` und `ImplementationPayload.qa_cycle_status`, `ClosurePayload.progress` (PhasePayload) sowie `PhaseMemory.implementation.qa_feedback_rounds`, `PhaseMemory.exploration.review_rounds` (PhaseMemory). Siehe §39.3, §39.5. [Entscheidung 2026-05-01: VerifyPayload und `memory.verify.feedback_rounds` entfallen; Felder leben jetzt in `ImplementationPayload` und `memory.implementation.qa_feedback_rounds`.]

> **[Entscheidung 2026-04-09, aktualisiert 2026-05-01]** Zwei getrennte Zaehlerfelder entfallen aus dem flachen `PhaseStateCore` und werden in `PhaseMemory` ueberfuehrt: (1) `exploration_review_round` (Exploration-Remediation-Zaehler) -> `memory.exploration.review_rounds` (`ExplorationPhaseMemory`); (2) `feedback_rounds` (QA-Subflow-Remediation-Zaehler) -> `memory.implementation.qa_feedback_rounds` (`ImplementationPhaseMemory`). Beide Zaehler werden per Carry-Forward ueber Phasenwechsel und Subflow-Iterationen mitgefuehrt. Kein Zusammenhang zwischen den beiden Zaehlern — `exploration_review_round` betrifft Design-Review-Runden, `qa_feedback_rounds` betrifft den Subflow-internen QA-Remediation-Loop. Verweis auf Designwizard R1+R2 vom 2026-04-09. Siehe §39.5.

### 39.2.2 PauseReason (StrEnum) [Entscheidung 2026-04-09]

Das Feld `pause_reason` akzeptiert ausschließlich einen der drei
definierten Werte. Jeder andere String ist ungültig und wird vom
Phase Runner mit einem Validierungsfehler abgewiesen.

```python
class PauseReason(StrEnum):
    AWAITING_DESIGN_REVIEW = "awaiting_design_review"
    AWAITING_DESIGN_CHALLENGE = "awaiting_design_challenge"
    GOVERNANCE_INCIDENT = "governance_incident"
```

| Wert | Wann gesetzt | Beschreibung |
|------|-------------|-------------|
| `AWAITING_DESIGN_REVIEW` | Exploration-Phase | Entwurfsartefakt liegt vor und wartet auf Design-Review (Mensch oder Review-Agent). Pipeline pausiert, bis Review-Ergebnis vorliegt. |
| `AWAITING_DESIGN_CHALLENGE` | Exploration-Phase | Design-Review hat Einwände erhoben (Design-Challenge). Pipeline pausiert, bis der Challenge-Prozess abgeschlossen ist. |
| `GOVERNANCE_INCIDENT` | Jede Phase | Governance-Observer hat einen kritischen Incident erkannt (kein harter Verstoß). Pipeline pausiert sofort, Mensch muss intervenieren und den Incident klären. |

**Abgrenzung:** `PAUSED` ist **kein Fehlerzustand** und **nicht
inhärent ein Wartet-auf-Mensch-Zustand**, sondern ein
**vorübergehender, kooperativer Kontrollfluss-Übergabepunkt**: AgentKit
übergibt den prozessualen Handle für eine definierte Teilstrecke
außerhalb der deterministischen Maschine. Der `PauseReason` benennt
diese Teilstrecke. Nach Abschluss löst der Orchestrator-Agent den
offiziellen Resume-/Re-Entry-Pfad aus, regulär über Service-Resume bzw.
den `Project Edge Client`; `agentkit resume` ist der
Operator-Recovery-Adapter. Ein Mensch ist nur bei ausdrücklich
menschlich normierten Sonderfällen beteiligt, insbesondere
`GOVERNANCE_INCIDENT` sowie Mandats-/Governance-Entscheidungen.
Demgegenüber ist `ESCALATED` ein **dauerhafter** Stopp der aktuellen
Iteration wegen Fehler/Mandatsgrenze. Laufzeit- und
Infrastrukturfehler dürfen nicht stillschweigend als `PAUSED`
modelliert werden; sie brauchen entweder einen explizit normierten
Interventionspfad oder laufen über Retry/Failure nach
`FAILED`/`ESCALATED`.

### 39.2.3 PhasePayload (discriminated union, phase-spezifisch)

Das `payload`-Feld enthält eine discriminated union, gesteuert über
`payload.type`. Je nach aktiver Phase enthält es unterschiedliche
Durable Contract Fields:

| Phase | Payload-Typ | Felder | Beschreibung |
|-------|-------------|--------|-------------|
| exploration | `ExplorationPayload` | `gate_status: ExplorationGateStatus` | Fortschritt durch das Exit-Gate. Werte: `PENDING`, `APPROVED`, `REJECTED` |
| implementation | `ImplementationPayload` | `qa_cycle_status: QaCycleStatus`, `verify_context: VerifyContext \| None` | QA-Subflow-Status (FK-27 §27.2.2: `idle`, `awaiting_qa`, `awaiting_policy`, `pass`, `awaiting_remediation`, `escalated`) und QA-Tiefe (`POST_IMPLEMENTATION` initial / `POST_REMEDIATION` nach Worker-Remediation). Wird vom Phase Runner beim Eintritt in den QA-Subflow gesetzt. Siehe FK-37 §37.1. [Entscheidung 2026-05-01: ImplementationPayload neu — vormals VerifyPayload der entfallenen Top-Phase `verify`.] |
| closure | `ClosurePayload` | `progress: ClosureProgress`, `multi_repo: MultiRepoClosureState \| None` | Fortschritt der Closure-Substates: `integrity_passed`, `story_branch_pushed`, `merge_done`, `story_closed`, `metrics_written`, `postflight_done` (je `bool`, sechs Booleans, vollständige Liste in FK-29 §29.1.0). [Hinweis: Der Pre-Merge-Scan-und-Merge-Block, das SonarQube-Green-Gate und die Integrity-Gate-Dimension 9 sind impl/bugfix-only. Concept/Research-Stories haben keinen Worktree und keinen `story/{story_id}`-Branch und arbeiten **direkt auf `main`** (kein Story-Branch, kein Merge eines Branches; FK-29 §29.1.1, FK-22 §22.5.1); fuer sie sind `story_branch_pushed` und `merge_done` **nicht anwendbare (N/A) Erfolgs-Booleans**, die — wie `integrity_passed` — vom Phase Handler **ohne jeden Push- oder Merge-Seiteneffekt** direkt auf `true` gesetzt werden, damit die `ClosureProgress`-Struktur typ-uniform bleibt. Code-Stories setzen `story_branch_pushed` erst nach dem realen Push innerhalb des Merge-Locks (FK-29 §29.1.1, §29.1a). Detaillierte Closure-Logik in FK-29 §29.1.] Bei Multi-Repo-Stories (`participating_repos` mit \|N\| >= 2) traegt `multi_repo` den per-Repo-Status (`pre_merge_check_passed`, `pushed_repos`, `merged_repos`, `rolled_back_repos`, `failed_repo`); fuer Single-Repo-Stories ist das Feld `None` und wird ignoriert (FK-29 §29.1.6.2). |
| setup | — | — | Kein Payload erforderlich (`payload: null`) |

### 39.2.4 PhaseMemory (phasenübergreifend, carry-forward)

`memory` enthält Zähler, die über Phase-Transitionen hinweg
mitgeführt werden. Sie werden von der Engine inkrementiert,
**nicht** von den Phase-Handlern.

| Pfad | Typ | Beschreibung |
|------|-----|-------------|
| `memory.exploration.review_rounds` | Integer | Zaehler fuer Design-Review-Remediation-Runden (max 3). Wird von der Engine inkrementiert, NICHT vom Handler. |
| `memory.implementation.qa_feedback_rounds` | Integer | Anzahl QA-Subflow-Remediation-Iterationen innerhalb der Implementation-Phase (max 3). Wird von der Engine inkrementiert, NICHT vom Handler. [Entscheidung 2026-05-01: vormals `memory.verify.feedback_rounds`; nach Cut der Top-Phase `verify` ist der Zaehler im `ImplementationPhaseMemory` gefuehrt.] |

> [Hinweis 2026-04-09, aktualisiert 2026-05-01] **Typnamen vs. Feldpfade:** Die Memory-Felder
> werden in FK-39 ueber ihren Feldpfad referenziert (z.B.
> `memory.exploration.review_rounds`). FK-23 verwendet stattdessen den
> Typnamen `ExplorationPhaseMemory.review_rounds`. Das ist kein
> Widerspruch: `memory.exploration` ist vom Typ `ExplorationPhaseMemory`,
> `memory.implementation` ist vom Typ `ImplementationPhaseMemory`. Die Kurzform
> `ExplorationPhaseMemory.review_rounds` in FK-23 referenziert denselben
> Feldpfad wie `memory.exploration.review_rounds` in FK-39.

**Max-Werte:** Die Maximalwerte (`max_feedback_rounds` etc.)
kommen aus der Pipeline-Config (`policy.max_feedback_rounds`),
nicht aus dem State. Der State zählt nur den Ist-Wert.

### 39.2.5 RuntimeMetadata (ephemer, NICHT persistiert)

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| `origin` | PhaseOrigin | Herkunft des States: `NEW` (frisch erzeugt) oder `LOADED` (aus `phase-state.json` geladen). Ephemer — wird nie auf Platte geschrieben. |

> [Korrektur 2026-04-09: RuntimeMetadata enthält ausschliesslich origin: PhaseOrigin — guard_failure/retry_count/elapsed_seconds entfernt.]

## 39.3 PhaseEnvelope und RuntimeMetadata

> **[Entscheidung 2026-04-09]** `PhaseEnvelope` wird als Execution Container eingeführt. RuntimeMetadata ist eine eigenständige frozen Dataclass. Persistenzgrenze: nur `state` wird geschrieben. `load_phase_state()` gibt `PhaseEnvelope | None` zurück. Verweis auf Designwizard R1+R2 vom 2026-04-09.

`PhaseEnvelope` ist ein **frozen Dataclass** (nicht Pydantic) und dient als Laufzeit-Container für eine Phase-Ausführung:

```python
@dataclass(frozen=True)
class RuntimeMetadata:
    origin: PhaseOrigin  # NEW | LOADED

@dataclass(frozen=True)
class PhaseEnvelope:
    state: PhaseState
    runtime: RuntimeMetadata
```

`PhaseOrigin` ist ein StrEnum mit den Werten `NEW` (frisch erzeugter State) und `LOADED` (aus `phase-state.json` geladen).

**Scope-Regel — welche Methoden welche Typen nehmen:**

| Methode / Funktion | Signatur-Typ | Begründung |
|--------------------|-------------|------------|
| `run_phase()`, `resume_phase()`, `_process_handler_result()` | `PhaseEnvelope` | Execution-Pfad, Laufzeit-Kontext relevant |
| Guards (`can_enter_phase`, `evaluate_transitions`, Guard-Funktionen) | `PhaseState` | Reine Zustandsprüfung, kein Laufzeit-Kontext nötig |
| Handler-Signaturen | `(ctx: StoryContext, state: PhaseState)` | Handler arbeiten nur mit fachlichem Zustand |

> [Hinweis 2026-04-09: run_phase() gibt nach außen PhaseState zurück (envelope.state); intern wird der vollständige PhaseEnvelope (state + runtime) verwendet. Kein Widerspruch — PhaseEnvelope.state ist vom Typ PhaseState.]

**Persistenzgrenze:** `save_phase_state(envelope.state)` — nur `state` wird geschrieben, nie der Envelope. `RuntimeMetadata` ist ephemer und überlebt keinen Prozess-Neustart.

**Erzeugen neuer States:** Die Engine erzeugt neue States immer als:
```python
PhaseEnvelope(
    state=new_state,
    runtime=RuntimeMetadata(origin=PhaseOrigin.NEW)
)
```

**`load_phase_state()` gibt `PhaseEnvelope | None` zurück:**
- Datei vorhanden → `PhaseEnvelope(state=loaded_state, runtime=RuntimeMetadata(origin=PhaseOrigin.LOADED))`
- Datei fehlt → `None` (nur `setup` erlaubt, FK-45 §45.2)

## 39.4 AttemptRecord und Write-Ordering [Entscheidung 2026-04-09]

> **[Entscheidung 2026-04-09]** `AttemptRecord` bekommt typisierte `AttemptOutcome` und `FailureCause` StrEnums. Write-Ordering: AttemptRecord wird VOR `save_phase_state` geschrieben (crash-safety). Verweis auf Designwizard R1+R2 vom 2026-04-09.

Jeder Phase-Durchlauf erzeugt einen `AttemptRecord` — einen
dauerhaften Eintrag in der Phasen-History, der unabhängig vom
Phase-State existiert und einen Crash überleben muss.

### 39.4.1 AttemptRecord-Struktur

```python
@dataclass(frozen=True)
class AttemptRecord:
    run_id: str              # UUID des Pipeline-Durchlaufs
    phase: str               # Phase, in der der Versuch stattfand
    attempt: int             # Versuchsnummer (1-basiert)
    outcome: AttemptOutcome  # Ergebnis des Versuchs
    failure_cause: FailureCause | None  # Nur bei FAILED/BLOCKED/ESCALATED
    started_at: str          # ISO-8601 Zeitstempel
    ended_at: str            # ISO-8601 Zeitstempel
    detail: str | None       # Optionale Freitextbeschreibung
```

### 39.4.2 AttemptOutcome (StrEnum)

`AttemptRecord` dokumentiert jeden Phasen-Durchlauf im Audit-Log. Ab v3 sind `outcome` und `failure_cause` typisiert:

| Wert | Bedeutung |
|------|-----------|
| `COMPLETED` | Phase-Versuch erfolgreich abgeschlossen |
| `FAILED` | Phase-Versuch fehlgeschlagen (Remediation möglich) |
| `ESCALATED` | Phase-Versuch eskaliert (menschliche Intervention nötig) |
| `SKIPPED` | Phase wurde übersprungen (z.B. Exploration bei Execution Mode) |
| `YIELDED` | Phase in PAUSED-Zustand übergegangen (wartet auf externen Trigger) |
| `BLOCKED` | Phase durch Guard oder Precondition blockiert |

### 39.4.3 FailureCause (StrEnum)

| Wert | Bedeutung |
|------|-----------|
| `GUARD_REJECTED` | Transition-Guard hat den Phaseneintritt abgelehnt |
| `STRUCTURAL_CHECK_FAIL` | Verify Schicht 1 (deterministisch) fehlgeschlagen |
| `SEMANTIC_REVIEW_FAIL` | Verify Schicht 2 (LLM-Review) fehlgeschlagen |
| `ADVERSARIAL_FINDING` | Verify Schicht 3 (Adversarial) hat Befunde |
| `POLICY_FAIL` | Verify Schicht 4 (Policy Engine) hat FAIL entschieden |
| `WORKER_BLOCKED` | Worker meldet unlösbaren Constraint |
| `INTEGRITY_FAIL` | Integrity-Gate in Closure fehlgeschlagen |
| `MERGE_FAIL` | Merge-Konflikt in Closure |
| `PREFLIGHT_FAIL` | Preflight-Checks in Setup fehlgeschlagen |
| `MAX_ROUNDS_EXCEEDED` | Feedback-Runden-Limit erreicht |
| `TIMEOUT` | Phase hat Zeitlimit überschritten |
| `GUARD_FAILED` | Guard-Funktion selbst hat eine unerwartete Exception geworfen (technischer Fehler, kein deliberates Reject) |
| `HANDLER_EXCEPTION` | Unerwartete Exception im Phase-Handler |
| `PRECONDITION_FAILED` | Semantische Precondition nicht erfüllt (FK-45 §45.2) |
| `HANDLER_REPORTED_FAILED` | Handler hat explizit FAILED zurückgemeldet |
| `HANDLER_REPORTED_ESCALATED` | Handler hat explizit ESCALATED zurückgemeldet |

`failure_cause: FailureCause | None` — nur gesetzt wenn `outcome` in (`FAILED`, `BLOCKED`, `ESCALATED`).

### 39.4.4 Write-Ordering (Crash-Safety)

> **WICHTIG:** Der `AttemptRecord` wird **VOR** `save_phase_state()` auf die Platte geschrieben. Diese Reihenfolge gilt für **phasenabschließende Saves** (COMPLETED, FAILED, ESCALATED, PAUSED). Ausnahme: Intermediate Saves (z.B. `save_phase_state()` für den `feedback_rounds`-Inkrement im Remediation-Übergang, FK-45 §45.2) sind keine Phasenabschlüsse — für sie ist kein eigener AttemptRecord nötig, da der Attempt noch aktiv läuft.

**Begründung:** Bei einem Crash zwischen den beiden Schreibvorgängen
ist der schlimmste Fall, dass ein AttemptRecord existiert, aber der
Phase-State noch den alten Zustand zeigt. Das ist sicher: Beim
Recovery kann der Phase Runner den AttemptRecord lesen und erkennen,
dass der letzte Versuch nicht sauber abgeschlossen wurde. Der
umgekehrte Fall (State aktualisiert, aber kein AttemptRecord) wäre
gefährlich, weil die History dann eine Lücke hätte.

**Ablauf:**

1. Phase-Handler führt seine Arbeit aus
2. `write_attempt_record(record)` → schreibt in `_temp/qa/{story_id}/attempt-history.jsonl` (append)
3. `save_phase_state(state)` → schreibt `phase-state.json` (atomic replace)

**Abgrenzung ephemer vs. durable:**

| Feld | Schicht | Persistiert? | Zweck |
|------|---------|-------------|-------|
| `RuntimeMetadata.origin` | RuntimeMetadata | Nein (ephemer) | Herkunft des States (NEW / LOADED) — nur in-memory für die Dauer eines `run-phase`-Aufrufs |
| `AttemptRecord.failure_cause` | AttemptRecord (History) | Ja (durable) | Permanente Aufzeichnung der Fehlerursache, überlebt Crashes |

> [Korrektur 2026-04-09: RuntimeMetadata enthält ausschliesslich origin: PhaseOrigin — guard_failure/retry_count/elapsed_seconds entfernt.]

Wenn ein Guard den Phaseneintritt **deliberat ablehnt** (Guard-Funktion gibt `False` zurück), wird er als `AttemptRecord` mit `failure_cause = GUARD_REJECTED` in die History geschrieben, bevor der Phase-State aktualisiert wird. Wenn die Guard-Funktion selbst eine **unerwartete Exception** wirft (technischer Fehler), wird `failure_cause = GUARD_FAILED` verwendet.

## 39.5 PhaseMemory — phasenübergreifende Laufzeitzähler

> **[Entscheidung 2026-04-09, aktualisiert 2026-05-01]** `PhaseMemory` wird als vierte Schicht in `PhaseState` eingefuehrt. `exploration_review_round` entfaellt von `PhaseStateCore` und wird in `memory.exploration.review_rounds` (`ExplorationPhaseMemory`) ueberfuehrt. Der QA-Remediation-Zaehler liegt in `memory.implementation.qa_feedback_rounds` (`ImplementationPhaseMemory`) und betrifft Subflow-interne QA-Iterationen — kein Zusammenhang mit `exploration_review_round`. Carry-Forward bei jedem Phasenwechsel und ueber Subflow-Iterationen. Verweis auf Designwizard R1+R2 vom 2026-04-09. [Entscheidung 2026-05-01: vormals `memory.verify.feedback_rounds` / `VerifyPhaseMemory` — mit Cut der Top-Phase `verify` jetzt im `ImplementationPhaseMemory`.]
>
> [Korrektur 2026-04-09: review_round -> memory.exploration.review_rounds (nicht feedback_rounds). qa_feedback_rounds = QA-Subflow-Remediation-Zaehler in memory.implementation.qa_feedback_rounds.]

`PhaseMemory` ist eine persistierte Schicht in `PhaseState` fuer phasenspezifische Zaehler und Akkumulatoren, die ueber Phasenwechsel hinweg erhalten bleiben:

```python
class ImplementationPhaseMemory(BaseModel):
    qa_feedback_rounds: int = 0  # Anzahl QA-Subflow-Remediation-Iterationen
                                 # (Worker-run -> qa-subflow FAIL -> remediation
                                 # -> qa-subflow re-run) innerhalb derselben
                                 # implementation-Phase

class ExplorationPhaseMemory(BaseModel):
    review_rounds: int = 0  # Exploration-Remediation-Zyklen (max 3)

class PhaseMemory(BaseModel):
    implementation: ImplementationPhaseMemory = Field(default_factory=ImplementationPhaseMemory)
    exploration: ExplorationPhaseMemory = Field(default_factory=ExplorationPhaseMemory)
```

**Exploration-Remediation-Zaehler:** Die Exploration-Phase erlaubt maximal 3 Remediation-Runden — gleiches Prinzip wie der QA-Subflow. Die Engine inkrementiert `phase_memory.exploration.review_rounds` beim Wiedereintritt in die Exploration-Phase fuer eine neue Remediation-Runde (PAUSED -> exploration re-entry), NICHT beim Uebergang exploration->implementation. `exploration_review_round` aus v2 war kein Artefakt, sondern wird als `ExplorationPhaseMemory.review_rounds` in die neue PhaseMemory-Schicht ueberfuehrt.

> [Korrektur 2026-04-09: Inkrementzeitpunkt review_rounds korrigiert — increment bei Wiedereintritt in Exploration (nach PAUSED), nicht bei exploration->implementation.]

**Semantik:** `PhaseMemory` zaehlt kumulativ ueber den gesamten Story-Lifecycle. Wenn der QA-Subflow nach einer Remediation erneut durchlaufen wird, ist `payload` (ImplementationPayload) frisch — aber `phase_memory.implementation.qa_feedback_rounds` enthaelt den kumulierten Zaehler aller bisherigen Subflow-Iterationen.

**Carry-Forward-Mechanismus:** Die Engine traegt `PhaseMemory` bei JEDEM Phasenwechsel und bei jeder Subflow-Iteration mit. Neue Phase-States erben die `PhaseMemory` aus dem vorigen State unveraendert.

**Inkrementierungszeitpunkt:** Die Engine inkrementiert `phase_memory.implementation.qa_feedback_rounds` zu Beginn einer neuen QA-Subflow-Remediation-Iteration (nach Worker-Spawn-Anforderung, VOR der erneuten QA-Subflow-Ausfuehrung), nicht beim Phasenwechsel.

**Abgrenzung zu anderen Schichten:**

| Schicht | Scope | Lebensdauer | Typischer Inhalt |
|---------|-------|-------------|-----------------|
| `PhasePayload` | Pro aktiver Phase | Durable (Teil von `phase-state.json`, überlebt Crashes); wird beim Phaseneintritt frisch gesetzt und bei Re-Entry der gleichen Phase überschrieben | Phase-spezifische Felder (z.B. `gate_status`, `verify_context`) |
| `PhaseMemory` | Phasenübergreifend | Persistent, Carry-Forward | Kumulierte Zähler (z.B. `feedback_rounds`) |
| `AttemptRecord` | Pro Attempt-Ereignis | Unveränderlich (Audit) | Outcome, Fehlerursache, Timestamps |

**Persistenz:** `PhaseMemory` wird als Teil von `phase-state.json` persistiert. Sie überlebt Crashes und Prozess-Neustarts — das ist ihr Hauptzweck.

## 39.6 Lese-/Schreibprotokoll

| Wer liest | Wann | Zweck |
|-----------|------|-------|
| Orchestrator-Skill | Nach jeder Phase | Entscheidet welchen Agent als nächstes spawnen |
| Phase Runner | Bei Phasenanfang | Weiß wo er weitermachen muss |
| Integrity-Gate | Bei Closure | Prüft ob Verify durchlaufen wurde |

| Wer schreibt | Wann | Was |
|-------------|------|-----|
| Phase Runner | Bei jedem Phasenwechsel | `PhaseStateCore`: phase, status, timestamps |
| Phase Runner | Bei Payload-Wechsel | `payload`: z.B. `qa_cycle_status`/`verify_context` beim QA-Subflow-Eintritt (ImplementationPayload), `progress` bei Closure-Substates |
| Phase Runner (Engine) | Bei QA-Subflow-Iteration / Review-Loop | `memory.implementation.qa_feedback_rounds++` bzw. `memory.exploration.review_rounds++` — Inkrement erfolgt NACH bestandenem Guard-Check, VOR der Subflow-Iteration (siehe FK-45 §45.2). [Entscheidung 2026-04-09, aktualisiert 2026-05-01: vormals `memory.verify.feedback_rounds++` an der Top-Phase-Transition `verify -> implementation`; jetzt Subflow-intern in `implementation`.] |
| AttemptRecord-Writer | Vor jedem **phasenabschließenden** `save_phase_state` (COMPLETED/FAILED/ESCALATED/PAUSED) — nicht vor Intermediate Saves (z.B. feedback_rounds-Inkrement, FK-45 §45.2) | AttemptRecord in History-Datei (siehe §39.4) |

**Nur der Phase Runner schreibt.** Der Orchestrator liest und
reagiert, manipuliert aber nie direkt den Phase-State.

## 39.7 Schema-Ownership PhaseStateProjection

**Normative Festlegung (BC-Schnitt, Row 33):** Das Schema der
`phase_state_projection` (alle Felder in `PhaseStateCore`, `PhasePayload`
und `PhaseMemory`) ist **Eigentuemer-BC pipeline-framework** (dieses Dokument).

`telemetry-and-events.ProjectionAccessor` ownt ausschliesslich die
DB-Zugriffsschicht (Lesen/Schreiben via `Telemetry.write_projection` und
`Telemetry.read_projection`). Das Schema selbst — d.h. die Pydantic-Modelle
fuer `PhaseStateCore`, `PhasePayload`, `PhaseMemory`, `AttemptRecord` — bleibt
in `agentkit.backend.pipeline_engine.phase_executor` (PhaseExecutor-Sub).

Querverweise: BC-Schnitt-Entscheidung Row 33; FK-10 §10.5 (State-Backend);
`concept/formal-spec/architecture-conformance/entities.md`
(architecture-conformance.group.phase_executor).
