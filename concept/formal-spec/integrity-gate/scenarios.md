---
id: formal.integrity-gate.scenarios
title: Integrity Gate Scenarios
status: active
doc_kind: spec
context: integrity-gate
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Integrity Gate Scenarios

Diese Traces pruefen die regulaeren Gate-Ausgaenge vor Closure.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integrity-gate.scenarios
schema_version: 1
kind: scenario-set
context: integrity-gate
scenarios:
  - id: integrity-gate.scenario.full-pass
    start:
      status: integrity-gate.status.open
    trace:
      - command: integrity-gate.command.run-gate
    expected_end:
      status: integrity-gate.status.passed
    requires:
      - integrity-gate.invariant.mandatory_artifacts_checked_first
      - integrity-gate.invariant.only_current_valid_run_is_evaluated
  - id: integrity-gate.scenario.missing-mandatory-artifact
    start:
      status: integrity-gate.status.open
    trace:
      - command: integrity-gate.command.run-gate
    expected_end:
      status: integrity-gate.status.failed
    requires:
      - integrity-gate.invariant.mandatory_artifacts_checked_first
      - integrity-gate.invariant.gate_failures_are_auditable
  - id: integrity-gate.scenario.explicit-human-override
    start:
      status: integrity-gate.status.failed
    trace:
      - command: integrity-gate.command.override-gate
    expected_end:
      status: integrity-gate.status.overridden
    requires:
      - integrity-gate.invariant.override_requires_explicit_human_reason
  - id: integrity-gate.scenario.dimension9-missing-attestation-fails
    start:
      status: integrity-gate.status.open
    trace:
      - command: integrity-gate.command.run-gate
    expected_end:
      status: integrity-gate.status.failed
    requires:
      - integrity-gate.invariant.dimension9_verifies_attestation_never_rescans
      - integrity-gate.invariant.gate_failures_are_auditable
  - id: integrity-gate.scenario.dimension9-tree-hash-drift-fails
    start:
      status: integrity-gate.status.open
    trace:
      - command: integrity-gate.command.run-gate
    expected_end:
      status: integrity-gate.status.failed
    requires:
      - integrity-gate.invariant.dimension9_attestation_binds_to_merge_state
  - id: integrity-gate.scenario.dimension9-quality-gate-red-on-overall-code-fails
    start:
      status: integrity-gate.status.open
    trace:
      - command: integrity-gate.command.run-gate
    expected_end:
      status: integrity-gate.status.failed
    requires:
      - integrity-gate.invariant.dimension9_attestation_binds_to_merge_state
  - id: integrity-gate.scenario.dimension9-ledger-hash-mismatch-fails
    start:
      status: integrity-gate.status.open
    trace:
      - command: integrity-gate.command.run-gate
    expected_end:
      status: integrity-gate.status.failed
    requires:
      - integrity-gate.invariant.dimension9_requires_ledger_and_version_match
  - id: integrity-gate.scenario.dimension9-tool-config-version-mismatch-fails
    start:
      status: integrity-gate.status.open
    trace:
      - command: integrity-gate.command.run-gate
    expected_end:
      status: integrity-gate.status.failed
    requires:
      - integrity-gate.invariant.dimension9_requires_ledger_and_version_match
  - id: integrity-gate.scenario.dimension9-skipped-for-concept-research
    start:
      status: integrity-gate.status.open
    trace:
      - command: integrity-gate.command.run-gate
    expected_end:
      status: integrity-gate.status.passed
    requires:
      - integrity-gate.invariant.dimension9_applies_to_code_stories_only
```
<!-- FORMAL-SPEC:END -->
