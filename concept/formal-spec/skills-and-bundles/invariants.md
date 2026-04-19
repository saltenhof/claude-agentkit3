---
id: formal.skills-and-bundles.invariants
title: Skills and Bundles Invariants
status: active
doc_kind: spec
context: skills-and-bundles
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/43_skills_system_task_automation.md
  - concept/technical-design/10_runtime_deployment_speicher.md
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
  - concept/technical-design/92_verzeichnis_namenskonventionen.md
---

# Skills and Bundles Invariants

Diese Invarianten definieren die harte Skill- und Bundle-Semantik.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.skills-and-bundles.invariants
schema_version: 1
kind: invariant-set
context: skills-and-bundles
invariants:
  - id: skills-and-bundles.invariant.profile_selects_one_variant_before_binding
    scope: profile
    rule: each project must resolve to exactly one active skill variant before any project binding is created
  - id: skills-and-bundles.invariant.bundle_binding_points_to_concrete_version
    scope: bundle-version
    rule: every production skill or prompt binding must target one concrete immutable bundle version and never latest or another moving alias
  - id: skills-and-bundles.invariant.project_binding_is_symlink_only
    scope: binding
    rule: project-local Claude Code skill exposure is implemented only through symlink-style bindings to system bundles and not by copying canonical skill sources
  - id: skills-and-bundles.invariant.project_local_repo_never_contains_canonical_skill_source
    scope: repository
    rule: the project repository may contain configuration and binding points but must not contain the canonical bundled skill or prompt source
  - id: skills-and-bundles.invariant.live-source-checkout-is-never-a-production-bundle
    scope: bundle-source
    rule: a live source checkout is never a valid production bundle target for project bindings
  - id: skills-and-bundles.invariant.runtime-branching-stays-out-of-skill-contract
    scope: skill-design
    rule: project capability differences such as core versus are are modeled by separate variants and not by broad runtime branching inside one canonical skill contract
  - id: skills-and-bundles.invariant.customized_bundle_bindings_are_never_silently_replaced
    scope: upgrade
    rule: an installer rerun or upgrade may only change a project binding intentionally and must preserve or surface explicit bundle overrides
```
<!-- FORMAL-SPEC:END -->
