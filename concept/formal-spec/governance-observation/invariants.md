---
id: formal.governance-observation.invariants
title: Governance Observation Invariants
status: active
doc_kind: spec
context: governance-observation
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Governance Observation Invariants

Diese Invarianten definieren die harte Governance-Logik ueber Zeit.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.governance-observation.invariants
schema_version: 1
kind: invariant-set
context: governance-observation
invariants:
  - id: governance-observation.invariant.threshold_breach_or_hard_signal_opens_incident
    scope: detection
    rule: an incident candidate may open only after a rolling-window threshold breach or an immediate hard signal
  - id: governance-observation.invariant.hard_signals_bypass_adjudication
    scope: detection
    rule: governance file manipulation and secret access are hard signals that bypass LLM adjudication and escalate immediately
  - id: governance-observation.invariant.non_hard_signals_require_adjudication
    scope: adjudication
    rule: non-hard signals may trigger pause or escalation only after structured adjudication has classified severity and recommendation
  - id: governance-observation.invariant.measure_requires_signal_or_adjudication
    scope: governance
    rule: every applied measure must cite either a hard signal or a completed adjudication record
  - id: governance-observation.invariant.signal_accumulation_is_story_scoped
    scope: run
    rule: rolling-window accumulation and incident scoring are always scoped to the current story and run context
```
<!-- FORMAL-SPEC:END -->
