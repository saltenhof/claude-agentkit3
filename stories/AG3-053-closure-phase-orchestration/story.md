# AG3-053: Closure-Phasen-Orchestrierung (FK-29 §29.1/§29.1a/§29.1.4) — Finding-Resolution-Gate -> Pre-Merge-Scan-und-Merge-Block (latest-main-integrieren -> Build/Test -> Integrated-Candidate-Sonar-Scan -> IntegrityGate gegen die FRISCHE Attestation -> Story-Branch-Push -> ff-Merge -> Post-Merge-Reconcile) -> Post-Merge-Finalization im ClosurePhaseHandler verdrahten

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:**
- AG3-007 (`ClosureProgress`-Schema — `integrity_passed`/`story_branch_pushed`/`merge_done`/`story_closed`/`metrics_written`/`postflight_done`; completed)
- AG3-008 (`MultiRepoClosureState` im `ClosurePayload`; completed)
- AG3-009 (Multi-Repo-Closure-Saga `run_multi_repo_closure` mit Pre-Merge-Check, ff-Merge mit Rollback, Push-main mit Partial-Push-Rollback, Teardown; completed)
- AG3-024 (PhaseEnvelope — `on_enter`/`on_resume`-Signaturen, Envelope-Store; completed)
- AG3-026 (VerifySystem-Top-Surface — `llm_evaluator` fuer Rueckkopplungstreue Ebene 4, FK-38 §38.3.1; completed)
- AG3-034 (IntegrityGate-9-Dimensionen + `build_integrity_gate` Composition-Root; completed)
- AG3-041 (QA-Zyklus-Mechanik — `advance_qa_cycle`/Remediation-Loop setzt den Finding-Resolution-Status `fully_resolved`/`partially_resolved`/`not_resolved` auf den Layer-2-Findings; ohne diese Resolution-Semantik hat das Finding-Resolution-Gate §29.2 nichts zu lesen; **in_progress**)
- AG3-043 (Layer-2-LLM-Evaluations — `StructuredEvaluator` produziert die drei Layer-2-QA-Artefakte `qa_review.json`/`semantic_review.json`/`doc_fidelity.json`, die das Finding-Resolution-Gate §29.2 konsumiert; **blocked**)
- AG3-052 (`sonarqube_gate`-Capability — Pre-Merge-Scan/Attestation, `build_sonar_gate_port_for_run`/`evaluate_sonarqube_gate`; completed)

> **Status `blocked`:** AG3-041 ist `in_progress`, AG3-043 ist `blocked` (transitiv ueber AG3-041). Das Finding-Resolution-Gate (§29.2) ist ein **harter** In-Scope-Schritt dieser Story und konsumiert die Layer-2-Resolution-Artefakte beider Stories — diese Story kann erst starten, wenn AG3-041 + AG3-043 `completed` sind. (Begruendung des Schnitts: §29.2.1 + bc-cut-decisions BC 7 `ClosureGates.FindingResolutionGate` prueft „gegen Layer-2-Artefakte qa_review/semantic_review/doc_fidelity"; deren Producer ist AG3-043, deren Resolution-Status-Feld AG3-041.)

**Unblocks:**
- AG3-018 (Fast-Modus — die Closure-`mode==fast`-Weiche „Sanity-Gate statt 9-Dim-IntegrityGate" braucht einen verdrahteten Closure-Orchestrierungspfad als Andockpunkt; diese Story modelliert die Fast-Weiche im Closure bereits explizit, AG3-018 erweitert/parametrisiert sie)

**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-29 §29.1` (Closure-Phase — Substate-Ablauf, `ClosureProgress`-Booleans, Closure-Verdict COMPLETED/ESCALATED)
- `FK-29 §29.1.1` (Voraussetzung: Closure nur nach Implementation COMPLETED; Concept/Research ohne Merge-Block; `integrity_passed`/`story_branch_pushed`/`merge_done` direkt `true`)
- `FK-29 §29.1.0` (die sechs `ClosureProgress`-Booleans als einziger Recovery-Wahrheitstraeger)
- `FK-29 §29.1.1` (Voraussetzung: Concept/Research ohne Merge-Block; `integrity_passed`/`story_branch_pushed`/`merge_done` direkt `true`)
- `FK-29 §29.1.2` (Ablauf mit Substates — Reihenfolge ist Pflicht; Story-Typ-Weiche impl/bugfix vs concept/research)
- `FK-29 §29.1.3` (Recovery-Dispatching: abgeschlossene Substates anhand `ClosureProgress` ueberspringen)
- `FK-29 §29.1.4` (**kanonische Closure-Reihenfolge ist Pflicht**: 1. Finding-Resolution-Gate -> 2. Pre-Merge-Scan-und-Merge-Block unter Lock [a. Lock/Fetch/Drift-Assert b. integrate main c. Build/Test d. Integrated-Candidate-Sonar-Scan **erzeugt die frische Attestation** e. IntegrityGate Dim 1-9 **verifiziert NACH dem Scan genau diese frische Attestation** f. Story-Branch-Push g. ff-Merge mit CAS h. Post-Merge-Reconcile] -> 3. Worktree-Teardown -> 4. Story-Done -> 5. Metriken -> 6. Rueckkopplungstreue Ebene 4 -> 7. Postflight -> 8. VektorDB-Sync -> 9. Guard-Deaktivierung. Das IntegrityGate liegt **innerhalb** des Locks **nach** dem Scan und **vor** Push/Merge — nicht davor.)
- `FK-29 §29.1a / §29.1a.1 / §29.1a.3` (Pre-Merge-Scan-und-Merge-Block unter Merge-Serialisierungs-Lock; strikte interne Sequenz: integrate-main -> Build/Test -> Sonar-Scan -> Ledger-Reconcile -> QG-verify -> `tree_hash(scan)==tree_hash(merge)` -> **IntegrityGate Dim 1-9** -> Push -> ff-Merge -> post-merge Reconcile; Drei-Pfad-Applicability APPLICABLE/absent/fast)
- `FK-29 §29.1a.6` (`mode=fast`: Sanity-Gate [Tests gruen + Worktree clean + Pre-Merge-Rebase OK] statt 9-Dim-IntegrityGate + Sonar-Scan; Rebase-Konflikt -> Eskalation an den Menschen)
- `FK-29 §29.1.5` (Merge-Policy `ff_only` default, `no_ff` dokumentierter Fallback; manuelle Rebases/Force-Push verboten)
- `FK-29 §29.2 / §29.2.1` (Finding-Resolution-Gate als Closure-Gate gegen die drei Layer-2-QA-Artefakte; `partially_resolved`/`not_resolved` -> harter Blocker; entfaellt fuer Concept/Research)
- `FK-29 §29.3 / §29.3.1 / §29.3.2` (Postflight-Gates: 5 Checks; Postflight-FAIL ist **non-blocking Warning** an den Menschen — der Schritt selbst ist trotzdem Pflicht, kein leerer Andockpunkt)
- `FK-29 §29.5` (Guard-Deaktivierung: Closure ruft `Governance.deactivate_locks(story_id)` als einzelnen Delegationsschritt; Closure haelt keine Lock-Logik)
- `FK-38 §38.3 / §38.3.1` (Rueckkopplungstreue/Doctreue Ebene 4 — `LlmEvaluator`-Aufruf `role=doc_fidelity` **nach Merge, vor Postflight**; non-blocking)
- `FK-35 §35.2 / §35.2.4a` (IntegrityGate-Delegation: Closure ruft das Gate inkl. Dim 9 auf — Owner der Gate-Logik ist governance-and-guards, Closure ist Aufrufer; Dim 9 verifiziert die FRISCHE Attestation NACH dem Scan, vermisst nicht neu)
- `FK-33 §33.6.3 / §33.6.4` (commit-gebundene Attestation des integrierten Kandidaten + Post-Merge-Reconcile gegen `main`)
- `FK-12 §12.4 / §12.5` (Branch-Push, ff-Merge, Worktree-Teardown als Git-Mechanik; Closure ownt die Reihenfolge, FK-12 die Einzeloperationen)
- `FK-20 §20.6 / §20.8.2` (Phase-Runner-Recovery; Concept/Research direkt auf `main`)
- `concept/_meta/bc-cut-decisions.md` BC 7 story-closure (`ClosureGates` Finding-Resolution+IntegrityGate-Invoker, `MergeSequence` Push/Merge/Teardown/Story-Close, `PostMergeFinalization` Metriken+Doctreue-Ebene-4+Postflight+VektorDB-Sync+Guard-Deaktivierung [alle non-blocking], `ExecutionReport`)
- `formal.story-closure.state-machine` / `formal.story-closure.invariants` (`push_precedes_merge`, `merge_rejection_never_completes_closure`, `manual_history_rewrite_forbidden`, `story-branch-pushed-is-resumable`)
- `formal.story-closure.scenarios` / `formal.story-closure.commands` / `formal.story-closure.events`

---

## 1. Kontext

Die **Capabilities** der Closure-Sequenz sind gebaut, aber **nicht in den Closure-Phasen-Handler verdrahtet**. Faktischer Ist-Zustand (verifiziert 2026-06-04):

- `src/agentkit/closure/phase.py:ClosurePhaseHandler.on_enter` (Zeilen 87-158) ruft heute ausschliesslich: Prior-Phase-Snapshot-Validierung (`_validate_prior_phases`), GitHub-Issue-Close (best-effort), Metriken (`build_story_metrics_record`), `write_execution_report`, `complete_story`. Es ruft **weder das IntegrityGate noch die Merge-Saga noch einen Pre-Merge-Scan/Rebase/Push** auf.
- `build_integrity_gate` (`bootstrap/composition_root.py:268`) ist gebaut und exportiert (`composition_root.py:611`), hat aber **keinen produktiven Aufrufer**: ein Grep auf `build_integrity_gate` ueber `src/` findet nur die Definition + den Export + die Klassendefinition in `governance/integrity_gate/__init__.py`. In `closure/` und `pipeline_engine/` gibt es **null** Treffer.
- `run_multi_repo_closure` (`closure/multi_repo_saga.py:338`) inkl. `pre_merge_check`, `local_ff_merge_with_rollback`, `push_main` (Partial-Push-Rollback), `push_story_branches`, `teardown_worktrees` ist gebaut, wird aber **nur im BC-`__init__.py` re-exportiert** — kein Aufrufer in `src/`. Die Saga setzt intern `progress = ClosureProgress(integrity_passed=True)` als **Annahme** (`multi_repo_saga.py:348`); d.h. sie erwartet, dass das IntegrityGate **vor** ihr lief — genau diese Vor-Schaltung fehlt.
- `ClosurePhaseHandler.on_resume` (`phase.py:169-186`) gibt deterministisch FAILED zurueck — das **Recovery-Dispatching** ueber `ClosureProgress` (FK-29 §29.1.3) ist nicht implementiert.

Der Gap ist **explizit von zwei completed-Stories an „die Closure-Story" delegiert** worden, die bisher nicht existiert:
- AG3-052 §2.2: „Closure-Pre-Merge-Scan + Merge-Serialisierungs-Lock + Post-Merge-Reconcile gegen `main` (FK-29 §29.1a) — Closure-Orchestrierung. Hier nur die Reconciler-Capability + Branch-Scan." und §8: „Setup/Closure-Call-Sites NICHT hier verdrahten (Out-of-Scope)".
- AG3-034 §2.2: „Closure-Pre-Merge-Scan + Merge-Serialisierungs-Lock + Post-Merge-Reconcile gegen `main` (FK-29 §29.1a) — Closure-Story. Dieser Scan ERZEUGT die Attestation, die Dim 9 nur verifiziert."

Diese Story ist die **Verdrahtungs-/Orchestrierungs-Story**: sie baut KEINE neue Gate-/Saga-/Sonar-Mechanik, sondern ruft die bestehenden Capabilities in der von FK-29 §29.1/§29.1a normierten **Pflicht-Reihenfolge** aus dem `ClosurePhaseHandler` heraus auf, schreibt die `ClosureProgress`-Checkpoints in den Phase-State zurueck und implementiert das Recovery-Dispatching. Die **Implementation->QA-Subflow-Verdrahtung ist NICHT Teil dieser Story** — sie ist bereits verdrahtet (`implementation/phase.py:163` ruft `verify_system.run_qa_subflow`).

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Closure-Orchestrierung im `ClosurePhaseHandler` (FK-29 §29.1.2/§29.1.4, Reihenfolge ist Pflicht)
- `ClosurePhaseHandler.on_enter` orchestriert die Closure-Sequence fuer **impl/bugfix** in der **kanonischen Reihenfolge aus §29.1.4** (jeder Checkpoint-Schritt setzt sein `ClosureProgress`-Boolean und persistiert es **vor** dem naechsten irreversiblen Seiteneffekt):
  1. Prior-Phase-Validierung (bereits vorhanden — bleibt; inkl. `qa_cycle_status == pass`).
  2. **Finding-Resolution-Gate (§29.2)**: liest die drei Layer-2-QA-Artefakte (`qa_review.json`, `semantic_review.json`, `doc_fidelity.json`, Producer AG3-043; Resolution-Status aus AG3-041) ueber den ArtifactManager und blockt fail-closed (-> ESCALATED), wenn ein Finding `partially_resolved`/`not_resolved` ist. (BC 7 `ClosureGates.FindingResolutionGate`.)
  3. **Pre-Merge-Scan-und-Merge-Block (§29.1a/§29.1a.3)** — ein **einziger** Block unter dem Merge-Serialisierungs-Lock, in dieser strikten internen Reihenfolge (keine Umsortierung):
     a. Lock erwerben (`locked_sha := origin/main`), `git fetch`, `assert origin/main == locked_sha`.
     b. latest-`main` in `story/{story_id}` integrieren, Workspace clean (`git clean -xfd`, leeres `git status --porcelain`).
     c. Build/Test/Coverage auf dem integrierten Stand (Layer-1-Determinismus).
     d. **Integrated-Candidate-Sonar-Scan** ueber die **AG3-052-Capability** (`build_sonar_gate_port_for_run`/`evaluate_sonarqube_gate`, Single-Match-Ledger-Reconcile, QG per `analysisId`, Overall-Code) — **erzeugt die commit-gebundene frische Attestation**; `tree_hash(scan) == tree_hash(merge)`. Diese Story ruft die Capability auf, baut sie nicht nach.
     e. **IntegrityGate Dim 1-9** ueber `build_integrity_gate(...).evaluate(story_dir, story_type)` (AG3-034-Capability), **nach** dem Scan, **vor** dem Push: Dim 9 (FK-35 §35.2.4a) **verifiziert genau die in Schritt d erzeugte frische Attestation** und vermisst nicht neu. PASS -> `integrity_passed = true` (Checkpoint persistieren); FAIL -> ESCALATED (opake Meldung, Detail im Audit-Log), **kein** Push, **kein** main-Update.
     f. **Story-Branch-Push** innerhalb des Locks (`story_branch_pushed = true`).
     g. **ff-only Update von `main`** mit CAS/Lease gegen `locked_sha`.
     h. **Post-Merge-Reconcile** (Ledger erneut gegen `main`, FK-33 §33.6.4), Worktree-Teardown, Lock freigeben (`merge_done = true`).
     Push-/Merge-/CAS-Fehler bzw. dauerhaft-rot/nicht-ff -> ESCALATED (Saga-Rollback, Partial-Push wird zurueckgerollt; main-Drift -> Remediation-Loop/Retry mit neuem `locked_sha`, §29.1a.4). Die Schritte d-h werden ueber die **AG3-009-Saga** `run_multi_repo_closure(...)` bzw. die atomaren Saga-Bausteine ausgefuehrt (siehe 2.1.3) — keine zweite Merge-Implementierung.
  4. **Story-Status Done** (`complete_story`, bereits vorhanden) -> `story_closed = true`.
  5. **Metriken** (`build_story_metrics_record` + `ProjectionAccessor.write_projection`, bereits vorhanden) -> `metrics_written = true`.
  6. **Rueckkopplungstreue Ebene 4 (§29.1.4 Schritt 6, FK-38 §38.3.1)** — **nach Merge, vor Postflight**: `LlmEvaluator.evaluate(role="doc_fidelity", ...)` (AG3-026) prueft, ob bestehende Doku aktualisiert werden muss. **Non-blocking** (FAIL -> Warning an den Menschen, §29.3.2-analog), aber der Schritt ist Pflicht — kein leeres Auslassen.
  7. **Postflight-Gates (§29.3, 5 Checks)**: `story_dir_exists`, `story_closed`, `metrics_set`, `telemetry_complete`, `artifacts_complete`. **Postflight-FAIL ist ein non-blocking Warning** an den Menschen (§29.3.2; kein Rollback nach Merge) — der **Schritt wird trotzdem ausgefuehrt** und sein Ergebnis festgehalten; `postflight_done = true` markiert „Postflight gelaufen", nicht „alle Checks gruen". Kein leerer Andockpunkt, der `postflight_done=true` ohne ausgefuehrte Checks setzt.
  8. **VektorDB-Sync (§29.1.4 Schritt 8)** — fuer Suchbarkeit nachfolgender Stories. Non-blocking (async/fire-and-forget zulaessig); der Schritt ist Pflicht.
  9. **Guard-Deaktivierung (§29.5)** — Closure ruft `Governance.deactivate_locks(story_id)` (governance Top-Surface) als **einzelnen Delegationsschritt**; Closure haelt keine eigene Lock-Logik. Schalter „AI-Augmented-Modus wieder frei".
- Schritte 6-9 sind die **`PostMergeFinalization`-Schritte** (BC 7 `agentkit.closure.post_merge_finalization`). Sie sind **non-blocking** (PASS/WARNING, §29.3.2), aber **verbindliche Pflichtschritte** — Closure deaktiviert die Governance-Locks und macht die Story suchbar; ein stilles Auslassen verletzt ZERO DEBT. (Eine Folge-Story darf nur die **Tiefe** einzelner Checks ausbauen, nicht die Schritte selbst weglassen — siehe 2.2.)
- **Closure-Verdict**: COMPLETED nur, wenn alle **harten** Substates (Finding-Gate, IntegrityGate, Merge) erfolgreich; ein non-blocking-Warning aus Schritt 6-8 verhindert COMPLETED **nicht** (es wird als Warning gespiegelt, §29.3.2). Jeder harte Blocker -> ESCALATED. Kein degradierter Abschluss-Modus.

#### 2.1.2 Story-Typ-Weiche (FK-29 §29.1.1)
- **impl/bugfix**: voller Block (2.1.1 Schritte 2-9).
- **concept/research**: Finding-Resolution-Gate, IntegrityGate und der gesamte gesperrte Merge-Block werden **uebersprungen**; `integrity_passed`/`story_branch_pushed`/`merge_done` werden direkt `true` gesetzt (kein Worktree, kein `story/{story_id}`-Branch, direkt auf `main`; FK-20 §20.8.2). Die `PostMergeFinalization`-Schritte (Story-Closed/Metriken/Doctreue-Ebene-4/Postflight/VektorDB-Sync/Guard-Deaktivierung, Schritte 4-9) laufen normal.
- Die Story-Typ-Fallunterscheidung wird **typisiert** ueber den Story-Type-Profil-Pfad (`get_profile`/`required_phases_for`) getroffen, nicht ueber String-/Flag-Kaskaden.

#### 2.1.2a Fast-Mode-Weiche im Closure (FK-29 §29.1a.6 / §29.1.4 Applicability-Geltung, FK-33 §33.6.5)
- Bei `mode == fast` (Mode-Profil Fast, FK-24 §24.3.4) ist das `sonarqube_gate` an diesem Closure-Lifecycle-Punkt **NOT_APPLICABLE_FAST**: der Closure-Handler **modelliert die Fast-Weiche explizit** und ueberspringt **sowohl** den Integrated-Candidate-Sonar-Scan (2.1.1 Schritt 3.d) **als auch** das 9-Dimensionen-IntegrityGate (Schritt 3.e). An ihre Stelle tritt das **Sanity-Gate**: Tests gruen **und** Worktree clean **und** Pre-Merge-Rebase auf `main` OK — als Pflicht-Vorbedingung des Merges. Der Merge erfolgt per **Pre-Merge-Rebase auf `main`** statt unter dem 9-Dim-gesperrten Block; bei **Rebase-Konflikt -> Eskalation an den Menschen** (ESCALATED; der Mensch begleitet die Fast-Story ohnehin aktiv).
- Die Fast-Applicability wird **typisiert** ueber `resolve_applicability(...)`/das Mode-Profil aufgeloest (FK-33 §33.6.5, AG3-052-Capability), nicht ueber String-/Flag-Kaskaden. Push/ff-Merge/Reconcile und alle `PostMergeFinalization`-Schritte (4-9) bleiben unveraendert.
- **Abgrenzung zu AG3-018:** Diese Story baut die Sanity-Gate-Weiche als **konzepttreuen, verdrahteten Closure-Pfad** (genau der Andockpunkt, den AG3-018 braucht). Was AG3-018 ergaenzt, ist die **uebergreifende** Fast-Mode-Konzeption/-Parametrisierung ueber alle Phasen (FK-24) — nicht der Closure-interne Sanity-Gate-Schritt selbst, der hier steht. Kein leerer „Andockpunkt", der `mode==fast` nur durchreicht.

#### 2.1.3 Single-Repo- vs Multi-Repo-Pfad
- Der Handler waehlt deterministisch zwischen Single-Repo- und Multi-Repo-Closure anhand des Run-`StoryContext`/der Repo-Liste. Der Multi-Repo-Pfad nutzt `run_multi_repo_closure` (AG3-009) unveraendert. Der Single-Repo-Pfad nutzt dieselbe Saga mit einer Ein-Element-Repo-Liste **oder** die atomaren Saga-Bausteine (`push_story_branches`/`local_ff_merge_with_rollback`/`push_main`/`teardown_worktrees`) — der Worker waehlt den konzepttreuen Weg (eine Wahrheit, kein zweiter Merge-Pfad) und belegt ihn. Es wird **keine** zweite Merge-Implementierung eingefuehrt.

#### 2.1.4 `ClosureProgress`-Persistenz + Recovery-Dispatching (FK-29 §29.1.3, C1 der Gap-Analyse)
- Nach jedem Substate wird das zugehoerige `ClosureProgress`-Boolean im `ClosurePayload` ueber den Phase-Envelope/State-Store persistiert (checkpoint-sicher, vor dem naechsten Seiteneffekt).
- `ClosurePhaseHandler.on_resume` **dispatcht** anhand der persistierten `ClosureProgress`-Booleans: bereits `true`-markierte Substates werden uebersprungen, ab dem ersten offenen Substate wird fortgesetzt (`story-branch-pushed-is-resumable`). Kein deterministisches FAILED mehr. Merge-irreversible Substates werden nie zurueckgerollt.

#### 2.1.5 Composition-Root-Anbindung
- Ein `build_closure_phase_handler(...)` im `bootstrap/composition_root.py` verdrahtet die Kollaborateure (IntegrityGate via `build_integrity_gate`, Sonar-Port via `build_sonar_gate_port_for_run`, ArtifactManager fuer die Layer-2-Lesung, StoryService, ProjectionAccessor) analog zu `build_setup_phase_handler`/`build_verify_system`. Der Handler baut diese Kollaborateure **nicht selbst** (DI-Muster, Truth-Boundary).
- Ein bestehender/neuer Orchestrator-Einstieg registriert den Handler auf der `PhaseHandlerRegistry` (der `run_pipeline`-Pfad existiert bereits, `pipeline_engine/runner.py`). Falls noch kein produktiver 4-Phasen-Registry-Aufbau existiert, ist **nur** die Closure-Registrierung + ihr Test in Scope (kein Vollausbau der Gesamt-Pipeline-Composition — siehe 2.2).

#### 2.1.6 Tests
- Unit: Reihenfolge-Erzwingung (jeder Schritt setzt sein Boolean vor dem naechsten; **IntegrityGate liegt NACH dem Sonar-Scan und VOR dem Push** — Negativtest: kein Scan-loses IntegrityGate, kein Merge ohne `integrity_passed`); Finding-Resolution-FAIL -> ESCALATED; IntegrityGate-FAIL -> ESCALATED; Push-Fehler/Merge-CAS-Fehler -> ESCALATED; Concept/Research-Weiche (kein Merge-Block, Booleans direkt `true`).
- Unit Fast-Mode: `mode==fast` -> Sanity-Gate statt Sonar-Scan+9-Dim-IntegrityGate; Tests-rot/Worktree-dirty/Rebase-Konflikt -> ESCALATED; kein Sonar-Scan-/IntegrityGate-Aufruf im Fast-Pfad (Negativtest: Capabilities werden nicht aufgerufen).
- Unit Post-Merge-Finalization: Doctreue-Ebene-4 (`LlmEvaluator role=doc_fidelity`) wird **nach Merge, vor Postflight** aufgerufen; Postflight fuehrt die 5 Checks aus und ein Postflight-FAIL erzeugt eine **Warning** (kein ESCALATED, COMPLETED bleibt) und setzt dennoch `postflight_done`; VektorDB-Sync-Trigger wird aufgerufen; `Governance.deactivate_locks(story_id)` wird als letzter Schritt aufgerufen. Negativtest: Auslassen eines `PostMergeFinalization`-Schritts ist im Code nicht erreichbar.
- Unit Recovery: `on_resume` mit teilweise gesetztem `ClosureProgress` ueberspringt abgeschlossene Substates und setzt am ersten offenen fort; merge_done=true -> kein erneuter Merge.
- Integration: vollstaendige impl-Closure gegen einen gestubbten Git-Backend (`GitBackend`-Protokoll der AG3-009-Saga) + gestubbte Sonar-/Gate-/LlmEvaluator-/Governance-Capability-Grenze — End-to-End vom Finding-Resolution-Gate ueber Merge, Doctreue-Ebene-4, Postflight, VektorDB-Sync bis Guard-Deaktivierung, COMPLETED. Negativpfad: IntegrityGate-FAIL bricht **vor** dem Push ab (kein Branch-Push, kein main-Update); Postflight-FAIL nach Merge -> COMPLETED + Warning (kein Rollback).
- Contract: `ClosureProgress`-Reihenfolge-Invariante + Closure-Verdict-Werte (COMPLETED/ESCALATED) gegen `formal.story-closure.state-machine`/`invariants` gepinnt (`push_precedes_merge`, `merge_rejection_never_completes_closure`).

### 2.2 Out of Scope (bewusst, mit Owner)
- **AG3-009-Saga-interne Mechanik** (Pre-Merge-Check, ff-Merge-Rollback, Push-main-Partial-Rollback, Teardown) — bereits gebaut; diese Story **ruft** sie auf, baut sie nicht nach.
- **AG3-034-IntegrityGate-Mechanik** (9 Dimensionen, Pflicht-Artefakt-Vorstufe, Dim 9) — bereits gebaut; Aufrufer, kein Owner (FK-35 §35.2.4a „verifiziert nur").
- **AG3-052-Sonar-Capability** (Attestation, Reconciler, Applicability) — bereits gebaut; der Pre-Merge-Scan ruft `build_sonar_gate_port_for_run`/`evaluate_sonarqube_gate` auf.
- **Implementation->QA-Subflow-Verdrahtung** — bereits verdrahtet (`implementation/phase.py:163`). Nicht hier.
- **Uebergreifende Fast-Mode-Konzeption ueber alle Phasen** (FK-24 Mode-Profil-Parametrisierung Setup/Exploration/Implementation/Closure) — AG3-018. **Der Closure-interne Sanity-Gate-Pfad selbst ist hier IN Scope** (§2.1.2a, FK-29 §29.1a.6): Sonar-Scan + 9-Dim-IntegrityGate entfallen, Sanity-Gate (Tests gruen/Worktree clean/Pre-Merge-Rebase OK) tritt an ihre Stelle, Rebase-Konflikt -> ESCALATED. Diese Story liefert damit den **verdrahteten** Andockpunkt (kein leeres Durchreichen).
- **Post-Merge-Finalization-SCHRITTE sind IN Scope** (FK-29 §29.1.4 Schritte 6-9; BC 7 `PostMergeFinalization`): Rueckkopplungstreue Ebene 4 (FK-38 §38.3.1), Postflight-Gates (5 Checks, FK-29 §29.3), VektorDB-Sync (§29.1.4 Schritt 8), Guard-Deaktivierung (FK-29 §29.5) werden alle als **verbindliche, non-blocking Pflichtschritte verdrahtet** (siehe 2.1.1 Schritt 6-9). **Out-of-Scope ist nur die fachliche TIEFE einzelner Bestandteile**, nicht das Auslassen der Schritte:
  - **WorkflowMetric-Schema-Ausbau (FK-29 §29.6)** — `WorkflowMetric`-Schema-Owner ist `PostMergeFinalization`, der Schema-VOLLAUSBAU bleibt separater Owner; der `metrics_written`-Schritt selbst laeuft hier (`StoryMetric` via `Telemetry.write_projection`, bereits vorhanden).
  - **ExecutionReport-9-Sektionen-Ausbau (FK-29 §29.4)** — separater Owner (`agentkit.closure.execution_report`); der bestehende flache Report bleibt; der Report-Aufruf am Closure-Ende bleibt unveraendert.
  - Kein halber Postflight, kein leerer `postflight_done=true`-Andockpunkt. Wenn die VEKTORDB-Anbindung (FK-13) im Zielprojekt nicht verfuegbar ist, ist der Sync ein non-blocking Warning — der **Schritt** wird trotzdem ausgefuehrt. Bei echtem Konzept-/Verfuegbarkeits-Konflikt: hart stoppen und ruecksprechen.
- **Vollausbau der 4-Phasen-Pipeline-Composition / Top-Orchestrator** (Setup+Exploration+Implementation+Closure auf einer `PhaseHandlerRegistry` mit `run_pipeline`) — nur die Closure-Registrierung ist hier in Scope; ein eigener Owner fuer den Gesamt-Pipeline-Bootstrap bleibt offen.

## 3. Betroffene Dateien (Richtwert)
| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/closure/phase.py` | Modifiziert | `on_enter` orchestriert Finding-Resolution-Gate -> Pre-Merge-Scan-und-Merge-Block (integrate-main -> Build/Test -> Sonar-Scan -> **IntegrityGate gegen die frische Attestation** -> Push -> ff-Merge -> Reconcile) -> Story-Done -> Metriken -> Doctreue-Ebene-4 -> Postflight -> VektorDB-Sync -> Guard-Deaktivierung; Fast-Mode-Sanity-Gate-Weiche; `on_resume` Recovery-Dispatching; Story-Typ-Weiche; `ClosureProgress`-Persistenz |
| `src/agentkit/closure/gates.py` / `merge_sequence.py` / `post_merge_finalization.py` (BC 7 Sub-Modul-Prefixes `agentkit.closure.gates`/`.merge_sequence`/`.post_merge_finalization`) | Neu/Erweitert | Reine Orchestrierungs-Helfer: Finding-Resolution-Gate-Lesung (`gates`), Pre-Merge-Block-Sequenz + Saga-Aufruf (`merge_sequence`), Post-Merge-Finalization-Schritte (Doctreue-Ebene-4-Aufruf an `LlmEvaluator`, Postflight-5-Checks, VektorDB-Sync-Trigger, `Governance.deactivate_locks`-Delegation) (`post_merge_finalization`) — duenn, ruft bestehende Capabilities; keine neue Merge-/Gate-/Sonar-/Lock-Mechanik |
| `src/agentkit/bootstrap/composition_root.py` | Modifiziert | `build_closure_phase_handler(...)` (DI der Kollaborateure analog `build_setup_phase_handler`); Export ergaenzen |
| `tests/unit/closure/test_closure_phase.py` | Erweitert | Reihenfolge-Erzwingung, Story-Typ-Weiche, Negativpfade (Finding/Integrity/Push/Merge -> ESCALATED) |
| `tests/unit/closure/test_closure_recovery.py` | Neu | `on_resume`-Recovery-Dispatching ueber `ClosureProgress` |
| `tests/integration/closure/test_closure_orchestration.py` | Neu | E2E impl-Closure gegen gestubbten `GitBackend` + gestubbte Gate-/Sonar-Grenze; COMPLETED + Negativpfad (Integrity-FAIL vor Push) |
| `tests/contract/closure/test_closure_state_machine.py` | Neu | `ClosureProgress`-Reihenfolge + Verdict-Werte gegen `formal.story-closure.*` |

## 4. Akzeptanzkriterien
1. **Closure ruft das IntegrityGate auf**: `ClosurePhaseHandler.on_enter` ruft fuer impl/bugfix `build_integrity_gate(...).evaluate(story_dir, story_type)` (AG3-034) auf. PASS -> `integrity_passed=true` + Fortsetzung; FAIL -> Closure-Verdict ESCALATED, **kein** Branch-Push, **kein** main-Update. Unit- + Integration-Test belegen die Verdrahtung (nicht nur die Gate-Unit).
2. **Closure ruft die Merge-Saga auf**: der Merge-Schritt delegiert an `run_multi_repo_closure` (AG3-009) bzw. die atomaren Saga-Bausteine (Single-Repo) — keine zweite Merge-Implementierung. Push-Story-Branch (`story_branch_pushed=true`), ff-Merge + Push-main (`merge_done=true`). Push-/Merge-/CAS-Fehler -> ESCALATED mit Saga-Rollback (Partial-Push wird zurueckgerollt). Test belegt den Aufruf + die Fehler-Eskalation.
3. **Pre-Merge-Block + Reihenfolge ist Pflicht** (FK-29 §29.1a/§29.1.4): innerhalb des Merge-Serialisierungs-Locks gilt die strikte Sequenz integrate-`main` -> Build/Test -> **Integrated-Candidate-Sonar-Scan (erzeugt die frische Attestation)** -> **IntegrityGate Dim 1-9 (verifiziert NACH dem Scan genau diese frische Attestation, kein Re-Scan, FK-35 §35.2.4a)** -> Story-Branch-Push -> ff-Merge -> Post-Merge-Reconcile. Negativtest: ein IntegrityGate-Aufruf ohne vorausgegangenen Scan bzw. ein Merge ohne `integrity_passed` ist im Code nicht erreichbar (Reihenfolge erzwungen).
4. **Finding-Resolution-Gate** (FK-29 §29.2): liest `qa_review.json`/`semantic_review.json`/`doc_fidelity.json` (Producer AG3-043, Resolution-Status AG3-041) ueber den ArtifactManager; ein `partially_resolved`/`not_resolved`-Finding -> Closure-Verdict ESCALATED (fail-closed). Entfaellt fuer Concept/Research. Test je Fall.
5. **Story-Typ-Weiche** (FK-29 §29.1.1): Concept/Research ueberspringen Finding-Resolution-Gate + IntegrityGate + Merge-Block; `integrity_passed`/`story_branch_pushed`/`merge_done` direkt `true`; kein Branch-Push, kein Merge. impl/bugfix durchlaufen den vollen Block. Die Weiche ist typisiert (Profil/`required_phases_for`), nicht String-basiert. Test je Story-Typ.
6. **Fast-Mode-Sanity-Gate-Weiche** (FK-29 §29.1a.6, FK-33 §33.6.5): bei `mode==fast` entfaellt **sowohl** der Integrated-Candidate-Sonar-Scan **als auch** das 9-Dim-IntegrityGate; an ihre Stelle tritt das **Sanity-Gate** (Tests gruen **und** Worktree clean **und** Pre-Merge-Rebase auf `main` OK); Rebase-Konflikt -> ESCALATED. Die Fast-Applicability ist typisiert aufgeloest (kein String-Branching). Test: Fast-Pfad ruft Sonar-Scan/IntegrityGate **nicht** auf; Sanity-Verletzung -> ESCALATED.
7. **Post-Merge-Finalization-Pflichtschritte** (FK-29 §29.1.4 Schritte 6-9; BC 7 `PostMergeFinalization`): nach Merge laufen **verbindlich** (a) Rueckkopplungstreue Ebene 4 (`LlmEvaluator role=doc_fidelity`, FK-38 §38.3.1, **nach Merge vor Postflight**), (b) Postflight-Gates (5 Checks, FK-29 §29.3), (c) VektorDB-Sync, (d) Guard-Deaktivierung (`Governance.deactivate_locks(story_id)`, FK-29 §29.5). Alle vier sind **non-blocking** (FAIL -> Warning an den Menschen, §29.3.2; kein Rollback, COMPLETED bleibt), aber **kein Schritt darf ausgelassen** werden; `postflight_done=true` markiert „Postflight gelaufen", nicht „alle Checks gruen". Test: jeder Schritt wird aufgerufen; Postflight-FAIL -> COMPLETED + Warning; Auslassen ist im Code nicht erreichbar.
8. **`ClosureProgress`-Checkpoint-Persistenz**: jedes Substate-Boolean wird im `ClosurePayload`/Phase-State **vor** dem naechsten irreversiblen Schritt persistiert. Test belegt die Schreib-Reihenfolge.
9. **Recovery-Dispatching** (FK-29 §29.1.3): `on_resume` ueberspringt alle `true`-Substates und setzt am ersten offenen fort; `merge_done=true` -> kein erneuter Merge/Push; kein Rollback irreversibler Substates. Kein deterministisches FAILED mehr. Test mit teilweise gesetztem `ClosureProgress`.
10. **Closure-Verdict** COMPLETED genau dann, wenn alle **harten** Substates (Finding-Gate, IntegrityGate, Merge) erfolgreich; jeder harte Blocker (Finding-FAIL, Integrity-FAIL, Push-/Merge-Fehler, Fast-Sanity-Verletzung) -> ESCALATED. Ein non-blocking-Warning aus den Finalization-Schritten (AK7) verhindert COMPLETED nicht. Kein degradierter Abschluss. Test je Verdict.
11. **Composition-Root**: `build_closure_phase_handler(...)` verdrahtet die Kollaborateure per DI (IntegrityGate, Sonar-Port, ArtifactManager, `LlmEvaluator`, Governance-Top-Surface, StoryService, ProjectionAccessor — kein Selbstbau im Handler); der Handler ist auf der `PhaseHandlerRegistry` registrierbar. Test belegt die Registrierung + dass der gebaute Handler die Capabilities aufruft.
12. **Architecture-Conformance**: keine zweite Merge-/Gate-/Sonar-/Lock-Wahrheit; Orchestrierungs-Helfer in `closure/` (BC-Grenze; `gates`/`merge_sequence`/`post_merge_finalization`), Sonar nur ueber `verify_system.sonarqube_gate`-Capability, Gate nur ueber `governance.integrity_gate`-Capability, Merge nur ueber die AG3-009-Saga, Guard-Deaktivierung nur ueber `governance`-Top-Surface, Doctreue-Ebene-4 nur ueber `verify_system.llm_evaluator`; Layer-2-Lesung nur ueber ArtifactManager. Keine zirkulaeren Abhaengigkeiten (`closure` -> `governance`/`verify_system`/`integrations` ist erlaubt; `verify_system`/`governance` duerfen NICHT auf `closure` zeigen).
13. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy default **und** `--platform linux`; ruff clean; Coverage >= 85%; LOC-Linter (`scripts/python/py_loc_to_sonar.py`) 0 Issues; vier CI-Konzept-Gates gruen.

## 5. Definition of Done
- AK 1-13 erfuellt.
- `.venv\Scripts\python -m pytest` gruen.
- `mypy src` (default) **und** `mypy --platform linux src` gruen; `ruff check src tests` gruen.
- LOC-Linter + vier CI-Konzept-Gates gruen.
- giftige Codex-Review (+ ggf. Grok) -> PASS; Jenkins SUCCESS; Sonar Quality Gate OK.
- Aenderungen committed auf `main`; AG3-018 als „Closure-Sanity-Gate-Weiche verdrahtet (Fast-Mode-Andockpunkt vorhanden)" vermerkt.

## 6. Konzept-Referenzen (autoritativ)
- **FK-29 §29.1.0 / §29.1 / §29.1.1 / §29.1.2 / §29.1.3 / §29.1.5** — `ClosureProgress`-Booleans, Closure-Phase, Substate-Ablauf, Recovery, Merge-Policy
- **FK-29 §29.1.4** — kanonische Closure-Reihenfolge (Pflicht): Finding-Gate -> Pre-Merge-Block [integrate-main -> Build/Test -> **Sonar-Scan** -> **IntegrityGate verifiziert die frische Attestation** -> Push -> ff-Merge -> Reconcile] -> Teardown -> Story-Done -> Metriken -> Doctreue-Ebene-4 -> Postflight -> VektorDB-Sync -> Guard-Deaktivierung
- **FK-29 §29.1a / §29.1a.1 / §29.1a.3 / §29.1a.6** — Pre-Merge-Scan-und-Merge-Block unter Merge-Serialisierungs-Lock (IntegrityGate **nach** Scan, **vor** Merge); Fast-Mode-Sanity-Gate
- **FK-29 §29.2 / §29.2.1** — Finding-Resolution-Gate gegen Layer-2-Artefakte
- **FK-29 §29.3 / §29.3.1 / §29.3.2** — Postflight-Gates (5 Checks); Postflight-FAIL = non-blocking Warning
- **FK-29 §29.5** — Guard-Deaktivierung (`Governance.deactivate_locks`)
- **FK-38 §38.3 / §38.3.1** — Rueckkopplungstreue/Doctreue Ebene 4 (nach Merge, vor Postflight; non-blocking)
- **FK-35 §35.2 / §35.2.4a** — IntegrityGate-Delegation (Closure = Aufrufer; Dim 9 verifiziert die frische Attestation, vermisst nicht neu)
- **FK-33 §33.6.3 / §33.6.4** — commit-gebundene Attestation + Post-Merge-Reconcile
- **FK-12 §12.4 / §12.5** — Branch-Push, ff-Merge, Worktree-Teardown (Git-Mechanik)
- **FK-20 §20.6 / §20.8.2** — Phase-Runner-Recovery; Concept/Research direkt auf `main`
- **concept/_meta/bc-cut-decisions.md BC 7 story-closure** — `ClosureGates` / `MergeSequence` / `PostMergeFinalization` (Schritte 6-9, alle non-blocking) / `ExecutionReport`; Modul-Prefixes
- **formal.story-closure.state-machine / invariants / scenarios / commands / events** — `push_precedes_merge`, `merge_rejection_never_completes_closure`, `manual_history_rewrite_forbidden`, `story-branch-pushed-is-resumable`
- **AG3-009 / AG3-034 / AG3-052 — Consumer-Vertraege** der jeweils gebauten Capabilities (Saga / IntegrityGate / Sonar-Gate)

## 7. Guardrail-Referenzen
- **FIX THE MODEL, NOT THE SYMPTOM**: keine zweite Merge-/Gate-/Sonar-Wahrheit; die Reihenfolge wird typisiert erzwungen, nicht in Flag-Kaskaden versteckt.
- **FAIL CLOSED**: Finding-FAIL / Integrity-FAIL / Push-/Merge-Fehler -> ESCALATED; kein fail-open, kein degradierter Abschluss.
- **ZERO DEBT**: Doctreue-Ebene-4, Postflight, VektorDB-Sync, Guard-Deaktivierung sind **verbindliche** (non-blocking) Closure-Pflichtschritte und werden vollstaendig verdrahtet — kein leerer `postflight_done=true`-Andockpunkt, kein stilles Auslassen. Out-of-Scope ist nur die fachliche TIEFE einzelner Checks (WorkflowMetric-Schema, ExecutionReport-9-Sektionen), nicht die Schritte.
- **NO ERROR BYPASSING**: keine impl/bugfix-Story darf ohne IntegrityGate-PASS (bzw. Fast-Sanity-Gate-PASS) mergen; die Reihenfolge (Scan VOR Gate, Gate VOR Push) ist im Code nicht umgehbar.
- **WORKFLOW- UND STATE-DISZIPLIN**: `ClosureProgress` ist der einzige Recovery-Wahrheitstraeger; keine Schatten-State-Datei.

## 8. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **NICHT neu bauen**: Saga (`agentkit.closure.multi_repo_saga`: `run_multi_repo_closure`, `pre_merge_check`, `local_ff_merge_with_rollback`, `push_main`, `push_story_branches`, `teardown_worktrees`, `GitBackend`-Protokoll), IntegrityGate (`agentkit.bootstrap.composition_root.build_integrity_gate` -> `IntegrityGate.evaluate`), Sonar-Gate (`agentkit.verify_system.sonarqube_gate`: `build_sonar_gate_port_for_run`, `evaluate_sonarqube_gate`). Diese Story ruft sie auf.
- Die Saga setzt intern `ClosureProgress(integrity_passed=True)` als **Annahme** (`multi_repo_saga.py:348`) — das IntegrityGate MUSS davor laufen; baue die Vor-Schaltung im Handler. **Reihenfolge im Lock ist normiert (§29.1a.3): Sonar-Scan ERZEUGT die Attestation, das IntegrityGate VERIFIZIERT sie NACH dem Scan und VOR dem Push — niemals Gate vor Scan.**
- Composition-Root-Muster: orientiere `build_closure_phase_handler` an `build_setup_phase_handler`/`build_verify_system` (DI; der Handler baut Kollaborateure nicht selbst). DI-Kollaborateure inkl. `LlmEvaluator` (Doctreue-Ebene-4), Governance-Top-Surface (`deactivate_locks`), VektorDB-Sync-Trigger.
- **Post-Merge-Finalization (§29.1.4 Schritte 6-9) ist IN Scope** (BC 7 `PostMergeFinalization`): Doctreue-Ebene-4, Postflight-5-Checks, VektorDB-Sync, `Governance.deactivate_locks` werden verdrahtet — alle non-blocking, aber kein Schritt darf fehlen. Nur die fachliche TIEFE (WorkflowMetric-Schema §29.6, ExecutionReport-9-Sektionen §29.4) bleibt separater Owner. KEIN leerer `postflight_done`-Andockpunkt.
- Fast-Mode: bei `mode==fast` Sanity-Gate (§29.1a.6) statt Sonar-Scan+9-Dim-IntegrityGate; Rebase-Konflikt -> ESCALATED. Explizit modellieren, nicht durchreichen.
- Tests gegen das `GitBackend`-Protokoll der Saga stubben (kein Live-Git/-Remote in CI); Sonar-/Gate-/LlmEvaluator-/Governance-/VektorDB-Grenze stubben (MOCKS-Ausnahme: externes System) — die Orchestrierungs-/Reihenfolge-Logik echt testen.
- Negativpfade an der Phasengrenze sind Pflicht (testing-guardrails): IntegrityGate-FAIL bricht VOR dem Push ab; Push-Fehler rollt Partial-Push zurueck; Postflight-FAIL nach Merge -> COMPLETED + Warning (kein Rollback); Fast-Rebase-Konflikt -> ESCALATED.
- Bei echtem Konzept-Widerspruch (z.B. VektorDB im Zielprojekt nicht verfuegbar und Schritt nicht non-blocking darstellbar): hart stoppen und ruecksprechen — keine neue Fehlannahme einbauen.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen.
