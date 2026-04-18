---
id: formal.story-creation.state-machine
title: Story Creation State Machine
status: active
doc_kind: spec
context: story-creation
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/21_story_creation_pipeline.md
  - concept/technical-design/12_github_integration_repo_operationen.md
---

# Story Creation State Machine

Story-Creation ist ein eigenstaendiger Ablauf vor der eigentlichen
Story-Bearbeitung.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-creation.state-machine
schema_version: 1
kind: state-machine
context: story-creation
states:
  - id: story-creation.status.draft
    initial: true
  - id: story-creation.status.concept_defined
  - id: story-creation.status.validated
  - id: story-creation.status.classified
  - id: story-creation.status.backlog
  - id: story-creation.status.exported
  - id: story-creation.status.approved
    terminal: true
  - id: story-creation.status.rejected
    terminal: true
transitions:
  - id: story-creation.transition.draft_to_concept_defined
    from: story-creation.status.draft
    to: story-creation.status.concept_defined
  - id: story-creation.transition.concept_defined_to_validated
    from: story-creation.status.concept_defined
    to: story-creation.status.validated
    guard: story-creation.invariant.validation_requires_vectordb_and_goal_fidelity
  - id: story-creation.transition.validated_to_classified
    from: story-creation.status.validated
    to: story-creation.status.classified
    guard: story-creation.invariant.classification_requires_required_fields
  - id: story-creation.transition.classified_to_backlog
    from: story-creation.status.classified
    to: story-creation.status.backlog
    guard: story-creation.invariant.github_issue_precedes_backlog_status
  - id: story-creation.transition.backlog_to_exported
    from: story-creation.status.backlog
    to: story-creation.status.exported
    guard: story-creation.invariant.story_md_export_after_issue_creation
  - id: story-creation.transition.exported_to_approved
    from: story-creation.status.exported
    to: story-creation.status.approved
    guard: story-creation.invariant.approval_requires_human_decision
  - id: story-creation.transition.validated_to_rejected
    from: story-creation.status.validated
    to: story-creation.status.rejected
compound_rules:
  - id: story-creation.rule.backlog-is-not-approved
    description: A story in Backlog is not executable until an explicit human approval promotes it to Approved.
```
<!-- FORMAL-SPEC:END -->
