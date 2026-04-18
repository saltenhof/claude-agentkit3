---
id: formal.conformance.commands
title: Conformance Commands
status: active
doc_kind: spec
context: conformance
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/32_dokumententreue_conformance_service.md
  - concept/technical-design/91_api_event_katalog.md
---

# Conformance Commands

Der ConformanceService verarbeitet je Ebene genau einen offiziellen
Bewertungsauftrag.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.conformance.commands
schema_version: 1
kind: command-set
context: conformance
commands:
  - id: conformance.command.evaluate-goal-fidelity
    signature: check_fidelity level=goal with story description and strategy references
    allowed_statuses:
      - conformance.status.pending
    requires:
      - conformance.invariant.subject_and_reference_bundle_required
    emits:
      - conformance.event.assessment.started
      - conformance.event.level.evaluated
      - conformance.event.assessment.completed
  - id: conformance.command.evaluate-design-fidelity
    signature: check_fidelity level=design with entwurfsartefakt and reference documents
    allowed_statuses:
      - conformance.status.pending
    requires:
      - conformance.invariant.subject_and_reference_bundle_required
    emits:
      - conformance.event.assessment.started
      - conformance.event.level.evaluated
      - conformance.event.assessment.completed
  - id: conformance.command.evaluate-implementation-fidelity
    signature: check_fidelity level=impl with diff handover and concept references
    allowed_statuses:
      - conformance.status.pending
    requires:
      - conformance.invariant.subject_and_reference_bundle_required
    emits:
      - conformance.event.assessment.started
      - conformance.event.level.evaluated
      - conformance.event.assessment.completed
  - id: conformance.command.evaluate-feedback-fidelity
    signature: check_fidelity level=feedback with final change and documentation references
    allowed_statuses:
      - conformance.status.pending
    requires:
      - conformance.invariant.feedback_level_requires_merged_change
    emits:
      - conformance.event.assessment.started
      - conformance.event.level.evaluated
      - conformance.event.assessment.completed
```
<!-- FORMAL-SPEC:END -->
