---
id: formal.exploration.invariants
title: Exploration Invariants
status: active
doc_kind: spec
context: exploration
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/23_modusermittlung_exploration_change_frame.md
  - concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/domain-design/03-governance-und-guards.md
---

# Exploration Invariants

Diese Invarianten definieren den zulaessigen Exploration-Pfad und das
Mandatsrouting.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.exploration.invariants
schema_version: 1
kind: invariant-set
context: exploration
invariants:
  - id: exploration.invariant.review_runs_on_editable_draft
    scope: process
    rule: review, premise challenge, design challenge, H1 aggregation and H2 classification operate on an editable draft and not on a previously frozen artifact
  - id: exploration.invariant.h2_classifies_after_review_aggregation
    scope: process
    rule: H2 may classify findings only after review and challenge findings have been aggregated
  - id: exploration.invariant.class2_routes_to_feindesign_only
    scope: mandate
    rule: class-2 findings stay inside the KI mandate and route into the feindesign subprocess instead of pausing the story
  - id: exploration.invariant.class134_pause_same_phase
    scope: mandate
    rule: class-1, class-3 and class-4 findings pause the same exploration run and phase instead of transitioning to another phase automatically
  - id: exploration.invariant.feindesign_returns_to_review
    scope: process
    rule: the feindesign subprocess must re-enter the review chain and may not approve the gate directly
  - id: exploration.invariant.remediation_returns_to_editable_draft
    scope: process
    rule: remediable findings return the flow to an editable draft and increment the review round instead of freezing the artifact
  - id: exploration.invariant.freeze_only_after_pass_without_open_findings
    scope: process
    rule: freezing is legal only after the gate has passed without open findings and after H2 has not produced class-1, class-3 or class-4 outcomes
  - id: exploration.invariant.paused_resume_same_run_same_phase
    scope: recovery
    rule: a paused exploration resumes the same run and same phase and does not spawn a new story run
  - id: exploration.invariant.gate_requires_approved_for_exit
    scope: outcome
    rule: exploration may exit to implementation only when gate_status is APPROVED
```
<!-- FORMAL-SPEC:END -->
