# AG3-131 — CCAG Permission-Requests/Leases + Mode-Lock central Postgres owner: DESIGN FREEZE

Authoritative design contract for the Codex worker. Story:
`stories/AG3-131-ccag-permission-modelock-central/story.md`. Size L, BC governance-and-guards. ONE
story. NOT LLM/hub-touching → no smoke-test concern, but REAL Postgres integration tests are mandatory
(the story forbids SQLite-only/mock-only for the core persistence). Dep AG3-129 = completed (hook is
already a REST requester). Grounded in the scout brief (facts file:line-cited); do not re-derive.

## 0. What this is
Move the CANONICAL runtime state — CCAG permission requests, permission leases, and the project
mode-lock HOLDER identity — from project-local SQLite/marker files into the central Postgres
state-backend (FK-10 I5 / §10.3.1 / §10.3.2). Local files become discardable short-TTL READ
PROJECTIONS; canonical truth is central; missing/divergent projection → fail-closed (no fallback to
local truth). The hook is a REST requester/reader (builds on AG3-129 `GovernanceEdgeClient`), never a
canonical writer. Blood types: schema + repositories + policy + models = A; REST/wire mappers = R;
SQLite projection + hook REST transport + file/CI = T. Governance code reaches central state via
INJECTED ports (DI), never importing `state_backend.store` directly (mirror the ModeLockRepository /
takeover-read wiring).

## 1. Central Postgres tables (AC1, AC2) — align to the formal-spec entities, close the gaps
Contract-pin against `concept/formal-spec/principal-capabilities/entities.md`. Today's SQLite tables are
WEAKER — add the missing fields.
- **`ccag_permission_requests`** (identity `request_id`): `request_id, project_key, story_id, run_id,
  principal_type, tool_name, operation_class, path_classes, request_fingerprint, status, requested_at,
  expires_at, resolution` (+ decided_at/decision_note as audit). Status `pending|approved|denied|
  expired`; `resolution` per §55.10.9a. Add the fields absent today (project_key, principal_type,
  operation_class, path_classes, request_fingerprint, resolution).
- **`ccag_permission_leases`** (identity `lease_id`): `lease_id, request_ref, project_key, story_id,
  run_id, principal_type, tool_name, operation_class, path_classes, request_fingerprint, max_uses,
  consumed, issued_at, expires_at`. Binding key (§55.9a): project_key+story_id+run_id+principal_type+
  tool_name+operation_class+path_class+request_fingerprint. `max_uses` (default 1) REPLACES today's
  hard-coded consume-once; `consumed` counts against `max_uses`.
- DDL in BOTH `postgres_store/postgres_schema.sql` (canonical) AND the parallel
  `sqlite_store/_schema_runtime.py` (test parity only). New repositories under `state_backend/store/`
  (mirror `mode_lock_repository.py` for the CAS/write idiom + the takeover-read for the read idiom):
  facade + row fns (postgres + sqlite twin), `persistence_mappers.py` mapper, backend `.pyi` if a new
  row fn is exposed. Postgres is canonical (`_is_postgres()` branch); fail-closed via
  `_require_postgres_control_plane_backend` where the story's I5 canonical path applies.

## 2. Mode-lock holder identity (AC4) — central, not the local marker
`project_mode_lock` (project_key, active_mode, holder_count) records HOW MANY + which mode, not WHICH
story. Add a holder-identity dimension: a child table
`project_mode_lock_holders(project_key, story_id, run_id, mode, acquired_at)` (PK project_key+story_id+
run_id). Extend `ModeLockRepository.acquire/release` (mode_lock_repository.py:252/:283) to INSERT/DELETE
the holder row ATOMICALLY within the SAME CAS transaction (pg_advisory_xact_lock+FOR UPDATE / sqlite
BEGIN IMMEDIATE). Re-entry (same story re-acquires) = idempotent (ON CONFLICT on the holder PK, no
double-count). `holder_count` stays consistent with the holder set (derive it or keep it in lockstep —
no second truth). Release removes only the commanding story's holder row + decrements. The local
`mode-lock-acquired` marker becomes a READ PROJECTION; central holder identity is the recovery truth
(pair acquire↔release centrally, not via the marker).

## 3. Backend REST + hook seam (AC3) — auth split, fail-closed
- Extend the hook-side `harness_client/projectedge/governance_client.py` `GovernanceEdgeClient` (on the
  shared `HttpsJsonTransport`, no psycopg/DSN) with: open-request, read-request(s), consume-lease
  (hook/project-token path); the human resolve-request + grant-lease are strateg-side.
- Backend routes in `control_plane_http`: POST writes mirror the AG3-129
  `/v1/governance/guard-counters` block in `_handle_post_request` (app.py:757-763) —
  `/v1/governance/permission-requests` (open/resolve), `/v1/governance/permission-leases`
  (grant/consume); reads via a small route class mirroring `TakeoverApprovalRoutes` or a GET in
  `_handle_get_request`. Pydantic request models in `control_plane/models.py`; errors via
  `_error_response`/`_backend_requirement_response` (422 op_id, 409 idempotency, 503 unavailable).
- **AUTH SPLIT (fail-closed):** the HOOK (auth_kind `project_api_token`) may OPEN a request, READ its
  own requests, and CONSUME a lease. The HUMAN decision — RESOLVE a request (approve/deny) and GRANT a
  lease — is strateg-cookie-only (`AuthResult.is_human_bff_session`), rejected for project-token/none
  BEFORE any state mutation (mirror `TakeoverApprovalRoutes.handle_get:44` + admin-abort app.py:1257).
  A grant creates ONLY the lease and does NOT auto-resume (§55.9a).

## 4. THE fail-closed fix (AC3 tail, ZERO DEBT) — eliminate the best-effort no-op
`governance/runner.py:1948-1982` `_block_with_permission_request` currently does
`try: ... open_permission_request(...) except Exception: request_id = None` and reports
`permission_request_opened=False` while still blocking — an invisible, un-resumable block (the human
sees no inbox row). REPLACE with a VISIBLE fail-closed outcome: when the request cannot be persisted
centrally (REST/persistence failure), surface the fault explicitly (a named error / a distinct
`permission_request_persist_failed` state on the block detail), NOT a silent `False`. A block without a
persisted central request is a named fault, never a silent downgrade. NOTE: the secondary escalation
swallow at runner.py:2235-2242 (`_escalate_expired_permission_requests`) is LEGITIMATELY best-effort
per the lazy-expiry rule (§55.10.9a) — leave it. Reproducing test: a persist/REST failure on request
open fails VISIBLY closed (asserted fault), not `permission_request_opened=False`.

## 5. Local files → read projections (AC5) — no second truth
`ccag_requests.db` (requests.py), the per-story lease SQLite (leases.py), the `mode-lock-acquired`
marker, and `.agent-guard/permission_state.json` (§55.10.4a) are NO LONGER canonical. They may remain
as discardable, short-TTL, hook-read fast-path artifacts, but canonical truth is central Postgres; if
the projection is missing/divergent the run is FAIL-CLOSED — NEVER falls back to the local SQLite/marker
as truth (own negative test). Do NOT introduce any new local canonical write path. Do NOT touch the
project-local CCAG rule YAML (`.agentkit/ccag/rules/`) — rules stay local config (FK-42 §42.7); only
requests/leases/mode-lock move.

## 6. Deterministic lazy expiry (AC6) — central owner
Request expiry is deterministic + LAZY (§55.10.9a): NOT daemon-driven; materialized at the next
hook/CLI access; an un-decided expired request → deterministic `DENIED` (no new rule/lease). The
central owner carries `requested_at`/`expires_at`/`resolution`; the existing escalator wiring
(runner.py:2191-2242) reads from the central owner. Test an expired request lazily materializes DENIED.

## 7. Concept nachzug + dogfood W4 (AC7)
Add the new endpoint rows to `concept/technical-design/91_api_event_katalog.md` §91.1a (3-col
`| Endpoint | Methode | Beschreibung |`) and pin the `principal-capabilities` formal-spec
(entities/commands/invariants/events) to the new central contracts. These are normative concept edits →
the W4 decision-record gate WILL trip: author `concept/_meta/decisions/2026-07-14-ccag-central-owner.md`
(frontmatter EXACTLY per precedent; concept_id META-DEC-2026-07-14-CCAG-CENTRAL-OWNER) OR a
`Concept-Decision:` trailer (prefer the record). Keep W1 reference-integrity green; state/schema changes
pull the contract/golden tests (CLAUDE.md).

## 8. Tests (AC1-6) — REAL Postgres, mandatory
Use the `postgres_isolated_schema` fixture (tests/fixtures/postgres_backend.py — ephemeral port, never
5432). Mirror tests/integration/governance/** + tests/integration/control_plane_http/
test_takeover_frontend_read_pg.py. Required: (1) request persisted+read server-mediated against real
Postgres (NOT SQLite/mock); (2) lease granted+consumed server-mediated incl. max_uses; (3) real
hook→REST integration (no route mock) + the fail-closed persist-failure test (§4); (4) mode-lock holder
identity central + re-entry/concurrency correct; (5) projection missing/divergent → fail-closed, no
local fallback; (6) expired request lazily DENIED; (7) auth split — hook token rejected for resolve/
grant (strateg-only), before any mutation. Contract/golden tests for the formal-spec entities.

## 9. Green-on-main + review plan
Worker owns green: pytest (unit/integration/contract, ex-e2e), ruff, mypy strict native + --platform
linux, coverage ≥85%, the concept gates (W1/W4 green — the 91_*.md + formal-spec edits need the dogfood
record), + the remote gates (Jenkins green + Sonar 0/0/0). Then Codex read-only review + orchestrator
code-adjudication → whole-story Fable finale (this IS a fail-closed/auth/ownership surface — focus:
the persist-failure fails VISIBLY closed not silently; auth split truly rejects the hook token for
resolve/grant before mutation; projection missing → no local-truth fallback; mode-lock holder
re-entry/release-ownership atomic; no second canonical write path survives) → Jenkins + Sonar 0/0/0 on
the final commit. Serialize: no orchestrator git/gate ops while the worker is active on the shared tree.
