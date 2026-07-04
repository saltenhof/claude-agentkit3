# AG3-141 CONCEPT Descope Review r3

## 1. Summary

APPROVE. The r2 blocker in AG3-150 is fixed, and the concept/story corpus no longer contains a non-negated normative demand for the removed project-scope serialization / lock-set / global acquisition-order / queue-fairness machinery.

Checked diff: `git -C T:/codebase/claude-agentkit3 diff caef6c94 33343593`.

Formal gates run:

- `.venv\Scripts\python scripts\ci\check_concept_frontmatter.py` -> `[concept-frontmatter] OK: 88 docs, all lints passed. Bounded-context layer: active.`
- `.venv\Scripts\python scripts\ci\compile_formal_specs.py` -> `[formal-spec] OK: 186 documents, 1619 ids, 1982 references, 135 scenarios, 440 prose links`

## 2. AG3-150 Fix Verified?

Yes. The four stale AG3-150 references now match the narrowed FK-54/FK-91 model:

- `stories/AG3-150-freeze-admission-blocker/story.md:20` now says each bounded sub-commit uses per-Story claim acquisition, with successor creation/story-number allocation in one transaction.
- `stories/AG3-150-freeze-admission-blocker/story.md:113` says AG3-141 is consumed as a per-Story object claim, while successor creation/number allocation is fully transactional.
- `stories/AG3-150-freeze-admission-blocker/story.md:186` says each Saga step acquires its per-Story object claim.
- `stories/AG3-150-freeze-admission-blocker/story.md:187` says successor number allocation is in one transaction.
- `stories/AG3-150-freeze-admission-blocker/story.md:232` references per-Story claim acquisition per sub-commit, with number allocation in one transaction.
- `stories/AG3-150-freeze-admission-blocker/story.md:237` references FK-91 rules 13/14 as per-Story object serialization plus bounded sub-commits.

I found no remaining AG3-150 demand for "globaler Ordnung", a global lock-set acquisition order, a project claim, or queue fairness.

## 3. Final Sweep Result

None - sweep complete. I found no remaining non-negated normative demand for the removed machinery in `concept/` or `stories/`.

Sweep patterns included: `globaler Ordnung`, `Erwerb.*Ordnung`, `global.*claim`, `claim.*global`, `lock-set`, `lock set`, `queue-fairness`, `queue fairness`, `projekt-claim`, `project claim`, `(project_key)-serialization`, `project_key.*serialization`, `serializ.*project_key`, project/project-wide serialization variants, global serialization variants, and `pending_project_claims_are_not_overtaken_by_younger_story_claims`.

Remaining relevant hits are acceptable:

- Explicit descope notes: `concept/technical-design/54_story_split_service_scope_explosion.md:261`, `concept/technical-design/91_api_event_katalog.md:246`, `concept/technical-design/91_api_event_katalog.md:250`, `stories/AG3-141-object-mutation-serialization/story.md:83`, `stories/AG3-141-object-mutation-serialization/story.md:87`, `stories/AG3-141-object-mutation-serialization/story.md:197`, `stories/AG3-141-object-mutation-serialization/status.yaml:15`.
- Legitimate single-transaction/mode-lock/story-number terms: `concept/technical-design/10_runtime_deployment_speicher.md:890`, `concept/technical-design/10_runtime_deployment_speicher.md:893`, `concept/technical-design/91_api_event_katalog.md:242`, `concept/technical-design/91_api_event_katalog.md:243`, `stories/AG3-034-preflight-integrity-gate/story.md:96`.
- Unrelated project-scoped telemetry/routing/tenancy terms and historical review/status files, including older r1/r2 review text under `stories/AG3-141-object-mutation-serialization/reviews/`.

## 4. Per-Story Guarantee + Formal-Spec Note

The per-Story guarantee remains intact:

- Durable per-Story claim before dispatch and held until Finalize/Abort: `concept/technical-design/10_runtime_deployment_speicher.md:883`, `concept/technical-design/10_runtime_deployment_speicher.md:887`, `concept/technical-design/91_api_event_katalog.md:239`, `concept/technical-design/91_api_event_katalog.md:240`.
- Reads remain lock-free: `concept/technical-design/10_runtime_deployment_speicher.md:897`, `concept/technical-design/91_api_event_katalog.md:242`.
- No wall-clock expiry: `concept/technical-design/10_runtime_deployment_speicher.md:901`, `concept/formal-spec/state-storage/invariants.md:61`, `concept/formal-spec/state-storage/invariants.md:63`.
- Single-transaction exception for project-wide atomics: `concept/technical-design/10_runtime_deployment_speicher.md:890`, `concept/technical-design/10_runtime_deployment_speicher.md:892`, `concept/technical-design/10_runtime_deployment_speicher.md:893`, `concept/technical-design/91_api_event_katalog.md:242`, `concept/technical-design/91_api_event_katalog.md:243`.

The deleted formal invariant is absent from `concept/formal-spec/state-storage/invariants.md`; the remaining locking invariants are structurally valid, and `compile_formal_specs.py` passes.

VERDICT: APPROVE
