# implementation-phase — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `implementation-phase` |
| Display-Name | `Implementation-Phase` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `FK-26, FK-49, formal.implementation.entities, formal.implementation.invariants, formal.implementation.state-machine, formal.implementation.commands, formal.implementation.events, formal.implementation.scenarios` |
| Codebase-Hauptpfade | `src/agentkit/pipeline/phases/implementation/`, `src/agentkit/workers/` |

## 1. Executive Summary

Die Implementation-Phase verfügt über einen funktionsfähigen QA-Subflow-Handler (`ImplementationPhaseHandler`, `QaSubflowCycle`) sowie grundlegende Enumerationen (`SpawnReason`, `EventType`-Einträge). Die Worker-seitige Kernlogik — WorkerSession, WorkerLoop, HandoverPackager, WorkerHealthMonitor — ist konzeptuell vollständig beschrieben (FK-26, FK-49, bc-cut-decisions §BC-6), aber im Produktionscode noch nicht umgesetzt. Die Komponenten für Spawn-Kontext-Resolution, Inkrement-Disziplin, Handover/Manifest-Erzeugung und den Worker-Health-Monitor (Scoring-Engine, Interventions-Gate, LLM-Assessment-Sidecar) fehlen vollständig. Damit ist der BC als QA-Empfänger teilweise implementiert, als Worker-Orchestrator aber noch im Skelettzustand.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 8 |
| B — Teilweise umgesetzt | 5 |
| C — Drift / Fehler | 3 |

## 2. Konzept-Soll (Kurzfassung)

- **WorkerSession: Spawn-Protokoll und Worker-Kontext-Resolution** — `FK-26 §26.2.1`, `FK-26 §26.2.2`; Aufrufkette `resolve_worker_context()` → `validate_worker_context()` → `compose_worker_prompt()` mit `WorkerContextItemKey` als StrEnum.
- **SpawnReason-gesteuerte Worker-Varianten** — `FK-26 §26.2.3`; drei Prompt-Templates (worker-implementation, worker-bugfix, worker-remediation) abhängig von `SpawnReason`.
- **WorkerLoop: Vier-Schritt-Inkrementzyklus** — `FK-26 §26.3.2`; Implementieren → Lokal verifizieren → Drift prüfen → Committen; deterministischer Hook-basierter Drift-Check (Stufe 1) per `increment_commit`-Hook.
- **Zweistufige Drift-Erkennung** — `FK-26 §26.3.5`; Stufe 1 deterministisch via Hook-basiertem Diff-gegen-Entwurf, Stufe 2 Worker-Selbsteinschätzung.
- **Finaler Build und Gesamttest** — `FK-26 §26.6`; vollständiger Build + Gesamt-Test-Suite über alle teilnehmenden Repos vor Handover.
- **HandoverPackager: handover.json-Schema und Pflichtfelder** — `FK-26 §26.7.2–26.7.3`; sieben Pflichtfelder inkl. `increments`, `risks_for_qa`, `drift_log`, `acceptance_criteria_status`.
- **WorkerManifest: drei Status und BLOCKED-Pflichtfelder** — `FK-26 §26.8.2`; COMPLETED / COMPLETED_WITH_ISSUES / BLOCKED; `blocking_category` als StrEnum (`POLICY_CONFLICT`, `ENVIRONMENTAL`, `FIXABLE_LOCAL`, `FIXABLE_CODE`).
- **BLOCKED-Exit-Protokoll** — `FK-26 §26.11.2`, `bc-cut-decisions §BLOCKED-Eskalation §26.11.2`; `ImplementationHandler` liest `worker-manifest.json`, gibt `HandlerResult.ESCALATED` bei `status=BLOCKED` zurück.
- **Bugfix Red-Green-Suite** — `FK-26 §26.9`; Reproducer-Test, Red-Phase (exit≠0), Green-Phase (exit==0), Suite-Phase; Structural-Check-Validierung aller drei Phasen.
- **LLM-Pool-Reviews während Implementierung** — `FK-26 §26.5.1–26.5.3`; Pflicht-Reviews über konfigurierte LLM-Rollen (kein Sub-Agent-Fallback); Template-Sentinel `[TEMPLATE:...]` Pflicht; Integrity-Gate prüft `review_compliant`.
- **WorkerHealthMonitor: PostToolUse Scoring-Engine** — `FK-49 §49.1.1`; deterministischer Score 0–100 aus 5 Heuristiken + LLM-Assessment-Korrekturfaktor; persistiert als `agent-health.json`.
- **WorkerHealthMonitor: PreToolUse Interventions-Gate** — `FK-49 §49.1.2`; Soft-Intervention bei Score ≥70, Hard Stop bei Score ≥85; Einmal-Garantie.
- **WorkerHealthMonitor: LLM-Assessment-Sidecar** — `FK-49 §49.1.3`; Pflichtbestandteil (kein Feature-Flag); asynchron per Polling-Prozess; Debounce-Regeln; Ergebnis als Score-Korrekturfaktor.
- **Hook-Commit-Failure-Klassifikation** — `FK-49 §49.1.4`; vier Kategorien (FIXABLE_LOCAL, FIXABLE_CODE, POLICY_CONFLICT, ENVIRONMENTAL); Eskalation bei Wiederholung.
- **Persistenz-Artefakte: agent-health.json und tool-call-log.jsonl** — `FK-49 §49.1.5`; Sliding-Window-Log, 100–500 Einträge; Post-mortem-Artefakt.
- **Telemetrie-Kontrakt der Implementation-Phase** — `FK-26 §26.10`; Events `worker_health_score`, `worker_health_intervention` fehlen in `EventType`; Erwartungswerte-Kontrakt.
- **Konfiguration `worker_health` in project.yaml** — `FK-49 §49.1.7`; kanonische Defaults, Schwellwerte (50/70/85), Story-Größen P50/P75/P95.
- **Formale Zustandsmaschine** — `formal.implementation.state-machine`; Zustände: requested → worker_spawned → worker_running → handover_ready → completed / escalated.

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/pipeline/phases/implementation/phase.py:ImplementationPhaseHandler` — orchestriert den QA-Subflow intern; liest `max_feedback_rounds`, delegiert an `QaSubflowCycle`, gibt `HandlerResult.COMPLETED` oder `.ESCALATED` zurück.
- `src/agentkit/pipeline/phases/implementation/phase.py:ImplementationConfig` — Konfigurationsklasse für `story_dir`, `max_feedback_rounds`, QA-Layer, PolicyEngine.
- `src/agentkit/pipeline/phases/implementation/qa_subflow.py:QaSubflowCycle` — führt eine Runde QA aus (alle Layer → PolicyEngine → Feedback).
- `src/agentkit/pipeline/phases/implementation/qa_subflow.py:QaSubflowCycleResult` — frozen dataclass mit `decision`, `feedback`, `attempt_nr`.
- `src/agentkit/workers/types.py:SpawnReason` — StrEnum `INITIAL / PAUSED_RETRY / REMEDIATION` (FK-26-Entscheidung Element 2 umgesetzt).
- `src/agentkit/telemetry/events.py:EventType` — enthält `AGENT_START`, `AGENT_END`, `INCREMENT_COMMIT`, `DRIFT_CHECK`, `REVIEW_REQUEST`, `REVIEW_RESPONSE`, `REVIEW_COMPLIANT`, `LLM_CALL`; fehlen: `WORKER_HEALTH_SCORE`, `WORKER_HEALTH_INTERVENTION`.
- `src/agentkit/prompt_composer/selectors.py:select_template_name` — wählt Worker-Template basierend auf `StoryType` und `spawn_reason`-String; SpawnReason-Enum wird als roher String verglichen.
- `src/agentkit/resources/internal/prompts/` — enthält `worker-implementation.md`, `worker-bugfix.md`, `worker-remediation.md`, `worker-exploration.md` (FK-26 §26.5.4-Templates fehlen im `prompts/sparring/`-Unterverzeichnis).
- `src/agentkit/workers/implementation/__init__.py` — leere Datei (1 Zeile); kein Produktionscode.
- `src/agentkit/workers/bugfix/__init__.py` — leere Datei; kein Produktionscode.
- `src/agentkit/workers/remediation/__init__.py` — leere Datei; kein Produktionscode.
- `src/agentkit/workers/adversarial/__init__.py` — leere Datei; kein Produktionscode.
- `src/agentkit/pipeline_engine/implementation_phase/phase.py` — Compat-Re-Export auf `ImplementationPhaseHandler`.

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | WorkerSession: Spawn-Protokoll, Worker-Kontext-Resolution/Validation/Composition | `FK-26 §26.2.1`, `FK-26 §26.2.2`, `bc-cut-decisions §BC-6` | Kein Modul unter `agentkit.implementation`. `WorkerContextItemKey` als StrEnum, `resolve_worker_context()`, `validate_worker_context()`, `compose_worker_prompt()` fehlen vollständig. |
| A2 | WorkerLoop: Vier-Schritt-Inkrementzyklus und deterministischer Drift-Check Stufe 1 | `FK-26 §26.3.2`, `FK-26 §26.3.5`, `bc-cut-decisions §BC-6` | Kein `increment_commit`-Hook-basierter Diff-gegen-Entwurf implementiert. Zweistufige Drift-Erkennung fehlt. `IncrementStep` als StrEnum + geordnetes Tupel (Element 4) fehlt. |
| A3 | HandoverPackager: handover.json-Erzeugung und -Validierung | `FK-26 §26.7.2`, `FK-26 §26.7.3`, `formal.implementation.entities §implementation.entity.handover` | Kein Modul für `handover.json`-Schema, Pflichtfeld-Validierung, AC-Status-Enums. Structural-Checker prüft `handover.json` nicht (A4). |
| A4 | WorkerManifest: Erzeugung, BLOCKED-Pflichtfelder, BlockingCategory-Enum | `FK-26 §26.8.1`, `FK-26 §26.8.2`, `formal.implementation.entities §implementation.entity.worker-manifest` | `BlockingCategory` als StrEnum fehlt. `worker-manifest.json`-Schema-Validierung in Schicht 1 fehlt. `ImplementationHandler` liest kein `worker-manifest.json` (Drift C1). |
| A5 | WorkerHealthMonitor: PostToolUse Scoring-Engine | `FK-49 §49.1.1`, `bc-cut-decisions §BC-6 WorkerHealthMonitor` | Gesamte Scoring-Engine (5 Heuristiken, Score-Berechnung, `agent-health.json`-Persistenz) fehlt. Kein `agentkit.implementation.worker_health.scoring_hook`. |
| A6 | WorkerHealthMonitor: PreToolUse Interventions-Gate (Soft-Intervention / Hard Stop) | `FK-49 §49.1.2` | Keine Hook-Implementierung. Einmal-Garantie, Beobachtungsphase, strukturierte Interventions-Nachrichten nicht vorhanden. |
| A7 | WorkerHealthMonitor: LLM-Assessment-Sidecar (`agentkit watch-worker`) | `FK-49 §49.1.3` | Sidecar-Prozess (Pflichtbestandteil, kein Feature-Flag) fehlt vollständig. Kein Polling auf `agent-health.json`, kein MCP-Pool-Aufruf, kein Debounce. |
| A8 | Hook-Commit-Failure-Klassifikation und `tool-call-log.jsonl` | `FK-49 §49.1.4`, `FK-49 §49.1.5` | Kein stderr-Parser für `git commit`-Fehler. Kein Sliding-Window-JSONL-Log. |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | BLOCKED-Exit-Protokoll im ImplementationHandler | `src/agentkit/pipeline/phases/implementation/phase.py:ImplementationPhaseHandler.on_enter` | `FK-26 §26.11.2`, `bc-cut-decisions §BLOCKED-Eskalation §26.11.2` | Handler gibt `PhaseStatus.ESCALATED` nach `max_feedback_rounds`-Erschöpfung zurück, liest aber kein `worker-manifest.json`. Blocker-Details (`blocking_issue`, `blocking_category`, `recommended_next_action`) werden nicht aus Manifest in `HandlerResult.suggested_reaction` übernommen. |
| B2 | SpawnReason-Enum | `src/agentkit/workers/types.py:SpawnReason` | `FK-26 §26.2.3`, `bc-cut-decisions §BC-6 WorkerSession` | Enum existiert korrekt. Wird aber in `select_template_name` als roher String verglichen (`spawn_reason == "remediation"`) statt typisiert gegen `SpawnReason.REMEDIATION`. |
| B3 | Telemetrie-Katalog der Implementation-Phase | `src/agentkit/telemetry/events.py:EventType` | `FK-26 §26.10` | `AGENT_START`, `AGENT_END`, `INCREMENT_COMMIT`, `DRIFT_CHECK`, `REVIEW_REQUEST`, `REVIEW_RESPONSE`, `REVIEW_COMPLIANT`, `LLM_CALL` vorhanden. Fehlen: `WORKER_HEALTH_SCORE`, `WORKER_HEALTH_INTERVENTION` (FK-26 §26.10 Tabelle). |
| B4 | LLM-Pool-Reviews: Template-Auswahl und Sparring-Prompts | `src/agentkit/prompt_composer/selectors.py:select_template_name`, `src/agentkit/resources/internal/prompts/` | `FK-26 §26.5.1`, `FK-26 §26.5.4` | Worker-Templates vorhanden. Review-Templates (`review-consolidated.md`, `review-bugfix.md`, `review-spec-compliance.md`, `review-implementation.md`, `review-test-sparring.md`, `review-synthesis.md`) fehlen im `prompts/sparring/`-Verzeichnis. REVIEW_TEMPLATE_REGISTRY (Element 5) nicht als StrEnum+Registry modelliert. |
| B5 | Structural-Check-Layer (Schicht 1) | `src/agentkit/verify_system/structural/checker.py:StructuralChecker` | `FK-26 §26.8.1` (Structural Check `artifact.protocol`), `FK-26 §26.9.2` (Red/Green/Suite-Validierung) | Prüft Kontext, Snapshots, Corrupt-State. Prüft nicht: `protocol.md` (>50 Bytes), `handover.json`-Pflichtfelder, `worker-manifest.json`-Schema, BLOCKED-Pflichtfelder, Bugfix-Red/Green-Phasen-Konsistenz. |

### 4.3 C — Drift / Fehler

> Hier landen Implementierungen, die etwas tun, aber nicht das, was im Konzept steht, **oder** offensichtlich fehlerhaft sind (Bug, Verletzung einer Invariante, falsche Trust-Boundary, etc.).

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | ImplementationHandler ignoriert worker-manifest.json; ESCALATED-Triggerung falsch | `src/agentkit/pipeline/phases/implementation/phase.py:ImplementationPhaseHandler.on_enter` | `FK-26 §26.11.2`, `formal.implementation.invariants §implementation.invariant.worker_blocked_escalates` | Konzept: `ESCALATED` wird ausgelöst wenn `worker-manifest.json` `status=BLOCKED` enthält. Code: `ESCALATED` wird nach Erschöpfung von `max_feedback_rounds` ohne Manifest-Auswertung ausgelöst. Invariante `worker_blocked_escalates` ist nicht prüfbar, da Manifest nicht gelesen wird. Dies verletzt auch `formal.implementation.state-machine §implementation.transition.worker_running_to_escalated` (Guard fehlt). |
| C2 | SpawnReason als String-Literal statt typisierter Enum-Vergleich | `src/agentkit/prompt_composer/selectors.py:select_template_name` | `FK-26 §26.2.3`, `bc-cut-decisions §BC-6 WorkerSession`, Entscheidung Element 2 | Entscheidung 2026-04-08 Element 2 spezifiziert `SpawnReason` als StrEnum in `core/types.py`. `select_template_name` vergleicht `spawn_reason == "remediation"` als rohen String; Parameter-Typ ist `str`, nicht `SpawnReason`. Kein Typ-Safety; falscher Modulpfad (nicht `core/types.py`). |
| C3 | QaSubflowCycle enthält keine Layer-4 (PolicyEngine) als separaten Konzept-Layer | `src/agentkit/pipeline/phases/implementation/qa_subflow.py:QaSubflowCycle` | `FK-26 §26.1` (4-Schichten-QA), CLAUDE.md §QA-Subflow | Konzept: 4-Schichten-QA (Structural / LLM-Evaluations / Adversarial / Policy Engine). Code: `QaSubflowCycle.run()` iteriert über parametrisierte `layers`-Liste und ruft `policy_engine.decide()` danach separat. Policy Engine ist konzeptuell Layer 4, wird aber als separate Entscheidungskomponente außerhalb der Layer-Liste modelliert. Kein strukturelles Problem für die QA-Funktion, aber die `layers`-Liste im Handler-Default enthält nur 3 statt 4 benannte Schichten — unklar ob Layer 4 in der Schichtenreferenz zählt. |

## 5. Ableitungen / Empfehlungen

1. **WorkerManifest-Auswertung in ImplementationHandler (C1 — Invariante verletzt):** Höchste Priorität. `ImplementationHandler.on_enter` muss `worker-manifest.json` lesen und bei `status=BLOCKED` sofort `HandlerResult.ESCALATED` mit Blocker-Details zurückgeben, bevor der QA-Subflow gestartet wird. Dies ist Voraussetzung für korrekte Invariante `worker_blocked_escalates` und für den `bc-cut-decisions §BLOCKED-Eskalation §26.11.2`-Vertrag. Blocker für: korrekte Pipeline-Zustandsmaschine, Closure-Phase (liest Worker-Manifest-Stand).

2. **Structural-Checker um Worker-Artefakt-Checks erweitern (B5 — Schicht 1 unvollständig):** `StructuralChecker` muss `protocol.md` (>50 Bytes), `handover.json`-Pflichtfelder und `worker-manifest.json`-Schema prüfen. Für Bugfix-Stories: Red/Green-Konsistenzprüfung. Ohne diese Checks kann Schicht 1 ihren Kontrakt laut FK-26 §26.8.1 nicht erfüllen.

3. **WorkerHealthMonitor (A5, A6, A7, A8 — Kernkomponente fehlt vollständig):** `WorkerHealthMonitor` ist gemäß FK-49 Pflichtbestandteil ohne Feature-Flag. Ohne ihn fehlt die Worker-Runaway-Prevention (REF-042). Implementierungsreihenfolge: (1) `agent-health.json`-Schema + `AgentHealthState`-Modell, (2) PostToolUse-Scoring-Hook mit 5 Heuristiken, (3) PreToolUse-Interventions-Gate, (4) LLM-Assessment-Sidecar (`agentkit watch-worker`). Abhängigkeit: MCP-Pool-Integration muss stabil sein (FK-11).

4. **WorkerSession / HandoverPackager / WorkerLoop (A1, A2, A3, A4 — Worker-Seite nicht vorhanden):** Diese Sub-Komponenten (laut `bc-cut-decisions §BC-6`) sind der eigentliche BC-Kern. Bis zu ihrer Umsetzung orchestriert der BC nur den QA-Subflow, nicht den Worker. `BlockingCategory`-Enum, `handover.json`-Validator und `WorkerContextItemKey`-Registry sind sauber zu modellieren, bevor die Worker-Prompt-Komposition erweitert wird.

5. **Telemetrie-Events vervollständigen und SpawnReason-Typ korrigieren (B3, C2):** `EventType.WORKER_HEALTH_SCORE` und `EventType.WORKER_HEALTH_INTERVENTION` fehlen; ohne sie ist der Telemetrie-Kontrakt aus FK-26 §26.10 nicht vollständig maschinenlesbar. `select_template_name` sollte `SpawnReason`-Typ statt rohem String akzeptieren, um die Entscheidung Element 2 vollständig umzusetzen.

## 6. Suchstrategie & Quellen

- **Vollständig gelesen:**
  - `concept/technical-design/26_implementation_runtime_worker_loop.md` (FK-26)
  - `concept/technical-design/49_worker_health_monitor.md` (FK-49)
  - `concept/formal-spec/implementation/entities.md`
  - `concept/formal-spec/implementation/invariants.md`
  - `concept/formal-spec/implementation/state-machine.md`
  - `concept/formal-spec/implementation/commands.md`
  - `concept/formal-spec/implementation/events.md`
  - `concept/formal-spec/implementation/scenarios.md`
  - `src/agentkit/pipeline/phases/implementation/phase.py`
  - `src/agentkit/pipeline/phases/implementation/qa_subflow.py`
  - `src/agentkit/workers/types.py`
  - `src/agentkit/telemetry/events.py`
  - `src/agentkit/prompt_composer/selectors.py`
  - `src/agentkit/verify_system/structural/checker.py`
  - `src/agentkit/exceptions.py`
  - `tests/unit/pipeline/phases/implementation/test_implementation_phase.py`
  - `stories/_gap-analyse-schema.md`
  - `CLAUDE.md`
- **Punktuell via Grep / Read (bc-cut-decisions):**
  - `concept/_meta/bc-cut-decisions.md` — Abschnitte BC 6 implementation-phase, BLOCKED-Eskalation §26.11.2, Offene Klärungen 12–16 für implementation-phase
  - `concept/technical-design/_meta/domain-registry.yaml` — BC-ID und contract_docs/member_docs Verifikation
- **Code-Scan (Glob/Grep):**
  - Pattern `src/agentkit/pipeline/phases/implementation/**/*` — Vollständige Dateiliste der Phase
  - Pattern `src/agentkit/workers/**/*` — Worker-Subpakete auf Produktionscode geprüft
  - Grep `worker_health|HealthMonitor|sidecar` in `src/` — Nachweis Fehlen von WorkerHealthMonitor
  - Grep `handover|worker_manifest|WorkerManifest` in `src/` — kein Produktionscode gefunden
  - Grep `BlockingCategory|POLICY_CONFLICT` in `src/` — kein Treffer
  - Grep `IncrementStep|WorkerContextItem|resolve_worker_context` in `src/` — kein Treffer
  - Grep `increment_commit|drift_check|worker_health_score` in `src/` — Nachweis teilweiser EventType-Abdeckung
  - Glob `src/agentkit/resources/internal/prompts/*.md` — Review-Sparring-Templates fehlen
  - Glob `tests/**/*implementation*`, `tests/**/*worker*` — Testabdeckung geprüft
