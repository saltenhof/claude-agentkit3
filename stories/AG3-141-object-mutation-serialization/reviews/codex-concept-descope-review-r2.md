# Codex Concept Descope Review R2

## Summary

REJECT. The core concept remediation is mostly correct: FK-10, FK-17, FK-54, FK-91 and the formal invariant now describe per-Story serialization plus single-transaction project-wide atomics. The per-Story guarantee is still present, and the formal-spec graph is structurally valid.

The sweep is not complete. AG3-150 still contains non-negated normative references to claim acquisition "in globaler Ordnung" for split-saga sub-commits, including a source-concept line, an acceptance criterion, and concept-reference lines. Current FK-54/FK-91 explicitly removed that global lock-set/acquisition-order model, so those AG3-150 lines are dangling normativity.

Checks run:

- `git -C T:/codebase/claude-agentkit3 diff caef6c94 07af2f77`
- `rg -n -i "queue[- ]fairness|lock[- ]set|lockset|erwerbsordnung|pending_project_claims_are_not_overtaken_by_younger_story_claims|projekt-claim|projektclaim|project claim|project-scoped claim|project-wide claim|projektweites sperrobjekt|project-wide.*serial|projektweite mutationen.*serial|serialisier.*\\(project_key\\)|serialize.*\\(project_key\\)|\\(project_key\\)-serialisierung|\\(project_key\\).*serialis" concept stories`
- `rg -n -i "global(e|er|en)?\\s+(erwerbsordnung|ordnung)|erwerb.*global|global.*claim|claims? in global|Claim-Erwerb in globaler Ordnung|Erwerb.*Ordnung" concept stories`
- `.venv\Scripts\python scripts\ci\check_concept_frontmatter.py` -> OK, 88 docs
- `.venv\Scripts\python scripts\ci\compile_formal_specs.py` -> OK, 186 documents, 1619 ids, 1982 references

## Part A - Round-1 Findings

1. FIXED - FK-10 §10.5.4 now states that the serialized object is the Story `(project_key, story_id)`, the durable object-mutation claim is acquired before dispatch and held until Finalize/Abort, project-wide atomics are only Mode-Lock and Story-Nummernvergabe in one transaction, and no project-wide serialization lock object / multi-object lock-set exists. Evidence: `concept/technical-design/10_runtime_deployment_speicher.md:881`, `concept/technical-design/10_runtime_deployment_speicher.md:885`, `concept/technical-design/10_runtime_deployment_speicher.md:893`, `concept/technical-design/10_runtime_deployment_speicher.md:896`.

2. FIXED - FK-17 §17.5 removed the `(project_key)` serialization object and now says object serialization is the Story `(project_key, story_id)` with durable claim before dispatch; Mode-Lock and Story-Nummernvergabe are single-transaction project-wide atomics without durable claim. Evidence: `concept/technical-design/17_fachliches_datenmodell_ownership.md:917`, `concept/technical-design/17_fachliches_datenmodell_ownership.md:921`, `concept/technical-design/17_fachliches_datenmodell_ownership.md:923`.

3. FIXED - FK-54 §54.8.2a now says successor creation/story-number allocation runs fully in one transaction (`FOR UPDATE`/xact lock), source/successor Story mutations use per-Story object claims, and project claim/global lock-set acquisition order is not needed. Evidence: `concept/technical-design/54_story_split_service_scope_explosion.md:252`, `concept/technical-design/54_story_split_service_scope_explosion.md:256`, `concept/technical-design/54_story_split_service_scope_explosion.md:260`.

4. NOT-FIXED - AG3-141 itself, `status.yaml`, README, and the dependent-story out-of-scope pointers were largely narrowed, but AG3-150 still has stale normative source/AK/reference text requiring "Claim-Erwerb in globaler Ordnung". Evidence: `stories/AG3-141-object-mutation-serialization/story.md:83`, `stories/AG3-141-object-mutation-serialization/status.yaml:15`, `stories/README.md:378`, `stories/AG3-137-run-ownership-schema-foundation/story.md:148`, `stories/AG3-138-instance-identity-startup-reconcile/story.md:118`, `stories/AG3-140-unified-idempotency-contract/story.md:125`, `stories/AG3-144-job-result-kinds-upsert-fences/story.md:149` are fixed; remaining stale AG3-150 lines are `stories/AG3-150-freeze-admission-blocker/story.md:20`, `stories/AG3-150-freeze-admission-blocker/story.md:185`, `stories/AG3-150-freeze-admission-blocker/story.md:230`, `stories/AG3-150-freeze-admission-blocker/story.md:234`.

## Part B - Dangling-Normativity Sweep

Remaining non-negated dangling normativity found:

- `stories/AG3-150-freeze-admission-blocker/story.md:20` - Source-concept block still describes FK-54 §54.8.2a as "Sub-Commits mit eigenem Claim-Erwerb in globaler Ordnung". Current FK-54 no longer says that; it says successor creation/number allocation is one transaction and source/successor mutations use per-Story claims.
- `stories/AG3-150-freeze-admission-blocker/story.md:185` - Acceptance criterion 7 still requires each Saga step to acquire "Claims in globaler Ordnung". That is an active implementation demand for the removed acquisition-order model.
- `stories/AG3-150-freeze-admission-blocker/story.md:230` - Concept-reference bullet still paraphrases FK-54 as "Claim-Erwerb in globaler Ordnung"; FK-54 now explicitly says global Lock-Set-Erwerbsordnung is not needed.
- `stories/AG3-150-freeze-admission-blocker/story.md:234` - FK-91 reference still says "Claim-Erwerb in globaler Ordnung"; current FK-91 Rule 13 says Mehr-Objekt-Lock-Sets do not exist and the earlier Lock-Set-Erwerbsordnung/Queue-Fairness have been removed.

Other hits are acceptable: FK-10/FK-54/FK-91 and AG3-141 contain explicit "does not exist / nicht noetig / entfallen" descope notes, while historical review files are non-normative review discussion. The still-valid `(project_key, story_id)` Rule-13 citations are intact for takeover-reconcile and command-result endpoints at `concept/technical-design/91_api_event_katalog.md:110` and `concept/technical-design/91_api_event_katalog.md:322`, and formal run-phase serialization remains at `concept/formal-spec/story-workflow/commands.md:49` and `concept/formal-spec/story-workflow/commands.md:68`.

## Part C - Consistency and Integrity

Concept consistency is now correct in the changed concept files: FK-10, FK-17, FK-54 and FK-91 uniformly describe durable per-Story serialization plus single-transaction project-wide atomics, with no durable `(project_key)` claim. The genuinely needed per-Story guarantee is preserved: durable claim before dispatch and until Finalize/Abort (`concept/technical-design/10_runtime_deployment_speicher.md:886`), reads lock-free (`concept/technical-design/10_runtime_deployment_speicher.md:897`, `concept/technical-design/91_api_event_katalog.md:242`), no wall-clock expiry (`concept/technical-design/10_runtime_deployment_speicher.md:900`, `concept/formal-spec/state-storage/invariants.md:61`), and the one-transaction exception for Mode-Lock / Story-Nummernvergabe (`concept/technical-design/10_runtime_deployment_speicher.md:891`, `concept/technical-design/91_api_event_katalog.md:243`).

Formal-spec integrity is preserved: `check_concept_frontmatter.py` passed, and `compile_formal_specs.py` reports 186 documents, 1619 ids, 1982 references. The only blocker is the remaining AG3-150 dangling global-acquisition-order normativity.

VERDICT: REJECT
