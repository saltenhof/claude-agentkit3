OVERALL: **CHANGES-REQUESTED**

**Per-Dimension Verdict**
- **Konzept-Vollstaendigkeit: WEAK** — `backend health`, `status`+weekly-review and cleanup scope are now addressed, but FK-04 §4.3.2 forms are still narrowed: FK shows `query-telemetry --run ...` and `--event ... --since 7d` without `--story`, while AG3-076 only specifies `query-telemetry --story ...`.
- **AC-Schaerfe: FAIL** — several Klasse-A ACs cannot be implemented from the declared CLI surface without inventing missing inputs or new service behavior.
- **Klarheit/Eindeutigkeit: FAIL** — Klasse A is still used for anchors that are not the claimed read services.
- **Kontext-Sinnhaftigkeit: FAIL** — key code anchors exist syntactically, but some are the wrong semantic anchor for the command contract.

**Remaining / New Must-Fix ERRORs**
1. **ERROR: `query-state --locks` is falsely anchored as an existing read path.**  
   AG3-076 says story/global lock listing is Klasse A via `LockRecordRepository` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:53), [story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:93)). Real code only exposes `deactivate_locks_for_story`, a mutating update path ([lock_record_repository.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/store/lock_record_repository.py:184)); there is no story/global list method.  
   **Fix:** add/require a real lock read repository anchor, or classify `query-state --locks` as Klasse C fail-closed with owner.

2. **ERROR: `run-phase` and `resume` still have unsatisfied service inputs.**  
   `run-phase` CLI only declares `phase --story [--config]`, but `start_phase` needs `run_id` plus `PhaseMutationRequest` fields `project_key`, `story_id`, `session_id`, `principal_type`, `worktree_roots` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:48), [models.py](T:/codebase/claude-agentkit3/src/agentkit/control_plane/models.py:53)). `resume --story` delegates to `resume_phase`, but that requires `StoryContext`, `PhaseEnvelope`, and `trigger` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:49), [engine.py](T:/codebase/claude-agentkit3/src/agentkit/pipeline_engine/engine.py:1119)).  
   **Fix:** define exact CLI flags or sanctioned derivation/loading paths for these inputs, including idempotency/session/run semantics; otherwise mark the command gap explicitly.

3. **ERROR: `export-telemetry [--dry-run]` omits required export inputs.**  
   The command surface has no `--story`, `--run`, or `--output-dir`, but the claimed service requires `story_id`, `run_id`, `output_dir` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:57), [story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:98)).  
   **Fix:** specify the CLI contract or config-derived source for those values.

4. **ERROR: `weekly-review` is claimed to render from existing read models, but the required data producers/read paths are not currently available.**  
   Story marks the renderer/status block Klasse A over “Read-Modelle” ([story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:55), [story.md](T:/codebase/claude-agentkit3/stories/AG3-076-operator-recovery-cli/story.md:96)). Real FailureCorpus review methods are explicit `NotImplementedError` slots ([top.py](T:/codebase/claude-agentkit3/src/agentkit/failure_corpus/top.py:128)), and `FC_PATTERNS`/`FC_CHECK_PROPOSALS` reads are fail-closed until follow-up owners ([projection_accessor.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:394)).  
   **Fix:** either depend on AG3-078 before rendering those report sections, or make unavailable sections explicit service-gap findings instead of silent empty reports.

Round-1 remediation fixed several wording/anchor problems, but the remaining false Klasse-A anchors and incomplete command-to-service contracts are blocking.
