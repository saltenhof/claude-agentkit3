---
id: formal.integrity-gate.commands
title: Integrity Gate Commands
status: active
doc_kind: spec
context: integrity-gate
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Integrity Gate Commands

Das Integrity-Gate wird als offizieller Closure-Schritt und nicht als
freier Hook ausgefuehrt.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integrity-gate.commands
schema_version: 1
kind: command-set
context: integrity-gate
commands:
  - id: integrity-gate.command.run-gate
    signature: check_integrity project_key story_id run_id before merge
    allowed_statuses:
      - integrity-gate.status.open
    requires:
      - integrity-gate.invariant.mandatory_artifacts_checked_first
      - integrity-gate.invariant.only_current_valid_run_is_evaluated
    emits:
      - integrity-gate.event.gate.started
      - integrity-gate.event.gate.result
  - id: integrity-gate.command.override-gate
    signature: agentkit override-integrity --story {story_id} --reason ...
    allowed_statuses:
      - integrity-gate.status.failed
    requires:
      - integrity-gate.invariant.override_requires_explicit_human_reason
    emits:
      - integrity-gate.event.gate.overridden
  - id: integrity-gate.command.query-audit-log
    signature: agentkit query-telemetry --story {story_id} --event integrity_gate_result
    allowed_statuses:
      - integrity-gate.status.failed
      - integrity-gate.status.overridden
      - integrity-gate.status.passed
    emits:
      - integrity-gate.event.gate.audit_queried
```
<!-- FORMAL-SPEC:END -->
