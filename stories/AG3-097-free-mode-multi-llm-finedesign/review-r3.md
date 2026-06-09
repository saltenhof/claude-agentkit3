OVERALL CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: FAIL
- AC-Schaerfe: FAIL
- Klarheit/Eindeutigkeit: FAIL
- Kontext-Sinnhaftigkeit: FAIL

**Remaining Must-Fix ERRORs**
1. ERROR: `infra_unavailable` routing to AG3-059 is not genuine.

AG3-097 claims AG3-059 delivers `escalation_reason` + escalation class incl. `infra_unavailable` for `status: PAUSED` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:50), [story.md](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:58)). That is not what FK-39/AG3-059 define. FK-39 has `pause_reason` for `PAUSED`, and `escalation_reason` only for `ESCALATED`, with a closed listed value set that does not include `infra_unavailable` ([39_phase_state_persistenz.md](T:/codebase/claude-agentkit3/concept/technical-design/39_phase_state_persistenz.md:242), [39_phase_state_persistenz.md](T:/codebase/claude-agentkit3/concept/technical-design/39_phase_state_persistenz.md:243)). AG3-059 explicitly tests `escalation_reason` only with `ESCALATED` and `pause_reason` only with `PAUSED` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-059-phase-state-core-fieldset-ownership/story.md:53)). Real code likewise has only `paused_reason`, no `escalation_class`/`escalation_reason` ([models.py](T:/codebase/claude-agentkit3/src/agentkit/story_context_manager/models.py:436)), and `PauseReason` has only three values ([pause_reason.py](T:/codebase/claude-agentkit3/src/agentkit/core_types/pause_reason.py:46)).

Required fix: either route the PAUSED `infra_unavailable` carrier to a story that actually owns and extends the PAUSED carrier model, or change AG3-097 to a buildable/honest behavior without claiming AG3-059 supplies fields/values it does not supply.

2. ERROR: Hook send-count routing to AG3-086/AG3-095 is not genuine.

AG3-097 now correctly says adapter-side max-10 sends is in scope, but it routes the real-time 11th-send hook block to AG3-086/AG3-095 ([story.md](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:51), [story.md](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:60)). AG3-086 does not scope `llm_send`, `*_send`, or send-count enforcement; its scope is WebCallBudgetGuard, skill_usage_check, Prompt-Integrity, CCAG, TTL, and rule generalization ([story.md](T:/codebase/claude-agentkit3/stories/AG3-086-hook-guard-buildout/story.md:32)). AG3-095 explicitly says the `llm-discussion` Feindesign transport is AG3-097, and AG3-095 only owns catalog presence of the bundle. The AG3-097 `status.yaml` also does not list AG3-095 despite the story text calling it a hard prerequisite ([status.yaml](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/status.yaml:8)).

Required fix: route the hook block to a story whose actual scope includes `*_send`/`llm_send` PostToolUse send-count enforcement, or explicitly create/update that owner. Adapter-side 10-round enforcement can stay in AG3-097, but the FK-25 hook obligation must not be assigned to stories that do not deliver it.
