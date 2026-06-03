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
  - id: deterministic-checks.command.run-tests-green-floor
    signature: internal run_tests_green_floor <gate_id>
    # FAST-ONLY terminal floor (FK-24 §24.3.4, FK-27 §27.6a): under mode fast
    # QA Layers 2-4 — including the Policy Engine (Layer 4) — are OUT. The only
    # check is the Layer-1 tests-green floor; a green floor reaches the terminal
    # `passed` DIRECTLY (tests_green_floor_passed -> passed) WITHOUT the policy
    # engine and WITHOUT a Sonar stage, while a failing floor reuses the
    # existing fail-closed edge stages_executed -> failed. This command never
    # emits a policy verdict; the closure-side "Sanity-Gate" (FK-29/FK-35) is a
    # CLOSURE term and is not produced here.
    allowed_statuses:
      - deterministic-checks.status.stages_executed
    requires:
      - deterministic-checks.invariant.sonarqube-fast-mode-not-applicable
      - deterministic-checks.invariant.fast-mode-terminates-via-tests-green-floor-without-policy
    emits:
      - deterministic-checks.event.tests-green-floor.passed
  - id: deterministic-checks.command.evaluate-policy
    signature: agentkit policy
    # The policy aggregator fires from exactly one applicability-resolved
    # entry status (FK-33 §33.6.5), and ONLY in the non-fast flows (under mode
    # fast the Policy Engine / Layer 4 is OUT, so this command never runs). For
    # an APPLICABLE Sonar flow that entry is sonarqube_gate_passed: the green
    # gate verdict gates the PASS (invariant.passed-requires-sonarqube-gate-passed).
    # For a NOT_APPLICABLE-but-non-fast gate (deliberately absent Sonar,
    # sonarqube.available false) the entry is sonarqube_gate_not_applicable —
    # policy aggregation STILL runs over the other layers, guarded by
    # invariant.passed-path-when-sonarqube-not-applicable. There is intentionally
    # NO sanity/fast entry here: mode fast does not aggregate policy at all and
    # terminates via run-tests-green-floor instead.
    # Every fail-closed branch (red gate, stale/unreadable attestation, an
    # already-failed prior layer, or a zero/multi-match exception ledger
    # reconciliation) reaches the terminal `failed` WITHOUT the policy engine,
    # and there is no stages_executed/attestation_read entry, so an APPLICABLE
    # PASS can be aggregated only after the green gate verdict status has
    # actually been reached. A deliberately absent Sonar (NOT_APPLICABLE) must
    # never be conflated with a configured-but-unreachable Sonar (available
    # true), which stays APPLICABLE and fails closed.
    allowed_statuses:
      - deterministic-checks.status.sonarqube_gate_passed
      - deterministic-checks.status.sonarqube_gate_not_applicable
    requires:
      - deterministic-checks.invariant.blocking-stage-failure-prevents-pass
      # APPLICABLE-only precondition: enforced only when the gate is APPLICABLE
      # (sonarqube.available true AND mode not fast). On the NOT_APPLICABLE
      # entry it is satisfied vacuously and the passed-path-when-... rule
      # governs instead.
      - deterministic-checks.invariant.passed-requires-sonarqube-gate-passed
      - deterministic-checks.invariant.passed-path-when-sonarqube-not-applicable
    emits:
      - deterministic-checks.event.policy.evaluated
```
<!-- FORMAL-SPEC:END -->
