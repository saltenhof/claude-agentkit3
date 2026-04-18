---
id: formal.story-closure.scenarios
title: Story Closure Scenarios
status: active
doc_kind: spec
context: story-closure
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/12_github_integration_repo_operationen.md
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/52_betrieb_monitoring_audit_runbooks.md
---

# Story Closure Scenarios

Diese Traces pruefen den offiziellen Closure-Pfad und seine kritischen
Edge Cases.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-closure.scenarios
schema_version: 1
kind: scenario-set
context: story-closure
scenarios:
  - id: story-closure.scenario.happy-path-ff-only
    start:
      status: story-closure.status.requested
    trace:
      - command: story-closure.command.execute-default
    expected_end:
      status: story-closure.status.completed
    requires:
      - story-closure.invariant.ff_only_is_default_policy
      - story-closure.invariant.push_precedes_merge
      - story-closure.invariant.completed_requires_merge_and_issue_close
  - id: story-closure.scenario.ff-only-rejected-then-no-ff-fallback
    start:
      status: story-closure.status.requested
    trace:
      - command: story-closure.command.execute-default
      - command: story-closure.command.execute-no-ff
    expected_end:
      status: story-closure.status.completed
    requires:
      - story-closure.invariant.ff_only_is_default_policy
      - story-closure.invariant.no_ff_only_official_fallback
      - story-closure.invariant.branch_guard_allows_official_closure
  - id: story-closure.scenario.manual-history-rewrite-rejected
    start:
      status: story-closure.status.policy_checked
    trace:
      - command: story-closure.command.illegal-history-rewrite
    expected_end:
      status: story-closure.status.escalated
    requires:
      - story-closure.invariant.manual_history_rewrite_forbidden
  - id: story-closure.scenario.resume-from-pushed-unmerged
    start:
      status: story-closure.status.story_branch_pushed
    trace:
      - command: story-closure.command.execute-default
    expected_end:
      status: story-closure.status.completed
    requires:
      - story-closure.invariant.merge_requires_pushed_story_branch
      - story-closure.invariant.completed_requires_merge_and_issue_close
  - id: story-closure.scenario.merge-rejected-after-push
    start:
      status: story-closure.status.story_branch_pushed
    trace:
      - command: story-closure.command.execute-default
    expected_end:
      status: story-closure.status.escalated
    requires:
      - story-closure.invariant.merge_rejection_never_completes_closure
```
<!-- FORMAL-SPEC:END -->
