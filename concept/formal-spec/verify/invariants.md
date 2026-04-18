---
id: formal.verify.invariants
title: Verify Invariants
status: active
doc_kind: spec
context: verify
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
  - concept/technical-design/20_workflow_engine_state_machine.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Verify Invariants

Diese Invarianten definieren den zulaessigen QA- und Evidenzprozess.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.verify.invariants
schema_version: 1
kind: invariant-set
context: verify
invariants:
  - id: verify.invariant.verify_context_required
    scope: process
    rule: verify may not start without a typed verify_context on the verify payload
  - id: verify.invariant.full_qa_required_for_both_contexts
    scope: process
    rule: both POST_IMPLEMENTATION and POST_REMEDIATION run the full four-layer QA path
  - id: verify.invariant.impact_violation_escalates_immediately
    scope: governance
    rule: impact violation escalates verify immediately and bypasses the normal feedback path
  - id: verify.invariant.pass_requires_no_blocking_findings
    scope: outcome
    rule: verify may pass only after policy evaluation with no blocking findings from any mandatory layer
  - id: verify.invariant.verify-does-not-close-story
    scope: boundary
    rule: verify produces a QA decision but does not merge, close the issue, or finalize the story
```
<!-- FORMAL-SPEC:END -->
