# AgentKit v2 Bestandsaufnahme: Worker-Phasen & Koordination

Analysezeitpunkt: 2026-04-07
Quellbasis: `T:/codebase/claude-agentkit/agentkit/` (v2 Codebase)

---

## 1. Implementation-Phase

### 1.1 Was passiert wenn ein Implementation-Worker startet

**Verantwortliche Dateien:**
- `agentkit/orchestration/worker.py` -- Worker Variant Registry, Context Spec
- `agentkit/orchestration/prompt_composer.py` -- Prompt-Komposition
- `agentkit/orchestration/phase_runner.py` -- `_phase_setup()`, `_phase_implementation()`
- `agentkit/core/implementation_contract.py` -- Delivery-Evidence-Prufung

**Ablauf:**

1. **Setup-Phase bestimmt Worker-Variante** (`_phase_setup()` in phase_runner.py):
   - `get_worker_variant(story_type)` wahlt Template aus Registry `WORKER_VARIANT_REGISTRY`
   - Drei Worker-Varianten: `IMPLEMENTATION`, `BUGFIX`, `REMEDIATION`
   - Template-Dateinamen: `worker-implementation-static.md`, `worker-bugfix-static.md`, `worker-remediation-static.md`

2. **Prompt wird komponiert** (`compose_worker_prompt()` in prompt_composer.py):
   - Dynamischer Import von `userstory/tools/orchestration/compose-prompt.py`
   - Liest `context.json`, wahlt Template basierend auf role + story_type + spawn_reason
   - Ladt Template, lost Runtime-Conditionals (`IF_CLARIFICATION_ANSWERS`, `IF_GUARDRAIL_FINDINGS`, `IF_REMEDIATION_ROUND`)
   - Lost Mustache-Stack-Placeholders aus `.story-pipeline.yaml`
   - Lost Guardrail-Konfiguration
   - Validiert offene Platzhalter (`validate_no_unreplaced`)
   - Schreibt fertigen Prompt als `{template}--{reason}--r{round}.md` + `agent-config.json`
   - Optional: erzeugt Resume-Capsule + Spawn-Spec (FK-36/REF-019)

3. **Spawn-Vertrag wird erstellt** (`_compose_agent_spawn()` in phase_runner.py):
   - `spawn_key` Format: `{spawn_type}--story={story_id}--r{round_nr}` (DD-06)
   - Spawn-Dict enthalt: type, spawn_key, story_id, model, prompt_file, config_file, worktree_path, worktree_paths
   - Wird in `state.agents_to_spawn` geschrieben
   - Der Orchestrator liest phase-state.json und spawnt den Agent extern

4. **AgentKit kontrolliert NICHT die eigentliche Implementierung** (F-24-009):
   - Implementation ist die einzige nicht-deterministische Phase
   - AgentKit kontrolliert nur den Rahmen: Worktree-Isolation, Guards, Reviews, Increment-Disziplin, Handover-Schema

### 1.2 Worker Context Spec (F-24-004)

**Datei:** `agentkit/orchestration/worker.py` -- Klasse `WorkerContextItem`, Konstante `WORKER_CONTEXT_SPEC`

Der Worker erhalt bei Start genau diese Kontext-Elemente:

| Context Item | Source | Pflicht? | Beschreibung |
|---|---|---|---|
| `story_description` | context.json | Ja | Story-Titel + Beschreibung aus GitHub Issue |
| `acceptance_criteria` | context.json (issue body) | Ja | AC aus Issue Body |
| `concept_artifact` | entwurfsartefakt.json | Nein | Design-Artefakt aus Exploration |
| `guardrails` | _guardrails/ files | Ja | Projekt-Guardrails |
| `defect_list` | _temp/qa/{id}/feedback.json | Nein | Mangelliste (nur Remediation) |
| `story_type_and_size` | context.json | Ja | Story-Typ + Grosse |
| `are_must_cover` | ARE MCP | Nein | ARE Requirements (optional) |

Funktion `context_items_for_story_type(story_type)` filtert nach Story-Typ: z.B. ist `defect_list` nur fur Remediation required.

### 1.3 Increment-Zyklus (F-24-010 bis F-24-019)

**Datei:** `agentkit/orchestration/increment.py`

**4-Schritt-Zyklus pro Increment** (`INCREMENT_CYCLE`):
1. `IMPLEMENT` -- Code fur genau diesen vertikalen Slice schreiben
2. `LOCAL_VERIFY` -- Compile/Lint + betroffene Tests (NICHT Full-Build)
3. `DRIFT_CHECK` -- 2-stufig: deterministischer Hook + Worker Self-Assessment
4. `COMMIT` -- Nur wenn Slice konsistent und lokal grun

**Vertikale Increments** (`VERTICAL_INCREMENT_POLICY`):
- Jedes Increment ist ein funktional lebensfaehiger Teilzustand
- Anti-Pattern: Technische Layer ("alle Entities", "alle Services")
- Pattern: Vertikale Slices ("BrokerAdapter + Entity + Endpoint + Tests")

**Drift Detection** (2-stufig):
- Stage 1: `DriftDetectionSpec` -- Hook-basiert, deterministisch (Diff-Analyse gegen Design-Artefakt)
- Stage 2: Worker Self-Assessment (Prompt-instruiert)
- Severity: `NONE`, `MINOR` (nur Dokumentation), `SIGNIFICANT` (Worker-Stop + Re-Exploration)
- `classify_drift_severity()` -- Klassifiziert basierend auf undeclared modules/endpoints + worker self-report

**Story-ID Trailer** (F-24-017):
- Commit-Messages mussen `Story-ID: {id}` Trailer enthalten
- `build_commit_message()`, `has_story_id_trailer()`, `extract_story_id_from_trailer()`
- Telemetrie-Event `increment_commit` bei jedem Commit im Worktree

**Full Build Policy** (F-24-019):
- Per-Increment: nur Compile/Lint + betroffene Tests
- Vor Handover: Full Build + Full Test Suite (F-24-031/032)

### 1.4 Worker-Artefakte (F-24-039 bis F-24-042)

**Datei:** `agentkit/orchestration/artifacts.py`

Drei Pflicht-Artefakte am Ende der Implementation:

| Artefakt | Format | Gepruft durch | Min. Grosse |
|---|---|---|---|
| `protocol.md` | Markdown | Structural (>50 bytes) | 51 bytes |
| `handover.json` | JSON | Verify Layer 2+3 | -- |
| `worker-manifest.json` | JSON | Verify Layer 1 | -- |

**Worker-Manifest Schema** (`MANIFEST_MANDATORY_FIELDS`):
- `story_id`, `files_changed`, `tests_added`, `commit_sha`, `acceptance_criteria_status`
- Strukturelle Validierung: `validate_manifest_dict()` pruft story_id-Match, Files auf Disk, commit_sha auf Branch

### 1.5 Handover Package (F-24-034 bis F-24-038)

**Datei:** `agentkit/orchestration/handover.py`

**Klasse `HandoverPackage`** -- alle Felder mandatory (Arrays durfen leer sein):
- `schema_version`, `story_id`, `run_id`, `created_at`
- `changes_summary` -- Zusammenfassung der Anderungen
- `increments` -- Liste von `IncrementEntry` (description, commit_sha, tests_added)
- `assumptions` -- Annahmen des Workers
- `existing_tests` -- Bestehende Tests
- `risks_for_qa` -- Risiken fur QA
- `drift_log` -- Liste von `DriftEntry` (increment, drift, justification)
- `acceptance_criteria_status` -- Dict AC-Key -> ACStatus (ADDRESSED/NOT_APPLICABLE/BLOCKED)

**Consumer Mapping** (`VERIFY_LAYER_CONSUMER_MAP`):
- Layer 1 (structural): `increments`, `existing_tests`
- Layer 2 (llm_review): `changes_summary`, `assumptions`, `drift_log`, `acceptance_criteria_status`
- Layer 3 (adversarial): `risks_for_qa`, `existing_tests`

**Validierung**: `validate_handover_dict()` pruft Struktur, Typen, ACStatus-Werte

### 1.6 LLM Reviews wahrend Implementation (F-24-025 bis F-24-030)

**Datei:** `agentkit/orchestration/review.py`

**Review-Frequenz** (`REVIEW_FREQUENCY_RULES`) nach Story-Grosse:
- XS/S: 1 Review (vor Handover)
- M: 2 Reviews (nach erstem Increment + vor Handover)
- L/XL/XXL: 3+ Reviews (alle 2-3 Increments + vor Handover)

**Template Sentinel Contract** (F-24-027):
- Format: `[TEMPLATE:{template-name}-v1:{story_id}]`
- 7 Review-Templates: consolidated, bugfix, spec-compliance, implementation, test-sparring, synthesis, mediation-round
- Review-Guard (PostToolUse Hook) schreibt `review_compliant` Event

**Review Flow** (5 Schritte):
1. Worker erreicht Review-Punkt
2. Worker sendet an LLM Pool mit Template Sentinel
3. LLM Pool antwortet
4. Review Guard Hook schreibt `review_compliant` Event
5. Worker integriert Feedback

**Review Context Requirements**: diff, story_description, concept_artifact (required); previous_review_feedback, normative_sources, secondary_context, evidence_manifest (optional)

### 1.7 Implementation-Phase im Phase Runner

**Datei:** `agentkit/orchestration/phase_runner.py` -- `_phase_implementation()`

Die Phase pruft:
1. Ob Implementation-Evidence existiert (`has_implementation_evidence()`)
2. Ob Primary-Delivery-Claims im Manifest existieren (`has_primary_delivery_claim()`)
3. Wenn beides vorhanden: COMPLETED, Worker geht in Verify
4. Wenn fehlend: PAUSED (Worker muss weitermachen) oder FAILED (Remediation noetig)
5. Deadlock-Detection: `_check_paused_deadlock()` via Evidence-Fingerprint -- gleicher Fingerprint uber 2 Zyklen = ESCALATED

### 1.8 Telemetrie-Vertrag (F-24-046)

**Datei:** `agentkit/orchestration/telemetry_contract.py`

Erwartete Events pro Worker-Run:
- `agent_start`: genau 1
- `increment_commit`: >= 1 pro Increment
- `drift_check`: >= 1 pro Increment
- `review_request`: abhaengig von Story-Grosse (1/2/3+)
- `review_response`: = Anzahl review_request
- `review_compliant`: = Anzahl review_request
- `llm_call`: = Anzahl review_request
- `agent_end`: genau 1

`evaluate_telemetry_contract()` pruft den Vertrag gegen beobachtete Event-Counts.
`detect_worker_crash()`: agent_start >= 1 und agent_end == 0 = Crash.

### 1.9 Final Build + Push (F-24-031 bis F-24-033)

**Datei:** `agentkit/orchestration/final_build.py`

Drei Schritte nach allen Increments:
1. `full_build` -- Ganzes Projekt kompilieren/linten
2. `full_test_suite` -- Alle Tests (Regressionserkennung)
3. `remote_push` -- `git push -u origin story/{story_id}`

Branch-Namenskonvention: `story/{story_id}`

---

## 2. Exploration-Phase

### 2.1 Design-Artefakt (Entwurfsartefakt) -- FK-23

**Datei:** `agentkit/exploration/design_artifact.py`

**Pydantic-Modell `DesignArtifact`** mit 7 Pflicht-Komponenten:

1. **`ZielUndScope`** (F-23-011): `aendert_sich` (non-empty), `aendert_sich_nicht`
2. **`BetroffeneBausteine`** (F-23-012): `betroffen` (min 1), `unangetastet`
3. **`Loesungsrichtung`** (F-23-013): `muster`, `verankerung`, `begruendung` (alle non-empty)
4. **`Vertragsaenderungen`** (F-23-014): `schnittstellen`, `datenmodell`, `events`, `externe_integrationen` (min 1 non-empty oder "keine")
5. **`Konformitaetsaussage`** (F-23-015): `referenzdokumente` (min 1), `konform`, `abweichungen`
6. **`Verifikationsskizze`** (F-23-016): `unit`, `integration`, `e2e` (min 1 non-empty)
7. **`OffenePunkte`** (F-23-017): `entschieden`, `annahmen`, `freigabe_noetig` (alle Arrays present)

**Freeze-Mechanismus** (F-23-019):
- `freeze_design_artifact()` setzt `frozen: true`, schreibt nach `_temp/qa/{story_id}/entwurfsartefakt.json`
- Atomares Schreiben (tmp+rename)
- Hook-basierter QA-Schutz blockiert nachtraegliche Worker-Schreibzugriffe

**Schema-Validierung** (F-23-018):
- `validate_design_artifact()` via Pydantic model_validate
- story_id Pattern: `^[A-Z][A-Z0-9]+(?:-[A-Z][A-Z0-9]+)*-[0-9]+$`
- run_id: UUID v4
- created_at: ISO 8601

### 2.2 Document Fidelity Level 2 (Entwurfstreue) -- FK-23 Sec. 23.5

**Datei:** `agentkit/exploration/doc_fidelity.py`

**Ablauf:**
1. `load_reference_documents()` sammelt Referenzdokumente aus 2 Quellen:
   - Worker-deklariert: `konformitaetsaussage.referenzdokumente`
   - System-erganzt: Manifest-Indexer scannt `_concept/` nach betroffenen Modulnamen
2. `run_doc_fidelity_check()` fuhrt LLM-Evaluierung durch (oder Stub-Mode ohne LLM)

**Ergebnisse** (`DocFidelityStatus`):
- `PASS` -- weiter; prüfe `freigabe_noetig` Gate
- `PASS_WITH_CONCERNS` -- weiter; Concerns an Worker
- `FAIL` -- Eskalation (ESCALATED)

**Freigabe-Gate** (F-23-023):
- Non-empty `offene_punkte.freigabe_noetig` -> Pipeline PAUSED auch bei PASS
- `pause_reason: "human_approval_required"`
- Resume: `agentkit resume --story {id}`

### 2.3 Exploration Exit-Gate (REF-034) -- 3-stufiges Design-Review

**Datei:** `agentkit/orchestration/phase_runner.py` -- `_phase_exploration()`, `_phase_exploration_design_gate()`

**Gate-Stufen:**

**Stufe 1: Dokumententreue Ebene 2** (deterministisch + LLM)
- Design-Artefakt laden, validieren, einfrieren
- `run_doc_fidelity_check()` ausfuhren
- FAIL -> ESCALATED
- PASS -> exploration_gate_status = `doc_compliance_passed`

**Stufe 2a: Design-Review** (LLM)
- Spawn `design-reviewer` Agent
- Agent liefert `design-review-preliminary.json`
- Yield-Point: PAUSED mit `pause_reason="awaiting_design_review"`

**Stufe 2b: Design-Challenge** (deterministisch + LLM, bedingt)
- `_evaluate_design_review_triggers()` pruft 7 Trigger:
  1. `public_interfaces` -- offentliche Schnittstellenanderungen
  2. `cross_cutting_change` -- >= 3 betroffene Module
  3. `data_migration` -- Datenmodellanderungen
  4. `security_auth` -- Security/Auth-Module betroffen
  5. `review_round_fail` -- vorherige Runde FAIL
  6. `weak_verification` -- nur Unit-Tests, keine Integration/E2E
  7. `simplification_unclear` -- aus Design-Review preliminary
- Wenn Trigger aktiv: Spawn `design-challenger` Agent
- Yield-Point: PAUSED mit `pause_reason="awaiting_design_challenge"`

**Stufe 2c: Aggregation** (`_aggregate_design_review()`)
- Challenge kann nur eskalieren (PASS -> PASS_WITH_CONCERNS -> FAIL), nie deeskalieren
- Verdikt-Rangfolge: FAIL > PASS_WITH_CONCERNS > PASS

**Gate-Entscheidung nach Aggregation:**
- FAIL:
  - Non-remediable (Marker-Heuristik) oder max Rounds (2) uberschritten -> ESCALATED
  - Remediable -> Spawn `worker-exploration` Remediation, PAUSED mit `awaiting_exploration_remediation`
- PASS/PASS_WITH_CONCERNS:
  - `required_before_impl` Concerns -> PAUSED mit `human_approval_required`
  - Sonst: `approved_for_implementation`, spawn Implementation Worker

**Artefakte im Exploration Exit-Gate:**
- `entwurfsartefakt.json` -- Gefrorenes Design-Artefakt
- `design-review-preliminary.json` -- Vorlaeufiges Design-Review
- `design-challenge.json` -- Challenge-Ergebnis (optional)
- `design-review.json` -- Finales aggregiertes Review
- `exploration-summary.md` -- Menschenlesbarer Exploration-Bericht

### 2.4 Yield/Resume-Zyklen in der Exploration

Die Exploration-Phase ist eine Zustandsmaschine mit mehreren Yield-Points:

```
_phase_exploration() aufgerufen
  |
  v
[Artefakt laden/validieren/einfrieren]
  |
  v
[Doc-Fidelity Check (Stufe 1)]
  |-- FAIL -> ESCALATED
  |-- PASS -> exploration_gate_status = "doc_compliance_passed"
  v
[Stufe 2: Design-Review Gate]
  |
  v
PAUSED (awaiting_design_review)  <-- Yield 1
  |-- Orchestrator spawnt design-reviewer
  |-- Orchestrator ruft run_phase("exploration") erneut auf
  v
[Trigger-Evaluation (deterministisch)]
  |-- Keine Trigger -> direkt Aggregation
  |-- Trigger aktiv:
      v
      PAUSED (awaiting_design_challenge)  <-- Yield 2
        |-- Orchestrator spawnt design-challenger
        |-- Orchestrator ruft run_phase("exploration") erneut auf
        v
[Aggregation (Stufe 2c)]
  |-- FAIL (remediable):
      v
      PAUSED (awaiting_exploration_remediation)  <-- Yield 3
        |-- Orchestrator spawnt exploration-worker fur Remediation
        |-- Orchestrator ruft run_phase("exploration") erneut auf
        |-- Neue Runde ab Stufe 1
  |-- FAIL (non-remediable/max rounds) -> ESCALATED
  |-- PASS/PASS_WITH_CONCERNS + freigabe_noetig:
      v
      PAUSED (human_approval_required)  <-- Yield 4
        |-- Mensch gibt frei
        |-- agentkit resume -> run_phase("exploration")
        v
  |-- PASS (ohne Freigabe-Bedarf):
      v
[approved_for_implementation -> spawn impl worker -> COMPLETED]
```

### 2.5 Drift Detection wahrend Implementation

**Datei:** `agentkit/exploration/drift.py`

**Stage 1** (`run_stage1_drift_check()`):
- Git-Diff gegen `base_ref` (default HEAD~1)
- Prufung 1: Geanderte Dateien gegen `betroffene_bausteine.betroffen` (Path-Segment-Matching)
- Prufung 2: Impact-Exceedance (>50% Dateien ausserhalb deklarierter Module)
- Prufung 3: Neue API-Endpoints nicht in `vertragsaenderungen.schnittstellen`
- Prufung 4: Neue Schema-Definitionen nicht in `vertragsaenderungen.datenmodell`
- Prufung 5: Neue Events nicht in `vertragsaenderungen.events`
- Prufung 6: Neue externe Integrationen nicht in `vertragsaenderungen.externe_integrationen`

**Stage 2** (Worker Self-Assessment, Prompt-instruiert):
- 4 Pruf-Fragen: new_structures, impact_exceedance, pattern_change, detail_deviation

**Drift-Klassifizierung** (`DriftType` -> `DriftSeverity`):
- `NEW_STRUCTURE` -> SIGNIFICANT
- `IMPACT_EXCEEDANCE` -> SIGNIFICANT
- `PATTERN_CHANGE` -> MINOR
- `DETAIL_DEVIATION` -> MINOR

**Reaktion bei Significant Drift** (F-23-034):
1. Orchestrator stoppt Worker
2. Ruft `run-phase exploration` auf (nur Doc-Fidelity Check, kein neues Artefakt)
3. PASS -> neuer Worker von Drift-Punkt
4. FAIL -> Eskalation an Menschen

---

## 3. Worker-Koordination

### 3.1 Rollen-Verteilung: AgentKit vs. Orchestrator

**AgentKit (Phase Runner) tut:**
- Deterministische Phasen-Steuerung als State Machine
- Phase-State lesen, schreiben, validieren
- Prompt-Komposition (Template-Auflosung, Platzhalter)
- Worktree-Erstellung + Branch-Management
- Guard-Aktivierung (Locks, Marker, QA-Verzeichnis)
- Mode-Determination (4-Trigger-Modell)
- Exploration Exit-Gate (3-stufig)
- Verify Pipeline (4-Layer QA)
- Feedback-Loop-Steuerung (Mangelliste, Max-Rounds)
- Closure (Integrity Gate, Merge, Issue-Close)
- Spawn-Vertrage in `agents_to_spawn` schreiben

**Der Orchestrator (Claude Code Agent mit Skill) tut:**
- `phase-state.json` lesen nach jedem Phase-Runner-Aufruf
- `agents_to_spawn` auswerten und Agents spawnen (Agent Tool)
- Warten bis Agent fertig ist
- Nachsten `run-phase` Aufruf absetzen
- Story-Auswahl vom GitHub Project Board
- Resume nach PAUSED (bestimmte Szenarien)

### 3.2 Spawn-Spezifikation

**Format des Spawn-Eintrags** (in `state.agents_to_spawn`):

```python
{
    "type": "worker-implementation" | "worker-exploration" | "worker-concept" | "worker-research" | "worker-remediation" | "design-reviewer" | "design-challenger" | "qa-semantic" | "qa-guardrail",
    "spawn_key": "{type}--story={story_id}--r{round}",  # DD-06
    "story_id": "BB2-042",
    "model": "opus" | "sonnet",
    "prompt_file": "/abs/path/to/composed/prompt.md",
    "config_file": "/abs/path/to/agent-config.json",
    "worktree_path": "/abs/path/to/worktree",  # optional
    "worktree_paths": {"repo-id": "/abs/path"},  # multi-repo
    "primary_repo_id": "main-repo",  # multi-repo
    "round": 1,
    # Typ-spezifische Felder:
    "design_artifact": "/path/to/entwurfsartefakt.json",  # design-reviewer/-challenger
    "output_dir": "/path/to/output",  # design-reviewer/-challenger/research
    "output_artifact": "design-review-preliminary.json",  # design-reviewer
    "triggers": ["public_interfaces", "..."],  # design-challenger
    "fail_reasons": ["..."],  # exploration remediation
    "remediation_round": 1,  # exploration remediation
}
```

### 3.3 Resume-Capsule + Spawn-Spec (FK-36 / REF-019)

**Erzeugt von:** `compose_worker_prompt()` wenn `spawn_key` gesetzt ist

- `resume-capsule--{spawn_key}.md` -- Post-Compaction Recovery: enthalt Prompt-Datei-Pfad, Story-ID, Story-Type, Role, Round
- `spawn-spec--{spawn_key}.json` -- Spawn-Spezifikation fur Wiederherstellung

### 3.4 Orchestrator Reaction Registry

**Datei:** `agentkit/orchestration/phase_runner.py` -- `ORCHESTRATOR_REACTION_REGISTRY`, `VERIFY_ESCALATION_REACTIONS`

Deterministische Lookup-Tabelle: `(phase, status) -> OrchestratorReaction`

| Phase | Status | Aktion |
|---|---|---|
| setup/COMPLETED | -- | Mode prüfen: exploration -> spawn exploration worker; execution -> spawn impl worker |
| setup/FAILED | -- | Eskalation |
| exploration/COMPLETED | -- | Spawn impl worker |
| exploration/PAUSED | -- | Je nach pause_reason: design-reviewer, design-challenger, exploration remediation, oder human approval |
| exploration/ESCALATED | -- | Eskalation |
| implementation/COMPLETED | -- | run-phase verify |
| implementation/PAUSED | -- | Resume implementation worker |
| implementation/FAILED | -- | Spawn remediation worker |
| implementation/ESCALATED | -- | Eskalation |
| verify/COMPLETED | -- | run-phase closure |
| verify/PAUSED | -- | Resume implementation worker (oder QA agents spawnen) |
| verify/FAILED | -- | Spawn remediation worker + re-verify |
| verify/ESCALATED | -- | Eskalation (mit Reason-spezifischen Varianten) |
| closure/COMPLETED | -- | Story fertig |
| closure/ESCALATED | -- | Eskalation |

`get_orchestrator_reaction()` unterstutzt reason-spezifische Verfeinerung:
- verify/ESCALATED + `impact_violation_exploration` -> zurück zu exploration
- verify/ESCALATED + `doc_fidelity_level3_exploration` -> zurück zu exploration
- verify/PAUSED + `awaiting_qa_agents` -> QA agents spawnen, nicht impl worker

### 3.5 Phase-Transition-Graph (F-20-009)

```
setup -> exploration | implementation | verify | closure
exploration -> implementation
implementation -> verify
verify -> implementation (feedback) | closure | exploration (impact violation)
closure -> (terminal)
```

**REF-040 Guards** in `run_phase()`:
- AC-1: Transition muss im Graph sein
- AC-2: Ohne phase-state.json ist nur "setup" erlaubt
- AC-3: Vorganger-Phase muss COMPLETED sein (Ausnahme: verify -> implementation/exploration bei PAUSED)
- AC-4: Implementation erfordert `exploration_gate_status="approved_for_implementation"` bei mode=exploration
- AC-6: Closure erfordert phase-state-verify.json mit status=COMPLETED
- AC-7: Same-Phase Re-Entry bei ESCALATED blockiert

### 3.6 PhaseState Modell

**Datei:** `agentkit/orchestration/phase_runner.py` -- Klasse `PhaseState`

Zentrale Felder:
- `story_id`, `phase`, `status`, `run_id`, `started_at`, `finished_at`
- `attempt`, `feedback_rounds`, `max_feedback_rounds`
- `mode` (execution/exploration/not_applicable), `story_type`
- `verify_layer`, `verify_result`
- `qa_cycle_round`, `qa_cycle_id`, `qa_cycle_status`, `current_evidence_epoch`
- `closure_substates` (ClosureSubstates)
- `agents_to_spawn` -- Array von Spawn-Dicts
- `pause_reason`, `paused_retry_count`, `last_paused_evidence_fingerprint`
- `drift_detected`
- `exploration_gate_status`, `exploration_review_round`
- `errors`, `warnings`, `context`
- `are_bundle`
- `suggested_reaction` (OrchestratorReaction)

Persistiert nach: `_temp/qa/{story_id}/phase-state.json`

---

## 4. Remediation-Loop

### 4.1 Feedback-Zyklus: Verify -> Remediation -> Implementation -> Verify

**Verantwortliche Dateien:**
- `agentkit/orchestration/feedback.py` -- Mangelliste-Assembly, Max-Rounds-Check
- `agentkit/orchestration/phase_runner.py` -- `_phase_verify()` Feedback-Path
- `agentkit/orchestration/worker.py` -- `WorkerVariant.REMEDIATION`
- `agentkit/orchestration/escalation.py` -- Eskalation bei Max-Rounds

**Ablauf:**

1. **Verify ergibt FAIL** (`_phase_verify()` in phase_runner.py):
   - Policy Engine aggregiert Layer-Ergebnisse -> `decision.json` mit FAIL
   - Phase Runner setzt `state.status = PhaseStatus.FAILED`

2. **Mangelliste wird erstellt** (`assemble_maengelliste()` in feedback.py):
   - Sammelt Findings aus 3 Quellen: structural, llm_review, adversarial
   - Jedes Finding: source, check_id, status="FAIL", detail/reason/description
   - Ergebnis: `FeedbackMaengelliste` mit story_id, run_id, feedback_round, findings

3. **Max-Rounds-Check** (`check_max_feedback_rounds()` in feedback.py):
   - `feedback_rounds < max_feedback_rounds` -> darf weitermachen
   - Sonst -> ESCALATED (F-20-030)
   - Default max_feedback_rounds = 3

4. **Orchestrator reagiert** (liest `suggested_reaction` aus phase-state.json):
   - verify/FAILED -> spawn_type="remediation_worker"
   - Orchestrator spawnt Remediation-Worker

5. **Remediation-Worker** (Worker-Variante `worker-remediation-static.md`):
   - Erhalt defect_list aus `_temp/qa/{story_id}/feedback.json`
   - Lost QA-Findings selbstaendig
   - Produziert handover.json + worker-manifest.json wie normaler Worker
   - Aber: spawn_reason="remediation" in compose_worker_prompt()

6. **Erneutes Verify** (Orchestrator ruft `run-phase verify` auf):
   - Verify lauft erneut komplett (alle 4 Layer)
   - feedback_rounds wird inkrementiert
   - Bei erneutem FAIL: zuruck zu Schritt 2 (bis max_rounds)

### 4.2 Feedback-Artefakte

**Input-Artefakte fur Remediation:**
- `_temp/qa/{story_id}/feedback.json` -- Mangelliste als JSON
- `_temp/qa/{story_id}/structural.json` -- Layer 1 Ergebnis
- `_temp/qa/{story_id}/semantic-review.json` -- Layer 2 Ergebnis
- `_temp/qa/{story_id}/adversarial.json` -- Layer 3 Ergebnis (nur Code-Stories)
- `_temp/qa/{story_id}/decision.json` -- Layer 4 Policy-Entscheidung

**FeedbackFinding** Struktur:
```python
{
    "source": "structural" | "llm_review" | "adversarial",
    "check_id": "structural.error_1" | "llm_review.unknown" | ...,
    "status": "FAIL",
    "detail": "...",      # bei structural
    "reason": "...",      # bei llm_review/adversarial
    "description": "..."  # bei llm_review/adversarial
}
```

**FeedbackMaengelliste** Struktur:
```python
{
    "story_id": "BB2-042",
    "run_id": "uuid",
    "feedback_round": 1,
    "findings": [FeedbackFinding, ...]
}
```

### 4.3 Wer steuert den Loop?

- **AgentKit Phase Runner** steuert: Verify ausfuhren, FAIL erkennen, Mangelliste assemblieren, Max-Rounds prufen, Status setzen, Spawn-Vertrag schreiben
- **Orchestrator** steuert: phase-state.json lesen, Remediation-Worker spawnen, run-phase verify erneut aufrufen
- **Kein automatischer Retry** (F-20-039): Der Phase Runner macht nie automatisch einen Retry. Feedback-Loop ist bewusste Orchestrator-Entscheidung.

### 4.4 Eskalation

**Datei:** `agentkit/orchestration/escalation.py`

11 Eskalations-Trigger (`EscalationTrigger`):
1. `PREFLIGHT_FAIL` -> FAILED (nicht ESCALATED)
2. `DOC_FIDELITY_2_FAIL` -> ESCALATED
3. `OPEN_APPROVAL_POINTS` -> PAUSED
4. `DOC_FIDELITY_3_FAIL` -> ESCALATED
5. `IMPACT_VIOLATION_EXECUTION` -> ESCALATED
6. `IMPACT_VIOLATION_EXPLORATION` -> ESCALATED (aber back_to_phase="exploration")
7. `MAX_FEEDBACK_ROUNDS` -> ESCALATED
8. `INTEGRITY_GATE_FAIL` -> ESCALATED
9. `MERGE_CONFLICT` -> ESCALATED
10. `GOVERNANCE_CRITICAL_INCIDENT` -> PAUSED
11. `GOVERNANCE_HARD_VIOLATION` -> ESCALATED

**Uniformes Eskalationsverhalten** (F-20-032):
- Story bleibt "In Progress" auf GitHub
- phase-state status = ESCALATED
- Orchestrator stoppt alle weiteren Aktionen
- Mensch muss eingreifen

**Reset**: `reset_escalation()` setzt phase auf "setup" (ausser verify), neues run_id, altes in forensic_run_ids
**Resume**: `resume_story()` setzt PAUSED -> IN_PROGRESS, gleiche run_id

### 4.5 Crash Recovery

**Datei:** `agentkit/orchestration/recovery_scenarios.py`

4 Recovery-Szenarien:
1. Agent-Crash wahrend Implementation (F-20-035): Neuer Run, Worktree erhalten
2. Phase-Runner-Crash wahrend Verify (F-20-036): run-phase verify wiederholen (idempotent)
3. Closure-Crash nach Merge (F-20-037): run-phase closure wiederholen (closure_substates schutzen vor Doppelausfuhrung)
4. Eskalation-Recovery (F-20-038): reset-escalation + neuer Run

### 4.6 Worker Abort/Crash Detection

**Datei:** `agentkit/orchestration/abort_recovery.py`

- `WorkerAbortKind`: CRASH oder FUNCTIONAL_FAILURE
- `describe_crash_state()`: Erkennt Crash via fehlende agent_end Events
- `build_functional_failure_state()`: BLOCKED ACs -> Verify wird FAILen
- `check_functional_failure_rounds()`: Max-Rounds-Check fur funktionale Fehler
- `build_abort_summary()`: Gesamtubersicht Crash/Failure/Rounds

---

## 5. Bewertung: Essentiell fur v3 vs. v2-Ballast

### Essentiell (muss in v3)

| Bereich | Warum essentiell |
|---|---|
| **PhaseState als zentrale Datenstruktur** | Gesamte Pipeline basiert auf diesem Contract |
| **Phase-Transition-Graph** | Verhindert ungultige Phasenfolgen |
| **Orchestrator Reaction Registry** | Deterministische Entscheidungstabelle fur Orchestrator |
| **Handover Package Schema** | Brucke Worker -> Verify, ohne das kein QA |
| **Worker-Manifest Schema + Validierung** | Strukturelle Integritatsprufung |
| **Feedback Mangelliste** | Kernmechanismus des Remediation-Loops |
| **Max-Rounds-Check** | Verhindert Endlos-Loops |
| **Spawn-Vertrag (agents_to_spawn)** | Schnittstelle AgentKit -> Orchestrator |
| **Design-Artefakt Pydantic-Modell** | Schema fur Exploration-Output |
| **Exploration Exit-Gate (3-stufig)** | Qualitatstor vor Implementation |
| **Prompt-Komposition** | Template-Auflosung + Platzhalter |
| **Worktree-Management** | Isolation pro Story |
| **Guard-Aktivierung** | Lock + Marker fur Governance |
| **Drift Detection (Stage 1)** | Deterministisch, Hook-basiert |
| **Eskalations-Katalog** | Definierte Abbruchpunkte |
| **Evidence-Fingerprint / Deadlock Detection** | Erkennt steckengebliebene Loops |
| **Story-Type Phase Overrides** | concept/research uberspringen Worktree/Verify/Merge |

### Wahrscheinlich Ballast / v2-Artefakte

| Bereich | Warum Ballast |
|---|---|
| **Dynamischer Import von compose-prompt.py** | Fragile Python-Importmechanik, besser als regulares Modul |
| **SpawnReason als separater Literal-Typ** | Kann in v3 direkt ins Spawn-Dict |
| **NON_DETERMINISTIC_PHASE/RATIONALE Konstanten** | Reine Doku-Konstanten, kein Laufzeiteffekt |
| **IncrementStep/INCREMENT_CYCLE Enums** | Prompt-Dokumentation, nicht Runtime-enforced |
| **ReviewTemplate/REVIEW_TEMPLATE_REGISTRY** | Template-Metadaten, nicht programmatisch genutzt |
| **FinalBuildStep Dataclasses** | Reine Policy-Doku, kein Laufzeiteffekt |
| **CrashScenario/CRASH_SCENARIO_CATALOG** | Doku-Katalog, nicht programmatisch genutzt |
| **NoSchedulerPolicy/ParallelStoriesPolicy/MergeConflictPolicy** | Reine Policy-Doku-Konstanten |
| **WorkerContextItem/WORKER_CONTEXT_SPEC** | Doku-Dataclass, context_items_for_story_type nur fur Doku |
| **ReviewFlowModel/ReviewFlowStep** | Doku, nicht Runtime |
| **WorkerArtifactDescriptor/WORKER_ARTIFACT_REGISTRY** | Registry nur fur get_artifact_descriptor, besser als einfaches Dict |
| **Telemetry Contract (build_telemetry_contract/evaluate)** | Nur fur Integrity Gate relevant; kann vereinfacht werden |
| **_recovered_from_context/_loaded_from_file/_guard_failure Flags** | Interne Workarounds fur state-recovery Bugs |
| **Exploration-Summary Markdown Generation** | Menschenlesbar, aber kein Pipeline-Effekt |
| **Multi-Repo Worktree Logic** | Nur wenn v3 Multi-Repo unterstutzen soll |

### Vereinfachungspotential in v3

| v2 Pattern | v3 Vereinfachung |
|---|---|
| Dataclass PhaseState mit 40+ Feldern | Pydantic-Modell mit klarer Trennung Core/Extension |
| compose-prompt.py als externes Script + dynamischer Import | Regulares Python-Modul in der Codebase |
| 11 Eskalations-Trigger als Katalog | Reduzieren auf die tatsachlich ausgelösten (~7) |
| Policy-Doku als frozen Dataclasses | YAML/Config oder einfach Docstrings |
| Evidence-Fingerprint uber Dateigroessen | Robuster Hash (z.B. SHA256 uber Dateiinhalt) |
| Yield/Resume via phase-state.json + pause_reason | Expliziteres State-Machine Pattern |

---

## Datei-Index

### Orchestration Layer (`agentkit/orchestration/`)

| Datei | LOC (ca.) | Fachliche Funktion |
|---|---|---|
| `phase_runner.py` | ~3500 | Zentrale State Machine, alle 5 Phase-Handler, REF-040 Guards |
| `worker.py` | ~260 | Worker-Varianten-Registry, Context Spec |
| `handover.py` | ~410 | Handover-Schema, Validierung, Verify-Layer-Consumer-Map |
| `feedback.py` | ~260 | Mangelliste-Assembly, Max-Rounds-Check |
| `prompt_composer.py` | ~440 | Prompt-Komposition Bridge zu compose-prompt.py |
| `artifacts.py` | ~300 | Worker-Artefakt-Registry, Manifest-Validierung |
| `increment.py` | ~390 | Increment-Zyklus, Drift Detection (Light), Commit-Trailer |
| `review.py` | ~450 | Review-Frequenz, Template-Sentinel, Review-Flow |
| `escalation.py` | ~550 | Eskalations-Katalog, Reset, Resume |
| `final_build.py` | ~160 | Final Build + Push Policy |
| `scheduling.py` | ~150 | No-Scheduler, Parallel-Stories, Merge-Conflict Policies |
| `recovery_scenarios.py` | ~290 | Crash-Recovery-Katalog |
| `telemetry_contract.py` | ~480 | Telemetrie-Vertrag, Contract-Evaluation |
| `abort_recovery.py` | ~360 | Worker-Crash/Failure Detection + Abort-Summary |

### Exploration Layer (`agentkit/exploration/`)

| Datei | LOC (ca.) | Fachliche Funktion |
|---|---|---|
| `design_artifact.py` | ~500 | DesignArtifact Pydantic-Modell, 7 Komponenten, Freeze |
| `doc_fidelity.py` | ~440 | Document Fidelity Level 2, Reference-Doc-Loading |
| `drift.py` | ~720 | 2-stufige Drift Detection, Binding Spec Contract |

### Core Layer (`agentkit/core/`)

| Datei | Relevante Funktion |
|---|---|
| `implementation_contract.py` | Story-Type-Checks, Required-Artifacts, Delivery-Evidence |
| `context.py` | StoryContext-Berechnung, GitHub-Lesen |
| `domain.py` | StoryType, StorySize Enums |
| `config.py` | PipelineConfig Pydantic-Modell |
| `states.py` | State-Konstanten |
