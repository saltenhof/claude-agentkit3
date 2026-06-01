---
id: formal.integrity-gate.events
title: Integrity Gate Events
status: active
doc_kind: spec
context: integrity-gate
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Integrity Gate Events

Diese Events bilden den offiziellen Gate-Lauf vor Closure ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integrity-gate.events
schema_version: 1
kind: event-set
context: integrity-gate
events:
  - id: integrity-gate.event.gate.started
    producer: integrity-gate
    role: lifecycle
    payload:
      required:
        - gate_id
        - project_key
        - story_id
        - run_id
  - id: integrity-gate.event.gate.result
    producer: integrity-gate
    role: verdict
    payload:
      required:
        - gate_id
        - status
        - failed_codes
  - id: integrity-gate.event.gate.overridden
    producer: integrity-gate
    role: governance
    payload:
      required:
        - gate_id
        - override_id
        - reason
  - id: integrity-gate.event.gate.audit_queried
    producer: integrity-gate
    role: audit
    payload:
      required:
        - gate_id
        - actor
  - id: integrity-gate.event.dimension9.sonar_not_green
    producer: integrity-gate
    role: verdict
    payload:
      required:
        - gate_id
        - fail_code
        - reason
    notes: >
      fail_code is the constant SONAR_NOT_GREEN, the dimension-9 FAIL-code
      added alongside the existing dimension fail-codes (NO_QA_ARTIFACTS,
      CONTEXT_INVALID, STRUCTURAL_SHALLOW, DECISION_INVALID, NO_LLM_REVIEW,
      NO_ADVERSARIAL, NO_VERIFY, TIMESTAMP_INVERSION). It is emitted as part
      of gate.result.failed_codes and never re-scanned by the gate itself.
```
<!-- FORMAL-SPEC:END -->
