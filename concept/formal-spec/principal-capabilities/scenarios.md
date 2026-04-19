---
id: formal.principal-capabilities.scenarios
title: Principal Capability Scenarios
status: active
doc_kind: spec
context: principal-capabilities
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/55_principal_capability_model_story_scope_enforcement.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Principal Capability Scenarios

Diese Traces pruefen, dass Schreibrechte nicht nur rollenbezogen,
sondern technisch story- und pfadklassenscharf erzwungen werden.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.principal-capabilities.scenarios
schema_version: 1
kind: scenario-set
context: principal-capabilities
scenarios:
  - id: principal-capabilities.scenario.worker-may-write-inside-story-scope
    start:
      status: principal-capabilities.status.story_scoped
    trace:
      - command: principal-capabilities.command.resolve-capability-context
      - command: principal-capabilities.command.evaluate-principal-operation
    expected_end:
      status: principal-capabilities.status.released
    requires:
      - principal-capabilities.invariant.story_scoped_writers_may_not_escape_story_scope
  - id: principal-capabilities.scenario.adversarial-writer-blocked-outside-sandbox
    start:
      status: principal-capabilities.status.story_scoped
    trace:
      - command: principal-capabilities.command.resolve-capability-context
      - command: principal-capabilities.command.evaluate-principal-operation
    expected_end:
      status: principal-capabilities.status.denied
    requires:
      - principal-capabilities.invariant.adversarial_writer_is_sandbox_only
  - id: principal-capabilities.scenario.normative-conflict-freeze-blocks-orchestrator-mutation
    start:
      status: principal-capabilities.status.story_scoped
    trace:
      - command: principal-capabilities.command.activate-conflict-freeze
      - command: principal-capabilities.command.evaluate-principal-operation
    expected_end:
      status: principal-capabilities.status.denied
    requires:
      - principal-capabilities.invariant.freeze_removes_orchestrator_mutation_rights
      - principal-capabilities.invariant.same_run_keeps_same_authority_basis
  - id: principal-capabilities.scenario.freeze-allows-official-resolution-path
    start:
      status: principal-capabilities.status.frozen
    trace:
      - command: principal-capabilities.command.resolve-conflict
    expected_end:
      status: principal-capabilities.status.released
    requires:
      - principal-capabilities.invariant.only_official_service_or_human_cli_may_mutate_during_freeze
  - id: principal-capabilities.scenario.unknown-permission-opens-request-and-expires
    start:
      status: principal-capabilities.status.story_scoped
    trace:
      - command: principal-capabilities.command.open-permission-request
      - command: principal-capabilities.command.expire-permission-request
    expected_end:
      status: principal-capabilities.status.denied
    requires:
      - principal-capabilities.invariant.no_native_prompt_during_story_lock
      - principal-capabilities.invariant.run_progress_not_dependent_on_external_permission_ui
  - id: principal-capabilities.scenario.permission-request-approved-via-lease
    start:
      status: principal-capabilities.status.story_scoped
    trace:
      - command: principal-capabilities.command.open-permission-request
      - command: principal-capabilities.command.approve-permission-request
    expected_end:
      status: principal-capabilities.status.released
    requires:
      - principal-capabilities.invariant.permission_leases_are_scoped_and_expiring
```
<!-- FORMAL-SPEC:END -->
