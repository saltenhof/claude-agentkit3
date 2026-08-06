---
id: formal.principal-capabilities.commands
title: Principal Capability Commands
status: active
doc_kind: spec
context: principal-capabilities
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/55_principal_capability_model_story_scope_enforcement.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/91_api_event_katalog.md
---

# Principal Capability Commands

Diese Kommandos werden als Guard-/Service-Entscheidungen verstanden,
nicht als freie Benutzerbefehle.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.principal-capabilities.commands
schema_version: 1
kind: command-set
context: principal-capabilities
commands:
  - id: principal-capabilities.command.resolve-capability-context
    signature: internal classify principal tool operation path class and story scope
    allowed_statuses:
      - principal-capabilities.status.normal
      - principal-capabilities.status.story_scoped
      - principal-capabilities.status.frozen
    emits:
      - principal-capabilities.event.capability_context_resolved
  - id: principal-capabilities.command.evaluate-principal-operation
    signature: internal evaluate principal against path class operation class story scope and freeze overlay
    allowed_statuses:
      - principal-capabilities.status.normal
      - principal-capabilities.status.story_scoped
      - principal-capabilities.status.frozen
    requires:
      - principal-capabilities.invariant.hard_capability_denials_are_final
      - principal-capabilities.invariant.orchestrator_is_control_plane_only
    emits:
      - principal-capabilities.event.capability_allowed
      - principal-capabilities.event.capability_denied
  - id: principal-capabilities.command.activate-conflict-freeze
    signature: internal activate story-scoped conflict_freeze on authoritative divergence or normative conflict
    allowed_statuses:
      - principal-capabilities.status.story_scoped
    requires:
      - principal-capabilities.invariant.freeze_removes_orchestrator_mutation_rights
      - principal-capabilities.invariant.freeze_has_backend_record_and_local_export
    emits:
      - principal-capabilities.event.conflict_freeze_entered
  - id: principal-capabilities.command.execute-official-service-path
    signature: human operator CLI invokes <absolute-agentkit-wrapper> split-story|reset-story|cleanup|resolve-conflict through official service principal
    allowed_statuses:
      - principal-capabilities.status.frozen
      - principal-capabilities.status.story_scoped
    requires:
      - principal-capabilities.invariant.privileged_principals_require_attestation
      - principal-capabilities.invariant.only_official_service_or_human_cli_may_mutate_during_freeze
    emits:
      - principal-capabilities.event.official_service_path_entered
      - principal-capabilities.event.official_service_path_completed
  - id: principal-capabilities.command.resolve-conflict
    signature: human operator CLI invokes <absolute-agentkit-wrapper> resolve-conflict --story <story_id> --decision <decision> --reason <reason>
    allowed_statuses:
      - principal-capabilities.status.frozen
    requires:
      - principal-capabilities.invariant.privileged_principals_require_attestation
      - principal-capabilities.invariant.only_official_service_or_human_cli_may_mutate_during_freeze
      - principal-capabilities.invariant.same_run_keeps_same_authority_basis
    emits:
      - principal-capabilities.event.conflict_resolution_requested
      - principal-capabilities.event.conflict_resolution_applied
      - principal-capabilities.event.conflict_freeze_released
      - principal-capabilities.event.official_service_path_completed
```
<!-- FORMAL-SPEC:END -->
