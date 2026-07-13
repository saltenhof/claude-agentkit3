# AG3-156 — Verify-Evidenz-Ausführungsort: DESIGN FREEZE

Authoritative design contract for the Codex worker. Story (spec-conform, Fable-bestätigt):
`stories/AG3-156-verify-evidence-edge-execution/story.md` @main ca097d0e. This freeze FIXES the
one open design decision the story delegates (variant a/b + timing model); the worker's
P3-Decision-Record (Story Scope 1) is authored ON TOP of this freeze. Size L, ONE story — no
sub-increment chopping; the review→fix loop within the story is normal, but it ships as one unit.

## 0. Decision (adjudicated at code + concept; llm_hub sparring confirmed)
**Variant (a): edge-command batch + EXISTING phase-yield/resume wait-point.** NOT a naive
in-request bounded-wait, NOT a new async framework, NOT variant (b) agent-turn.

**Deadlock confirmed** (why the naive path is dead): FK-91 §91.1a Regel 14
(91_api_event_katalog.md:253-269) — the QA-subflow runs synchronously and HOLDS the
`(project_key, story_id)` object-serialization for its duration; §91.1b (:328) — the edge result
POST is a mutating op on the SAME serialization object. An in-request wait therefore holds the
claim the result POST needs → systematic timeout. Resolution: the phase YIELDS (persists PAUSED,
finalizes the request, RELEASES the claim); the edge collects; the result POST acquires the claim
and terminalizes ONLY the command record; a separate client-driven Resume re-acquires the claim and
consumes the checkpointed result.

## 1. Timing model (the core — must be honored exactly)
TWO wait-points (the QA-preflight needs base evidence BEFORE the preflight LLM can compute the
dynamic reviewer requests):

- **Wait-point A — base collection.** `EvidenceAssembler.assemble()` needs Stage-1 file contents +
  import evidence before the preflight bundle exists (assembler.py:156-187, :189-239). Commission
  the base-collection batch → yield PAUSED → release claim → edge collects → result POST
  terminalizes the command → client Resume consumes it.
- **Wait-point B — dynamic reviewer requests.** Resume builds the manifest + preflight prompt
  deterministically; the preflight LLM is called EXACTLY ONCE; raw response + canonical requests +
  request-digest + assembly/candidate-digest are checkpointed IMMEDIATELY; backend-local requests
  (`NEED_CONCEPT_SOURCE`) answered locally; all worktree-dependent requests commissioned as ONE
  multi-repo batch command (edge returns observations/candidates, NOT the final D3 decision);
  yield PAUSED again → release claim → result POST → separate Resume loads ONLY the checkpoint +
  terminal result (NO second preflight LLM call) → backend applies D3, extends the review bundle,
  continues the QA-subflow.
- **Bounded wait / no sleeping request.** Deadline is part of the checkpoint. The ORCHESTRATOR/
  CLIENT drives edge-polling to the deadline and calls Resume even without a result (the backend
  cannot wake a paused client). Resume semantics: open & pre-deadline → PAUSED again; terminal →
  consume; deadline passed → terminalize the open command `superseded`, emit per-request
  `TIMEOUT`/`UNRESOLVED`.

## 2. Reuse (do NOT reinvent — cited coordinates)
- Timeout + supersede of a stale open command: `push_barrier_lifecycle.py:236-274`
  (`block_timed_out_open_command` / `open_command_timed_out`) — the sync_push precedent.
- Rule-15 ownership fence (SELECT … FOR UPDATE, run/session/epoch compare):
  `postgres_store/_mutation_commit_rows.py:24-110`. Result-that-hits-a-closed-command rollback incl.
  op-row: `postgres_store/_ownership_rows.py:346-404`.
- sync_push secondary fence (boundary-id/epoch + ownership-epoch):
  `runtime/_push_barrier_results.py:53-92`.
- Command identity + stamped epoch: `control_plane/records.py:518-553`; client result op_id:
  `control_plane/models.py:1349-1367`; fenced apply on resume: `implementation/phase.py:277-299`.
- Existing edge command kinds as executor template (AG3-152 merge_local is the freshest):
  `harness_client/projectedge/`. Storage: REUSE `edge_command_records` — NO new table (K5
  Postgres-only; a new table needs a Decision-Record justification, not expected).

## 3. New contract elements (blood-type A core)
- `collect_verify_evidence` command kind (edge_commands.py closed vocabulary) with a TWO-STAGE
  batch payload (stage A base-collection, stage B dynamic-requests) + a typed result type
  (observations/candidates per request, named statuses incl. `TIMEOUT`/`UNRESOLVED`).
- **Generation-specific command id** — NOT today's `(run_id, kind, repo)` scheme
  (edge_commands.py:134-152): include generation so a re-commission after drift is distinct.
- `batch_id = hash(run_id, implementation_attempt, candidate_digest, stage, preflight_template_version)`.
- Result MUST echo `batch_id`, `generation`, candidate-digest, request-digest; server compares
  against the command payload. On candidate/ownership drift the OLD open command is `superseded`
  under the story claim BEFORE a new generation is commissioned.
- Result POST NEVER writes bundle/QA projection; application happens ONLY on Resume under the bound
  ownership fence. NOTE `EdgeCommandRecord.ownership_epoch` is AUDIT ONLY, not a 2nd fence
  (records.py:522-527) — hence the explicit generation/candidate supersede rule is required.

## 4. HIGHEST RESIDUAL RISK — crash-safe preflight checkpoint (freeze-mandated)
`PreflightReviewSender.send()` has no idempotency/session key (preflight_sender.py:19-24). A crash
AFTER a successful preflight LLM response but BEFORE the request checkpoint is persisted would cause
a SECOND, possibly divergent preflight call. The design MUST fix this: either transport
idempotency/session-correlation OR an audited new `preflight_attempt` that is NEVER mixed with an
older batch. The preflight LLM is called exactly once per (checkpointed) attempt; the raw response +
requests + digests are checkpointed transactionally before any yield.

## 5. shell=True hardening (own AC)
LLM-supplied `request.target` is NEVER run as shell text (today's sole `shell=True` hit:
request_resolver.py:162). A typed command contract (whitelist of test-runner forms, arg-wise, no
shell interpretation, hard timeout) is enforced AT the execution site (edge); a non-conforming
command is a deterministic named finding, never executed.

## 6. Invariants the backend KEEPS (only collection moves)
D3 ambiguity rule (1→RESOLVED, ≥2/0→UNRESOLVED, no heuristic pick) + the 8-cap (`MAX_REQUESTS`),
timeout classification, and bundle application stay deterministic backend-side. No-Lease-no-Write
(the whole point) governs the apply. `_resolve_concept_source` keeps reading only backend-local
`concept/`/`stories/` (regression pin — no worktree widening).

## 7. Concept nachzug (P3, worker authors, this freeze is the basis)
FK-47 §47.2/§47.3/§47.5 + code sketches (execution location = edge/agent, never backend), FK-46
(import resolver), FK-28 (assembler boundary vs AG3-147 change-evidence), FK-33 (Sonar/attestation
binding must not presume backend git), FK-91 §91.1b (new command kind + result type in the closed
catalog). P3-Decision-Record under `concept/_meta/decisions/` (Vorbild
`2026-07-02-k1-worktree-topologie.md`) records variant (a) + the timing model + Betroffenheitsmatrix.
Mind the AG3-157 reference-integrity gate: any new §-anchor/doc-id/path must resolve; add real
headings before referencing them.

## 8. One-story guardrails (Scout) + review plan
Keep it one story: existing `edge_command_records`; one two-stage verify-evidence command contract;
existing phase-yield/resume (no general async framework); NO new generic agent result channel;
backend stays owner of D3 / timeout classification / bundle application. Blood types: contract +
D3 + status model = A; wire/result mapper + preflight-turn wiring = R; edge-side FS/subprocess
mechanics = T with a thin R reporting layer.
Review: Codex worker owns green-on-main (pytest ex-e2e, ruff, mypy strict + --platform linux, 5
concept gates, coverage ≥85%) → Codex read-only review + orchestrator code-adjudication every round
→ whole-story Fable finale → Jenkins + Sonar 0/0/0 on the final commit. Serialize: no orchestrator
git/gate ops while the worker is active on the shared tree.
