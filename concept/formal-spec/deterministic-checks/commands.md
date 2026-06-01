---
id: formal.deterministic-checks.commands
title: Deterministic Checks Commands
status: active
doc_kind: spec
context: deterministic-checks
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
  - concept/technical-design/91_api_event_katalog.md
---

# Deterministic Checks Commands

Registry und Policy werden nur ueber den offiziellen Verify-Pfad
materialisiert und ausgewertet.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.deterministic-checks.commands
schema_version: 1
kind: command-set
context: deterministic-checks
commands:
  - id: deterministic-checks.command.materialize-stage-plan
    signature: internal materialize_stage_plan <story_type> <gate_id>
    allowed_statuses:
      - deterministic-checks.status.requested
    requires:
      - deterministic-checks.invariant.stage-plan-derived-from-registry
    emits:
      - deterministic-checks.event.stage-plan.materialized
  - id: deterministic-checks.command.execute-deterministic-stages
    signature: internal execute_deterministic_stages <gate_id>
    allowed_statuses:
      - deterministic-checks.status.plan_materialized
    requires:
      - deterministic-checks.invariant.only-applicable-stages-execute
    emits:
      - deterministic-checks.event.stage.executed
      - deterministic-checks.event.stage.failed
  - id: deterministic-checks.command.run-sonarqube-gate
    signature: internal run_sonarqube_gate <gate_id> <scan_target>
    # A Sonar verdict can only be produced AFTER the commit-bound
    # attestation has been read (status.attestation_read). There is no
    # green shortcut directly from stages_executed; both the green and the
    # red verdict are reached through attestation_read.
    allowed_statuses:
      - deterministic-checks.status.attestation_read
    requires:
      - deterministic-checks.invariant.sonarqube-gate-sequenced-after-adversarial
      - deterministic-checks.invariant.sonarqube-green-requires-overall-code-zero-issues
      - deterministic-checks.invariant.sonarqube-gate-read-by-analysis-id
    emits:
      - deterministic-checks.event.sonarqube-gate.passed
      - deterministic-checks.event.sonarqube-gate.failed
  - id: deterministic-checks.command.read-attestation
    signature: internal read_sonar_attestation <analysis_id>
    allowed_statuses:
      - deterministic-checks.status.stages_executed
    requires:
      - deterministic-checks.invariant.sonarqube-gate-read-by-analysis-id
    # read-attestation only MATERIALIZES the commit-bound attestation
    # (status.attestation_read). It does NOT decide the gate verdict, so it
    # must NOT emit sonarqube-gate.passed/failed — only run-sonarqube-gate
    # (the qa-sonarqube-gate producer) emits a verdict. Emitting a green
    # verdict here was the bypass that let a PASS skip the actual gate.
    emits:
      - deterministic-checks.event.sonar-attestation.read
  - id: deterministic-checks.command.apply-exception-ledger
    signature: internal apply_exception_ledger <gate_id> <scan_target>
    allowed_statuses:
      - deterministic-checks.status.stages_executed
    requires:
      - deterministic-checks.invariant.ledger-application-single-match-or-fail-closed
    # The ledger reconciler is fail-closed: a zero/multi-match reconciliation
    # routes stages_executed -> failed directly. It never produces a green
    # gate verdict on its own, so it emits ONLY the failed verdict.
    emits:
      - deterministic-checks.event.sonarqube-gate.failed
  - id: deterministic-checks.command.evaluate-policy
    signature: agentkit policy
    # The policy aggregator may fire ONLY from sonarqube_gate_passed. Every
    # fail-closed branch reaches the terminal `failed` without the policy
    # engine, and there is no stages_executed/attestation_read entry, so a
    # PASS can be aggregated only after the green gate verdict status has
    # actually been reached (invariant.passed-requires-sonarqube-gate-passed).
    allowed_statuses:
      - deterministic-checks.status.sonarqube_gate_passed
    requires:
      - deterministic-checks.invariant.blocking-stage-failure-prevents-pass
      - deterministic-checks.invariant.passed-requires-sonarqube-gate-passed
    emits:
      - deterministic-checks.event.policy.evaluated
```
<!-- FORMAL-SPEC:END -->
