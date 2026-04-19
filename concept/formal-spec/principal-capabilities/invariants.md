---
id: formal.principal-capabilities.invariants
title: Principal Capability Invariants
status: active
doc_kind: spec
context: principal-capabilities
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/55_principal_capability_model_story_scope_enforcement.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/42_ccag_tool_governance_permission_runtime.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Principal Capability Invariants

Diese Invarianten definieren die harte Plattformgrenze zwischen
Control-Plane, Story-Scope und privilegierten Servicepfaden.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.principal-capabilities.invariants
schema_version: 1
kind: invariant-set
context: principal-capabilities
invariants:
  - id: principal-capabilities.invariant.orchestrator_is_control_plane_only
    scope: governance
    rule: the orchestrator may read control-plane signals but may not read content-plane artifacts or mutate codebase governance plane or git internals
  - id: principal-capabilities.invariant.story_scoped_writers_may_not_escape_story_scope
    scope: governance
    rule: worker write access is restricted to the active story scope and does not extend to out-of-scope productive paths
  - id: principal-capabilities.invariant.adversarial_writer_is_sandbox_only
    scope: governance
    rule: adversarial write access is restricted to registered sandbox paths and may not directly mutate productive repository files
  - id: principal-capabilities.invariant.llm_evaluator_has_no_local_filesystem_capability
    scope: governance
    rule: evaluator-style principals may call configured pools but do not receive local filesystem or shell capabilities
  - id: principal-capabilities.invariant.freeze_removes_orchestrator_mutation_rights
    scope: governance
    rule: once a conflict_freeze is active for a story the orchestrator may not perform story-scoped write git_mutation curate or admin_transition operations
  - id: principal-capabilities.invariant.privileged_principals_require_attestation
    scope: governance
    rule: pipeline_deterministic admin_service and human_cli capabilities require platform or service attestation and may not be inferred from prompt or command text
  - id: principal-capabilities.invariant.only_official_service_or_human_cli_may_mutate_during_freeze
    scope: governance
    rule: while a conflict_freeze is active only official service principals or explicit human_cli commands may execute mutating recovery paths
  - id: principal-capabilities.invariant.ccag_never_elevates_hard_capabilities
    scope: governance
    rule: ccag may not override a hard deny produced by the principal capability matrix or freeze overlay
  - id: principal-capabilities.invariant.git_internal_never_mutated_via_free_bash
    scope: governance
    rule: mutations below .git or equivalent repository internals must never be allowed through generic shell operations and require an official service path
  - id: principal-capabilities.invariant.freeze_has_backend_record_and_local_export
    scope: governance
    rule: an active conflict_freeze must exist both as canonical backend record and as local hook-readable export with matching freeze_version
  - id: principal-capabilities.invariant.same_run_keeps_same_authority_basis
    scope: governance
    rule: a running story may not swap its authoritative setup snapshot in place; authoritative divergence requires freeze and official resolution
  - id: principal-capabilities.invariant.no_native_prompt_during_story_lock
    scope: governance
    rule: while a story_execution lock is active an unknown permission may not be delegated to a native host prompt and must resolve to a blocked permission request path
  - id: principal-capabilities.invariant.run_progress_not_dependent_on_external_permission_ui
    scope: governance
    rule: active story progress may not depend on the response time or session semantics of external permission dialogs tty prompts or host ui confirmation layers
  - id: principal-capabilities.invariant.permission_leases_are_scoped_and_expiring
    scope: governance
    rule: temporary permission exceptions must be scoped to project story run principal operation class and path class and must expire deterministically
  - id: principal-capabilities.invariant.external_permission_substrate_is_non_authoritative
    scope: governance
    rule: native host permission prompts tty requirements and protected-directory special cases may influence execution behavior but never define AK3 capability authority
  - id: principal-capabilities.invariant.permission_request_approval_requires_human_cli
    scope: governance
    rule: approving or rejecting a permission request requires explicit human cli authority and may not be inferred from admin-service automation alone
  - id: principal-capabilities.invariant.no_auto_rule_promotion_from_permission_request
    scope: governance
    rule: a permission request approval may issue at most a scoped lease by default and must never silently create a persistent ccag rule
```
<!-- FORMAL-SPEC:END -->
