# Second-QA Review — AG3-072 StorySplitService + Split-Plan + Dependency-Rebinding

- **Story:** AG3-072 (`stories/AG3-072-story-split-service/story.md`)
- **Reviewer:** Fable second-QA (independent adversarial re-review, write authority)
- **Reviewed commit:** `fa57c21` (main, "feat(story-lifecycle): AG3-072 ... -> completed", post 4 Codex rounds)
- **Review mode:** real-path probing of the six rebinding invariants, the convergent
  resume, the export/reindex fail-closed chain, idempotency, the entry gate and the
  schema/wire round-trip — with fixes applied in-place where a defect was real.

## Findings

| ID | Severity | Location | Finding | Action taken |
|----|----------|----------|---------|--------------|
| F1 | **Blocker** | `src/agentkit/story_split/service.py` (`_apply_rebinding`, pre-fix :851-910) + `tests/unit/story_split/test_service.py` (`_InMemoryDependencyRepo`, pre-fix :88-111) | The "convergent, crash-recoverable resume" claim was NOT backed for a crash **inside the rebinding apply**. Pre-fix code removed/added edges directly from a freshly derived plan; after a crash mid-apply (e.g. first removal persisted, process dies) the rerun re-derives against the half-mutated graph and **permanently dead-ends**: `plan_rebinding` raises `no_silent_drop: rebinding entry for 'AK3-051' declares an old edge onto 'AK3-001' that does not exist` on EVERY rerun (reproduced, see test). The fence stays committed forever; the §54.5 end-state is unreachable. The dependency `kind` of the addition is unrecoverable from the mutated graph (it is inherited from the already-deleted old edge). Compounding seam gap: the unit-test fake repo was **more forgiving than production** — its `remove` silently no-opped on a missing edge and `add` allowed duplicates, while the real `StateBackendStoryDependencyRepository.add/remove` (`story_dependency_repository.py:42-59`) raise `StoryDependencyConflictError` / `StoryDependencyNotFoundError`. The docstring claim "an already-rebound graph is detected and skipped" only covered the FULLY rebound graph, never the partial one. | **FIXED in-place.** The fully-resolved edge-mutation plan (incl. kinds) is now CHECKPOINTED onto the durable fence (`rebinding_plan` payload) BEFORE the first edge mutation, and the apply is idempotent (remove-if-present / add-if-absent — matching the raising production repo semantics). A resume loads the checkpointed plan instead of re-deriving against a half-mutated graph; a corrupt checkpoint or one targeting a non-successor fails closed. Test fake upgraded to production-faithful raising semantics. New real-path test: `test_resume_converges_after_real_mid_rebinding_fault` (red on pre-fix code with the exact `no_silent_drop` dead-end, green post-fix; also proves the third run is a pure no-op replay). |
| F2 | **Major** | `src/agentkit/story_split/service.py` (`_check_entry_preconditions`, pre-fix :433-482) | The entry gate never checked the source story's **backend status**. A source NOT In Progress (e.g. Approved/Backlog) passed all four gate checks, then the split **mutated** (quiesce, successors created + exported, rebinding, lineage) and died at step 6 in `administratively_cancel_for_story_split` with `InvalidStatusTransitionError` — not even a `StorySplitError` — leaving a permanently stranded committed-but-unfinalized fence (every rerun fails identically; the status never changes). That violates §54.4 "Reject ohne Teil-Mutation" for a condition knowable at the gate, and §54.8.7 (the administrative split-cancel's only legal pre-state is In Progress). Reproduced red. | **FIXED in-place.** Gate now rejects fail-closed (`status=failed` audit record, zero mutation) when `str(source.status) != StoryStatus.IN_PROGRESS.value`. New real-path test: `test_entry_gate_rejects_source_not_in_progress` (asserts source still Approved, no successors, no exports, only the failed audit record). |
| F3 | **Major** | `src/agentkit/story_split/service.py` (`_resume`, pre-fix :982-1036) | The resume path **skipped the §54.4(c) human-approval check entirely**. The principal is only validated in `_check_entry_preconditions`, which a committed fence bypasses — so a non-`HUMAN_CLI` principal submitting the identical plan could drive a crashed split's convergent mutation (quiesce, successor creation, export, rebinding, lineage materialization) and only failed at the very last cancel step inside `StoryService` (reproduced red: `ForbiddenError` raised AFTER all of the above already mutated). A committed fence is no license for a non-human principal. | **FIXED in-place.** `_resume` re-asserts `request.principal is Principal.HUMAN_CLI` BEFORE any resumed work (fail-closed `StorySplitError`). New real-path test: `test_resume_requires_human_cli_principal` (seeds a committed-unfinalized fence, ORCHESTRATOR principal → reject with zero mutation: no successor, no quiesce, no export). |
| F4 | **Major** | `src/agentkit/state_backend/config.py:149` + `tests/unit/state_backend/test_schema_versioning.py:62` | The two new `stories` columns (`split_from`, `split_successors` / SQLite `split_successors_json`) were added to the canonical DDL + ALTER migrations **without bumping `SCHEMA_VERSION`** (left at `"3.25.0"`). Every prior stories-DDL change followed the FK-18 §18.9a versioned-schema convention — AG3-068 bumped 3.24.0→3.25.0 for the *identical* single-column pattern, documented in the `config.py` comment chain and pinned by `test_schema_versioning.py`. The Codex chain missed the missing representation: no AG3-072 entry existed in either place. | **FIXED in-place.** `SCHEMA_VERSION = "3.26.0"` with a documented 3.26.0 (AG3-072) entry in `config.py`; `test_schema_versioning.py` updated (AG3-072 comment line, `3.26.0`, `ak3_v3_26_0`, `agentkit_3_26_0.sqlite`). |
| F5 | Minor | `src/agentkit/story_split/service.py` (pre-fix :704) | `created_id = str(getattr(created, "story_display_id", successor.story_id))` — a **silent fallback to the plan-local id**, directly contradicting the module's repeated claim that real allocated ids are used and "no fabricated plan-local ids are ever used". Dead in practice (the Story-Creation contract always returns a `Story`), but it is exactly the fail-open shape this codebase forbids. | **FIXED in-place:** direct typed access `created_id = str(created.story_display_id)` (the port returns `Story`; mypy enforces the attribute). |
| F6 | Minor | `src/agentkit/story_split/service.py:831`, `src/agentkit/bootstrap/composition_root.py:324` | ARCH-55 nit: the German noun "Integrationsfolgen" used as plain prose inside two English comments ("a silent Integrationsfolgen gap"). | **FIXED in-place:** rephrased to English with the FK-54 §54.11 German concept term kept as an explicit quoted citation. |
| F7 | Minor | `src/agentkit/story_split/models.py:188-192` vs FK-54 §54.8.5 | FK-54 §54.8.5 also names "**ausgehende** Dependencies der Ausgangs-Story" as relations the service updates per plan; the typed `SplitPlan` (per the §54.7 minimal structure, which is what the story's cut binds to) only models inbound rebinding — `old_dependency` MUST equal the source. The source's outgoing edges survive as edges of a Cancelled story. An attempted outgoing-edge entry is explicitly rejected by the model (fail-closed, never a silent drop), so within the story's agreed cut this is correct; the outgoing-edge axis is a concept-level FK-54/plan-shape follow-up. | Left as-is + flagged (story cut = §54.7 minimal plan structure; extending the canonical plan shape is not this story's scope; rejection is explicit, not silent). |
| F8 | Minor | `src/agentkit/story_split/models.py:30` vs `src/agentkit/story_context_manager/service.py` (admin cancel) | `SPLIT_CANCEL_REASON` ("scope_split") is exported but drives no behavior; the administrative cancel composes the literal `f"Story-Split scope_split ({op_id})"` and `_valid_story_split_record` checks string literals. | Left as-is: pattern-consistent with the established `_valid_story_exit_record` structural string checks; importing the producer-BC constant into `story_context_manager` would invert the BC dependency direction for a cosmetic gain. |
| F9 | Minor | `src/agentkit/cli/main.py:709` | `stories_root = Path("stories")` is cwd-relative. | Left as-is: consistent with the CLI's existing cwd-relative defaults (`--project-root` default `"."`); the admin CLI contract is invocation from the project root. |
| F10 | Minor | `src/agentkit/bootstrap/composition_root.py` (`_default_split_source_state_loader`) | The §54.4(d) competing-admin-operation signal checks committed `story_exit` operations only. Verified: `story_exit` and `story_split` are the ONLY administrative control-plane `operation_kind`s in the codebase today (no `story_reset` op kind exists yet), so the representation is currently complete — but the loader must be extended when reset-class admin operations land as control-plane ops. | Left as-is + flagged for the future reset story. |

## Explicitly probed and found SOUND (no fabricated-state / dead-seam pattern)

- **Six rebinding invariants fail closed in production:** `no_silent_drop`,
  `no_stale_cancelled_target`, `deterministic_target_selection`,
  `no_unjustified_fanout`, `graph_integrity_preserved` are all enforced by the single
  pure planner `plan_rebinding` over **real `StoryDependency` edge models**, and the
  service's entry gate (`_validate_plan_rebinding`) runs the identical derivation against
  the real project graph BEFORE any mutation — the end-to-end negatives
  (`test_split_fails_closed_on_stale_cancelled_target`,
  `test_rebinding_invalid_plan_is_clean_failclosed_reject_and_reject_on_rerun`) drive the
  real service + real `StoryService`, not a seam. `mapping_requires_successors_created`
  holds by service ordering (step 5 strictly after step 4).
- **Export/reindex `StoryMdExportResult.success` is checked at every call site:** (1)
  successor export → `_export_successor` → `_require_export_success`; (2) source
  superseded re-export → `composition_root._SupersededIndex.mark_superseded` raises on
  `success=False` (never returns 0); (3) defense-in-depth `reindexed < 1` guard in
  `_run_split_to_completion`. The r4 tests drive the REAL `export_story_md` with a real
  `VectorDbWriteError` (production failure channel), including persistent-failure
  no-silent-finalize.
- **Idempotency:** deterministic `split_id` from `(project_key, source_story_id,
  plan_ref)` with length-prefixed hashing; successor `create_story` reuses deterministic
  op_ids (real Story-Creation idempotency proven by the convergence tests — no duplicate
  successors after faults); the administrative cancel is op_id-idempotent and a no-op on
  Cancelled; finalized fences replay as pure no-ops.
- **Wire/contract round-trip is real:** `split_from`/`split_successors` flow through
  `story_to_wire_summary` → `_story_to_internal_snapshot` (idempotency snapshots) and
  through the REAL SQLite repository round-trip
  (`test_state_backend_split_lineage_sqlite_roundtrip` reads back via a fresh repository
  instance); SQLite/Postgres migrations are additive with sane defaults (NULL / `'[]'`)
  and old rows deserialize to the fail-closed model defaults.
- **No second result-axis truth:** `StorySplitRecord` consumes AG3-074's
  `ExitClass.SCOPE_SPLIT` / `TerminalState.CANCELLED` and validates via the shared
  `validate_exit_class_constraints`; no rival enum/constraint. `terminal_state.py` was
  not touched by this review.
- **Closure/frontend-guard separation holds:** the split never calls `complete_story`
  (tracked in every end-to-end test), never `cancel_story`; `_ALLOWED_TRANSITIONS` was
  not widened — `In Progress → Cancelled` stays illegal for the frontend surface and the
  dedicated admin path is gated on principal + committed fence + valid producer record.
- **Branch guard:** only the existing `_OFFICIAL_ALLOW_PREFIXES` prefix path is tested
  (allow `agentkit split-story`, block free `git push`), allowlist not extended, no
  AG3-087 servicepath verdict modeled — exactly the story's cut.
- **Telemetry-derived gate state:** `_default_split_source_state_loader` matches the
  real FK-25 emission contract (`scope_explosion_check.status="exploded"`,
  `mandate_classification.escalation_class="scope_explosion"`); run-scoped event reads
  work because `StateBackendEmitter._resolve_run_id` resolves the run id for the
  run_id-less scope-check events before persistence.

## Before/after (one line per FIXED finding)

- **F1:** before — derive-then-mutate, rerun after mid-apply crash dead-ends with
  `no_silent_drop ... does not exist`; after — plan checkpointed on the fence pre-mutation,
  idempotent remove-if-present/add-if-absent apply, checkpoint replay on resume converges
  (`service.py` `_apply_rebinding`/`_checkpoint_rebinding_plan`/`_load_rebinding_plan_checkpoint`).
- **F2:** before — non-In-Progress source mutates then strands at step 6
  (`InvalidStatusTransitionError`); after — gate rejects `"... is 'Approved', but the
  administrative split-cancel path (§54.8.7) requires In Progress"` with zero mutation +
  failed audit record.
- **F3:** before — `_resume` mutated (quiesce/create/export/rebind/lineage) for any
  principal and failed only at the cancel; after — `_resume` rejects non-HUMAN_CLI
  first: `"resume rejected: split resume requires Principal.HUMAN_CLI ..."`.
- **F4:** before — `SCHEMA_VERSION = "3.25.0"` despite two new stories columns; after —
  `"3.26.0"` + documented config entry + pinned schema-versioning test.
- **F5:** before — `getattr(created, "story_display_id", successor.story_id)` (silent
  plan-local fallback); after — `created.story_display_id` (typed, no fallback).
- **F6:** before — "a silent Integrationsfolgen gap"; after — "a silent
  integration-consequences gap (FK-54 §54.11, \"Integrationsfolgen\")".

## Verification (post-fix, project venv, `-n0`)

- `pytest tests/unit/story_split tests/unit/cli tests/unit/governance
  tests/unit/story_context_manager tests/integration/closure tests/contract
  tests/unit/state_backend -q -n0` → **1956 passed, 12 skipped** (3 new real-path tests
  included; each was RED against `fa57c21` before the fix).
- `mypy src` → Success: no issues found in 674 source files.
- `mypy --platform linux src` → Success: no issues found in 674 source files.
- `ruff check src tests` → All checks passed!
- Concept gates: `check_architecture_conformance.py` OK ·
  `check_concept_code_contracts.py` OK · `check_concept_frontmatter.py` OK (88 docs) ·
  `compile_formal_specs.py` OK (186 documents, 1558 ids).

**POST-FIX STATE: clean** — no blocking finding remains; residual Minor observations
F7–F10 are documented above as deliberate left-as-is with justification (concept-level
follow-ups outside this story's cut, or pattern-consistent existing conventions).
Edits are uncommitted in the working tree for orchestrator review (per mandate).
