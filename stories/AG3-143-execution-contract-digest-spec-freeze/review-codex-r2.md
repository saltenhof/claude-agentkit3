## Per-Finding Confirmation

### 1) CRITICAL/AC1 -- skill_versions total-order determinism

Resolved: yes.

Evidence:

- `src/agentkit/backend/prompt_runtime/execution_contract.py:128` / `:162` now canonicalizes `skill_versions` with the total key `(skill_name, bundle_id, bundle_version)`, not `skill_name` alone.
- `tests/contract/prompt_runtime/test_execution_contract_digest_format.py:131` reproduces the exact r1 duplicate-name case: `("same", "a", "1")` and `("same", "b", "1")` in both orders. It asserts both canonical strings and computed digests are identical.
- The golden digest test remains unaffected because the golden input uses distinct skill names (`implement`, `review`) and the expected canonical/digest still passes unchanged.
- I found no other unordered multiset in the canonical payload. Story-spec tuple/list fields preserve the authoritative spec order; the remaining digest components are scalar/object fields serialized by sorted JSON keys. Runtime still pre-sorts skill bindings by `skill_name` at `src/agentkit/backend/control_plane/runtime.py:1318`, but the pure canonicalizer re-sorts by the total key, so this upstream ordering is no longer load-bearing.

### 2) CRITICAL/AC2 -- fail-closed malformed/empty project config

Resolved: yes.

Evidence:

- `src/agentkit/backend/control_plane/runtime.py:183` defines the lowercase 64-char SHA-256 regex, and `src/agentkit/backend/control_plane/runtime.py:1285` rejects blank `config_version` or malformed `config_digest` by returning `_ExecutionContractDigestOutcome(digest=None, rejection_reason=...)`.
- That is the same propagation mechanism as missing registration: `_start_phase_after_claim` sees `rejection_reason` at `src/agentkit/backend/control_plane/runtime.py:1080` and returns `_fail_closed_setup_rejection` at `:1094`; the caller releases the won operation/object claims instead of finalizing state.
- Ownership and digest rows are only built in `_finalize_start_phase` after the admitted path (`src/agentkit/backend/control_plane/runtime.py:1508`, `:1530`) and inserted in the same Postgres finalize transaction (`src/agentkit/backend/state_backend/postgres_store.py:3796`, `:3924`). The rejection path never reaches this.
- The two added Postgres phase-boundary tests at `tests/integration/control_plane/test_execution_contract_digest_pg.py:314` and `:341` assert `status == "rejected"`, no active ownership record, and no digest row.
- The decision not to add a `ProjectRegistration` model validator is justified: installer/upgrade/workspace tests still construct non-hex placeholders such as `deadbeef`, `stale-registered-digest`, `some-digest`, and `a-different-registered-digest` (for example `tests/unit/control_plane/test_workspace_locator.py:47`, `tests/integration/installer/test_upgrade_entry.py:90`, `tests/unit/installer/upgrade/test_failclosed_branches.py:66`). `ProjectRegistration` remains the installer registry shape; the execution digest builder is the correct fail-closed boundary for values admitted into the digest.
- The productive HTTP composition uses `ControlPlaneRuntimeService()` without an injected dispatcher (`src/agentkit/backend/control_plane_http/app.py:731`), so the productive setup path lazily binds the real digest builder. I found no productive setup path that still hashes an invalid project config component.

### 3) MAJOR -- ARCH-55

Resolved: yes.

Evidence:

- The German terms cited in r1 are translated in the remediation diff across the Python and test files.
- I ran a broad German-token sweep over every source/test/schema file in `git diff --name-only ad07dbcc..32347b22`, plus a zero-context diff sweep over added lines. Residual full-file hits are pre-existing lines outside the story-added lines, e.g. old comments in `postgres_schema.sql` and old `stammdaten` docstrings in `service.py`.
- The zero-context added-line sweep had no hits for the German terms/tokens searched. I found no new/changed German identifier, comment, docstring, wire key, or error code in the story delta.

### 4) MAJOR/AC6 -- honest freeze proof

Resolved: yes.

Evidence:

- `src/agentkit/backend/story_context_manager/patch_handlers.py:205` shows `_PATCH_HANDLERS` has only story metadata handlers; none of `need`, `solution`, `acceptance`, `definition_of_done`, `concept_refs`, `guardrail_refs`, or `external_sources` has a live PATCH handler.
- `src/agentkit/backend/story_context_manager/service.py:662` / `:664` show the service-side spec write is creation-only via `create_story_atomic`. Repository-level `save_specification`/upsert APIs exist, but I found no service/API route that mutates load-bearing spec fields and bypasses the freeze.
- `tests/unit/story_context_manager/test_service.py:733` explicitly proves the field is inert outside an active regime by comparing the persisted `StorySpecification` before/after an `acceptance` PATCH attempt.
- `tests/unit/story_context_manager/test_service.py:768` still proves active-regime rejection, and `src/agentkit/backend/story_context_manager/service.py:783` runs `_reject_if_spec_frozen` before the idempotency claim. `tests/unit/story_context_manager/test_service.py:845` covers the no-cached-rejection retry behavior.

## New / Residual Findings

None blocking. I did not find a new second source of truth, a Pydantic v2 issue, a blood-type-A import leak in `execution_contract.py`, or new TODO/stub debt in the remediation delta.

Verification run:

- `.venv\Scripts\python -m pytest tests/contract/prompt_runtime/test_execution_contract_digest_format.py tests/unit/prompt_runtime/test_execution_contract.py tests/unit/story_context_manager/test_service.py -q` -> 116 passed
- `.venv\Scripts\python -m pytest tests/integration/control_plane/test_execution_contract_digest_pg.py -q` -> 8 passed
- `.venv\Scripts\python -m pytest tests/unit/story_context_manager/test_wire_adapter.py tests/contract/story_context_manager/test_spec_freeze_error_shape.py -q` -> 68 passed

VERDICT: APPROVE
