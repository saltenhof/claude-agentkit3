---
id: formal.concept-incubation.entities
title: Concept Incubation Entities
status: active
doc_kind: spec
context: concept-incubation
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/78_concept_incubation_process.md
---

# Concept Incubation Entities

Kernentitaeten des Inkubationslaufs und der verlustfreien Promotionskette.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.concept-incubation.entities
schema_version: 1
kind: entity-set
context: concept-incubation
entities:
  - id: concept-incubation.entity.incubation-run
    identity_key: run_id
    attributes:
      - run_id
      - profile
      - state
      - state_revision
      - lease_fencing_token
      - current_round
      - base_revision
      - data_class
      - register_digests
      - last_completed_action
      - next_action
  - id: concept-incubation.entity.participant
    identity_key: participant_id
    attributes:
      - participant_id
      - run_id
      - model
      - backend
      - spawn_mode
      - principal_id
      - session_ref
      - data_release
      - status
  - id: concept-incubation.entity.writer-lease
    identity_key: run_id
    attributes:
      - run_id
      - owner_principal_id
      - owner_session_ref
      - fencing_token
      - acquired_at
      - ttl_seconds
      - released
  - id: concept-incubation.entity.mutation-mutex
    identity_key: run_id
    attributes:
      - run_id
      - owner_principal_id
      - owner_session_ref
      - nonce
      - acquired_at
      - heartbeat_at
      - ttl_seconds
  - id: concept-incubation.entity.artifact-record
    identity_key: path
    attributes:
      - path
      - sha256
      - artifact_kind
      - input_refs
      - declared_class
      - effective_class
      - vcs_disposition
      - declassification_receipt
  - id: concept-incubation.entity.declassification-receipt
    identity_key: receipt_id
    attributes:
      - receipt_id
      - source_path
      - source_digest
      - output_path
      - output_digest
      - rules_applied
      - target_class
      - approved_by_principal
      - approved_at
  - id: concept-incubation.entity.scope-lock
    identity_key: scope_id
    attributes:
      - scope_id
      - locked_by_run
      - fencing_token
      - backend
      - acquired_at
      - ttl_seconds
  - id: concept-incubation.entity.round
    identity_key: round_key
    attributes:
      - run_id
      - round
      - sealed
      - sealed_proposal_digests
      - participant_outcomes
  - id: concept-incubation.entity.source-record
    identity_key: source_id
    attributes:
      - source_id
      - run_id
      - source_phase
      - role
      - path
      - sha256
      - author_principal_id
      - genealogy_parents
  - id: concept-incubation.entity.source-unit
    identity_key: unit_id
    attributes:
      - unit_id
      - source_id
      - unit_locator
      - unit_digest
      - claim_refs
      - empty_reason
  - id: concept-incubation.entity.claim
    identity_key: claim_id
    attributes:
      - claim_id
      - source_id
      - unit_refs
      - statement
      - qualifiers
      - synthesis_disposition
      - residual_edge
      - atom_refs
  - id: concept-incubation.entity.atom-record
    identity_key: atom_id
    attributes:
      - atom_id
      - statement
      - atom_type
      - normative_status
      - expected_authority
      - target_refs
      - disposition
      - claim_refs
      - receipt_refs
  - id: concept-incubation.entity.projection-receipt
    identity_key: receipt_id
    attributes:
      - receipt_id
      - atom_id
      - target_path
      - target_anchor
      - source_digest
      - target_section_digest
      - writer_principal_id
      - writer_session_ref
      - reviewer_principal_id
      - reviewer_session_ref
      - verdict
  - id: concept-incubation.entity.promotion-manifest
    identity_key: run_id
    attributes:
      - run_id
      - base_revision
      - scopes
      - required_sets
      - targets
      - scope_locks
      - semantic_gates
  - id: concept-incubation.entity.incubation-finding
    identity_key: finding_id
    attributes:
      - finding_id
      - severity
      - status
      - path
      - locator
      - statement
      - resolution
```
<!-- FORMAL-SPEC:END -->
