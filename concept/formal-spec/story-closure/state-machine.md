---
id: formal.story-closure.state-machine
title: Story Closure State Machine
status: active
doc_kind: spec
context: story-closure
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/12_github_integration_repo_operationen.md
  - concept/technical-design/29_closure_sequence.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
---

# Story Closure State Machine

Der offizielle Closure-Pfad ist ein checkpointfaehiger Abschluss-Flow
mit klarer Reihenfolge und offizieller Fallback-Policy.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-closure.state-machine
schema_version: 1
kind: state-machine
context: story-closure
states:
  - id: story-closure.status.requested
    initial: true
  - id: story-closure.status.policy_checked
  - id: story-closure.status.story_branch_pushed
  - id: story-closure.status.merged_to_main
  - id: story-closure.status.issue_closed
  - id: story-closure.status.completed
    terminal: true
  - id: story-closure.status.escalated
    terminal: true
transitions:
  - id: story-closure.transition.request_to_policy_checked
    from: story-closure.status.requested
    to: story-closure.status.policy_checked
    guard: story-closure.invariant.verify_completed_before_closure
  - id: story-closure.transition.policy_checked_to_story_branch_pushed
    from: story-closure.status.policy_checked
    to: story-closure.status.story_branch_pushed
    guard: story-closure.invariant.push_precedes_merge
  - id: story-closure.transition.story_branch_pushed_to_merged_to_main
    from: story-closure.status.story_branch_pushed
    to: story-closure.status.merged_to_main
    guard: story-closure.invariant.merge_requires_pushed_story_branch
  - id: story-closure.transition.merged_to_main_to_issue_closed
    from: story-closure.status.merged_to_main
    to: story-closure.status.issue_closed
  - id: story-closure.transition.issue_closed_to_completed
    from: story-closure.status.issue_closed
    to: story-closure.status.completed
    guard: story-closure.invariant.completed_requires_merge_and_issue_close
  - id: story-closure.transition.policy_checked_to_escalated
    from: story-closure.status.policy_checked
    to: story-closure.status.escalated
    guard: story-closure.invariant.manual_history_rewrite_forbidden
  - id: story-closure.transition.story_branch_pushed_to_escalated
    from: story-closure.status.story_branch_pushed
    to: story-closure.status.escalated
    guard: story-closure.invariant.merge_rejection_never_completes_closure
compound_rules:
  - id: story-closure.rule.ff-only-is-default-policy
    description: The default closure path selects ff_only unless the official no_ff flag is explicitly chosen.
  - id: story-closure.rule.story-branch-pushed-is-resumable
    description: A closure resumed from story_branch_pushed continues with merge and must not require a new semantic re-entry into verify.
```
<!-- FORMAL-SPEC:END -->
