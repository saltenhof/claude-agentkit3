---
id: formal.llm-evaluations.events
title: LLM Evaluations Events
status: active
doc_kind: spec
context: llm-evaluations
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/48_adversarial_testing_runtime.md
  - concept/technical-design/91_api_event_katalog.md
---

# LLM Evaluations Events

Diese Events bilden den Evidence-Prozess von Layer 2 und Layer 3 ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.llm-evaluations.events
schema_version: 1
kind: event-set
context: llm-evaluations
events:
  - id: llm-evaluations.event.layer2.started
    producer: llm-evaluations
    role: lifecycle
    payload:
      required:
        - batch_id
        - story_id
        - run_id
  - id: llm-evaluations.event.layer2.completed
    producer: llm-evaluations
    role: lifecycle
    payload:
      required:
        - batch_id
        - status
        - blocking_failures
  - id: llm-evaluations.event.layer2.aggregated
    producer: llm-evaluations
    role: verdict
    payload:
      required:
        - batch_id
        - divergence_status
        - concern_count
  - id: llm-evaluations.event.adversarial.started
    producer: llm-evaluations
    role: lifecycle
    payload:
      required:
        - adversarial_id
        - sandbox_path
  - id: llm-evaluations.event.adversarial.completed
    producer: llm-evaluations
    role: lifecycle
    payload:
      required:
        - adversarial_id
        - status
        - executed_test_count
        - sparring_count
```
<!-- FORMAL-SPEC:END -->
