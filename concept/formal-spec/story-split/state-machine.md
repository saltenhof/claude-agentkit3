---
id: formal.story-split.state-machine
title: Story Split State Machine
status: active
doc_kind: spec
context: story-split
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Story Split State Machine

Der Story-Split ist kein normaler Pipeline-Run, sondern ein eigener
administrativer Service-Prozess.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-split.state-machine
schema_version: 1
kind: state-machine
context: story-split
states:
  - id: story-split.status.requested
    initial: true
  - id: story-split.status.fenced
  - id: story-split.status.quiesced
  - id: story-split.status.successors_created
  - id: story-split.status.dependencies_rebound
  - id: story-split.status.source_cancelled
  - id: story-split.status.completed
    terminal: true
  - id: story-split.status.failed
    terminal: true
transitions:
  - id: story-split.transition.request_to_fenced
    from: story-split.status.requested
    to: story-split.status.fenced
    guard: story-split.invariant.split_requires_official_preconditions
  - id: story-split.transition.fenced_to_quiesced
    from: story-split.status.fenced
    to: story-split.status.quiesced
    guard: story-split.invariant.no_resume_while_fenced
  - id: story-split.transition.quiesced_to_successors_created
    from: story-split.status.quiesced
    to: story-split.status.successors_created
  - id: story-split.transition.successors_created_to_dependencies_rebound
    from: story-split.status.successors_created
    to: story-split.status.dependencies_rebound
    guard: story-split.invariant.dependencies_rebound_before_completion
  - id: story-split.transition.dependencies_rebound_to_source_cancelled
    from: story-split.status.dependencies_rebound
    to: story-split.status.source_cancelled
    guard: story-split.invariant.source_story_ends_cancelled
  - id: story-split.transition.source_cancelled_to_completed
    from: story-split.status.source_cancelled
    to: story-split.status.completed
    guard: story-split.invariant.runtime_residues_cleared_before_completion
  - id: story-split.transition.any_to_failed
    from: story-split.status.requested
    to: story-split.status.failed
compound_rules:
  - id: story-split.rule.split_does_not_resume_source_run
    description: The administrative split path never resumes the paused source run; it terminates the source story contract and creates successors.
```
<!-- FORMAL-SPEC:END -->
