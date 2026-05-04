---
id: formal.verify.commands
title: Verify Commands
status: active
doc_kind: spec
context: verify
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
  - concept/technical-design/38_verify_feedback_und_doctreue_schleife.md
  - concept/technical-design/91_api_event_katalog.md
---

# Verify Commands

Verify ist eine Capability und keine Top-Phase. Es gibt keinen
`agentkit run-phase verify`-Aufruf. Der QA-Subflow wird intern aus
der aufrufenden Phase (Exploration-Exit-Gate, Implementation-QA-Subflow)
ueber den Capability-Vertrag `run_qa_subflow` ausgeloest.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.verify.commands
schema_version: 1
kind: command-set
context: verify
commands:
  - id: verify.command.run-qa-subflow
    signature: VerifySystem.run_qa_subflow(story_id, qa_context, target) -> PolicyVerdict
    allowed_statuses:
      - verify.status.pending
    requires:
      - verify.invariant.verify_context_required
      - verify.invariant.full_qa_required_for_both_contexts
    emits:
      - verify.event.verify.started
      - verify.event.layer1.completed
      - verify.event.layer2.completed
      - verify.event.layer3.completed
      - verify.event.policy.evaluated
      - verify.event.verify.passed
      - verify.event.verify.failed
      - verify.event.verify.escalated
```
<!-- FORMAL-SPEC:END -->
