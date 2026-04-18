---
id: formal.conformance.events
title: Conformance Events
status: active
doc_kind: spec
context: conformance
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/32_dokumententreue_conformance_service.md
  - concept/technical-design/91_api_event_katalog.md
---

# Conformance Events

Diese Events bilden den normativen Bewertungsprozess fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.conformance.events
schema_version: 1
kind: event-set
context: conformance
events:
  - id: conformance.event.assessment.started
    producer: conformance
    role: lifecycle
    payload:
      required:
        - assessment_id
        - level
        - story_id
        - run_id
  - id: conformance.event.level.evaluated
    producer: conformance
    role: verdict
    payload:
      required:
        - assessment_id
        - level
        - status
        - reason
  - id: conformance.event.assessment.completed
    producer: conformance
    role: lifecycle
    payload:
      required:
        - assessment_id
        - level
        - status
        - references_used
```
<!-- FORMAL-SPEC:END -->
