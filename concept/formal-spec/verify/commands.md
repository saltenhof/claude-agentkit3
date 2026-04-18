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
  - concept/technical-design/91_api_event_katalog.md
---

# Verify Commands

Verify laeuft ueber den offiziellen Phase-Runner-Pfad.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.verify.commands
schema_version: 1
kind: command-set
context: verify
commands:
  - id: verify.command.run-phase
    signature: agentkit run-phase verify --story <story_id>
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
