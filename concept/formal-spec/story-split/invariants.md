---
id: formal.story-split.invariants
title: Story Split Invariants
status: active
doc_kind: spec
context: story-split
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
  - concept/technical-design/12_github_integration_repo_operationen.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Story Split Invariants

Diese Invarianten definieren den zulaessigen Split-Pfad bei
Scope-Explosion.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-split.invariants
schema_version: 1
kind: invariant-set
context: story-split
invariants:
  - id: story-split.invariant.split_requires_official_preconditions
    scope: command
    requires:
      - story-workflow.status.paused
      - story-workflow.phase.exploration
    rule: split execution is legal only after official scope explosion handling, explicit human approval, a plan artifact, and no competing administrative operation
  - id: story-split.invariant.no_resume_while_fenced
    scope: process
    rule: once the source story is fenced, normal workflow commands such as resume or reset-escalation must not continue that source story run
  - id: story-split.invariant.source_story_ends_cancelled
    scope: outcome
    rule: successful split must set the source story project status to Cancelled
  - id: story-split.invariant.source_issue_closes_not_planned
    scope: external-status-coupling
    rule: successful split must close the source GitHub issue with reason not planned
  - id: story-split.invariant.successors_start_in_backlog
    scope: outcome
    rule: all successor stories created by split start in Backlog, never in Done or In Progress
  - id: story-split.invariant.dependencies_rebound_before_completion
    scope: process
    rule: split may not complete while declared dependency rebinding still points dependents at the cancelled source story
  - id: story-split.invariant.runtime_residues_cleared_before_completion
    scope: process
    rule: split may not complete while source-story runtime locks, leases, worktrees, branches, or resumable control residues remain active
```
<!-- FORMAL-SPEC:END -->
