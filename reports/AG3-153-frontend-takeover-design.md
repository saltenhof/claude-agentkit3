# AG3-153 — Frontend Takeover: DESIGN FREEZE

Authoritative design contract for the Codex worker. Story:
`stories/AG3-153-frontend-takeover-overlay/story.md`. Size L, ONE story — ships as one unit; the
internal review→fix loop is normal. Hub-free. Deps met (AG3-144/148/151 landed). This freeze fixes the
delegated decisions + corrects three story paraphrase-drifts the scout found. Grounded in the scout
brief (facts file:line-cited); do not re-derive.

## 0. Drifts to honor (concept/code wins over the story paraphrase) + scope decisions
- **Status enum:** the formal contract `frontend-contracts.entity.takeover_approval_request`
  (concept/formal-spec/frontend-contracts/entities.md:1034-1045) has FIVE values
  `pending|approved|denied|expired|invalidated`. Story AC5 lists only four — incomplete paraphrase.
  Follow the FORMAL contract (include `invalidated`; confirm's stale/invalidated-challenge → terminal
  `invalidated`, commands.md:503-529). Do NOT edit the formal spec.
- **`/v1/events/hub` does not exist in code** (only in concept). The real non-project precedent is the
  `/v1/hub` routes + the tenant-scope-bypass in control_plane_http/app.py (non-project GET matched in
  `_handle_get_request` before project matching; tenant middleware runs only for
  `^/v1/projects/{key}/…`, so `/v1/events/governance` is auto-exempt — app.py `_is_project_scoped_path`
  ~:1446, comment ~:1472).
- **state_backend facade layout:** the story's `store/facade.py`/`_public_api_names.py` do NOT exist.
  The real sanctioned 3-file (+mapper) edge: facade fn in `state_backend/story_lifecycle_store.py`
  (+ `__all__`), row fn in `postgres_store/_ownership_rows.py` + the `sqlite_store` twin, re-export
  lines in BOTH `postgres_store/__init__.pyi` and `sqlite_store/__init__.pyi`, mapper in
  `state_backend/persistence_mappers/`. Mirror `list_pending_takeover_approvals_global` /
  `load_takeover_challenge_global` exactly.
- **Frontend test infra = OUT of scope (decision):** there is NO JS test runner (no vitest/jest), no
  frontend tests, no frontend CI stage today; i18n infra is already carved out as separate scope. Do
  NOT stand up a JS test stack. Verification is (1) Python contract/integration/unit tests + (2)
  `npm run build` (`tsc -b && vite build`) clean proving the type-safe frontend. Frontend components
  are R-class slot-fillers (FK-72 §72.4) — their correctness is "renders the contract-pinned data".
  If a specific AC genuinely cannot be met without a rendered-component assertion, STOP and report —
  do NOT silently add vitest.

## 1. Cross-project governance SSE stream (AC1,2,3,13) — reuse, no second schema
- Generalize `telemetry/sse_stream.py`: add a cross-project iterator mirroring
  `iter_project_sse_stream` (:136) but sourcing pending approvals from the EXISTING cross-project read
  `list_pending_takeover_approvals_global(project_key=None)` (story_lifecycle_store.py:390). REUSE the
  SAME envelope path (`_takeover_approval_snapshot_envelope` :223, `render_sse_event` :97,
  `_iter_pending_takeover_approval_events` :190) — the wire schema MUST be byte-identical to the
  project stream (AC1; contract-pin). NO second event definition (SOLL-130).
- Topic filter via `parse_project_topics` (:56): unknown topic → ValueError → route returns
  400 `invalid_sse_topics` (AC2). NO all-topic `/v1/events` (404). Only the `governance` topic subset.
- Route `GET /v1/events/governance` on `telemetry/http/routes.py` + wired in
  control_plane_http/app.py's non-project GET dispatch (peer of the `/v1/hub` GET), text/event-stream,
  lossy unchanged (§91.8.2 — fresh read on reconnect, no cursor).
- **Auth fail-closed (AC3):** strateg-cookie-only. `AuthResult.is_human_bff_session`
  (auth/middleware.py:44) must be true; `project_api_token`/`none` → deterministic reject
  (`_forbidden_response`). CRITICAL: the GET path does NOT currently receive `auth_result`
  (`_handle_get_request(route_path, query, correlation_id)` ~:541) — thread `auth_result` into the GET
  dispatch so the governance route can enforce it. Add a negative test (token/no-session → rejected).

## 2. Merged approvals read model + read-only initial-GET (AC4,5) — the main backend build
- The `takeover_approvals` row alone LACKS the display fields. Build a facade read that JOINS the
  approval (records.TakeoverApprovalRecord) with its challenge via `challenge_ref`
  (records.TakeoverChallengeRecord + per-repo TakeoverChallengeRepoRecord) and projects EXACTLY the
  formal entity `takeover_approval_request` (entities.md:949-1057, schema_version 3): `approval_id`,
  `challenge_id` (wire key for `challenge_ref`), `project_key`, `story_id`, `run_id`,
  `requested_by_principal`, `reason`, `owner_session_id`, `ownership_epoch`, `binding_version`,
  `phase`, `last_api_contact_at` (optional), `open_operation_ids`, `repo_push_status`
  (list `{repo_id,last_pushed_head_sha,last_push_at,push_lag_hint}` — NO dirty field), 
  `takeover_history_count`, `status` (5-value enum), `requested_at`, `expires_at` (optional).
  Challenge fields come from the OWNER BC (records/models), not lagging read-models (AC5).
- New read-only endpoint (non-project-scoped, strateg-cookie-only, same auth rule as §1) returning the
  cross-user open approvals in this shape. Path per FK-91 conventions (e.g.
  `GET /v1/governance/takeover-approvals`). Must answer within the 12s client budget (api.ts:156).
- **§91.8.2 re-sync (AC4):** the frontend calls this initial-GET on EVERY connect + reconnect; overlay
  state never depends on the lossy SSE alone. Must reconstruct "approved but a fresh challenge awaits
  confirm": the read returns the approval + its currently linked `challenge_id`, reopening the confirm
  step.
- **`expired`/`invalidated`/`denied` = decision-lifecycle only, ZERO ownership effect** (AC9; negative
  test: ownership record unchanged).

## 3. Concept nachzug (small) + dogfood W4
- §91.8.1 governance SSE row + §91.8.2/§91.8.3 ALREADY exist (91_api_event_katalog.md:682, :703-732).
  The ONLY nachzug: add ONE conformal read-only row to the §91.1a endpoint table (3 columns
  `| Endpoint | Methode | Beschreibung |`, ~:99) for the approvals initial-GET, pointing at
  `frontend-contracts.entity.takeover_approval_request`.
- Editing 91_*.md is an in-scope normative concept change → the new AG3-158 W4 gate applies. DOGFOOD
  it: author `concept/_meta/decisions/<today>-frontend-takeover-approvals-read.md` (frontmatter EXACTLY
  per the two precedents; concept_id META-DEC-<DATE>-...) OR add a `Concept-Decision:` trailer to the
  commit. Prefer the record. Keep AG3-157 reference-integrity green (any anchor/id/path resolves).

## 4. Frontend (AC4,6-13) — App.tsx state + Shell slot + two components
- **Second EventSource** on `/v1/events/governance?topics=governance` in App.tsx, MODELED on the
  project SSE effect (:194-229) but the existing project stream + its subscription stay UNTOUCHED
  (AC13, regression test the project effect is unchanged). `withCredentials:true`. onmessage:
  `takeover_approval_changed` → open/refresh/close overlay per status (pending→show; approved WITH a
  fresh pending challenge→confirm step; denied/expired/invalidated→close/refresh); an `approved` event
  ALONE never closes the overlay (SOLL-104). On connect/reconnect → fresh initial-GET (§2).
- **api.ts:** `request_story_run_takeover` (POST `…/ownership/takeover-request`; inputs run_id + reason
  (required) + client-minted `op_id` via `makeOpId` :225; NO frontend event — challenge returns
  synchronously; typed 409 not-admissible / 403 / 404 / idempotency_mismatch) and
  `confirm_story_run_takeover` (POST `…/ownership/takeover-confirm`; inputs run_id + `challenge_id`
  selector + new `op_id`; response may be `challenge_reissued` (HTTP 200, NOT an error) → second
  confirm with a new op_id, no transfer on the first; human-EXCLUSIVE: any non-human auth → 403;
  409 on stale/invalidated challenge). Plus the approvals initial-GET. All inside the 12s
  AbortController budget (:156). Typed `ApiError{status,errorCode,correlationId}` (:6).
- **Shell overlay slot (AC6):** `Shell.tsx` hosts an overlay region as a new unconditional top-level
  child of `<main className="shell">` (peer of DetailInspector), driven by data/actions props — the
  Shell makes NO domain decision (FK-72 §72.4 R-clause). Content comes from the story slice.
- **`TakeoverApprovalOverlay.tsx`** (new, contexts/story_context_manager/components/ or a new
  governance slice): renders the challenge incl. the **loss-corridor mandatory text UNABRIDGED with the
  concrete per-repo `<sha>`** (AC7 — sourced from the challenge's `loss_corridor_notice_text`/`_key`
  fields, models.TakeoverChallenge:384; NO confirm path bypasses it). Confirm sends the DISPLAYED,
  server-stored `challenge_id` (AC8). Cross-user + immediate: opens for EVERY logged-in session (AC6).
  Reject/expire → request lapses, never revokes ownership (AC9).
- **`TakeoverPanel.tsx`** (new, cockpit view in DetailInspector as a story-slice tab): ownership
  (owner session, principal, `ownership_epoch`), "last active" WITH the explicit non-diagnosis hint
  (info, never a trigger), open jobs + op_ids + phase, per-repo `last_pushed_head_sha` + push freshness
  (`last_push_at`/`push_lag_hint`) and post-transfer `takeover_base_sha` as the responsibility boundary
  — NO dirty/local state anywhere (AC10, FK-10 §10.2.4a), takeover history prominent (ping-pong
  visibility). The four edge states (`takeover_reconcile_required`, `contested_local_writes`,
  `remote_branch_diverged_after_takeover`, `local_stale_or_dirty_takeover_target`) rendered as distinct
  BLOCKING named states with a plaintext resolution-path hint; MISSING state signal → fail-closed
  "unknown" render, never a green default (AC11). Display-only (AG3-151 owns semantics).
- **DetailInspector.tsx:** wire the cockpit panel as a new story-slice tab (extend the tab union + nav
  button + section, mirroring :98-139).

## 5. Verification (AC14) — Python contract/integration + tsc/vite build; NO JS runner
- **Contract (tests/contract/):** governance-stream envelope byte-identical to the project stream
  (AC1); approvals read-model field-exact to the formal entity incl. 5-value status + repo_push_status
  + NO dirty field (AC5, AC10); both command contracts incl. `challenge_reissued` + error codes
  409/403/404/idempotency_mismatch (AC12); loss-corridor text present in the challenge projection (AC7).
- **Integration (tests/integration/, Postgres fixture):** an approval in project Y is visible on the
  global stream + initial-GET WITHOUT selecting project Y (AC1); auth negative — token/no-session
  rejected (AC3); lossy re-sync after a simulated drop + reconnect, incl. "approved + fresh challenge
  pending" reopening the confirm step (AC4); reject/expire leaves the ownership record unchanged (AC9).
- **Unit (tests/unit/telemetry, tests/unit/control_plane):** stream composition / topic filter / auth
  decision over ports/fakes.
- **Build:** `npm run build` (`tsc -b && vite build`) clean (AC14) — proves the frontend compiles
  type-safely against the contract types. Keep new TS strictly typed.
- Backend gates: `pytest --ignore=tests/e2e`, ruff, mypy strict native + `--platform linux`, coverage
  ≥85%, the 4 concept gates (W1 reference-integrity + W4 decision-record must stay green — the §91.1a
  change needs the dogfood record/trailer). Postgres-only fail-closed via
  `_require_postgres_control_plane_backend`.

## 6. Blood types + review plan
Backend stream composition / topic filter / wire mappers / read-model projection = R; state_backend
read adapter = AT/T (localized there); frontend modules = R with T (browser APIs) — NO A-logic in the
frontend (FK-72 §72.4; domain statements come only from the owner BC). Worker owns green-on-main.
Then Codex read-only review + orchestrator code-adjudication → whole-story Fable finale (this IS a
runtime/auth/fail-closed surface — focus: strateg-cookie-only enforcement is truly fail-closed incl.
the GET auth_result plumbing; cross-project isolation (no project-scoped leakage); read-model field-
exactness + NO dirty field; loss-corridor text un-bypassable; reject/expire/invalidated = zero
ownership effect; envelope byte-identity) → Jenkins + Sonar 0/0/0 on the final commit. Serialize: no
orchestrator git/gate ops while the worker is active on the shared tree.
