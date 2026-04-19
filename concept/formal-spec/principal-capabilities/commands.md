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
      - principal-capabilities.invariant.ccag_never_elevates_hard_capabilities
      - principal-capabilities.invariant.orchestrator_is_control_plane_only
    emits:
      - principal-capabilities.event.capability_allowed
      - principal-capabilities.event.capability_denied
  - id: principal-capabilities.command.open-permission-request
    signature: internal open audit-ready permission request for unknown permission in story execution
    allowed_statuses:
      - principal-capabilities.status.story_scoped
    requires:
      - principal-capabilities.invariant.no_native_prompt_during_story_lock
      - principal-capabilities.invariant.run_progress_not_dependent_on_external_permission_ui
    emits:
      - principal-capabilities.event.permission_request_opened
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
    signature: agentkit split-story|reset-story|cleanup|resolve-conflict through official service principal
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
    signature: agentkit resolve-conflict --story <story_id> --decision <decision> --reason <reason>
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
  - id: principal-capabilities.command.approve-permission-request
    signature: agentkit approve-permission-request --request <request_id>
    allowed_statuses:
      - principal-capabilities.status.permission_pending
    requires:
      - principal-capabilities.invariant.permission_leases_are_scoped_and_expiring
      - principal-capabilities.invariant.external_permission_substrate_is_non_authoritative
      - principal-capabilities.invariant.permission_request_approval_requires_human_cli
      - principal-capabilities.invariant.no_auto_rule_promotion_from_permission_request
    emits:
      - principal-capabilities.event.permission_request_approved
      - principal-capabilities.event.permission_lease_issued
  - id: principal-capabilities.command.reject-permission-request
    signature: agentkit reject-permission-request --request <request_id>
    allowed_statuses:
      - principal-capabilities.status.permission_pending
    requires:
      - principal-capabilities.invariant.permission_request_approval_requires_human_cli
    emits:
      - principal-capabilities.event.permission_request_rejected
  - id: principal-capabilities.command.expire-permission-request
    signature: internal expire open permission request after ttl without human decision
    allowed_statuses:
      - principal-capabilities.status.permission_pending
    emits:
      - principal-capabilities.event.permission_request_expired
```
<!-- FORMAL-SPEC:END -->
