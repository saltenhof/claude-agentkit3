# Codex Concept Review R1 - 7fc7a834

## Faithfulness Check

The edited core decision text in FK-91 is faithful:

- Rule 14 now normatively says long-running phase work runs synchronously in the request, holds object serialization for its duration, has no async `202` acceptance, and reconciles the dropped-connection case via story-run status / `GET /v1/project-edge/operations/{op_id}` under Rule 17.
- Rule 15 now makes the active `RunOwnershipRecord` lease the fence for mutating story completions. A session that no longer holds the lease is rejected through the ex-owner error path in Rule 18 with no state write; result-kind classification, `stale_observation`, and extra stale predicates are explicitly removed.
- The formal invariant `state-storage.invariant.stale_results_never_overwrite_current_projections` keeps its id and now states deterministic lease-loss rejection with no state write and no stale-observation history.

However, the commit did not fully reconcile FK-44's exported glossary term:

1. `concept/technical-design/44_prompt_bundles_materialization_audit.md:85` - ERROR - The exported glossary definition for `execution-contract-digest` still says the digest "Dient als Fencing-Praedikat fuer gefencte Abschluss-Commits". This directly contradicts the new §44.3a prose at lines 261-270 and the PO decision that the digest is only run-pinning/audit, not a fence predicate.
   Exact fix: rewrite the glossary definition to match §44.3a, e.g. "Der run-prompt-pin ist eine Komponente davon. Dient als Run-Pinning-/Audit-Artefakt zur reproduzierbaren Festhaltung des eingefrorenen fachlichen Contracts eines Runs; kein Fencing-Praedikat." Remove the "gefencte Abschluss-Commits" wording from the glossary.

## Landed Mechanisms Preserved Check

- AG3-142 ownership-lease fencing is preserved in FK-91 Rule 15 as the sole story-completion fence: the active ownership record / lease is checked at commit time and lease loss rejects the commit with no write.
- AG3-138/140 in-flight idempotency is not removed. FK-91 keeps Rule 16 for instance-bound in-flight claims, the admin-abort endpoint still says finalize is fenced by `operation_epoch` CAS, and `concept/formal-spec/state-storage/invariants.md:67` still contains `state-storage.invariant.operation_finalize_requires_cas_on_operation_epoch`.
- AG3-143 still has a coherent purpose in §44.3a as run-pinning/audit: the run works against an execution-contract digest, later default changes affect future runs, and deliberate admin intervention is explicit. The glossary residue above is the only direct contradiction found.
- FK-91 §91.1b remains semantically valid under the new Rule 15: `POST /v1/project-edge/commands/{command_id}/result` says the result commit is fenced against the active ownership record, which is exactly the new lease-only Rule 15.

## Broad-Sweep Result

Broad grep across `concept/` covered at least: `202`, `op_id.*Job` / `Job.*op_id`, `Job-Muster`, `Job-Abschluss`, `Job-Ergebnis`, `Ergebnisart`, `append_only_observation`, `projection_upsert`, `steering` as result-kind language, `stale_observation`, digest-as-`Fencing-Praedikat` / `Fence-Praedikat`, `Bounded-Pflicht`, and "drei Ergebnisarten".

Category-(i) unreconciled live concept hits:

1. `concept/technical-design/44_prompt_bundles_materialization_audit.md:85` - ERROR - Digest is still described as a `Fencing-Praedikat` in the exported glossary.
   Exact fix: same as finding 1 above; align the glossary definition with §44.3a's run-pinning/audit wording and explicitly remove the fence role.

2. `concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md:470` - ERROR - The takeover challenge data still lists "offene Jobs/`op_id`s". Under the new synchronous model there are no async jobs to list; the live model is operations / in-flight operation status observed through `op_id`.
   Exact fix: replace "offene Jobs/`op_id`s" with "laufende synchrone Operationen (`op_id`s)" or "laufende Operationen mit `op_id`s", preserving the Owner-BC data-source requirement.

3. `concept/technical-design/72_frontend_architektur.md:660` - ERROR - The Story Cockpit takeover view still lists "offene Jobs mit ihren `op_id`s". This is the same unreconciled async-job vocabulary in a live frontend concept section. The same file later correctly says "laufende (synchrone) Operationen" at lines 693-695, so this is an internal sibling miss.
   Exact fix: replace the bullet with "laufende synchrone Operationen mit ihren `op_id`s und der Phasenstand" or equivalent wording aligned with §72.14.7(3) and FK-91 Rule 17.

Category-(ii) negating text, fine:

- `concept/technical-design/91_api_event_katalog.md:257` negates `202` async acceptance.
- `concept/technical-design/91_api_event_katalog.md:278-287` negates result-kind classification, `stale_observation`, stale predicate catalogs, and digest-as-fence.
- `concept/technical-design/44_prompt_bundles_materialization_audit.md:263` negates digest-as-`Fencing-Praedikat`.

Other `concept/` hits were not removed-model references: dates containing 2026, Jenkins jobs, scheduled failure-corpus jobs, Windows Job Objects, generic "Hintergrund", and ordinary "steuernd" prose not used as a result-kind classification.

`stories/` sweep result, noted separately: many hits remain in historical story/review material, especially `stories/AG3-144-job-result-kinds-upsert-fences/story.md`, prior AG3-144 fence-half reviews, `stories/AG3-143-execution-contract-digest-spec-freeze/story.md`, `stories/AG3-145-edge-command-queue-worktree-ops/story.md`, `stories/AG3-141-object-mutation-serialization/story.md`, `stories/AG3-140-unified-idempotency-contract/story.md`, and `stories/README.md`. Per instruction, these are historical/story-planning artifacts rather than canonical concept correctness and are not used as rejection findings.

## Consistency Check

Rule 14/15 references inside the edited FK-91 section are internally coherent, and the formal invariant id stayed stable while its rule text changed to lease-based rejection. FK-17's FK-91 pointer now names synchronous execution and ownership fencing rather than the removed job pattern.

The remaining concept consistency failure is not in the core FK-91 rule text but in sibling canonical prose/glossary: FK-44's glossary contradicts §44.3a, and FK-56/FK-72 still expose "open jobs" as takeover display/challenge data even though the async job pattern has been removed. Those are live concept references, not harmless historical notes.

VERDICT: REJECT
