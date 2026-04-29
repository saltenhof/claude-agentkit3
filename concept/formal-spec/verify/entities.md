---
id: formal.verify.entities
title: Verify Entities
status: active
doc_kind: spec
context: verify
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
  - concept/technical-design/39_phase_state_persistenz.md
---

# Verify Entities

Verify benoetigt wenige fachlich stabile Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.verify.entities
schema_version: 1
kind: entity-set
context: verify
entities:
  - id: verify.entity.attempt
    identity_key: qa_cycle_id
    attributes:
      - qa_cycle_id
      - qa_cycle_round
      - story_id
      - verify_context
      - status
  - id: verify.entity.finding
    identity_key: finding_id
    attributes:
      - finding_id
      - source
      - severity
      - blocking
      - message
  - id: verify.entity.decision
    identity_key: qa_cycle_id
    attributes:
      - qa_cycle_id
      - outcome
      - blocking_sources
      - evidence_fingerprint
```
<!-- FORMAL-SPEC:END -->
