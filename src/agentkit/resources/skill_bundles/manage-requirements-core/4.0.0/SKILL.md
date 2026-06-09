# Manage Requirements

Manage ARE requirements from the harness when the project has
`features.are: true`.

**Invocation:** `/manage-requirements <request>`

**Profile:** CORE

## Contract

`skill_name=manage-requirements` is the suffix-free FK-43 skill identity.
`bundle_id=manage-requirements-core` is the deployed CORE bundle identity.

## Required Flow

1. Read the operator request and the current ARE requirement context.
2. Identify affected requirement IDs and ownership boundaries.
3. Propose requirement changes with traceable rationale and impact.
4. Detect conflicts between story scope, requirement status, and project
   conventions.
5. Stop for human clarification when requirement ownership, status, or evidence
   is incomplete.

## Boundaries

This bundle standardizes the harness workflow. It does not implement the ARE
backend, requirement persistence, or story creation logic.
