---
id: formal.exploration.scenarios
title: Exploration Scenarios
status: active
doc_kind: spec
context: exploration
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/23_modusermittlung_exploration_change_frame.md
  - concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Exploration Scenarios

Diese Traces pruefen den Exploration-Pfad gegen die haeufigsten
Mandats- und Gate-Faelle.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.exploration.scenarios
schema_version: 1
kind: scenario-set
context: exploration
scenarios:
  - id: exploration.scenario.pass-without-findings
    start:
      status: exploration.status.draft_in_progress
    trace:
      - command: exploration.command.run-phase
    expected_end:
      status: exploration.status.gate_approved
    requires:
      - exploration.invariant.freeze_only_after_pass_without_open_findings
      - exploration.invariant.gate_requires_approved_for_exit
  - id: exploration.scenario.class2-feindesign-loop
    start:
      status: exploration.status.draft_in_progress
    trace:
      - command: exploration.command.run-phase
    expected_end:
      status: exploration.status.gate_approved
    requires:
      - exploration.invariant.class2_routes_to_feindesign_only
      - exploration.invariant.feindesign_returns_to_review
  - id: exploration.scenario.scope-explosion-pauses
    start:
      status: exploration.status.draft_in_progress
    trace:
      - command: exploration.command.run-phase
      - command: exploration.command.resume
    expected_end:
      status: exploration.status.paused_for_human
    requires:
      - exploration.invariant.class134_pause_same_phase
      - exploration.invariant.paused_resume_same_run_same_phase
  - id: exploration.scenario.remediation-loop
    start:
      status: exploration.status.draft_in_progress
    trace:
      - command: exploration.command.run-phase
    expected_end:
      status: exploration.status.draft_in_progress
    requires:
      - exploration.invariant.remediation_returns_to_editable_draft
```
<!-- FORMAL-SPEC:END -->
