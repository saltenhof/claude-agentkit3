# story-closure — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `story-closure` |
| Display-Name | `Story-Closure` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `FK-29`, `formal.story-closure.entities`, `formal.story-closure.state-machine`, `formal.story-closure.commands`, `formal.story-closure.events`, `formal.story-closure.invariants`, `formal.story-closure.scenarios` |
| Codebase-Hauptpfade | `src/agentkit/closure/`, `src/agentkit/pipeline/phases/closure/` |

## 1. Executive Summary

Der BC story-closure hat eine solide Teilimplementierung: Das Datenmodell (`ClosurePayload`, `ClosureProgress`, `MultiRepoClosureState`) ist vollstaendig und formal-spec-konform, die Multi-Repo-Saga (`agentkit.backend.closure.multi_repo_saga`) deckt die fuenf atomaren Stufen ab, und der `ClosurePhaseHandler` setzt Phase-Einstieg, Snapshot-Validierung, Metriken und `ExecutionReport` um. Jedoch fehlen vier der fuenf konzeptionell definierten Sub-Komponenten (ClosureGates, MergeSequence, PostMergeFinalization als eigenstaendige Sub-Module) vollstaendig — Finding-Resolution-Gate, Postflight-Gates, VektorDB-Sync und Guard-Deaktivierung sind nicht implementiert. Das Recovery-Dispatching basierend auf `ClosureProgress`-Booleans fehlt ebenso wie die `ClosureVerdict`- und `MergePolicy`-Typen im BC. `ClosurePhaseHandler.on_resume` verweigert deterministisch statt Recovery-Dispatching zu betreiben.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 9 |
| B — Teilweise umgesetzt | 4 |
| C — Drift / Fehler | 3 |

## 2. Konzept-Soll (Kurzfassung)

- **Closure-Top mit ClosureVerdict (COMPLETED/ESCALATED) und MergePolicy (ff_only/no_ff) als typisierte Datenmodelle** — `concept/_meta/bc-cut-decisions.md §BC7`, `FK-29 §29.1.5`
- **ClosureGates-Sub: Finding-Resolution-Gate gegen Layer-2-Artefakte (qa_review/semantic_review/doc_fidelity), Integrity-Gate-Delegation an governance-and-guards** — `FK-29 §29.2`, `concept/_meta/bc-cut-decisions.md §BC7`
- **MergeSequence-Sub: Branch-Push, Merge (ff_only/no_ff), Worktree-Teardown, Issue-Close als Recovery-idempotente Substates** — `FK-29 §29.1.2`, `FK-29 §29.1.4`, `concept/_meta/bc-cut-decisions.md §BC7`
- **Multi-Repo-Atomicity: merge_done erst nach Push aller Repos, Partial-Push-State-Eskalation** — `FK-29 §29.1.6`, `formal.story-closure.invariants §multi_repo_atomicity`
- **PostMergeFinalization-Sub: Metriken (StoryMetric/WorkflowMetric), Rückkopplungstreue Ebene 4 (FK-38), fuenf Postflight-Checks, VektorDB-Sync (async fire-and-forget), Guard-Deaktivierung via Governance** — `FK-29 §29.1.4 Schritte 7-11`, `FK-29 §29.3`, `FK-29 §29.5`, `concept/_meta/bc-cut-decisions.md §BC7`
- **ExecutionReport-Sub: Markdown-Report mit neun Sektionen, auch bei FAILED/ESCALATED (Graceful Degradation), Sektionen Failure Diagnosis und Policy Engine Verdict** — `FK-29 §29.4`
- **Recovery-Dispatching: `on_resume` ueberspringt abgeschlossene Substates basierend auf ClosureProgress-Booleans** — `FK-29 §29.1.3`, `formal.story-closure.state-machine §story-closure.rule.story-branch-pushed-is-resumable`
- **Closure-Sequence immer als letzter Schritt ausgefuehrt (auch bei FAILED/ESCALATED in fruehen Phasen) — Skip-Modus mit ExecutionReport-Erzeugung** — `FK-29 §29.4.1`
- **Formale State-Machine mit sieben Zustaenden (requested, policy_checked, story_branch_pushed, merged_to_main, story_closed, completed, escalated)** — `formal.story-closure.state-machine`
- **Closure-Events emittieren (closure.started, policy.ff_only_selected, story_branch.pushed, merge.attempted, merge.completed, issue.closed, closure.completed, closure.escalated)** — `formal.story-closure.events`
- **Invarianten: push_precedes_merge, merge_rejection_never_completes_closure, manual_history_rewrite_forbidden** — `formal.story-closure.invariants`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/story_context_manager/models.py:ClosureProgress` — sechs Bool-Felder mit Reihenfolge-Validator; spec-konform gemaess `FK-29 §29.1.0`
- `src/agentkit/story_context_manager/models.py:ClosurePayload` — diskriminierte Union-Payload mit `phase_type="closure"`, `progress`, `multi_repo`; FK-39-konform
- `src/agentkit/story_context_manager/models.py:MultiRepoClosureState` — fuenf Listen/Felder fuer Multi-Repo-Recovery; FK-29 §29.1.6.2-konform
- `src/agentkit/closure/multi_repo_saga.py:run_multi_repo_closure` — fuenf-stufige Saga (pre_merge_check, push_story_branches, local_ff_merge_with_rollback, push_main, teardown_worktrees) mit lokaler Rollback-Garantie
- `src/agentkit/closure/multi_repo_saga.py:local_ff_merge_with_rollback` — pre_merge_sha-Rollback aller bereits gemergten Repos bei Fehler
- `src/agentkit/closure/multi_repo_saga.py:push_main` — Partial-Push-State mit Rollback verbleibender Repos; escaliert korrekt
- `src/agentkit/closure/execution_report/records.py:ExecutionReport` — Datenklasse mit neun Feldern (story_id, story_type, status, phases_executed, started_at, completed_at, story_closed, warnings, metrics)
- `src/agentkit/closure/post_merge_finalization/records.py:StoryMetricsRecord` — Metriken-Datenklasse mit Closure-time-Feldern
- `src/agentkit/pipeline/phases/closure/phase.py:ClosurePhaseHandler` — Phase-Einstieg mit Snapshot-Validierung (inkl. qa_cycle_status), GitHub-Issue-Close (best-effort), Metriken, ExecutionReport, `complete_story`-Delegation
- `src/agentkit/pipeline/phases/closure/metrics.py:build_story_metrics_record` — baut StoryMetricsRecord aus Telemetrie-Events und Attempt-Records
- `src/agentkit/pipeline/phases/closure/execution_report.py:write_execution_report` — Wrapper, delegiert an `state_backend.store.record_closure_report`

## 4. GAP-Analyse

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | Finding-Resolution-Gate (ClosureGates-Sub) | `FK-29 §29.2`, `concept/_meta/bc-cut-decisions.md §BC7` | Kein Code unter `agentkit.backend.closure.gates`. Gate-Pruefung gegen Layer-2-Artefakte (qa_review/semantic_review/doc_fidelity) fehlt vollstaendig; ClosurePhaseHandler.on_enter fuehrt diesen Schritt nicht aus. |
| A2 | Integrity-Gate-Delegation an governance-and-guards | `FK-29 §29.1.2`, `FK-35 §35.2`, `concept/_meta/bc-cut-decisions.md §BC7` | `agentkit.backend.closure.gates` und damit der `IntegrityGateInvoker` fehlen. Kein Code, der `agentkit.backend.governance.integrity_gate` vor dem Merge aufruft. |
| A3 | MergeSequence-Sub (Branch-Push, Merge, Worktree-Teardown als recovery-idempotente Substates in Single-Repo) | `FK-29 §29.1.2`, `FK-29 §29.1.3`, `concept/_meta/bc-cut-decisions.md §BC7` | `agentkit.backend.closure.merge_sequence` existiert nicht. Single-Repo-Branch-Push und -Merge fehlen; `multi_repo_saga.py` deckt nur den Multi-Repo-Pfad ab. `ClosurePhaseHandler.on_enter` delegiert nicht an eine MergeSequence. |
| A4 | Recovery-Dispatching basierend auf ClosureProgress-Booleans | `FK-29 §29.1.3`, `formal.story-closure.state-machine §story-closure.rule.story-branch-pushed-is-resumable` | `ClosurePhaseHandler.on_resume` gibt sofort FAILED zurueck. Kein Dispatch auf abgeschlossene Substates; Recovery-Semantik laut State-Machine nicht implementiert. |
| A5 | Postflight-Gates (fuenf Checks: story_dir_exists, story_closed, metrics_set, telemetry_complete, artifacts_complete) | `FK-29 §29.3`, `concept/_meta/bc-cut-decisions.md §BC7 PostMergeFinalization` | Kein Code unter `agentkit.backend.closure.post_merge_finalization` jenseits des Records-Moduls. Keine Klasse `PostflightGate` oder `PostflightCheck`. |
| A6 | Rückkopplungstreue Ebene 4 (Dokumententreue via LlmEvaluator) | `FK-29 §29.1.4 Schritt 8`, `FK-38 §38.3.1`, `concept/_meta/bc-cut-decisions.md §BC7 PostMergeFinalization` | `FeedbackFidelityCheck` fehlt. Keine Verbindung zu `agentkit.backend.verify_system.llm_evaluator` aus dem Closure-Pfad. |
| A7 | VektorDB-Sync (async fire-and-forget) | `FK-29 §29.1.4 Schritt 10`, `FK-13`, `concept/_meta/bc-cut-decisions.md §BC7 PostMergeFinalization` | Kein `VectorDbSyncTrigger`. Closure-Phase triggert keinen Vektor-DB-Sync nach Merge. |
| A8 | Guard-Deaktivierung via Governance.deactivate_locks(story_id) | `FK-29 §29.5`, `concept/_meta/bc-cut-decisions.md §BC7 PostMergeFinalization` | `GuardDeactivator` fehlt. Kein Aufruf an `agentkit.backend.governance` zum Beenden des Lock-Records und Entfernen der Lock-Exporte. |
| A9 | ClosureVerdict (COMPLETED/ESCALATED) und MergePolicy (ff_only/no_ff) als typisierte Enums im BC | `FK-29 §29.1.5`, `concept/_meta/bc-cut-decisions.md §BC7 Top-Datenmodell` | Weder `ClosureVerdict` noch `MergePolicy` sind als Typen im `agentkit.backend.closure`-Namespace definiert. Die Konzept-Skizze erwartet diese als Teil des Top-Datenmodells. |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | ExecutionReport: Sektionen und Graceful Degradation | `src/agentkit/closure/execution_report/records.py:ExecutionReport` | `FK-29 §29.4.2`, `FK-29 §29.4.3` | `ExecutionReport`-Datenklasse hat nur neun Top-Level-Felder (story_id, status usw.) statt der neun Sektion-Gruppen (Failure Diagnosis, Artifact Health, Structural Check Results, Policy Engine Verdict, Closure Sub-Step Status, Telemetry Event Counts, Integrity Violations Log). Graceful Degradation (`MISSING`-Markierung fehlender Quellen) und Skip-Modus-Auslosung bei FAILED/ESCALATED-Fruehphasen fehlen als ausfuehrender Code-Pfad. |
| B2 | Multi-Repo-Closure: merge_done-Setzung und Teardown-Idempotenz | `src/agentkit/closure/multi_repo_saga.py:run_multi_repo_closure` | `FK-29 §29.1.6.1`, `FK-29 §29.1.3` | `merge_done = true` wird erst nach erfolgreichem Teardown gesetzt (Zeile 434), nicht nach Stufe-4-Push-Erfolg — konzeptuell muss Teardown erst danach erfolgen und `merge_done` deckt Stufe 4+5 ab. Zudem: Die `ClosureProgress`-Booleans werden innerhalb der Saga nicht in den persistierten Phase-State zurueckgeschrieben; der State-Store wird nicht aktualisiert. |
| B3 | ClosurePhaseHandler: Closure-Sequenz (11 Schritte) | `src/agentkit/pipeline/phases/closure/phase.py:ClosurePhaseHandler.on_enter` | `FK-29 §29.1.2`, `FK-29 §29.1.4` | `on_enter` validiert Prior-Phase-Snapshots, schliesst das GitHub-Issue (best-effort), schreibt Metriken und ExecutionReport, und ruft `complete_story` auf. Fehlt: Finding-Resolution-Gate, Integrity-Gate, Branch-Push, Merge, Worktree-Teardown, Postflight-Gates, Rückkopplungstreue, VektorDB-Sync, Guard-Deaktivierung — also Schritte 1-2 und 3-11 bis auf Story-Closed und Metriken. |
| B4 | StoryMetricsRecord als Schema-Owner (WorkflowMetric fehlt) | `src/agentkit/closure/post_merge_finalization/records.py:StoryMetricsRecord` | `FK-29 §29.6`, `concept/_meta/bc-cut-decisions.md §BC7 PostMergeFinalization` | `StoryMetricsRecord` ist implementiert. `WorkflowMetric` (zweites Schema, das story-closure laut FK-29 §29.6 besitzen soll) fehlt. `WorkflowMetricCalculator` ist nicht vorhanden; es gibt keinen Code, der Workflow-Metriken berechnet und via `Telemetry.write_projection` schreibt. |

### 4.3 C — Drift / Fehler

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | on_resume verweigert statt Recovery-Dispatching | `src/agentkit/pipeline/phases/closure/phase.py:ClosurePhaseHandler.on_resume` | `FK-29 §29.1.3`, `formal.story-closure.state-machine §story-closure.rule.story-branch-pushed-is-resumable` | `on_resume` gibt deterministisch FAILED zurueck mit der Meldung "Closure phase does not support resume". Das ist ein direkter Widerspruch zum Konzept: ClosureProgress-Booleans und Crash-Recovery sind explizit der Kern von FK-29 §29.1.3; die formale State-Machine definiert Resumierbarkeit ab `story_branch_pushed`. |
| C2 | Closures Sub-Komponenten-Paketschnitt weicht von bc-cut-decisions ab | `src/agentkit/closure/` (Verzeichnisstruktur) | `concept/_meta/bc-cut-decisions.md §BC7 Modul-Prefixes` | BC-cut-decisions erwartet `agentkit.backend.closure.gates`, `agentkit.backend.closure.merge_sequence`, `agentkit.backend.closure.post_merge_finalization`, `agentkit.backend.closure.execution_report`. Tatsaechlich existieren nur `agentkit.backend.closure.execution_report` (fast leer) und `agentkit.backend.closure.post_merge_finalization` (nur Records). `agentkit.backend.closure.gates` und `agentkit.backend.closure.merge_sequence` fehlen; die Haupt-Phase-Logik liegt stattdessen in `agentkit.pipeline.phases.closure` — ein sachfremder Schnitt, der dem Top-Surface-Prinzip des BC widerspricht. |
| C3 | GitHub-Issue-Close ist blocking statt innerhalb MergeSequence | `src/agentkit/pipeline/phases/closure/phase.py:_close_github_issue` | `FK-29 §29.1.4 Schritt 6`, `concept/_meta/bc-cut-decisions.md §BC7 MergeSequence` | Laut FK-29 §29.1.4 erfolgt Story-Closed (Issue-Close) nach Merge und Worktree-Teardown als Substate (story_closed = true). In der Implementierung wird `_close_github_issue` vor der Metriken-Materialisierung aufgerufen, ohne dass Merge oder Worktree-Teardown stattgefunden haben — die konzeptionelle Reihenfolge wird verletzt. |

## 5. Ableitungen / Empfehlungen

1. **ClosureGates-Sub implementieren (A1, A2) — hoechste Prioritaet.** Das Finding-Resolution-Gate und die Integrity-Gate-Delegation blockieren jede produktive Closure-Ausfuehrung: Ohne diese Checks kann keine Story sicher abgeschlossen werden. Blocker fuer vollstaendige Pipeline-E2E-Faehigkeit.

2. **Recovery-Dispatching in on_resume herstellen (A4, C1).** Der Widerspruch zwischen Konzept und Implementierung ist ein harter Invarianten-Bruch. Crash-Recovery ist ein zentrales Designziel von FK-29; das deterministisch fehlende `on_resume` macht Closure-Restarts unmoeglich.

3. **MergeSequence-Sub mit Single-Repo-Pfad aufbauen (A3, C3).** Single-Repo-Branch-Push, Merge und Worktree-Teardown fehlen vollstaendig. Die konzeptuell korrekte Reihenfolge (erst Merge, dann Issue-Close) ist verletzt. Dies ist Voraussetzung fuer jeden produktiven Abschluss-Flow.

4. **BC-Paketschnitt gemaess bc-cut-decisions korrigieren (C2).** Phase-Logik gehoert in `agentkit.backend.closure.*`-Sub-Module, nicht in `agentkit.pipeline.phases.closure`. Der aktuelle Schnitt verletzt das Top-Surface-Prinzip und erschwert Erweiterungen.

5. **PostMergeFinalization vollstaendig ausbauen (A5, A6, A7, A8, B4).** Postflight-Gates, Rückkopplungstreue Ebene 4, VektorDB-Sync und Guard-Deaktivierung sind alle nicht umgesetzt. WorkflowMetric als zweites Schema fehlt. Diese Luecke macht den letzten Abschnitt der Closure-Sequenz (Schritte 7-11) komplett unbesetzt.

6. **ExecutionReport auf vollstaendige neun Sektionen erweitern (B1).** Aktuell ist der Report eine flache Datenstruktur. Failure Diagnosis, Artifact Health, Policy Engine Verdict, Integrity Violations Log und Closure Sub-Step Status fehlen als ausfuehrende Sektionen. Ohne diese ist der Report fuer Oversight/Audit unzureichend.

7. **ClosureVerdict und MergePolicy als Typen hinzufuegen (A9).** Fehlende StrEnums im Top — geringer Aufwand, aber Pflicht fuer typsichere Aggregation und Routing im Recovery-Dispatching.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/technical-design/29_closure_sequence.md`
  - `concept/formal-spec/story-closure/entities.md`
  - `concept/formal-spec/story-closure/state-machine.md`
  - `concept/formal-spec/story-closure/commands.md`
  - `concept/formal-spec/story-closure/events.md`
  - `concept/formal-spec/story-closure/invariants.md`
  - `concept/formal-spec/story-closure/scenarios.md`
  - `concept/formal-spec/story-closure/README.md`
  - `src/agentkit/closure/multi_repo_saga.py`
  - `src/agentkit/closure/execution_report/records.py`
  - `src/agentkit/closure/post_merge_finalization/records.py`
  - `src/agentkit/pipeline/phases/closure/phase.py`
  - `src/agentkit/pipeline/phases/closure/metrics.py`
  - `src/agentkit/pipeline/phases/closure/execution_report.py`
  - `tests/unit/pipeline/phases/closure/test_closure_phase.py`
  - `tests/unit/closure/test_multi_repo_saga.py`
- **Punktuell gelesen:**
  - `concept/_meta/bc-cut-decisions.md §BC7 story-closure` (Zeilen 539-654)
  - `concept/technical-design/_meta/domain-registry.yaml` — story-closure-Eintrag
- **Code-Scan (Glob/Grep):**
  - Pattern `src/agentkit/closure/**/*`: Verzeichnisstruktur des BC ermitteln
  - Pattern `src/agentkit/pipeline/phases/closure/**/*`: Phase-Implementierung ermitteln
  - Pattern `ClosureVerdict|MergePolicy|FindingResolutionGate|...`: Typen-Existenz pruefen
  - Pattern `postflight|VectorDb|GuardDeactivat`: Implementierung der PostMergeFinalization-Schritte pruefen
  - Pattern `ClosurePayload|ClosureProgress|ClosureVerdict|MergePolicy` in `models.py`: Verortung der Datenmodelle bestaetigen
