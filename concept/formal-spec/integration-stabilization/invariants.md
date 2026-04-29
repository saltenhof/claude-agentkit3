---
id: formal.integration-stabilization.invariants
title: Integration Stabilization Invariants
status: active
doc_kind: spec
context: integration-stabilization
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/57_integration_stabilization_contract.md
  - concept/technical-design/55_principal_capability_model_story_scope_enforcement.md
  - concept/technical-design/37_verify_context_und_qa_bundle.md
---

# Integration Stabilization Invariants

Diese Invarianten verhindern, dass die Stabilisierung zum Freibrief fuer
ungesteuerte Cross-Scope-Arbeit wird.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integration-stabilization.invariants
schema_version: 1
kind: invariant-set
context: integration-stabilization
invariants:
  - id: integration-stabilization.invariant.integration_contract_requires_exploration_first
    scope: governance
    rule: implementation_contract integration_stabilization requires an exploration-derived approved integration scope manifest before productive stabilization work starts
  - id: integration-stabilization.invariant.integration_contract_requires_approved_manifest
    scope: governance
    rule: no productive cross-scope stabilization work may run without an approved integration scope manifest
  - id: integration-stabilization.invariant.manifest_approval_requires_backend_attestation
    scope: governance
    rule: manifest approval is valid only with an attested backend approval record bound to project story run and manifest hash and never from file presence alone
  - id: integration-stabilization.invariant.undeclared_surface_is_not_normal_stabilization_work
    scope: governance
    rule: a newly touched productive surface outside the approved manifest is not normal stabilization work and must be treated as scope explosion or replan
  - id: integration-stabilization.invariant.manifest_may_not_expand_repo_set
    scope: governance
    rule: the approved integration manifest may only authorize productive paths inside the already bound participating repos and may not silently add new repos or worktrees
  - id: integration-stabilization.invariant.manifest_may_not_be_mutated_in_place_during_active_stabilization
    scope: governance
    rule: an active stabilization campaign may not silently widen its manifest in place and requires an explicit amendment request path
  - id: integration-stabilization.invariant.reclassification_may_not_legalize_pre_manifest_cross_scope_delta
    scope: governance
    rule: reclassifying a standard implementation story into integration stabilization may not retroactively legalize pre-manifest productive cross-scope mutations and requires a fresh approved snapshot boundary
  - id: integration-stabilization.invariant.failed_e2e_verify_may_continue_only_inside_budget
    scope: governance
    rule: a failed integration verify may only lead back into another stabilization cycle while the approved stabilization budget remains available
  - id: integration-stabilization.invariant.budget_exhaustion_requires_replan_or_decomposition
    scope: governance
    rule: once the approved stabilization budget is exhausted the story may not continue normal stabilization work and must enter replan decomposition or escalation
  - id: integration-stabilization.invariant.budget_exhaustion_blocks_live_capability
    scope: governance
    rule: exhausted stabilization budget blocks further productive stabilization writes and execution in the capability layer before the next loop proceeds
  - id: integration-stabilization.invariant.closure_requires_stability_gate_pass
    scope: governance
    rule: closure for integration_stabilization may only proceed after the dedicated stability gate has passed
  - id: integration-stabilization.invariant.capability_overlay_is_manifest_scoped
    scope: governance
    rule: any widened worker write capability in integration stabilization is limited to the approved seam allowlist and never becomes a global guard relaxation
  - id: integration-stabilization.invariant.declared_surfaces_only_is_deterministic
    scope: governance
    rule: declared_surfaces_only is a deterministic diff and allowlist check in layer one or the hook layer and must not depend on llm judgement
```
<!-- FORMAL-SPEC:END -->
