# Handover for Next Codex Agent

This file is the operational handover for the next agent continuing work in
`claude-agentkit3`.

It is not optional context. Read it before making architectural or larger code
changes.

## Current Repo State

- Branch: `main`
- Head at handover time: `e04c398cf5cc5f46350e2885c4b7c9fea7d00afd`
- Worktree was clean when this handover was written.

Recently completed large slice:
- Canonical runtime/build/contract/integration truth was moved off JSON-file
  reads and onto the state backend.
- Real contract/integration/e2e test paths now run on Postgres.
- Jenkins now has a dedicated Postgres stage for contract/integration/e2e.
- SQLite is now fail-closed unless explicitly enabled for narrow unit tests.

## User Priorities and Non-Negotiables

These are not style preferences. Treat them as operational constraints.

1. Concepts are normative.
- Do not implement behavior that deviates from the concepts just because the
  legacy code is easier.
- If code and concept conflict, fix the code or first fix the concept
  explicitly. Do not silently improvise.

2. Quality is the primary criterion.
- Do not optimize for speed or “quick pragmatic hacks” at the expense of
  architecture.
- The user explicitly does not want “fast now, clean later” behavior.

3. Avoid tiny, stop-start micro-slices.
- The user is frustrated by 20-30 line edits followed by frequent “next step”
  chatter.
- Prefer larger, coherent slices that actually remove a class of drift or
  complete a meaningful subsystem step.

4. Keep the repo clean.
- Do not leave a degenerating dirty worktree.
- At logical stopping points, changes must be committed and pushed, or
  intentionally ignored if they are local-only artifacts.

5. DB truth, not JSON truth.
- JSON files are not canonical runtime truth.
- JSON projections are allowed only as export/projection/interop/debug
  artifacts.
- Governance/runtime/verify/closure decisions must not read truth from JSON
  files.

6. Postgres is the real backend.
- Postgres is the only acceptable canonical backend for runtime, real build,
  contract tests, integration tests, and e2e tests.
- SQLite is tolerated only for narrow, isolated unit tests.
- Never let SQLite become a silent fallback for real runtime or real CI paths.

7. `ai_augmented` mode is outside AgentKit governance.
- AK3 governs the clean exit from `story_execution`.
- AK3 does not try to over-model or govern free human-led work after that exit.

8. Use multi-LLM sparring when beneficial, but do not block on it.
- Repo-level instruction says to use `llm_hub` whenever multi-LLM sparring or
  cross-model review helps.
- However, if the hub is temporarily unavailable or the user says not to use
  it in that moment, continue locally instead of stalling.

## Architectural Positions Already Clarified

### 1. Formal concept layer

The repo now has:
- `concept/formal-spec/`
- `tools/concept_compiler/`
- CI compile/lint checks for the formal spec

The formal layer is meant to be deterministically checkable. It is not just
documentation garnish.

### 2. Truth boundary

The user explicitly rejected any architecture where JSON files are treated as
runtime truth.

Current direction:
- canonical truth in DB / canonical record families
- file artifacts are only projections or exports
- concept-to-code truth-boundary checks exist and must remain strict

### 3. Prompt architecture

The prompt path was reworked substantially.

Current intended model:
- central canonical prompt bundle store
- project-local prompt exposure under `prompts/` is projection/binding, not
  authority
- runtime authority comes from bundle lock + run pin + canonical store
- project-local prompt copies/projections must never become truth

Important nuance:
- On Windows and across filesystem boundaries, installer prompt projection may
  now fall back from hardlink -> symlink -> copy.
- That fallback is operationally tolerated only because runtime authority stays
  in the canonical store and not in the project projection.
- Do not regress this into “project prompt files are source of truth”.

### 4. Operating modes

The clarified cut is:
- `story_execution` is governed by AK3
- `ai_augmented` is not governed as a detailed AgentKit workflow
- AgentKit owns the clean exit from story execution into free human-led work,
  not the human-led work itself

### 5. Integration stabilization

Late-stage whole-system integration was clarified as a distinct contract
problem:
- not a free-for-all
- not endless scope inflation
- but also not a trivial normal story

There is concept work around:
- `integration_stabilization`
- clean story exit / human takeover when the problem turns into solution
  evaluation rather than bounded stabilization

## What Was Just Finished

The last major code slice was the Postgres truth lift.

### Implemented

- `src/agentkit/state_backend/store.py`
  now dispatches to backend implementations.
- `src/agentkit/state_backend/postgres_store.py`
  introduced a real psycopg-backed Postgres implementation.
- `src/agentkit/state_backend/sqlite_store.py`
  keeps the narrow unit-test backend path.
- `src/agentkit/state_backend/config.py`
  now fail-closes SQLite unless explicitly allowed.
- `tests/contract/`, `tests/integration/`, `tests/e2e/`
  auto-bind to Postgres via Docker-backed fixtures.
- `tests/unit/state_backend/test_config.py`
  asserts the fail-closed backend-selection policy.
- `Jenkinsfile`
  now has:
  - unit tests with `AGENTKIT_STATE_BACKEND=sqlite` and
    `AGENTKIT_ALLOW_SQLITE=1`
  - separate Postgres contract/integration/e2e stage

### Important bug classes uncovered and fixed

1. Shared-DB scoping bugs
- loaders had unscoped `LIMIT 1` behavior that only “worked” under per-story
  SQLite
- this was fixed for story-context, phase-state, and flow-execution reads

2. Incorrect uniqueness model
- `attempt_id` was treated as globally unique
- in a shared Postgres store this is wrong
- global uniqueness was removed

3. Test drift toward file-truth
- integration tests were still asserting file-tree artifacts like
  `phase-runs/...`
- they were moved toward canonical backend reads such as:
  - `load_attempts(...)`
  - `load_phase_snapshot(...)`

## Verification State of the Last Completed Slice

These were green at the end of the last slice:

- `pytest tests/contract tests/integration tests/e2e -m "not requires_gh"`
  - `104 passed, 18 deselected`
- targeted unit slice
  - `144 passed`
- targeted `ruff` over the changed slice
  - green
- `python scripts/ci/compile_formal_specs.py`
  - green
- `python scripts/ci/check_concept_code_contracts.py`
  - green
- `git diff --check`
  - clean

## Known Follow-Up Debt

These are not necessarily bugs right now, but they are good next candidates.

1. The Postgres state backend is still a pragmatic adapter cut.
- It is much better than JSON truth or SQLite-only reality.
- But it is not yet guaranteed to be the final, concept-perfect FK-18 style
  relational design.
- Expect further alignment work around true canonical table families,
  `project_key`, and scope handling.

2. `story_dir` is still a strong runtime boundary.
- There is groundwork for explicit scope handling, but the public state-backend
  facade still largely revolves around `story_dir`.
- This may need further tightening if the concept model wants more explicit
  runtime scope objects.

3. Telemetry/analytics truth-boundary work is still a likely next area.
- There are still SQLite traces in telemetry storage code.
- The next serious truth-boundary review should probably look there.

4. Prompt projection fallback is operationally ugly.
- It is acceptable only because runtime authority remains elsewhere.
- If you touch prompt runtime or installer again, preserve the authority split.

## Recommended Next Step

The most plausible next substantial slice is:

### Option A: Telemetry / analytics / projection truth-boundary

Reason:
- the DB-truth and Postgres runtime cut is now in place for the core runtime
- telemetry/storage/projection areas are the next likely place for the same
  drift class to reappear

If taking this path:
- use the concept-to-code contract checker mindset aggressively
- extend checks if needed
- remove any remaining places where projections masquerade as runtime truth

### Option B: Deeper Postgres alignment to the formal relational concept

Reason:
- current Postgres backend is operationally real, but not yet necessarily the
  final concept-perfect relational shape

If taking this path:
- align carefully against:
  - `concept/technical-design/18_relationales_abbildungsmodell_postgres.md`
  - `concept/formal-spec/state-storage/`
- avoid replacing working behavior with a broad rewrite unless the contract gain
  is clear and verified

## How to Work in This Repo

1. Before substantial work, inspect the current code and concept state.
2. If a task benefits from cross-model review, use `llm_hub` unless currently
   unavailable or explicitly disabled by the user for that moment.
3. Prefer meaningful slices over constant “what next?” interruptions.
4. Verify thoroughly before claiming a slice is done.
5. Do not leave the repo dirty at a logical stopping point.

## What Not To Do

- Do not reintroduce JSON-file truth for runtime/governance decisions.
- Do not allow SQLite to slip back into real runtime/build/contract/e2e paths.
- Do not over-model `ai_augmented` mode inside AK3.
- Do not treat legacy file artifacts as authoritative just because they still
  exist.
- Do not prioritize convenience over the normative concepts.
- Do not chip away in tiny cosmetic edits while leaving the real drift intact.
