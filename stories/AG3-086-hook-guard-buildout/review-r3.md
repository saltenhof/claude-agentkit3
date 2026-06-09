OVERALL CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: FAIL
- AC-Schaerfe: FAIL
- Klarheit: PASS
- Kontext-Sinnhaftigkeit: FAIL

**Remaining Must-Fix ERRORs**

1. **ERROR: `integrity_violation` fix is not genuinely buildable against the real telemetry contract.**  
   The story now correctly requires `skill_usage_check` and `WebCallBudgetGuard` block events without `stage` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-086-hook-guard-buildout/story.md:79), [story.md](T:/codebase/claude-agentkit3/stories/AG3-086-hook-guard-buildout/story.md:86), [story.md](T:/codebase/claude-agentkit3/stories/AG3-086-hook-guard-buildout/story.md:106)). But real code still pins `stage` as mandatory for **every** `EventType.INTEGRITY_VIOLATION` ([events.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/events.py:173), [events.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/events.py:257)), and the contract test locks that in ([test_event_catalog.py](T:/codebase/claude-agentkit3/tests/contract/telemetry/test_event_catalog.py:112)). AC9 requires contract tests green ([story.md](T:/codebase/claude-agentkit3/stories/AG3-086-hook-guard-buildout/story.md:89)), so the story currently asks for no-stage budget/skill events while the shared contract still requires stage.

   **Fix:** Add explicit scope/AC/tests to migrate the telemetry payload contract: `integrity_violation` must require `guard`/`detail`; `stage` is conditional and only valid/required for `guard="prompt_integrity_guard"`. Update `MANDATORY_PAYLOAD_FIELDS`, `validate_event_payload` behavior if needed, and `tests/contract/telemetry/test_event_catalog.py`.

Round-2 budget fail-closed migration is otherwise covered: unresolved story type moves to `WebCallBudgetGuard`, emitter verdict removal is specified, and `runner.py:960-968` behavior is explicitly preserved/migrated.
