---
id: formal.conformance.invariants
title: Conformance Invariants
status: active
doc_kind: spec
context: conformance
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/32_dokumententreue_conformance_service.md
---

# Conformance Invariants

Diese Invarianten definieren den zulaessigen Bewertungsraum des
ConformanceService.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.conformance.invariants
schema_version: 1
kind: invariant-set
context: conformance
invariants:
  - id: conformance.invariant.only_curated_references_enter_assessment
    scope: input
    rule: only explicitly declared references and curated manifest-index matches may enter a conformance assessment
  - id: conformance.invariant.subject_and_reference_bundle_required
    scope: input
    rule: every conformance assessment requires both a subject payload and a resolved reference bundle before evaluator execution may start
  - id: conformance.invariant.payload_limit_fail_closed
    scope: runtime
    rule: when the hard payload limit is exceeded the assessment must terminate with FAIL and no evaluator call may be attempted
  - id: conformance.invariant.feedback_level_requires_merged_change
    scope: process
    rule: feedback fidelity may run only on the merged final change set and never as a pre-merge substitute for design or implementation fidelity
  - id: conformance.invariant.one_verdict_per_assessment
    scope: outcome
    rule: a completed assessment has exactly one final verdict status out of PASS PASS_WITH_CONCERNS or FAIL
```
<!-- FORMAL-SPEC:END -->
