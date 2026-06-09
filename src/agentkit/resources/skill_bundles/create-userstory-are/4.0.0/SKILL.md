# Create User Story ARE

Create a new user story for an ARE-enabled project.

**Invocation:** `/create-userstory <request>`

**Profile:** ARE

## Contract

Use the same suffix-free harness identity as the CORE variant:
`skill_name=create-userstory`. The profile-specific bundle identity is
`bundle_id=create-userstory-are`.

## Required Flow

1. Read the operator request and the project story conventions.
2. Reconcile the request with the AK3 story backend and existing requirements.
3. Apply ARE-specific requirement checks before drafting the story.
4. Produce the story with acceptance criteria, scope boundaries, anchors, and
   explicit requirement traceability.
5. Stop and ask the operator when ARE ownership, requirement status, or story
   classification is ambiguous.

## Boundaries

This bundle standardizes the harness-side creation workflow only. Deterministic
story persistence and backend reconciliation remain owned by AgentKit runtime
components.
