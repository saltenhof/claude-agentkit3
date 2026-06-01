---
id: formal.story-closure.events
title: Story Closure Events
status: active
doc_kind: spec
context: story-closure
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/29_closure_sequence.md
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/technical-design/04_betrieb_monitoring_audit_runbooks.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Closure Events

Diese Events bilden den offiziellen Closure-Pfad und seine
Ausnahmesituationen fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-closure.events
schema_version: 1
kind: event-set
context: story-closure
events:
  - id: story-closure.event.closure.started
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
  - id: story-closure.event.policy.ff_only_selected
    producer: story-closure
    role: policy
    payload:
      required:
        - closure_id
        - story_id
        - merge_policy
  - id: story-closure.event.policy.no_ff_selected
    producer: story-closure
    role: policy
    payload:
      required:
        - closure_id
        - story_id
        - merge_policy
  - id: story-closure.event.policy_fallback.used
    producer: story-closure
    role: recovery
    payload:
      required:
        - closure_id
        - story_id
        - fallback_reason
  - id: story-closure.event.integrity_gate.passed
    producer: integrity-gate
    role: gate
    payload:
      required:
        - closure_id
        - story_id
        - dimension_9_attestation_analysis_id
  - id: story-closure.event.merge_lock.acquired
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
        - locked_sha
  - id: story-closure.event.integrated_candidate.green
    producer: qa-sonarqube-gate
    role: verdict
    payload:
      required:
        - closure_id
        - story_id
        - analysis_id
        - tree_hash
  - id: story-closure.event.integrated_candidate.red
    producer: qa-sonarqube-gate
    role: verdict
    payload:
      required:
        - closure_id
        - story_id
        - analysis_id
        - failure_reason
  - id: story-closure.event.story_branch.pushed
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
  - id: story-closure.event.merge.attempted
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
        - merge_policy
  - id: story-closure.event.merge.completed
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
        - merge_policy
  - id: story-closure.event.post_merge.reconciled
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
        - analysis_id
  - id: story-closure.event.merge_lock.released
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
        - locked_sha
  - id: story-closure.event.merge.rejected
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
        - rejection_reason
  - id: story-closure.event.issue.closed
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
  - id: story-closure.event.manual_git.rejected
    producer: branch-guard
    role: governance
    payload:
      required:
        - story_id
        - rejected_operation
  - id: story-closure.event.closure.completed
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
  - id: story-closure.event.closure.escalated
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
        - escalation_reason
```
<!-- FORMAL-SPEC:END -->
