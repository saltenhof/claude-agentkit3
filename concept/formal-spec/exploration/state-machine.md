---
id: formal.exploration.state-machine
title: Exploration State Machine
status: active
doc_kind: spec
context: exploration
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/23_modusermittlung_exploration_change_frame.md
  - concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Exploration State Machine

Exploration ist ein editierbarer Draft- und Gate-Prozess mit
Mandatsrouting ueber H2.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.exploration.state-machine
schema_version: 1
kind: state-machine
context: exploration
states:
  - id: exploration.status.draft_in_progress
    initial: true
  - id: exploration.status.structurally_validated
  - id: exploration.status.review_aggregated
  - id: exploration.status.classified_h2
  - id: exploration.status.feindesign_active
  - id: exploration.status.paused_for_human
  - id: exploration.status.gate_approved
    terminal: true
  - id: exploration.status.gate_rejected
    terminal: true
transitions:
  - id: exploration.transition.draft_to_structurally_validated
    from: exploration.status.draft_in_progress
    to: exploration.status.structurally_validated
  - id: exploration.transition.structurally_validated_to_review_aggregated
    from: exploration.status.structurally_validated
    to: exploration.status.review_aggregated
    guard: exploration.invariant.review_runs_on_editable_draft
  - id: exploration.transition.review_aggregated_to_classified_h2
    from: exploration.status.review_aggregated
    to: exploration.status.classified_h2
    guard: exploration.invariant.h2_classifies_after_review_aggregation
  - id: exploration.transition.classified_h2_to_feindesign_active
    from: exploration.status.classified_h2
    to: exploration.status.feindesign_active
    guard: exploration.invariant.class2_routes_to_feindesign_only
  - id: exploration.transition.classified_h2_to_paused_for_human
    from: exploration.status.classified_h2
    to: exploration.status.paused_for_human
    guard: exploration.invariant.class134_pause_same_phase
  - id: exploration.transition.classified_h2_to_draft_in_progress
    from: exploration.status.classified_h2
    to: exploration.status.draft_in_progress
    guard: exploration.invariant.remediation_returns_to_editable_draft
  - id: exploration.transition.classified_h2_to_gate_approved
    from: exploration.status.classified_h2
    to: exploration.status.gate_approved
    guard: exploration.invariant.freeze_only_after_pass_without_open_findings
  - id: exploration.transition.feindesign_active_to_review_aggregated
    from: exploration.status.feindesign_active
    to: exploration.status.review_aggregated
    guard: exploration.invariant.feindesign_returns_to_review
  - id: exploration.transition.paused_for_human_to_review_aggregated
    from: exploration.status.paused_for_human
    to: exploration.status.review_aggregated
    guard: exploration.invariant.paused_resume_same_run_same_phase
  - id: exploration.transition.structurally_validated_to_gate_rejected
    from: exploration.status.structurally_validated
    to: exploration.status.gate_rejected
compound_rules:
  - id: exploration.rule.approved-means-phase-completed
    description: Exploration is completed only when gate_status is APPROVED and the design artifact has been frozen after successful gating.
```
<!-- FORMAL-SPEC:END -->
