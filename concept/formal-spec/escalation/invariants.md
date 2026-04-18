---
id: formal.escalation.invariants
title: Escalation Invariants
status: active
doc_kind: spec
context: escalation
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Escalation Invariants

Diese Invarianten definieren die harte Aufloesungslogik fuer
`PAUSED` und `ESCALATED`.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.escalation.invariants
schema_version: 1
kind: invariant-set
context: escalation
invariants:
  - id: escalation.invariant.paused_resume_preserves_run
    scope: process
    rule: resuming a PAUSED story continues the same run_id and current phase
  - id: escalation.invariant.escalated_reset_requires_new_run
    scope: process
    rule: resolving ESCALATED requires reset-escalation and reopens work only through a new run_id
  - id: escalation.invariant.explicit_human_intervention_required
    scope: governance
    rule: every transition out of PAUSED or ESCALATED requires an explicit human-issued command
  - id: escalation.invariant.scope_explosion_defaults_to_explicit_redirect_decision
    scope: governance
    rule: scope explosion may not silently fall back into normal work; it requires an explicit human decision for split or another directed follow-up path
```
<!-- FORMAL-SPEC:END -->
