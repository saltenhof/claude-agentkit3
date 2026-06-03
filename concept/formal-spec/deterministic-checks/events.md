---
id: formal.deterministic-checks.events
title: Deterministic Checks Events
status: active
doc_kind: spec
context: deterministic-checks
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/91_api_event_katalog.md
---

# Deterministic Checks Events

Diese Events bilden Registry-Planung und Policy-Entscheidung fachlich
ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.deterministic-checks.events
schema_version: 1
kind: event-set
context: deterministic-checks
events:
  - id: deterministic-checks.event.stage-plan.materialized
    producer: stage-registry
    role: lifecycle
    payload:
      required:
        - gate_id
        - flow_id
        - stage_ids
  - id: deterministic-checks.event.stage.executed
    producer: deterministic-checks
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - stage_id
  - id: deterministic-checks.event.stage.failed
    producer: deterministic-checks
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - stage_id
        - failure_reason
  - id: deterministic-checks.event.policy.evaluated
    producer: policy-engine
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - outcome
        - blocking_stage_ids
  # FAST-ONLY (FK-24 §24.3.4, FK-27 §27.6a): the Layer-1 tests-green floor
  # verdict under mode fast. It carries NO policy aggregation (Layer 4 is OUT)
  # and is the only QA-subflow event on the fast terminal path.
  - id: deterministic-checks.event.tests-green-floor.passed
    producer: deterministic-checks
    role: verdict
    payload:
      required:
        - qa_cycle_id
  - id: deterministic-checks.event.sonar-attestation.read
    producer: qa-sonarqube-gate
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - analysis_id
      references:
        # read-attestation materializes the commit-bound attestation for the
        # gate to verdict on. It is a lifecycle (read) event, NOT a verdict;
        # only run-sonarqube-gate emits the passed/failed verdict.
        - entity: deterministic-checks.entity.sonar-attestation
          by: analysis_id
  - id: deterministic-checks.event.sonarqube-gate.passed
    producer: qa-sonarqube-gate
    role: verdict
    payload:
      required:
        - qa_cycle_id
        - analysis_id
      references:
        # Canonical attestation payload is the sonar-attestation entity
        # (commit_sha, tree_hash, ce_task_id, quality_gate_status,
        # quality_gate_hash, quality_profile_hash, analysis_scope_hash,
        # new_code_definition, exception_ledger_hash, last_analyzed_revision,
        # sonarqube_version, branch_plugin_version, scanner_version, status;
        # FK-27 §27.6a.3, FK-33 §33.6.3). The event carries it by
        # reference (analysis_id is the identity key) rather than
        # duplicating or partially listing the fields.
        - entity: deterministic-checks.entity.sonar-attestation
          by: analysis_id
  - id: deterministic-checks.event.sonarqube-gate.failed
    producer: qa-sonarqube-gate
    role: verdict
    payload:
      required:
        - qa_cycle_id
        - analysis_id
        - failure_reason
```
<!-- FORMAL-SPEC:END -->
