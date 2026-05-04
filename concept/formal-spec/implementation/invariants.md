---
id: formal.implementation.invariants
title: Implementation Invariants
status: active
doc_kind: spec
context: implementation
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/39_phase_state_persistenz.md
  - concept/domain-design/02-pipeline-orchestrierung.md
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
---

# Implementation Invariants

Diese Invarianten definieren den zulaessigen Herstellungsprozess.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.implementation.invariants
schema_version: 1
kind: invariant-set
context: implementation
invariants:
  - id: implementation.invariant.start_requires_setup_or_exploration_gate
    scope: process
    rule: implementation may start only after setup completed for execution mode or after exploration gate approved for exploration mode
  - id: implementation.invariant.completed_requires_manifest_and_handover
    scope: outcome
    rule: implementation may complete only after worker manifest and handover artifacts exist, are structurally valid, and the implementation-internal QA-subflow against the verify-system capability has reached a passing verdict
  - id: implementation.invariant.worker_blocked_escalates
    scope: governance
    rule: a worker manifest with BLOCKED status escalates implementation instead of leaving the phase in a resumable in-progress state
  - id: implementation.invariant.qa_subflow_failure_loops_internally
    scope: boundary
    rule: a failed QA-subflow run against the verify-system capability triggers a subflow-internal remediation iteration in the same implementation phase and never a phase transition; only escalation may leave the phase before a passing verdict
  - id: implementation.invariant.implementation-does-not-close-story
    scope: boundary
    rule: implementation records produced outputs, drives the QA-subflow against the verify-system capability, and either reaches a passing verdict or escalates; it does not merge, close the issue, or finalize the story
```
<!-- FORMAL-SPEC:END -->
