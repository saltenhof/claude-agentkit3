OVERALL CHANGES-REQUESTED

**R3 ERROR Verification**
- RESOLVED: The current story now names the `StoryService` administrative exit transition owner and keeps normal `cancel_story` closed for `In Progress -> Cancelled`.
- RESOLVED: The current story now names `_run_admission_evidence` as the run-terminal read owner and requires committed `story_exit` to override generic run admission before `has_committed_operation_for_run`.

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: FAIL
- AC-Schaerfe: WEAK
- Klarheit/Eindeutigkeit: WEAK
- Kontext-Sinnhaftigkeit: FAIL

**Remaining/New Must-Fix ERRORs**

1. ERROR: Exit orchestration can leave a partially exited run because story cancellation and control-plane teardown are specified as separate ordered mutations without atomicity or recovery.

Evidence: `story.md` orders `story_exit` control-plane commit + teardown before the administrative `Cancelled` transition, then fallback, then `exit_gate` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:62)). The control-plane primitive is atomic only for op/binding/locks/events, not StoryService status ([facade.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/store/facade.py:871), [postgres_store.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/postgres_store.py:2405)). `StoryService.complete_story/cancel_story` persist status via the separate story repository path ([service.py](T:/codebase/claude-agentkit3/src/agentkit/story_context_manager/service.py:640), [service.py](T:/codebase/claude-agentkit3/src/agentkit/story_context_manager/service.py:737), [story_repository.py](T:/codebase/claude-agentkit3/src/agentkit/story_context_manager/story_repository.py:616)). If teardown commits and the later administrative cancel fails, the run is terminal/binding-revoked while the story can remain `In Progress`.

This also conflicts with the formal story-exit state machine, which transitions `exit_gate_passed -> story_cancelled -> binding_revoked -> ai_augmented_resumed` ([state-machine.md](T:/codebase/claude-agentkit3/concept/formal-spec/story-exit/state-machine.md:42)).

Fix: Specify one authoritative atomic or idempotently recoverable exit transaction boundary for `story_exit` op, administrative `Cancelled`, binding/lock teardown, and gate/fallback. Add negative tests for failure between `story_exit` op commit and StoryService cancellation: no durable half-exit, or deterministic recovery to `Cancelled + non-resumable + binding revoked`.

Additional note: the current backend narrows `has_committed_operation_for_run` to committed setup `phase_start`, so the stale setup op is the generic admission evidence after exit, not the `story_exit` op itself ([postgres_store.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/postgres_store.py:2517)). The required priority override is still correct.
