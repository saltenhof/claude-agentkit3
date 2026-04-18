---
id: formal.escalation.entities
title: Escalation Entities
status: active
doc_kind: spec
context: escalation
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Escalation Entities

Eskalation arbeitet auf dem aktuellen Story-Run und modelliert nur
den offiziellen menschlichen Aufloesungspfad.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.escalation.entities
schema_version: 1
kind: entity-set
context: escalation
entities:
  - id: escalation.entity.case
    identity_key: escalation_id
    attributes:
      - escalation_id
      - story_id
      - run_id
      - trigger
      - status
  - id: escalation.entity.intervention
    identity_key: intervention_id
    attributes:
      - intervention_id
      - escalation_id
      - actor
      - action
      - reason
```
<!-- FORMAL-SPEC:END -->
