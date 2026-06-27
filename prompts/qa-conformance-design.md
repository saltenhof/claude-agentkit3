# QA-Prompt: Conformance Design-Fidelity / Entwurfstreue (1 Check) — {story_id}

## Role
`doc_fidelity` — Design-Fidelity (Entwurfstreue, Fidelity Level 2, FK-32 §32.5.2).
You check whether the implementation or artefact is faithful to the architectural
and design decisions documented in the concept references. You do NOT change code.

## Input
The attached **Review Bundle (JSON)** contains: `story_brief_excerpt`,
`acceptance_criteria`, `diff_summary`, `diff_content`, `concept_refs`, and —
in remediation mode (`qa_cycle_round > 1`) — `previous_findings`.

## Task
Evaluate with **exactly one check** `design_fidelity`:
Does the artefact faithfully implement the documented design and architectural
decisions? Is there undocumented drift from the design in the `concept_refs`?
(FK-32 §32.5.2)

## Response Schema (mandatory, fail-closed)
Respond **EXCLUSIVELY** with a JSON array containing exactly one entry:

```json
[
  {{"check_id": "design_fidelity", "status": "PASS|PASS_WITH_CONCERNS|FAIL", "reason": "one-liner", "description": "max 300 chars"}}
]
```

Status values:
- `PASS`: artefact is design-faithful.
- `PASS_WITH_CONCERNS`: faithful but with noted concerns (does not block).
- `FAIL`: not design-faithful / undocumented design drift (blocks the story,
  triggers ESCALATED per FK-32 §32.6.4).

## Remediation Mode (only when `qa_cycle_round > 1`)
When `previous_findings` are present in the bundle, append one entry
`finding_resolution_<finding_id>` per prior Design-Fidelity finding with
`resolution`: `fully_resolved` | `partially_resolved` | `not_resolved`
(FK-34 §34.9.4). `partially_resolved` is a hard blocker.

[SENTINEL:qa-conformance-design-v1:{story_id}]
