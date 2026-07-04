## Summary

REJECT. The digest/persistence half is not safe enough for AG3-143 as submitted.

The good parts: the main HTTP composition root constructs `ControlPlaneRuntimeService()` without an injected dispatcher, so the productive path lazily binds the real `_build_execution_contract_digest`; the digest row is inserted in the same Postgres transaction as setup-start finalize after the claim CAS; a CAS loser writes no digest row; there is no `UPDATE`/upsert path for `execution_contract_digests`; the Postgres bootstrap canary includes the new table; Spec-Freeze runs before the idempotency claim and reads the AG3-137 active ownership repository by default.

Blocking problems remain: the canonicalizer does not impose a total order on `skill_versions`, malformed/empty project config components can be accepted into the digest instead of failing closed, and new production/test code violates ARCH-55 with German terms in comments/docstrings.

## Fork-half independent-verification notes

I read the fork-risk modules directly, not only the diff hunks:

- `prompt_runtime/execution_contract.py`: pure A-style module with stdlib + pydantic only; no `state_backend`, no HTTP. `formed_at` is only on `ExecutionContractDigestRecord`, not in `ExecutionContractInputs`; no run id, timestamp, wall clock, locale, float, or set enters the hashed payload.
- `control_plane/runtime.py`: fresh setup (`mints_ownership_record=True`) resolves a digest before dispatch. Rejections release claims and store no success replay. Finalize converts the digest to `ExecutionContractDigestRecord` and passes it into `finalize_start_phase`; the row insert is inside `finalize_control_plane_start_phase_global_row`.
- `state_backend`: only strict insert/load facade functions are exposed for digest rows. Grep found no `UPDATE`, no upsert, and no SQLite mirror for `execution_contract_digests`. `_schema_is_bootstrapped` includes `execution_contract_digests`, so an already-bootstrapped pre-AG3-143 DB should rerun idempotent schema creation.
- `story_context_manager`: `update_story_fields` loads the story, runs `_reject_if_spec_frozen`, and only then claims idempotency. The default reader is `load_active_run_ownership_record_global`, so the active-regime predicate is the AG3-137 active ownership record, not a second source.

## Findings

### CRITICAL: `skill_versions` canonicalization is not total-order deterministic

File: `src/agentkit/backend/prompt_runtime/execution_contract.py:148`

Failure scenario: two callers provide the same skill-version component multiset with duplicate `skill_name` values but different `bundle_id`/`bundle_version` order:

- `(SkillVersionComponent(skill_name="same", bundle_id="a", bundle_version="1"), SkillVersionComponent(skill_name="same", bundle_id="b", bundle_version="1"))`
- `(SkillVersionComponent(skill_name="same", bundle_id="b", bundle_version="1"), SkillVersionComponent(skill_name="same", bundle_id="a", bundle_version="1"))`

`canonicalize_execution_contract` sorts only by `skill_name`. Python's stable sort preserves the original order for equal keys, so the canonical JSON and SHA-256 digest differ for equivalent unordered input. I reproduced this locally with the project venv; the two digests were different.

The current production repository orders by `skill_name` and probably prevents duplicate skill names, but the pure canonicalizer is the contract boundary and AC1 explicitly requires deterministic canonicalization of the `skill_versions` list. The canonicalizer must not rely on upstream uniqueness to get a stable byte shape.

Fix direction: sort `skill_versions` by a total key such as `(skill_name, bundle_id, bundle_version)` or reject duplicate `skill_name` components at the `ExecutionContractInputs` boundary with a clear validation error and a contract test for the duplicate-name case.

### CRITICAL: malformed/empty project config components are hashed instead of rejected fail-closed

Files: `src/agentkit/backend/control_plane/runtime.py:1338`, `src/agentkit/backend/installer/registration.py:77`, `src/agentkit/backend/state_backend/postgres_schema.sql:1092`

Failure scenario: a `project_registry` row exists, but `config_version` or `config_digest` is empty/malformed. The schema only says `TEXT NOT NULL`, and `ProjectRegistration` has no validator for non-empty `config_version` or 64-char lowercase SHA-256 `config_digest`. `_build_execution_contract_digest` then copies those values directly into `ExecutionContractInputs` and commits a digest over a partial/invalid project/QA/gate config component.

That violates AC2's fail-closed requirement: missing or unresolvable project/QA/gate config must reject setup, not produce a digest with an empty component.

Fix direction: enforce project config component validity before digest formation, preferably at the `ProjectRegistration` model/repository boundary and defensively in `_build_execution_contract_digest`. Add a negative setup-boundary test for a registered project with blank/malformed `config_digest`/`config_version`, asserting no ownership record and no digest row.

### MAJOR: ARCH-55 is violated in new code and tests

Files include:

- `src/agentkit/backend/prompt_runtime/execution_contract.py:15`
- `src/agentkit/backend/prompt_runtime/execution_contract.py:49`
- `src/agentkit/backend/prompt_runtime/execution_contract.py:225`
- `src/agentkit/backend/story_context_manager/wire_adapter.py:17`
- `src/agentkit/backend/story_context_manager/wire_adapter.py:292`
- `src/agentkit/backend/story_context_manager/errors.py:103`
- `src/agentkit/backend/control_plane/runtime.py:1210`
- `tests/unit/prompt_runtime/test_execution_contract.py:118`
- `tests/unit/prompt_runtime/test_execution_contract.py:251`
- `tests/unit/story_context_manager/test_wire_adapter.py:305`

Failure scenario: ARCH-55 requires English-only code, identifiers, wire keys, comments, and docstrings. The diff adds German terms in production comments/docstrings and tests: `fachlich tragende`, `Spec-Felder`, `Akzeptanzkriterien`, `Wirkungsklassen`, `Anzeigename`, `Komponentenzuordnung`, `Repo-Affinitaet`, `Vertragsachse`, `Regel`, and `stammdaten`.

Fix direction: translate all new code/test comments and docstrings to English. Concept prose can stay German, but this diff's Python files and test files cannot.

### MAJOR: Spec-Freeze tests do not prove a real load-bearing spec write path

Files: `tests/unit/story_context_manager/test_service.py:733`, `src/agentkit/backend/story_context_manager/patch_handlers.py:80`

Failure scenario: `test_update_story_fields_load_bearing_field_with_active_regime_raises_409` uses `updates={"acceptance": [...]}` and proves the pre-claim freeze gate rejects that key during an active regime. But outside the active regime, `_apply_updates` has no handler for `acceptance`, `need`, `solution`, or the other `StorySpecification` fields; unknown fields are silently ignored. The paired retry test at `tests/unit/story_context_manager/test_service.py:806` succeeds after the regime ends, but it does not assert that acceptance changed because it cannot change through this path.

This does not by itself prove production is fail-open, but it means AC6's "no write" proof is partially proxy-based: the rejected field is not a real writeable spec field on this service path today.

Fix direction: either cover the actual spec mutation path if one exists, or add an explicit test/contract documenting that `StorySpecification` fields are not currently mutable through PATCH and that the freeze gate is intentionally preemptive for future fields. If spec mutation is expected through `update_story_fields`, add the missing typed write path and then prove active-regime rejection leaves the persisted spec unchanged.

## Explicit assessments

### AC4 proxy: second story instead of second run of the same story

Verdict: adequate for current scope, but not a full literal proof of AC4.

Given AG3-149 has not built ownership-end/disown, a genuine second active run for the same story is not currently representable without violating the active ownership invariant. The submitted test still proves the important digest behavior for this scope: an already-persisted run digest remains unchanged after config drift, and a later setup over the same project observes the changed config and gets a different digest. Once AG3-149 exists, add the same-story second-run integration test.

### Story-Spec-Version interpretation

Verdict: sound and spec-faithful.

The current domain has no separate spec version counter. Content-addressing the digest over the authoritative `StorySpecification` fields is at least as strong for drift detection as hashing a monotonic version number, because any persisted content change changes the digest. This is acceptable as long as all load-bearing spec fields are included and real mutation paths are covered by freeze/fence tests.

### Project/QA/gate config interpretation

Verdict: conceptually sound, implementation needs the fail-closed validation from the finding above.

Using `ProjectRegistration.config_version` + `config_digest` as the SSOT is the right model; re-canonicalizing `project.yaml`/QA/gate config inside the digest builder would create a second config truth. However, those two fields must be validated as resolvable config coordinates. A blank or malformed `config_digest` cannot be treated as a valid digest component.

VERDICT: REJECT
