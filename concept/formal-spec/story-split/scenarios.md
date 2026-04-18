---
id: formal.story-split.scenarios
title: Story Split Scenarios
status: active
doc_kind: spec
context: story-split
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Story Split Scenarios

Diese Traces pruefen den offiziellen Story-Split als administrativen
Recovery-Pfad.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-split.scenarios
schema_version: 1
kind: scenario-set
context: story-split
scenarios:
  - id: story-split.scenario.happy-path
    start:
      status: story-split.status.requested
    trace:
      - command: story-split.command.execute
    expected_end:
      status: story-split.status.completed
    requires:
      - story-split.invariant.source_story_ends_cancelled
      - story-split.invariant.source_issue_closes_not_planned
      - story-split.invariant.successors_start_in_backlog
  - id: story-split.scenario.reject-without-scope-explosion-preconditions
    start:
      status: story-split.status.requested
    trace:
      - command: story-split.command.execute
    expected_end:
      status: story-split.status.failed
    requires:
      - story-split.invariant.split_requires_official_preconditions
  - id: story-split.scenario.reject-while-runtime-residues-remain
    start:
      status: story-split.status.source_cancelled
    trace:
      - command: story-split.command.execute
    expected_end:
      status: story-split.status.failed
    requires:
      - story-split.invariant.runtime_residues_cleared_before_completion
```
<!-- FORMAL-SPEC:END -->
