OVERALL CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: **FAIL** — FK-04 `query-telemetry --run` / event-only forms are still not coherently mapped.
- AC-Schaerfe: **FAIL** — `resume` and `query-telemetry --run` still cannot be implemented from the declared contract without inventing missing derivation.
- Klarheit/Eindeutigkeit: **FAIL** — false semantic anchors remain (`StoryContext` via `load_phase_state`; “no project-wide Event-Reader” despite existing facade).
- Kontext-Sinnhaftigkeit: **FAIL** — most R2 anchors improved, but key remaining anchors are still the wrong code surfaces.

**Round-2 Error Verification**
- R2 ERROR 1 `query-state --locks`: **resolved**. Story now marks story/global `--locks` as Klasse C fail-closed, not `LockRecordRepository` read path.
- R2 ERROR 2 `run-phase` / `resume`: **partially resolved**. `run-phase` inputs are now explicit; `resume` still has false loading anchors.
- R2 ERROR 3 `export-telemetry`: **resolved**. `--story --run --output-dir` are now required.
- R2 ERROR 4 `weekly-review`: **resolved**. Failure-Corpus sections are now explicit AG3-078 service-gap findings.

**Remaining / New Must-Fix ERRORs**
1. **ERROR: `resume` still uses false `StoryContext` / `PhaseEnvelope` anchors.**  
   Story says `StoryContext` is loaded via `story/repository.py:50` + `story/service.py:63` / `governance/repository.py:265`, and treats the phase-state record as the `PhaseEnvelope` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:51), [story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:91), [story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:109)). Real code: `story/repository.py:50` is `load_phase_state`, `story/service.py:63` loads phase state for summaries, and `governance/repository.py:265` returns a phase-state record, not `StoryContext` or `PhaseEnvelope`. `resume_phase` requires `StoryContext` + `PhaseEnvelope` ([engine.py](T:/codebase/claude-agentkit3/src/agentkit/pipeline_engine/engine.py:1119)).  
   **Fix:** anchor `StoryContext` to the real context loader (`state_backend/store/facade.py:171` or `StoryRepository.load_story_context` at `story/repository.py:47`) and `PhaseEnvelope` to `PhaseEnvelopeStore.load` / `StateBackendPhaseEnvelopeRepository` ([store.py](T:/codebase/claude-agentkit3/src/agentkit/pipeline_engine/phase_envelope/store.py:60), [phase_envelope_repository.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/store/phase_envelope_repository.py:46)).

2. **ERROR: `query-telemetry` still has an invalid run/event contract.**  
   Story declares `--run` as Klasse A via `StateBackendExecutionEventReader.read_run_events`, but that reader is constructed with `project_key` and `story_id` and is story-scope bound ([storage.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/storage.py:187), [storage.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/storage.py:192)). The CLI surface has no `--project`, and the story does not define a real run-id-to-story resolver. It also claims no project-wide event reader exists for story/run-less event queries ([story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:56), [story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:100)), but real code exposes `load_execution_events_for_project_global(project_key)` ([facade.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/store/facade.py:626), [public_api.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/store/public_api.py:32)).  
   **Fix:** define the project/scope selector explicitly. Either add/derive `project_key` and use the existing project-wide reader with adapter-side `run_id`/`event`/`since` filtering, or classify `--run` without resolvable scope as Klasse C. Do not claim the project-wide reader is missing.
