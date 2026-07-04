# Codex Concept Descope Review

## Summary

REJECT. The actual descope direction is defensible: I found no concept-grounded mutation that needs whole-project exclusivity across a dispatch. FK-54's split path is explicitly a Saga and holds no serialization claim across the Saga lifetime; mode-lock and story-number allocation are single-transaction cases.

The concept change is not complete, though. FK-91 Rule 13 was narrowed, and the deleted formal invariant leaves the formal-spec graph structurally valid, but other normative concept/story text still requires the removed `(project_key)` object, lock-set/global ordering, or queue/fairness machinery. That is dangling normativity, so the concept set is internally inconsistent.

Checks run:

- `git -C T:/codebase/claude-agentkit3 diff caef6c94 24db65a8`
- `git -C T:/codebase/claude-agentkit3 grep ... 24db65a8 -- concept stories`
- `.venv\Scripts\python scripts\ci\check_concept_frontmatter.py` -> OK, 88 docs
- `.venv\Scripts\python scripts\ci\compile_formal_specs.py` -> OK, 186 documents, 1619 ids, 1982 references

## Findings

1. `concept/technical-design/10_runtime_deployment_speicher.md:883` - ERROR - FK-10 still normatively points to "Lock-Set-Ordnung" and says project-wide mutations serialize on `(project_key)` with a durable object-mutation claim before dispatch. That directly contradicts the new FK-91 Rule 13 (`concept/technical-design/91_api_event_katalog.md:236`), which says the durable object is only the Story and project-wide atomic operations use one transaction with xact locks / `FOR UPDATE`. Fix: rewrite §10.5.4 to match the descope: durable claims only for `(project_key, story_id)` Story mutations that span dispatch; mode-lock and story-number allocation remain single-transaction exceptions; remove lock-set/order and durable `(project_key)` language.

2. `concept/technical-design/17_fachliches_datenmodell_ownership.md:917` - ERROR - FK-17 §17.5 still states that project-wide mutations serialize on `(project_key)`. This leaves a second active ownership/serialization rule beside the narrowed FK-91 rule and the implemented per-Story claim model. Fix: update §17.5 so object serialization means per-mutated Story unless a mutation is fully completed inside one database transaction; remove the `(project_key)` serialization object.

3. `concept/technical-design/54_story_split_service_scope_explosion.md:254` - ERROR - FK-54 §54.8.2a correctly models Split as a Saga with no claim held over the full Saga lifetime, but step 2 still requires "Projekt-Claim fuer Anlage/Nummernvergabe" and "globale Erwerbsordnung". That is the removed project/lock-set apparatus reintroduced for the split path. It is not evidence that removal went too far, because the same section says each step is short and bounded and the known project-wide parts are story creation/number allocation. Fix: rewrite this step to say successor creation/story-number allocation is serialized inside its own transaction (`FOR UPDATE`/xact lock), while source/successor Story mutations use per-Story claims; remove global acquisition order.

4. `stories/AG3-141-object-mutation-serialization/story.md:1` - ERROR - The AG3-141 story still has stale normative metadata and cross-story references to the removed machinery: the title says "Story-/Projekt-Claims ... Lock-Sets, Queue-Fairness"; the source-concept block still cites Lock-Set, Queue-Fairness, and the deleted `pending_project_claims_are_not_overtaken_by_younger_story_claims` invariant at lines 14-21; the test guardrail still expects fairness/order violations at line 237; K5 still says "Claim-Erwerb/Queue" at line 247. The same stale scope remains in `stories/AG3-141-object-mutation-serialization/status.yaml:2`, `status.yaml:13`, `stories/README.md:378`, `stories/AG3-137-run-ownership-schema-foundation/story.md:148`, `stories/AG3-140-unified-idempotency-contract/story.md:125`, `stories/AG3-144-job-result-kinds-upsert-fences/story.md:149`, and `stories/AG3-150-freeze-admission-blocker/story.md:112`. Fix: update the story/status/README/dependent-story wording to "durable per-Story claim + 409/Retry-After; no project claim, no lock-set, no queue fairness"; remove references to the deleted invariant except where explicitly saying it was removed.

## Explicit Answer

The removal did not go too far: I found no real concept-grounded caller that needs whole-project exclusivity across a dispatch. The takeover-reconcile and command-result endpoints still correctly cite `(project_key, story_id)` serialization (`concept/technical-design/91_api_event_katalog.md:110`, `:322`), and `formal.story-workflow.commands` still preserves per-Story object serialization for run-phase/resume (`concept/formal-spec/story-workflow/commands.md:49`, `:68`).

The removal did not go far enough: FK-10, FK-17, FK-54, and several story/backlog references still contain normative or scope-bearing references to the removed `(project_key)`/lock-set/queue-fairness model. Formal-spec structure is intact, but semantic consistency is not.

VERDICT: REJECT
