---
id: formal.governance-observation.entities
title: Governance Observation Entities
status: active
doc_kind: spec
context: governance-observation
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Governance Observation Entities

Governance-Beobachtung arbeitet mit normalisierten Signalen und einem
Incident-Prozess ueber die Zeit.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.governance-observation.entities
schema_version: 1
kind: entity-set
context: governance-observation
entities:
  - id: governance-observation.entity.signal
    identity_key: signal_id
    attributes:
      - signal_id
      - source
      - signal_type
      - risk_points
      - story_id
  - id: governance-observation.entity.incident-candidate
    identity_key: incident_id
    attributes:
      - incident_id
      - story_id
      - run_id
      - risk_score
      - status
  - id: governance-observation.entity.adjudication
    identity_key: adjudication_id
    attributes:
      - adjudication_id
      - incident_id
      - severity
      - recommendation
  - id: governance-observation.entity.measure
    identity_key: measure_id
    attributes:
      - measure_id
      - incident_id
      - action
      - resulting_status
```
<!-- FORMAL-SPEC:END -->
