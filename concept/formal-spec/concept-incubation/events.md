---
id: formal.concept-incubation.events
title: Concept Incubation Events
status: active
doc_kind: spec
context: concept-incubation
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/78_concept_incubation_process.md
---

# Concept Incubation Events

Events der Lauf-Chronik. Persistenz: `RUN.json`-Zustandsuebergaenge plus
append-only `journal.md`; es gibt in v1 keinen Backend-Event-Bus.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.concept-incubation.events
schema_version: 1
kind: event-set
context: concept-incubation
events:
  - id: concept-incubation.event.run.created
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - profile
  - id: concept-incubation.event.lease.acquired
    producer: concept-incubation
    role: coordination
    payload:
      required:
        - run_id
        - owner_principal_id
        - fencing_token
  - id: concept-incubation.event.lease.taken-over
    producer: concept-incubation
    role: coordination
    payload:
      required:
        - run_id
        - owner_principal_id
        - fencing_token
  - id: concept-incubation.event.baseline.frozen
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - base_revision
        - corpus_baseline_digest
  - id: concept-incubation.event.staffing.approved
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - participant_ids
  - id: concept-incubation.event.round.dispatched
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - round
        - participant_ids
  - id: concept-incubation.event.round.sealed
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - round
        - sealed_proposal_digests
  - id: concept-incubation.event.input-sources.frozen
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - source_register_digest
        - source_units_digest
  - id: concept-incubation.event.claims.inventory-closed
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - claims_inventory_digest
  - id: concept-incubation.event.synthesis.recorded
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - synthesis_digest
  - id: concept-incubation.event.decisions.recorded
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - po_decision_source_ids
  - id: concept-incubation.event.scope-lock.acquired
    producer: concept-incubation
    role: coordination
    payload:
      required:
        - run_id
        - scope_id
        - fencing_token
  - id: concept-incubation.event.promotion.started
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - scope_ids
  - id: concept-incubation.event.promotion.check-failed
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - finding_ids
  - id: concept-incubation.event.promotion.retried
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - resolved_finding_ids
  - id: concept-incubation.event.scope-lock.released
    producer: concept-incubation
    role: coordination
    payload:
      required:
        - run_id
        - scope_id
        - fencing_token
  - id: concept-incubation.event.promotion.completed
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - promotion_manifest_digest
  - id: concept-incubation.event.run.blocked
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - reason
        - since_state
  - id: concept-incubation.event.run.resumed
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - restored_state
  - id: concept-incubation.event.recheck.adjudicated
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - drifted_paths
        - resolution
  - id: concept-incubation.event.run.aborted
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
        - reason
  - id: concept-incubation.event.run.closed
    producer: concept-incubation
    role: lifecycle
    payload:
      required:
        - run_id
```
<!-- FORMAL-SPEC:END -->
