OVERALL: CHANGES-REQUESTED

**Per-Dimension**
- Konzept-Vollstaendigkeit: FAIL
- AC-Schaerfe: WEAK
- Klarheit/Eindeutigkeit: FAIL
- Kontext-Sinnhaftigkeit: FAIL

**Remaining Must-Fix ERROR**

1. **R1 ERROR 2 is not genuinely resolved.**  
   FK-48 requires mandatory targets from `assertion_weakness` findings with `addressed_part` and `extract_mandatory_targets` plus the prompt section ([FK-48](T:/codebase/claude-agentkit3/concept/technical-design/48_adversarial_testing_runtime.md:279), [FK-48](T:/codebase/claude-agentkit3/concept/technical-design/48_adversarial_testing_runtime.md:318), [FK-48](T:/codebase/claude-agentkit3/concept/technical-design/48_adversarial_testing_runtime.md:353)). The story now routes that to AG3-067/AG3-064 ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:52), [story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:99)), but `status.yaml` still only depends on AG3-044 and AG3-065 ([status.yaml](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/status.yaml:8)). AG3-067 itself only consumes `mandatory_target_results`; it does not own `assertion_weakness`/`addressed_part` extraction ([AG3-067 story.md](T:/codebase/claude-agentkit3/stories/AG3-067-context-sufficiency-packing-feedback-fidelity/story.md:34), [AG3-067 story.md](T:/codebase/claude-agentkit3/stories/AG3-067-context-sufficiency-packing-feedback-fidelity/story.md:41)). Real code still derives from every `Severity.BLOCKING` finding and has no `addressed_part` ([spawn.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/adversarial_orchestrator/spawn.py:127), [spawn.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/adversarial_orchestrator/spawn.py:147)).  
   **Fix:** either make AG3-079 own FK-48 §48.2.2/§48.2.3, or add real hard predecessor ownership in story and `status.yaml`, and update that predecessor to explicitly deliver `assertion_weakness`, `addressed_part`, `extract_mandatory_targets`, and the prompt section before AG3-079 can consume it.

2. **New anchor issue.**  
   Sub-agent guidance cites `_dimension_specs.py:37,83-90` for “Dim `NO_ADVERSARIAL`, SSOT-Konstanten” ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:94)). `NO_ADVERSARIAL` is line 37, but producer/stage constants are imported at lines 15-17 and re-exported at 111-114; lines 83-90 are code-only dimension tables ([ _dimension_specs.py](T:/codebase/claude-agentkit3/src/agentkit/governance/integrity_gate/_dimension_specs.py:15)).  
   **Fix:** correct that anchor to the actual constant/import/re-export lines, or point implementers to `qa_artifact_names.py:77,90`.

R1 producer, `llm_call`, sandbox `{epoch}`, and the main old Ist-Zustand anchors are otherwise materially corrected.
