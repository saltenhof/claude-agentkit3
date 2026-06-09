OVERALL: CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: FAIL
- AC-Schaerfe: FAIL
- Klarheit/Eindeutigkeit: WEAK
- Kontext-Sinnhaftigkeit: WEAK

**Remaining / New Must-Fix ERRORs**

1. ERROR: §58.3 context prohibitions are still not genuinely enforceable/tested.

Evidence: FK-58 explicitly forbids exit for normal difficulty, mere agent uncertainty, usual remediation, and split/replan-solvable cases ([FK-58](T:/codebase/claude-agentkit3/concept/technical-design/58_story_exit_human_takeover_handoff.md:132)). The revised story only requires `AlternativeReview` booleans plus non-empty rejection strings ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:45)), and AC3 tests missing alternatives / empty reasons only ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:71)). A non-empty rejection reason can still encode “agent was unsure” or “normal remediation is hard”; the ACs would pass.

Fix: Add typed, testable admissibility checks for the §58.3 forbidden contexts, not just alternative-presence checks. Required negative tests: normal difficulty, agent uncertainty, usual remediation, split/replan-solvable. Also define who produces `AlternativeReview` while preserving FK-58’s lightweight CLI rule ([FK-58](T:/codebase/claude-agentkit3/concept/technical-design/58_story_exit_human_takeover_handoff.md:147), [story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:43)).

2. ERROR: Teardown anchor/owner is still imprecise enough to risk closure-path reuse.

Evidence: The story cites `src/agentkit/control_plane/runtime.py:1233` as teardown owner ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:30)), but that line is inside `complete_closure` and writes `operation_kind="closure_complete"` / `phase="closure"` ([runtime.py](T:/codebase/claude-agentkit3/src/agentkit/control_plane/runtime.py:1213)). The reusable atomic primitive is actually `ControlPlaneRuntimeRepository.commit_operation_with_side_effects` at [repository.py](T:/codebase/claude-agentkit3/src/agentkit/control_plane/repository.py:95). The story says normal closure must not be called, but it does not require an exit-specific control-plane operation kind/record.

Fix: Require a dedicated exit control-plane operation, e.g. `operation_kind="story_exit"` / non-closure phase or no phase, using the repository primitive at `repository.py:95`; explicitly forbid `complete_closure` and `operation_kind="closure_complete"` in exit tests.

**Resolved From R1**
- `exit-story` allowlist handling is now hard in scope, not optional.
- Human-only enforcement is now tied to `Principal.HUMAN_CLI` / `PrincipalResolver` and has negative tests for orchestrator/worker.
- `BindingDeleteScope` is no longer described as the teardown itself.
- Code anchors for `ADMIN_SUBCOMMANDS`, BranchGuard allowlist, `StoryStatus.CANCELLED`, and `Principal.HUMAN_CLI` are real.
