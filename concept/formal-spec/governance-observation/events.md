---
id: formal.governance-observation.events
title: Governance Observation Events
status: active
doc_kind: spec
context: governance-observation
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Governance Observation Events

Diese Events bilden den Incident-Prozess der Governance-Beobachtung
ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.governance-observation.events
schema_version: 1
kind: event-set
context: governance-observation
events:
  - id: governance-observation.event.signal.ingested
    producer: governance-observation
    role: lifecycle
    payload:
      required:
        - signal_id
        - signal_type
        - risk_points
  - id: governance-observation.event.incident_candidate.opened
    producer: governance-observation
    role: lifecycle
    payload:
      required:
        - incident_id
        - story_id
        - risk_score
  - id: governance-observation.event.adjudication.completed
    producer: governance-observation
    role: verdict
    payload:
      required:
        - incident_id
        - severity
        - recommendation
  - id: governance-observation.event.measure.applied
    producer: governance-observation
    role: governance
    payload:
      required:
        - incident_id
        - action
        - resulting_status
```
<!-- FORMAL-SPEC:END -->
