---
id: formal.setup-preflight.invariants
title: Setup Preflight Invariants
status: active
doc_kind: spec
context: setup-preflight
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/22_setup_preflight_worktree_guard_activation.md
  - concept/technical-design/24_story_type_mode_terminalitaet.md
  - concept/technical-design/45_phase_runner_cli.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Setup Preflight Invariants

Diese Invarianten definieren die zulaessige Startfaehigkeit einer Story.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.setup-preflight.invariants
schema_version: 1
kind: invariant-set
context: setup-preflight
invariants:
  - id: setup-preflight.invariant.all_ten_checks_pass_before_context
    scope: process
    rule: story context materialization is legal only after all ten preflight checks have completed and passed
  - id: setup-preflight.invariant.fail_closed_on_any_preflight_failure
    scope: process
    rule: any failed preflight check prevents setup completion and terminates setup with failed status
  - id: setup-preflight.invariant.no_active_runtime_residue_before_start
    scope: process
    rule: active runtime residue, stale worktrees, stale story branches, or overlapping active scope prevent a new setup run
  - id: setup-preflight.invariant.code_stories_require_worktree_setup
    scope: process
    rule: implementation and bugfix stories require participating repo worktrees and branch setup before setup may complete
  - id: setup-preflight.invariant.noncode-stories-skip-worktrees
    scope: process
    rule: concept and research stories complete setup without worktree or code mode routing
  - id: setup-preflight.invariant.no_competing_story_mode_active
    scope: process
    rule: a story may only start setup when the project-level mode_lock is null or holds the same execution_route mode (standard or fast); fast and standard are mutually exclusive at the project level for the duration of any active in-progress story
  - id: setup-preflight.invariant.code_stories_require_green_main_attestation
    scope: process
    rule: implementation and bugfix worktree creation is legal only when the sonarqube_gate main attestation is GREEN read by analysisId on the overall-code invariant AND the revision matches (sonar_last_analyzed_revision == git main HEAD); a RED or STALE attestation refuses setup fail-closed
  - id: setup-preflight.invariant.main_green_refusal_emits_active_cleanup_proposal
    scope: process
    rule: a main-green precondition refusal must emit an active blame-free out-of-story cleanup-worker proposal in the phase-state result; silent refusal without a proposal is a ZERO-DEBT violation
  - id: setup-preflight.invariant.main_green_unreachable_fails_closed
    scope: process
    rule: if SonarQube or the branch plugin is unreachable so the main attestation cannot be read, the precondition is an unresolved state and setup fails closed rather than proceeding on an assumed-green main
```
<!-- FORMAL-SPEC:END -->
