# pipeline-framework — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `pipeline-framework` |
| Display-Name | `Pipeline-Framework (Knotenkomposition + Kontrollfluss)` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `DK-02, FK-20, FK-36, FK-39, FK-45` |
| Codebase-Hauptpfade | `src/agentkit/pipeline/`, `src/agentkit/pipeline_engine/`, `src/agentkit/phase_state_store/` |

## 1. Executive Summary

Das Pipeline-Framework ist in weiten Teilen funktionsfaehig umgesetzt: PipelineEngine, WorkflowDSL, Phasen-Handler fuer Setup, Implementation und Closure sowie eine vollstaendige Transition-Test-Suite existieren. Drei gravierende Luecken praegen das Bild: (1) Der Ziel-Prefix `agentkit.pipeline_engine` ist nur ein Fassaden-Facade — die kanonische Implementierung lebt weiterhin unter `agentkit.pipeline`, was dem bc-cut-decisions-Migrations-Auftrag widerspricht. (2) `CompactionResilience` (FK-36) ist konzeptuell voll beschrieben, aber kein einziges Python-Modul unter `agentkit.pipeline_engine.compaction_resilience` existiert. (3) `PhaseEnvelope`, `PauseReason`-StrEnum, `AttemptOutcome`/`FailureCause`-StrEnums und das `PhaseEnvelopeStore`-Sub sind im Konzept (FK-39) normiert, im Code aber nicht vorhanden oder abweichend implementiert.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 6 |
| B — Teilweise umgesetzt | 5 |
| C — Drift / Fehler | 5 |

## 2. Konzept-Soll (Kurzfassung)

- **Einheitliche hierarchische Prozess-DSL** auf allen Ebenen (Pipeline, Phase, Komponente) mit `FlowDefinition`, `NodeDefinition`, `EdgeRule`, `Guard`, `Gate`, `YieldPoint`, `ExecutionPolicy`, `RetryPolicy`, `OverridePolicy` — `FK-20 §20.1.2/20.1.3`
- **Ziel-Modul-Prefix `agentkit.pipeline_engine`** fuer alle BC-Komponenten; Migration weg von `agentkit.pipeline` ist Pflicht-Konzept-Refactor-Listeneintrag — `concept/_meta/bc-cut-decisions.md §BC 1`
- **PhaseEnvelope** als frozen Dataclass (`state: PhaseState` + `runtime: RuntimeMetadata`) ist der normierte Laufzeit-Container; nur `state` wird persistiert — `FK-39 §39.1/39.3`
- **PauseReason** als StrEnum mit genau drei Werten (`AWAITING_DESIGN_REVIEW`, `AWAITING_DESIGN_CHALLENGE`, `GOVERNANCE_INCIDENT`) — `FK-39 §39.2.2`
- **AttemptOutcome** und **FailureCause** als typisierte StrEnums fuer `AttemptRecord` — `FK-39 §39.4.2/39.4.3`
- **CompactionResilience** als Sub-Komponente (`agentkit.pipeline_engine.compaction_resilience`) mit vier Hook-Scripten (`manifest_writer`, `recovery_injector`, `epoch_writer`, `cleanup`) und zentralem Compaction-State-Store — `FK-36 §36.7/36.8`
- **PhaseEnvelopeStore** als Sub-Komponente fuer Envelope-Persistenz — `concept/_meta/bc-cut-decisions.md §BC 1 Layer 1`
- **PipelineRegistry** fuer Registrierung von Phase-Handlern — `concept/_meta/bc-cut-decisions.md §BC 1 Layer 4`
- **Phase-Transition-Enforcement** fail-closed gegen `PHASE_TRANSITION_GRAPH` (setup→exploration|implementation, exploration→implementation, implementation→closure) mit Status-Pruefung und semantischen Preconditions (`gate_status == APPROVED`, Closure-Precondition) — `FK-45 §45.2, DK-02 §Phase-Transition-Enforcement`
- **StoryResetService** als eigenstaendige Top-Level-Komponente ausserhalb PipelineEngine — `FK-20 §20.1.1, §20.2.1a`
- **Exploration-Phase-Handler** als vollstaendiger Phase-Handler mit Design-Review-Gate, Mandatsklassifikation (Klasse 1-4), Feindesign-Subprozess, Pause/Resume-Semantik — `FK-20 §20.2.2, DK-02 §Exploration-Phase`
- **Worker-Health-Monitor** (Scoring-Modell, Eskalationsleiter, LLM-Assessment-Sidecar) als Subflow der Implementation-Phase — `DK-02 §Worker-Runaway-Prevention`
- **Write-Ordering Crash-Safety**: `AttemptRecord` wird VOR `save_phase_state` geschrieben (phasenabschliessende Saves) — `FK-39 §39.4.4`
- **Recovery-Vertrag pro Phase** mit Subflow-Atomicitaet; `agentkit recover-story` als CLI-Befehl fuer Worker-Loop-Recovery — `FK-20 §20.7.3, FK-45 §45.4`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/pipeline/engine.py:PipelineEngine` — Kernklasse; interpretiert `WorkflowDefinition`, ruft Handler auf, persistiert State und AttemptRecord, wertet Guards aus
- `src/agentkit/pipeline/runner.py:run_pipeline` — High-Level-Orchestrierung; iteriert Phasen bis Terminal/Yield/Fail
- `src/agentkit/pipeline_engine/engine.py` — Facade-Modul; re-exportiert lazy aus `agentkit.pipeline.engine`
- `src/agentkit/pipeline_engine/runner.py` — Facade-Modul; re-exportiert aus `agentkit.pipeline.runner`
- `src/agentkit/process/language/model.py:FlowLevel, NodeKind, ExecutionPolicy, RetryPolicy, OverridePolicy, YieldPoint` — DSL-Kernkonstrukte (Subset implementiert)
- `src/agentkit/process/language/definitions.py:resolve_workflow` — Liefert `WorkflowDefinition` pro `StoryType`; vier Story-Typ-Workflows statisch definiert
- `src/agentkit/process/language/definitions.py:_build_implementation_workflow` — Korrekte Transitionen setup→exploration/implementation, exploration→implementation, implementation→closure
- `src/agentkit/pipeline/phases/setup/phase.py:SetupPhaseHandler` — Preflight, Context-Build, Worktree-Setup, begin_progress
- `src/agentkit/pipeline/phases/setup/preflight.py` — Preflight-Checks gegen StoryService
- `src/agentkit/pipeline/phases/implementation/phase.py:ImplementationPhaseHandler` — QA-Subflow-Koordination mit Remediation-Loop (intern, kein Top-Phasenwechsel)
- `src/agentkit/pipeline/phases/implementation/qa_subflow.py:QaSubflowCycle` — Orchestriert Layer-Evaluation + PolicyEngine
- `src/agentkit/pipeline/phases/closure/phase.py:ClosurePhaseHandler` — Prueft Prior-Phases, schliesst Issue, schreibt ExecutionReport, setzt Story Done
- `src/agentkit/pipeline_engine/phase_executor/records.py:AttemptRecord` — Immutable Dataclass; Felder `attempt_id, phase, entered_at, exit_status, outcome` (ohne typisierte StrEnums)
- `src/agentkit/pipeline/state.py` — Compatibility-Re-Export auf `agentkit.state_backend.store`
- `src/agentkit/phase_state_store/store.py` — Re-Export auf `agentkit.state_backend.store` (flow-orientiert)
- `tests/unit/process/language/test_transitions.py` — Vollstaendige Transition-Graph-Tests fuer alle vier Story-Typen (valid/invalid, Guards)

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | CompactionResilience — alle vier Hook-Module fehlen komplett | `FK-36 §36.7/36.8` | Kein Verzeichnis `src/agentkit/pipeline_engine/compaction_resilience/`; kein `manifest_writer`, kein `recovery_injector`, kein `epoch_writer`, kein `cleanup`-Modul. Ohne diese Hooks fehlt der Compaction-Schutz fuer Sub-Agenten vollstaendig. |
| A2 | PhaseEnvelopeStore als Sub-Komponente | `concept/_meta/bc-cut-decisions.md §BC 1 Layer 1` | Sub-Komponente `agentkit.pipeline_engine.phase_envelope_store` existiert nicht. Phase-State-Persistenz laeuft ueber `agentkit.state_backend.store` ohne BC-eigenen Store. |
| A3 | PipelineRegistry als Sub-Komponente | `concept/_meta/bc-cut-decisions.md §BC 1 Layer 4` | Kein `agentkit.pipeline_engine.pipeline_registry`. Phase-Handler-Registrierung erfolgt derzeit ad hoc ueber `PhaseHandlerRegistry` in `agentkit.pipeline.lifecycle`. |
| A4 | StoryResetService als eigenstaendige Komponente | `FK-20 §20.2.1a` | Kein `StoryResetService`-Modul im BC. Konzept normiert ihn als Top-Level-Komponente ausserhalb PipelineEngine mit explizitem menschlichem CLI-Auftrag und Purge-Semantik. |
| A5 | Exploration-Phase-Handler (vollstaendig) | `FK-20 §20.2.2, DK-02 §Exploration-Phase` | `src/agentkit/pipeline/phases/exploration/__init__.py` existiert, ist aber leer (kein Inhalt). Kein Design-Review-Gate, keine Mandatsklassifikation (Klasse 1-4), kein Feindesign-Subprozess, keine Pause/Resume-Semantik implementiert. |
| A6 | Worker-Health-Monitor | `DK-02 §Worker-Runaway-Prevention` | Kein Scoring-Modell, keine Eskalationsleiter (Warnung/Soft-Intervention/Hard-Stop), kein LLM-Assessment-Sidecar (als Pflicht deklariert: „Entscheidung 2026-04-08 Element 23 — kein Feature-Flag") im BC implementiert. |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | Modul-Prefix-Migration `agentkit.pipeline_engine` | `src/agentkit/pipeline_engine/engine.py`, `src/agentkit/pipeline_engine/runner.py`, `src/agentkit/pipeline_engine/implementation_phase/phase.py` | `concept/_meta/bc-cut-decisions.md §BC 1 Konzept-Refactor-Liste` | Alle drei `pipeline_engine`-Module sind nur Facades/Re-Exports auf `agentkit.pipeline.*`. Die kanonische Implementierung liegt weiterhin unter dem alten Prefix. FK-20/FK-39/FK-45-Konzept-Refactor-Listenpunkte sind offen. |
| B2 | AttemptRecord — typisierte StrEnums fehlen | `src/agentkit/pipeline_engine/phase_executor/records.py:AttemptRecord` | `FK-39 §39.4.2/39.4.3` | `AttemptRecord` hat Felder `outcome: str | None` und `exit_status: PhaseStatus | None`, aber kein typisiertes `AttemptOutcome`-StrEnum (Werte: COMPLETED/FAILED/ESCALATED/SKIPPED/YIELDED/BLOCKED) und kein `FailureCause`-StrEnum (15 Werte). Freie Strings statt normierter Typen. |
| B3 | Phase-Transition-Enforcement | `src/agentkit/pipeline/runner.py:run_pipeline`, `src/agentkit/pipeline/engine.py:PipelineEngine.run_phase` | `FK-45 §45.2, DK-02 §Phase-Transition-Enforcement` | Transition-Graph ist korrekt in `WorkflowDefinition` abgebildet und per Test verprobt. Aber kein expliziter Enforcement-Code der FK-45-Semantik: keine separaten Fehlermeldungen mit `from_phase`, `to_phase`, `from_status`, kein Erstaufruf-Check (nur setup ohne State-Datei), keine fail-closed ESCALATED-Rueckgabe bei ungueltigem Uebergang (aktuell `PipelineError`-Exception statt ESCALATED-Status). |
| B4 | Write-Ordering Crash-Safety (AttemptRecord vor PhaseState) | `src/agentkit/pipeline/engine.py:_handle_completed_result`, `_handle_terminal_result`, `_handle_guard_failure_result` | `FK-39 §39.4.4` | In `_handle_completed_result` wird `save_phase_state` VOR `save_attempt` aufgerufen (Zeilen 327, 344). Bei phasenabschliessenden Saves ist das falsch: das Konzept fordert explizit `write_attempt_record` VOR `save_phase_state` fuer Crash-Safety. In Terminal-Pfaden ist die Reihenfolge korrekt. |
| B5 | Recovery-CLI (`agentkit run-phase`, `agentkit resume`, `agentkit reset-escalation`, `agentkit recover-story`) | `src/agentkit/pipeline/runner.py:run_pipeline` (nur als API) | `FK-45 §45.4, FK-20 §20.7.3` | `run_pipeline` ist eine Python-API, keine CLI. Operator-Recovery-CLI-Befehle (`agentkit run-phase`, `agentkit resume`, `agentkit reset-escalation`, `agentkit recover-story`) sind konzeptuell normiert, aber kein CLI-Einstiegspunkt implementiert. |

### 4.3 C — Drift / Fehler

> Hier landen Implementierungen, die etwas tun, aber nicht das, was im Konzept steht, **oder** offensichtlich fehlerhaft sind (Bug, Verletzung einer Invariante, falsche Trust-Boundary, etc.).

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | `PhaseEnvelope` nicht vorhanden — Engine verwendet `PhaseState` direkt | `src/agentkit/pipeline/engine.py:PipelineEngine.run_phase`, `src/agentkit/pipeline/runner.py:run_pipeline` | `FK-39 §39.1/39.3` | Konzept normiert `PhaseEnvelope(state: PhaseState, runtime: RuntimeMetadata)` als einzigen Laufzeit-Container. Engine arbeitet direkt mit `PhaseState`. `RuntimeMetadata` mit `origin: PhaseOrigin (NEW|LOADED)` existiert nicht. `load_phase_state()` gibt `PhaseState | None` zurueck (Konzept: `PhaseEnvelope | None`). |
| C2 | `PauseReason` als freier String statt StrEnum | `src/agentkit/pipeline/engine.py:_handle_paused_result` (Feld `paused_reason=result.yield_status`) | `FK-39 §39.2.2` | Konzept definiert `PauseReason` als StrEnum mit exakt drei Werten. Im Code wird `result.yield_status` (freier String) direkt als `paused_reason` geschrieben. Kein Validierungsschutz gegen ungueltige Werte. |
| C3 | ImplementationPhaseHandler laeuft Remediation-Loop inline (Konzept: Orchestrator spawnt Worker) | `src/agentkit/pipeline/phases/implementation/phase.py:ImplementationPhaseHandler.on_enter` (Zeilen 86-153, `while True`-Schleife) | `FK-20 §20.5.1, DK-02 §QA-Subflow` | Konzept: QA-Subflow FAIL → Engine inkrementiert Zaehler, persistiert, gibt `agents_to_spawn=[remediation_worker]` zurueck; Orchestrator spawnt Worker; neuer `run-phase`-Aufruf. Code: Handler laeuft `while True` ohne Orchestrator-Beteiligung, kein Worker-Spawn, kein Phasen-Resume-Zyklus. Subflow-internem Remediation-Loop fehlt Orchestrator-Trennlinie. |
| C4 | `AttemptRecord` ohne `failure_cause`-Feld; Felder nicht konzeptkonform | `src/agentkit/pipeline_engine/phase_executor/records.py:AttemptRecord` | `FK-39 §39.4.1` | Konzept-Schema: `run_id, phase, attempt, outcome: AttemptOutcome, failure_cause: FailureCause | None, started_at, ended_at, detail`. Code-Felder: `attempt_id, phase, entered_at, exit_status: PhaseStatus | None, guard_evaluations, artifacts_produced, outcome: str | None, yield_status, resume_trigger`. Kein `failure_cause`, kein `ended_at`, stattdessen nicht-konzeptuelles `guard_evaluations`/`artifacts_produced`/`yield_status`. |
| C5 | `phase_state_store`-Paket als zweite Persistenz-Facade neben `pipeline.state` | `src/agentkit/phase_state_store/store.py`, `src/agentkit/pipeline/state.py` | `CLAUDE.md §SINGLE SOURCE OF TRUTH IST PFLICHT` | Zwei separate Compat-Facades (`agentkit.phase_state_store.store` und `agentkit.pipeline.state`) exportieren dieselbe `agentkit.state_backend.store`-API unter unterschiedlichen Modulpfaden. Kein kanonischer BC-eigener Store (`PhaseEnvelopeStore`). Verstoss gegen SINGLE SOURCE OF TRUTH. |

## 5. Ableitungen / Empfehlungen

1. **Compaction-Resilience implementieren (A1) — Blocker fuer Produktion.** Alle vier Hook-Scripte unter `agentkit.pipeline_engine.compaction_resilience` fehlen. Sub-Agenten haben ohne diesen Schutz nach Compaction keine Guardrail-Kontinuitaet. FK-36 ist vollstaendig konzipiert; Implementierung kann direkt beginnen.

2. **Write-Ordering-Bug beheben (B4) — Crash-Safety-Invariante verletzt.** In `_handle_completed_result` (`src/agentkit/pipeline/engine.py`) wird `save_phase_state` vor `save_attempt` aufgerufen. FK-39 §39.4.4 fordert die umgekehrte Reihenfolge fuer phasenabschliessende Saves. Risiko: Bei Crash zwischen den beiden Schreibvorgaengen fehlt der AttemptRecord in der History.

3. **PhaseEnvelope + PauseReason einfuehren (C1, C2).** Ohne `PhaseEnvelope` fehlt die Persistenzgrenze zwischen `PhaseState` (durable) und `RuntimeMetadata` (ephemer). Ohne typisierte `PauseReason` koennen ungueltige Pause-Zustands-Strings unbemerkt in den State gelangen. Beide Aenderungen sind konzeptkonform normiert (FK-39) und haben keine aeusseren Abhaengigkeiten.

4. **AttemptRecord typisieren (B2, C4).** Freie `outcome: str`-Strings und fehlende `failure_cause`/`FailureCause` machen Audit-Trail unzuverlaessig. Typisierte StrEnums `AttemptOutcome` + `FailureCause` gemaess FK-39 §39.4 einfuehren; bestehende String-Werte migrieren. Blockiert zukuenftige Post-Mortem-Analyse.

5. **Exploration-Phase-Handler (A5).** Leeres Package ist der groesste Konzept-zu-Code-Abstand. Ohne Exploration kein Exploration-Mode fuer Implementation/Bugfix-Stories. Abhaengig von verify-system (QA-Subflow) und governance-and-guards (Eskalation); als naechste grosse Story priorisieren.

6. **Prefix-Migration `agentkit.pipeline_engine` abschliessen (B1).** Alle `pipeline_engine`-Module sind aktuell Facades auf `agentkit.pipeline.*`. Migration auf kanonischen Prefix ist in bc-cut-decisions als Pflicht-Refactor eingetragen. Blockiert andere BCs, die gegen `agentkit.pipeline_engine`-Pfade importieren wuerden.

7. **Orchestrator-Trennlinie im Remediation-Loop herstellen (C3).** `ImplementationPhaseHandler` laeuft inline-Remediation ohne Worker-Spawn. Das verletzt die Orchestrator-Trennlinie und verhindert echtes Multi-Agent-Remediation. Abhaengig von einem spawnbaren Remediation-Worker (BC implementation-phase).

8. **PipelineRegistry, PhaseEnvelopeStore, StoryResetService anlegen (A2, A3, A4).** Drei Sub-Komponenten aus der bc-cut-decisions-Layer-Order fehlen. PipelineRegistry ist Voraussetzung fuer das Exploration-BC-Registrierungsmodell (`PipelineRegistry.register_phase_handler`).

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/domain-design/02-pipeline-orchestrierung.md`
  - `concept/technical-design/20_workflow_engine_state_machine.md`
  - `concept/technical-design/36_compaction_resilience_prompt_persistence.md`
  - `concept/technical-design/39_phase_state_persistenz.md`
  - `concept/technical-design/45_phase_runner_cli.md`
  - `concept/_meta/bc-cut-decisions.md` (Abschnitte BC 1, uebergreifende Entscheidungen, Verify-als-Capability)
  - `src/agentkit/pipeline/engine.py`
  - `src/agentkit/pipeline/runner.py`
  - `src/agentkit/pipeline/state.py`
  - `src/agentkit/pipeline_engine/engine.py`
  - `src/agentkit/pipeline_engine/runner.py`
  - `src/agentkit/pipeline_engine/phase_executor/records.py`
  - `src/agentkit/pipeline_engine/exploration_phase/__init__.py`
  - `src/agentkit/pipeline_engine/implementation_phase/phase.py`
  - `src/agentkit/phase_state_store/store.py`
  - `src/agentkit/pipeline/phases/setup/phase.py`
  - `src/agentkit/pipeline/phases/implementation/phase.py`
  - `src/agentkit/pipeline/phases/implementation/qa_subflow.py`
  - `src/agentkit/pipeline/phases/closure/phase.py`
  - `src/agentkit/pipeline/phases/exploration/__init__.py`
  - `src/agentkit/process/language/model.py`
  - `src/agentkit/process/language/definitions.py`
  - `tests/unit/process/language/test_transitions.py`
- **Code-Scan (Glob/Grep):**
  - Glob `src/agentkit/pipeline/**/*.py`: Vollstaendiger Dateibaum des Pipeline-Pakets
  - Glob `src/agentkit/pipeline_engine/**/*.py`: Vollstaendiger Dateibaum des pipeline_engine-Pakets
  - Glob `src/agentkit/phase_state_store/**/*.py`: Vollstaendiger Dateibaum des phase_state_store-Pakets
  - Glob `src/agentkit/**/process/**/*.py`: Prozess-DSL-Paketbaum
  - Glob `src/agentkit/pipeline_engine/compaction_resilience/**/*.py`: Bestaetigt fehlende Module (kein Ergebnis)
  - Grep `PhaseEnvelope|PauseReason|FailureCause|AttemptOutcome|StoryResetService|compaction_resilience`: Kein Treffer — bestaetigt A1/A4 und C1/C2
  - Grep `PHASE_TRANSITION_GRAPH|is_valid_phase_transition`: Kein Treffer — Enforcement laeuft via WorkflowDefinition-DSL, nicht als expliziter Graph-Lookup
  - Grep `class.*Exploration|ExplorationPhaseHandler`: Kein Handler-Code gefunden (nur Pydantic-Modelle in story_context_manager)
  - Glob `tests/unit/pipeline*/**/*.py`: Test-Coverage ueberprueft
