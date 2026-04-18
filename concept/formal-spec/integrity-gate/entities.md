---
id: formal.integrity-gate.entities
title: Integrity Gate Entities
status: active
doc_kind: spec
context: integrity-gate
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Integrity Gate Entities

Das Integrity-Gate arbeitet auf einem geschlossenen Snapshot des
aktuellen gueltigen Runs.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integrity-gate.entities
schema_version: 1
kind: entity-set
context: integrity-gate
entities:
  - id: integrity-gate.entity.gate-run
    identity_key: gate_id
    attributes:
      - gate_id
      - project_key
      - story_id
      - run_id
      - status
  - id: integrity-gate.entity.gate-failure
    identity_key: failure_id
    attributes:
      - failure_id
      - gate_id
      - fail_code
      - phase
      - source
  - id: integrity-gate.entity.gate-override
    identity_key: override_id
    attributes:
      - override_id
      - gate_id
      - reason
      - actor
      - decided_at
```
<!-- FORMAL-SPEC:END -->
