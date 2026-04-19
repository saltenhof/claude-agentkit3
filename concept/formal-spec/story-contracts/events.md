---
id: formal.story-contracts.events
title: Story Contract Events
status: active
doc_kind: spec
context: story-contracts
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/59_story_contract_axes_and_combination_matrix.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Contract Events

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-contracts.events
schema_version: 1
kind: event-set
context: story-contracts
events:
  - id: story-contracts.event.story_contract_classified
    role: lifecycle
  - id: story-contracts.event.runtime_classification_derived
    role: lifecycle
  - id: story-contracts.event.story_marked_done
    role: lifecycle
  - id: story-contracts.event.story_cancelled_administratively
    role: lifecycle
  - id: story-contracts.event.invalid_contract_combination_detected
    role: audit
```
<!-- FORMAL-SPEC:END -->

