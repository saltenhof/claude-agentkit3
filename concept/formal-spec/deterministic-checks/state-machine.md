---
id: formal.deterministic-checks.state-machine
title: Deterministic Checks State Machine
status: active
doc_kind: spec
context: deterministic-checks
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
---

# Deterministic Checks State Machine

Stage-Registry und Policy-Engine bilden zusammen einen kleinen Plan-
und Aggregationsprozess.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.deterministic-checks.state-machine
schema_version: 1
kind: state-machine
context: deterministic-checks
states:
  - id: deterministic-checks.status.requested
    initial: true
  - id: deterministic-checks.status.plan_materialized
  - id: deterministic-checks.status.stages_executed
  # SonarQube-Green-Gate (FK-27 §27.6a, FK-33 §33.6.3): the gate is
  # sequenced after the adversarial layer (stages_executed) and reads a
  # commit-bound attestation before the policy engine aggregates. The
  # attestation must EXIST (be read by analysisId/ceTaskId) before the
  # gate verdict, so the read step is its own status.
  - id: deterministic-checks.status.attestation_read
  - id: deterministic-checks.status.sonarqube_gate_passed
  - id: deterministic-checks.status.policy_evaluated
  - id: deterministic-checks.status.passed
    terminal: true
  - id: deterministic-checks.status.failed
    terminal: true
transitions:
  - id: deterministic-checks.transition.requested_to_plan_materialized
    from: deterministic-checks.status.requested
    to: deterministic-checks.status.plan_materialized
    guard: deterministic-checks.invariant.stage-plan-derived-from-registry
  - id: deterministic-checks.transition.plan_materialized_to_stages_executed
    from: deterministic-checks.status.plan_materialized
    to: deterministic-checks.status.stages_executed
    guard: deterministic-checks.invariant.only-applicable-stages-execute
  # SonarQube-gate read/verdict edges. read-attestation materializes the
  # commit-bound attestation; run-sonarqube-gate turns it into a green
  # verdict or fails closed into remediation (status.failed directly).
  - id: deterministic-checks.transition.stages_executed_to_attestation_read
    from: deterministic-checks.status.stages_executed
    to: deterministic-checks.status.attestation_read
    guard: deterministic-checks.invariant.sonarqube-gate-read-by-analysis-id
  - id: deterministic-checks.transition.attestation_read_to_sonarqube_gate_passed
    from: deterministic-checks.status.attestation_read
    to: deterministic-checks.status.sonarqube_gate_passed
    guard: deterministic-checks.invariant.sonarqube-green-requires-overall-code-zero-issues
  # UNBYPASSABLE GATE (FK-27 §27.6a, FK-33 §33.6.3): policy_evaluated — and
  # therefore the terminal `passed` — is reachable ONLY from
  # sonarqube_gate_passed. There is intentionally NO direct
  # stages_executed -> sonarqube_gate_passed edge and NO
  # stages_executed -> policy_evaluated / attestation_read -> policy_evaluated
  # edge. The single green-capable path is
  #   stages_executed -> attestation_read -> sonarqube_gate_passed
  #                   -> policy_evaluated -> passed.
  # Every fail-closed branch (a red gate, a stale/unreadable attestation, an
  # already-failed prior layer, or a zero/multi-match exception ledger
  # reconciliation) routes directly into the terminal `failed` and NEVER
  # through policy_evaluated, so the policy aggregator can solve a PASS only
  # after the gate verdict status sonarqube_gate_passed has actually been
  # reached. See invariant.passed-requires-sonarqube-gate-passed.
  - id: deterministic-checks.transition.sonarqube_gate_passed_to_policy_evaluated
    from: deterministic-checks.status.sonarqube_gate_passed
    to: deterministic-checks.status.policy_evaluated
  - id: deterministic-checks.transition.stages_executed_to_failed
    from: deterministic-checks.status.stages_executed
    to: deterministic-checks.status.failed
  - id: deterministic-checks.transition.attestation_read_to_failed
    from: deterministic-checks.status.attestation_read
    to: deterministic-checks.status.failed
  - id: deterministic-checks.transition.policy_evaluated_to_passed
    from: deterministic-checks.status.policy_evaluated
    to: deterministic-checks.status.passed
    guard: deterministic-checks.invariant.blocking-stage-failure-prevents-pass
  - id: deterministic-checks.transition.policy_evaluated_to_failed
    from: deterministic-checks.status.policy_evaluated
    to: deterministic-checks.status.failed
compound_rules:
  - id: deterministic-checks.rule.failure-corpus-enters-via-registry
    description: Promoted checks from the Failure Corpus become active only through StageRegistry materialization, not by direct hardcoding in Verify.
```
<!-- FORMAL-SPEC:END -->
