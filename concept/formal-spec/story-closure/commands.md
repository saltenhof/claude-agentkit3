---
id: formal.story-closure.commands
title: Story Closure Commands
status: active
doc_kind: spec
context: story-closure
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/12_github_integration_repo_operationen.md
  - concept/technical-design/29_closure_sequence.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/04_betrieb_monitoring_audit_runbooks.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Closure Commands

Closure darf nur ueber offizielle Pipeline-Kommandos oder explizit als
verbotener manueller Eingriff modelliert werden. Normative Aufruf-Parameter
sind in FK-91 §91.1a (Service-API) als Schema-Owner definiert.
Die CLI-Signaturen sind menschliche Operator-Recovery-Pfade (FK-91 §91.1,
FK-45 §45.4).

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-closure.commands
schema_version: 1
kind: command-set
context: story-closure
commands:
  - id: story-closure.command.execute-default
    signature: "POST /v1/story-runs/{run_id}/phases/closure/start -- body: {story_id}"
    allowed_statuses:
      - story-closure.status.requested
      - story-closure.status.policy_checked
      - story-closure.status.integrity_passed
      - story-closure.status.merge_lock_acquired
      - story-closure.status.integrated_candidate_green
      - story-closure.status.story_branch_pushed
    requires:
      - story-closure.invariant.ff_only_is_default_policy
      - story-closure.invariant.branch_guard_allows_official_closure
      - story-closure.invariant.merge_block_runs_under_serialization_lock
      - story-closure.invariant.integrated_candidate_scanned_green_before_push
    emits:
      - story-closure.event.closure.started
      - story-closure.event.policy.ff_only_selected
      - story-closure.event.integrity_gate.passed
      - story-closure.event.merge_lock.acquired
      - story-closure.event.integrated_candidate.green
      - story-closure.event.integrated_candidate.red
      - story-closure.event.story_branch.pushed
      - story-closure.event.merge.attempted
      - story-closure.event.merge.completed
      - story-closure.event.post_merge.reconciled
      - story-closure.event.merge_lock.released
      - story-closure.event.issue.closed
      - story-closure.event.closure.completed
      - story-closure.event.closure.escalated
  - id: story-closure.command.execute-no-ff
    signature: "POST /v1/story-runs/{run_id}/phases/closure/start -- body: {story_id, no_ff: true}"
    allowed_statuses:
      - story-closure.status.requested
      - story-closure.status.policy_checked
      - story-closure.status.integrity_passed
      - story-closure.status.merge_lock_acquired
      - story-closure.status.integrated_candidate_green
      - story-closure.status.story_branch_pushed
    requires:
      - story-closure.invariant.no_ff_only_official_fallback
      - story-closure.invariant.branch_guard_allows_official_closure
      - story-closure.invariant.merge_block_runs_under_serialization_lock
      - story-closure.invariant.integrated_candidate_scanned_green_before_push
    emits:
      - story-closure.event.closure.started
      - story-closure.event.policy.no_ff_selected
      - story-closure.event.policy_fallback.used
      - story-closure.event.integrity_gate.passed
      - story-closure.event.merge_lock.acquired
      - story-closure.event.integrated_candidate.green
      - story-closure.event.integrated_candidate.red
      - story-closure.event.story_branch.pushed
      - story-closure.event.merge.attempted
      - story-closure.event.merge.completed
      - story-closure.event.post_merge.reconciled
      - story-closure.event.merge_lock.released
      - story-closure.event.issue.closed
      - story-closure.event.closure.completed
      - story-closure.event.closure.escalated
  - id: story-closure.command.illegal-history-rewrite
    signature: manual git rebase or git push --force-with-lease during active closure
    allowed_statuses: []
    requires:
      - story-closure.invariant.manual_history_rewrite_forbidden
    emits:
      - story-closure.event.manual_git.rejected
      - story-closure.event.closure.escalated
```
<!-- FORMAL-SPEC:END -->
