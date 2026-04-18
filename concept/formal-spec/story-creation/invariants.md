---
id: formal.story-creation.invariants
title: Story Creation Invariants
status: active
doc_kind: spec
context: story-creation
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/21_story_creation_pipeline.md
  - concept/technical-design/12_github_integration_repo_operationen.md
  - concept/technical-design/54_story_split_service_scope_explosion.md
---

# Story Creation Invariants

Diese Invarianten definieren den zulaessigen Story-Creation-Pfad.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-creation.invariants
schema_version: 1
kind: invariant-set
context: story-creation
invariants:
  - id: story-creation.invariant.validation_requires_vectordb_and_goal_fidelity
    scope: process
    rule: story creation may proceed to classified only after vectordb conflict checking and goal-fidelity validation have completed successfully
  - id: story-creation.invariant.classification_requires_required_fields
    scope: process
    rule: story type, size, affected modules, acceptance criteria, and mode-related fields must be set before GitHub issue creation
  - id: story-creation.invariant.github_issue_precedes_backlog_status
    scope: process
    rule: a story reaches Backlog only after GitHub issue creation, custom field population, and project item insertion have succeeded
  - id: story-creation.invariant.story_md_export_after_issue_creation
    scope: process
    rule: story.md export is legal only after the story exists in GitHub and the project status is Backlog
  - id: story-creation.invariant.approval_requires_human_decision
    scope: governance
    rule: promotion from Backlog or Exported to Approved requires an explicit human approval and may not be performed autonomously by AgentKit
  - id: story-creation.invariant.no_direct_agent_gh_issue_create
    scope: governance
    rule: agents may not directly create GitHub issues outside the official story creation path
```
<!-- FORMAL-SPEC:END -->
