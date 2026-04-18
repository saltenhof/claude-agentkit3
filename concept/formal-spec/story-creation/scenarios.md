---
id: formal.story-creation.scenarios
title: Story Creation Scenarios
status: active
doc_kind: spec
context: story-creation
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/21_story_creation_pipeline.md
  - concept/technical-design/54_story_split_service_scope_explosion.md
---

# Story Creation Scenarios

Diese Traces pruefen den normalen Story-Creation-Pfad und seinen
administrativen Reuse durch Story-Split.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-creation.scenarios
schema_version: 1
kind: scenario-set
context: story-creation
scenarios:
  - id: story-creation.scenario.happy-path
    start:
      status: story-creation.status.draft
    trace:
      - command: story-creation.command.create
      - command: story-creation.command.export-story-md
      - command: story-creation.command.approve
    expected_end:
      status: story-creation.status.approved
    requires:
      - story-creation.invariant.validation_requires_vectordb_and_goal_fidelity
      - story-creation.invariant.github_issue_precedes_backlog_status
      - story-creation.invariant.approval_requires_human_decision
  - id: story-creation.scenario.validation-fails-before-github
    start:
      status: story-creation.status.concept_defined
    trace:
      - command: story-creation.command.create
    expected_end:
      status: story-creation.status.rejected
    requires:
      - story-creation.invariant.validation_requires_vectordb_and_goal_fidelity
  - id: story-creation.scenario.export-before-issue-forbidden
    start:
      status: story-creation.status.validated
    trace:
      - command: story-creation.command.export-story-md
    expected_end:
      status: story-creation.status.rejected
    requires:
      - story-creation.invariant.story_md_export_after_issue_creation
  - id: story-creation.scenario.split-reuses-creation-contract
    start:
      status: story-creation.status.draft
    trace:
      - command: story-creation.command.create
      - command: story-creation.command.export-story-md
    expected_end:
      status: story-creation.status.exported
    requires:
      - story-creation.invariant.github_issue_precedes_backlog_status
      - story-creation.invariant.story_md_export_after_issue_creation
```
<!-- FORMAL-SPEC:END -->
