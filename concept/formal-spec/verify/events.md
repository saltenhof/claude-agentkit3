---
id: formal.verify.events
title: Verify Events
status: active
doc_kind: spec
context: verify
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
  - concept/technical-design/38_verify_feedback_und_doctreue_schleife.md
  - concept/technical-design/91_api_event_katalog.md
---

# Verify Events

Diese Events bilden den Verify-Pfad fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.verify.events
schema_version: 1
kind: event-set
context: verify
events:
  - id: verify.event.verify.started
    producer: verify
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - story_id
        - verify_context
  - id: verify.event.layer1.completed
    producer: verify
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - story_id
  - id: verify.event.layer2.completed
    producer: verify
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - story_id
  - id: verify.event.layer3.completed
    producer: verify
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - story_id
  - id: verify.event.policy.evaluated
    producer: verify
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - story_id
        - outcome
  - id: verify.event.verify.passed
    producer: verify
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - story_id
  - id: verify.event.verify.failed
    producer: verify
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - story_id
  - id: verify.event.verify.escalated
    producer: verify
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - story_id
        - escalation_reason
```
<!-- FORMAL-SPEC:END -->
