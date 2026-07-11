# AG3-154 — CLI/admin commands + edge-tool + recover-story: frozen design

**Status:** FROZEN implementation contract. Feasibility verified at main@c77b706d (scout + orchestrator
code-adjudication of the two load-bearing claims: confirm-auth is BFF-session-only; acquired_via=recovery
is enum/schema-only writer-less). Two design decisions were adjudicated by a concept-grounded Fable ruling
(citations below); ONE product/concept-conflict item is escalated to the human and ships fail-closed until
answered. `story.md` loci are STALE (cli/main.py decomposed; ownership/takeover reworked by 148/149/150/151)
— coordinates below are ground truth. If a decision conflicts with the concept, STOP and report.

## 0. Adjudicated coordinates (HEAD)
- CLI: `backend/cli/main.py` is a 223-line dispatcher (main() :71, subparser :96-105, dispatch :129-161);
  commands in `story_commands.py`, `operator_recovery_commands.py` + `_operator_recovery_admin.py`
  (admin-abort EXISTS: `_cmd_admin_abort` `_operator_recovery_admin.py:18-84` — the adapter template),
  `installer_commands.py`, `lifecycle.py`, `evidence_commands.py`. CLI commands are THIN REST adapters over
  `ProjectEdgeClient` (HTTP), never in-process core.
- Takeover backend: `evaluate_takeover_confirm` (`control_plane/ownership_transfer.py:248`), `LOSS_CORRIDOR_TEXT`
  (:28-33), `OwnershipBasis` (:60-74), ping-pong `evaluate_disowned_session_takeover_barrier` (:326, codes
  DISOWNED_SESSION_CANNOT_IMMEDIATELY_RECLAIM :48 / REPEAT_TRANSFER_REQUIRES_PRIVILEGED_PRINCIPAL_AND_REASON :51).
  Runtime: `runtime/_ownership_transfer.py` confirm_ownership_takeover :271, request_ownership_takeover :222.
  HTTP: `control_plane_http/takeover_handlers.py` request :152 / confirm :215 / dispatcher :38.
- Confirm auth (VERIFIED): confirm requires `auth_result.is_human_bff_session` else 403 agent_confirm_forbidden
  (`takeover_handlers.py:227-237`), stamps `confirmed_by_principal=HUMAN_CLI` :249; runtime requires
  `confirmed_by_principal is HUMAN_CLI` (`_ownership_transfer.py:278`). `is_human_bff_session == auth_kind=="strategist_session"`
  (`auth/middleware.py:45-47`), a session-cookie login. Strategist login infra EXISTS: `auth/http/routes.py`,
  `auth/credentials.py`, `auth/entities.py` (FK-15 §15.10.3).
- Recovery slot: `acquired_via` enum SETUP/TAKEOVER/RECOVERY (`ownership.py:81-86`), DB CHECK allows 'recovery'
  (`postgres_schema.sql:326-327`), mapper round-trips (`persistence_mappers/_control_plane.py:169,195`). NO writer
  mints recovery (SETUP at `_admission_start_phase.py:747-758`; TAKEOVER CAS at `_takeover_rows.py:60`). New-run-on-
  existing-worktree precedent: `reset-escalation` mints new run_id reusing story_dir (`runtime/_admission_dispatch.py:49-51`).
  disown baustein `disown.py:49` (recovery becomes its 5th caller).
- Edge tool: `bundles/target_project/tools/agentkit/projectedge.py` — agent commands :87-120 (phase-*, sync,
  create-story, run-commands :113 delegating to shared `harness_client.projectedge.process_open_commands`
  :34/:380-388 — SINGLE SOURCE OF TRUTH). op_id helper `_client_op_id` :436-444. Transport on `client.py`:
  admin_abort_operation :685, reconcile_takeover_worktree :946 (no takeover_request/recover yet).
- Principal: `HUMAN_CLI` PRIVILEGED (`principals.py:61-67`), assumable only via explicit service attestation.

## 1. Settled design decisions (Fable ruling, concept-grounded, orchestrator-adjudicated)

### D1 — recover-story semantics (CONCEPT-DERIVABLE; AG3-154 owns recovery)
- **New run, existing worktree** (FK-20 §20.7.4, FK-10 §10.6.1): recovery mints a NEW run_id + a
  `RunOwnershipRecord(acquired_via=RECOVERY)` on the existing worktree/story_dir. (Takeover differs: same run_id,
  new ownership_epoch.)
- **Explicit human command only, NO automatism** (FK-10 §10.6.2, FK-20 §20.7.2, invariant
  `ownership_transfer_requires_explicit_confirmed_request` "…or recovery and never through timeout/heartbeat").
- **Precondition (fail-closed, precise):** admissible ONLY when EXACTLY ONE active `RunOwnershipRecord` for the
  story exists (the orphaned claim) — recovery SUPERSEDES precisely it. NOT "no active record" (a crashed run's
  record is still active). If NO active record → nothing to recover → hard-refuse (restart = normal setup). Plus:
  serialized behind in-flight story mutations (FK-56 §56.13 Grundsatz 4 — refuse/wait at the fence, no two-writer
  window); human_cli-attested principal + mandatory `reason` + op-class `admin_transition` + full audit.
- **Freeze BLOCKS recovery** (FK-56 §56.13f, invariant `freeze_states_are_admission_blockers_and_invalidate_challenges`):
  recovery is a story mutation and is NOT a sanctioned resolution command of any AG3-150 freeze; an active blocking
  freeze (conflict/contested/split/repair) OR an unreconciled takeover_reconcile obligation → hard-refuse 409 with a
  DISTINCT machine-readable reason. Recovery resolves no freeze (NO ERROR BYPASSING).
- **Supersede mechanics:** the old active record is NEVER deleted — it transitions to a terminal status in the SAME
  unit of work that inserts the recovery record. Use an EXISTING AG3-137 record-status enum value (prefer
  `transferred`, currently writer-less; if the enum disagrees, follow the enum — NEVER invent a value; a genuinely
  new value is a formal.state-storage migration to DECLARE, not smuggle). Old binding revoked via the AG3-149 disown
  baustein (5th caller, own reason vocabulary), edge tombstone + deterministic reconcile answer. Epoch fencing +
  at_most_one_active_ownership_per_story fence out a late-returning "crashed" session (no liveness heuristic — inactivity
  is not a diagnosis).
- **Übernehmen/Verwerfen** (FK-20 §20.7.3): worktree unchanged on Übernehmen; Verwerfen physical reset runs as an
  AG3-145 edge job, never a backend git subprocess.
- **Four abuse barriers** (all pinned): (1) human-exclusive trigger; (2) recovery routes through the AG3-149
  CAPABILITY-layer ping-pong enforcement (disowned_session_cannot_immediately_reclaim covers the whole transfer
  family — negative test); (3) supersede-only-the-active-record (a disowned ex-owner has no orphaned active claim;
  recovery against a story someone else actively owns = the competing-active-owner hard-refuse → operator uses
  takeover); (4) audited admin_transition, visible in future challenges.

### D1(e) — SOLL-091 co-sign-free agent self-rebind: ESCALATED, ships fail-closed
FK-56 §56.13g mandates "no human co-sign for the SAME harness identity" self-rebind IN PROSE, but (1) NO attestable
"stable harness identity" primitive exists anywhere in the concept (a restarted harness has a NEW session_id;
FK-55 §55.3a: absent proof → fail-closed most-restrictive), and (2) FK-56 §56.13g vs FK-20 §20.7.3 (Übernehmen/
Verwerfen is human-decided) are UNRECONCILED. **Safe 154 scope:** the edge-tool `recover` adapter exists, but the
server DETERMINISTICALLY REFUSES agent-principal recovery with a machine-readable reason (`recovery_requires_human_cli`);
recovery is NOT wired into the approval queue. This is a fail-closed application of FK-55 §55.3a, safe under EITHER
eventual human answer. **The freeze NAMES this** (ZERO DEBT): SOLL-091's co-sign-free clause is dormant pending the
human decision. ESCALATION QUESTION (mirrored to the human, non-blocking): "FK-56 §56.13g promises co-sign-free
self-rebind for 'the same harness identity', but no attestable stable harness-identity primitive exists and FK-20
§20.7.3 reserves the take-over/discard choice for the human. (A) build the identity primitive + agent-side decision
rule as a NEW story, or (B) narrow/strike §56.13g so agent recovery always requires human approval?" Until answered,
agent recovery = refused.

### D2 — CLI takeover-confirm auth (CONCEPT-DERIVABLE): strategist session, gates untouched
CLI confirm IS concept-intended (FK-56 §56.13b: "Menschlich initiierte Takeovers (UI/CLI) durchlaufen denselben
informierten Challenge-Dialog direkt … admin_transition, auditiert"; FK-91 §91.1a: human_cli gets the challenge
directly). Concept-correct auth = **option (i): the operator CLI obtains a GENUINE strategist session via the
existing FK-15 §15.10.3 login (password → session cookie + CSRF) and confirms through the UNCHANGED human-BFF-session
gate.** The AG3-148 two-layer gate (HTTP is_human_bff_session + runtime HUMAN_CLI) stays byte-identical. **Option (ii)
— a new boundary-attested human_cli HTTP token — is RULED OUT** (adds a 4th FK-15 §15.10.2 identity class; contradicts
Decision-Record §7.3 + the formal confirm 403 contract "any non-human auth incl project_api_token → 403"; weakens
"agent can never confirm"; a standing human-power token is an exfiltration target — FIX THE MODEL: the human's
credential IS the local strategist password/session). `--ak3-principal-attest` is an INNER-layer PrincipalResolver
attest and proves NOTHING at the HTTP boundary — do NOT use it for HTTP confirm. Single-user/single-tenant + loopback
BFF (FK-15 §15.10.1) makes the same-host CLI login natural.

## 2. Implementation plan — TWO increments
Each increment owns green-on-main and is review-converged (Codex + orchestrator code-adjudication + Fable finale)
before the next; the story closes only after both + full DoD.

- **Increment 1 — Backend recovery acquisition (the only A-logic).** New recovery endpoint (or a declared recovery
  variant of the ownership routes) under `control_plane_http/`; A-core recovery admissibility (supersede-the-one-
  active-record precondition, freeze/obligation hard-refuse with distinct codes, mandatory reason, human_cli-only);
  mint new run + `RunOwnershipRecord(acquired_via=RECOVERY)` + terminalize the superseded record (existing enum value)
  + revoke old binding via disown (5th caller) — ALL in one unit of work (no crash window); recovery routes through
  the AG3-149 capability ping-pong enforcement; agent-principal recovery refused fail-closed (`recovery_requires_human_cli`).
  Transport method `recover` on `client.py`. FK-91 §91.1a recovery endpoint row + formal writer pin for the terminal
  status if the formal command set requires it (DECLARE, don't smuggle). Contract/integration tests over the REAL
  crash→dispatch fixture (supersede, freeze-refuse, obligation-refuse, no-active-refuse, in-flight-serialize,
  disowned-agent-refuse-at-capability-layer, audit).
- **Increment 2 — CLI + edge-tool adapters.** CLI `takeover-request` (full challenge + LOSS_CORRIDOR_TEXT verbatim),
  `takeover-confirm` (challenge-echo, NO --force) via a GENUINE strategist-session login (FK-15 §15.10.3; interactive
  password prompt / documented local reuse; CSRF), `recover-story --story` (Übernehmen/Verwerfen) — all thin adapters
  copied from `_cmd_admin_abort`, errors 403/409 passed 1:1. Edge-tool `takeover-request` (agent → deterministic
  pending_human_approval + op_id), `abort` (server 403 for unprivileged agent), `recover` (server fail-closed refusal
  for agents) — thin, mirrored to shared transport, NO `takeover-confirm` in the edge tool. Transport `takeover_request`
  on `client.py`. FK-91 §91.1 CLI-table rows (+ "requires strategist session" note on confirm) + FK-15 §15.10.2 one-word
  clarification (Stratege class covers operator CLI) as declared Konzept-Nachzug; 4 concept gates green. Story-text
  correction: remove the stale "SOLL-091 gehört AG3-149" sentence (story.md:166-168); claim SOLL-090 + the SOLL-091
  DISPOSITION in Traceability (no orphaned SOLL).

## 3. Guardrails carried into every worker prompt
venv only; local Postgres 127.0.0.1:55442 then 55642; `--basetemp var\t` removed; single-pass coverage + scoped inner
loop; full suite once pre-push; mypy full both platforms; 4 concept gates. Green-on-main: ruff → mypy src → mypy src
--platform linux → pytest → 4 gates → push main → Jenkins buildWithParameters (CSRF crumb + admin:password) → SUCCESS +
Sonar OK. Sonar http://localhost:9901 admin/`meinSonarCube2026!` key claude-agentkit3 (0/0/0, new-code cov≥80). Do NOT
set status.yaml=completed (review + Fable finale + Inc-2 follow). Fire Codex jobs serially. CLI/edge adapters are thin
REST over ProjectEdgeClient — never in-process core; edge tool mirrors shared harness_client transport (no divergent copy).

---

## CORRECTION (2026-07-11) — D1(e) escalation WITHDRAWN; §56.13g is satisfied, not deferred

The earlier D1(e) framing ("no attestable stable-harness-identity primitive → escalate")
was WRONG end-to-end. Corrected reasoning (operator workflow, not abstract):

- A crashed harness does not need recovery at all when the operator uses `/resume`. AK3's
  `owner_session_id` IS the Claude Code hook `session_id` (verified: harness_adapters/
  claude_code.py:147 maps `session_id=claude_event.session_id` for EVERY operation). `/resume`
  preserves that session_id, so the resumed session STILL OWNS the story (the ownership fence
  matches `owner_session_id@ownership_epoch`) and simply continues; an interrupted in-flight
  operation reconciles via op_id idempotency (FK-91 rule 14/16). No recovery event, no human
  co-sign. THAT is FK-56 §56.13g "same harness identity self-rebind needs no co-sign" — satisfied
  BY CONSTRUCTION via the existing session-derived-ownership + op-id model. The identity primitive
  is the durable Claude Code session that `/resume` restores; there is nothing to build and nothing
  to strike.
- `recover-story` (human_cli, new run, acquired_via=recovery) is ONLY the fresh-session fallback:
  the transcript is gone / a clean slate is wanted / a takeover happened during the downtime (→ the
  AG3-149 disowned path). Any `recover-story` invocation is by definition NOT the `/resume` path,
  so it is correctly a deliberate human decision.

IMPACT ON THE CODE: NONE. The frozen behavior (recover-story = human_cli; agent recovery fail-closed
`recovery_requires_human_cli`; no co-sign-free path; no approval-queue wiring) is CORRECT under the
corrected understanding — only the justification changed (agent recovery is refused because it is
inherently the fresh-session/human path, NOT because identity is unprovable). No escalation to the
human. Do NOT narrow/strike §56.13g. Inc-1 and Inc-2 proceed unchanged.
