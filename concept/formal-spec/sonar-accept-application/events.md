---
id: formal.sonar-accept-application.events
title: Sonar Accept Application Events
status: active
doc_kind: spec
context: sonar-accept-application
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
---

# Sonar Accept Application Events

Diese Events bilden den synchronen Accept-Self-Assessment-Pfad ab: Antrag,
Akzeptanz mit Ledger-Eintrag oder Ablehnung mit sofortigem Feedback an den
Worker.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.sonar-accept-application.events
schema_version: 1
kind: event-set
context: sonar-accept-application
events:
  - id: sonar-accept-application.event.application-requested
    producer: worker
    role: lifecycle
    payload:
      required:
        - story_id
        - rule_key
        - file_path
        - rationale
  - id: sonar-accept-application.event.accepted
    producer: ak3
    role: lifecycle
    payload:
      required:
        - story_id
        - rule_key
        - ledger_entry_id
  - id: sonar-accept-application.event.rejected
    producer: ak3
    role: lifecycle
    payload:
      required:
        - story_id
        - rule_key
        - feedback_reasonings
```
<!-- FORMAL-SPEC:END -->
