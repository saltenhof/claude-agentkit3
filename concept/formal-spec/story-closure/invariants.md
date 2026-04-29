---
id: formal.story-closure.invariants
title: Story Closure Invariants
status: active
doc_kind: spec
context: story-closure
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/12_github_integration_repo_operationen.md
  - concept/technical-design/29_closure_sequence.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/04_betrieb_monitoring_audit_runbooks.md
---

# Story Closure Invariants

Diese Invarianten definieren den zulaessigen Closure-Pfad bis zum
terminalen Abschluss oder zur offiziellen Eskalation.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-closure.invariants
schema_version: 1
kind: invariant-set
context: story-closure
invariants:
  - id: story-closure.invariant.verify_completed_before_closure
    scope: process
    rule: closure may start only after verify has completed successfully for implementing stories or after the direct closure shortcut for non-implementing stories has been selected
  - id: story-closure.invariant.push_precedes_merge
    scope: process
    rule: the final story branch state must be pushed to the remote before any merge into the target branch is attempted
  - id: story-closure.invariant.merge_requires_pushed_story_branch
    scope: process
    rule: merge into main is legal only after story_branch_pushed has been reached for the same closure attempt
  - id: story-closure.invariant.ff_only_is_default_policy
    scope: policy
    rule: ff_only is the default closure merge policy unless the official no_ff closure command is explicitly chosen
  - id: story-closure.invariant.no_ff_only_official_fallback
    scope: policy
    rule: no_ff is legal only as an official closure fallback path and never as an implicit manual workaround
  - id: story-closure.invariant.manual_history_rewrite_forbidden
    scope: governance
    rule: manual rebase, manual reset, and force-push are forbidden while a story is in the official closure path
  - id: story-closure.invariant.branch_guard_allows_official_closure
    scope: governance
    rule: the branch guard must allow the official closure push and official no_ff fallback path while still rejecting manual history-rewrite operations
  - id: story-closure.invariant.completed_requires_merge_and_issue_close
    scope: outcome
    rule: closure is completed only after merge into main and issue closing have both succeeded for the same closure attempt
  - id: story-closure.invariant.merge_rejection_never_completes_closure
    scope: outcome
    rule: if merge is rejected after the story branch has been pushed the story must not complete and the closure path must remain resumable or escalate explicitly
```
<!-- FORMAL-SPEC:END -->
