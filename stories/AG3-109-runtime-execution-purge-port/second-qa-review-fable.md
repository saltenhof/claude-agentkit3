# Second-QA Review — AG3-109 Runtime-Execution-Purge-Port

- **Story:** AG3-109 (`stories/AG3-109-runtime-execution-purge-port/story.md`)
- **Reviewer:** Fable second-QA (independent adversarial re-review, write authority)
- **Reviewed commits:** `4476b6c` (feat) + `bfef0c8` (status), main, post Codex code-scope APPROVE
- **Review mode:** concept cross-check against FK-53 §53.6.2/§53.7.5/§53.9.1 *and the
  actual table/reader inventory of the codebase* (not only the story's §1.3 list);
  real-path probing of both driver purge implementations, the residue probe's
  fail-closed value, the production wiring, schema/key parity, and the test seams —
  with fixes applied in-place where a defect was real.

## Findings

| ID | Severity | Location | Finding | Action taken |
|----|----------|----------|---------|--------------|
| F1 | **Blocker** | `runtime_execution_purge.py` (domain list), `facade.py`, `sqlite_store.py`, `postgres_store.py` — vs. FK-53 §53.7.5 rule / story AK4 | **The §53.7.5 rule ("Kein verbleibendes Objekt … darf einen spaeteren Neustart, Resume oder Guard-Entscheid beeinflussen"), which AK4 claims proven, was NOT actually satisfied.** Two runtime tables written by the SAME owner facade this story built on were missing from the purge surface AND from the residue probe: (1) **`phase_snapshots`** — PK `(story_id, phase)`, **no run_id**; written by `facade.save_phase_snapshot`; read story-keyed by `backend_has_completed_snapshot(story_dir, "setup")`, which the Integrity Gate uses for Dim 2 CONTEXT_INVALID (`store/integrity_gate_repository.py:144`) — a purged run's completed-setup snapshot keeps answering "PASS" for the next run. (2) **`decision_records`** — canonical verify decisions, SQLite PK `(story_id, decision_kind, attempt_nr)`, **no run_id**; written by `facade.record_verify_decision`; read by `load_latest_verify_decision` via `ORDER BY attempt_nr DESC` **story-wide** (`sqlite_store.py:2863ff`) — and `attempt_nr` restarts at 1 in the next run (`implementation/phase.py:223` `attempt_nr = qa_rounds + 1` from the purged PhaseState memory), so a leftover late-attempt decision of the corrupted run **SHADOWS the new run's verify decision in the Integrity Gate**. The Postgres reader makes the hazard explicit: it falls back to the story-wide MAX(attempt_nr) lookup when no run-scoped record exists (`postgres_store.py:3119-3129`) — i.e. exactly the post-reset state. The story's §1.3 mapped §53.6.2 entity→table 1:1 and missed these in-code companions (same drift class as `attempt_records`→`attempts`, which §1.2 DID catch). The residue probe — the story's own §53.10 safety net — was equally blind, so `verify_reset_clean_state` would have certified "clean" over live, decision-influencing residue. | **FIXED in-place.** `phase_snapshots` + `decision_records` added as runtime purge domains: new owner APIs `facade.purge_phase_snapshots` / `facade.purge_decision_records` (story-keyed, idempotent §53.9.1), driver helpers in BOTH stores, both tables added to the residue counters, domain tuple now 10 entries, §1.3 mapping mirror + module docstrings updated and honestly marked as a second-QA closure of the story's mapping (doc-only §1.3 nachtrag flagged below). New tests: `test_phase_snapshots_roundtrip`, `test_decision_records_roundtrip` (both stores), and the §53.7.5 regression `test_stale_snapshot_and_verify_decision_cannot_influence_next_run` (seeds a LATE attempt_nr=3 decision + completed setup snapshot, purges, then proves `backend_has_completed_snapshot` and `backend_verify_decision_passed` can no longer answer for the purged run and the probe is clean). |
| F2 | **Major** | `sqlite_store.py` / `postgres_store.py` `_count_runtime_execution_residue` (pre-fix) | **Probe shared the purge's exact scoping blind spot (fail-open seam).** Both the destructive purge AND the residue counts filtered the project-keyed tables by `project_key = ?`. A mis-scoped call (wrong-but-non-empty `project_key` for an existing `(story_id, run_id)`) would delete nothing in `flow_executions`/`node_execution_ledgers`/`override_records`/`guard_decisions`/`execution_events` — and the probe would **count zero too**, certifying "clean" over surviving runtime rows. A verification building block that can only confirm the purge's own predicate adds no fail-closed value for scoping bugs (it only catches "purge never ran"). `(story_id, run_id)` is globally unique in this schema family (`attempts`/`artifact_envelopes` already key without `project_key`; run_id is a UUID), so broader counting cannot mis-attribute residue in a healthy store. | **FIXED in-place.** Residue counting is now deliberately `project_key`-agnostic: run-bound tables counted by `(story_id, run_id)`, story-keyed tables by `story_id`, in BOTH stores; the destructive purge keeps its narrow `project_key` predicate (asymmetry documented: destructive = narrow, verification = broad, mismatch surfaces as residue → ERROR → human). `project_key` stays validated (non-empty, fail-closed) at the port. New test `TestResidueProbeScoping::test_mis_scoped_purge_is_flagged_as_residue`: wrong-project purge deletes 0, probe flags `guard_decisions == 1` (red on pre-fix logic), correctly scoped purge then converges clean. |
| F3 | Minor | `src/agentkit/state_backend/store/__init__.pyi` | The story added 9 symbols to `PUBLIC_API` (8 `purge_*` + `count_runtime_execution_residue`) but **not to the boundary's `.pyi` stub** — `from agentkit.backend.state_backend.store import purge_attempts` (the import form AG3-071 will use; the boundary `__init__.py` re-exports via `PUBLIC_API`) would fail mypy strict with attr-defined. A typed-boundary symbol that the type checker cannot see is a latent write-never seam for the declared consumer. | **FIXED in-place:** all 9 story symbols + the 2 new F1 symbols added to the `.pyi` in alphabetical order. NOT fixed (out of story scope, pre-existing): `load_execution_events_for_project_global` is also missing from the `.pyi` — flagged for the separate cleanup round. |
| F4 | Minor | `runtime_execution_purge.py:90` (pre-fix) | `purged_rows: dict[str, int] = field(default_factory=dict)` allowed constructing a `RuntimeExecutionPurgeResult` with an empty map, silently violating the docstring invariant "every domain … is present". | **FIXED in-place:** field is now required (no default); invariant documented. Also added the missing `story_id` fail-closed negative test (`test_missing_story_id_raises`) — pre-fix tests only covered `project_key`/`run_id`. |
| F5 | Minor | filesystem projections (`phase-state-*.json`, `decision.json`, QA artifact files written by `_write_projection` next to the DB rows) | The purge removes DB rows but not the projection mirror FILES the same writers emit into the story/projection dir. Per the project rules these files are ephemera, never fachliche Wahrheit, and workspace/ephemera cleanup is explicitly §53.7.7/§53.7.8 → story §2.2 out of scope (D11/worktree owner). | Left as-is + **flagged for AG3-071**: the reset flow must compose the workspace/ephemera cleanup step so stale projection files cannot confuse a human/agent reading the story dir (they are never read back as truth by the canonical backend — verified: all `load_*` paths read the DB). |
| F6 | Minor | `facade.purge_attempts` / SQLite story_dir↔story_id coupling | On SQLite, `save_attempt_row` derives `story_id` from `story_dir.name` while the purge takes `story_id` explicitly; a caller passing `story_id != story_dir.name` would purge nothing. Not a defect: the SQLite DB is per-story-dir, so foreign-named rows belong to a different story and MUST survive; Postgres ignores `story_dir`. Input consistency is the documented caller contract (same convention as every existing `load_*`). | Left as-is + noted for AG3-071: pass the story display id together with its canonical `story_dir` (`story_dir(project_root, story_display_id)`), as everywhere else. |

## Checked beyond the story's own checklist — found SOUND

- **No God-Purge / BC-ownership (AK5):** the port calls only `facade.purge_*` owner
  APIs; SQL exclusively in `sqlite_store.py`/`postgres_store.py`; no port-owned SQL,
  no new module under the unregistered `agentkit.backend.phase_state_store` path; GAC-1 exit 0.
- **No phantom tables:** `attempt_records`/`node_executions`/`artifact_records` appear
  nowhere in code or SQL (only as documented drift in comments/docstrings); all DELETE/
  COUNT targets exist in BOTH DDLs (`sqlite_store.py` schema, `postgres_schema.sql`)
  with exactly the key columns the predicates use (verified column-by-column:
  `flow_executions`/`node_execution_ledgers`/`override_records`/`guard_decisions`/
  `execution_events` carry `project_key, story_id, run_id`; `attempts`/
  `artifact_envelopes` have no `project_key`; `phase_states` PK `story_id`).
- **Own result type (HIGH-1/SSOT):** `RuntimeExecutionPurgeResult` is a distinct frozen
  dataclass; the projection `PurgeResult` (`projection_accessor.py:149`,
  `ProjectionKind`-keyed) is not imported by the port module; the type assertion test
  exists and is real.
- **Read-model boundary (AK1/§2.2):** no duplicate of `phase_state_projection`/
  `story_metrics`/`qa_*`/`risk_window`/`fc_*` purges anywhere in the new code; canonical
  `phase_states` purged story-keyed (correct: PK is `story_id`, one runtime row per
  story — run-scoped deletion is impossible and reset semantics want the story cleared).
- **Tests run the REAL drivers, not fakes:** the `backend` fixture drives real SQLite
  files and, via `postgres_isolated_schema`, the real dockerized Postgres with the real
  `postgres_schema.sql` + `_CompatConnection` (`?`→`%s`) — seeding via the canonical
  `save_*`/repository write paths, assertions via the canonical `load_*` read paths.
  No in-memory fake exists in this test module at all.
- **Idempotency (§53.9.1/AK3):** second port purge == 0 via real rowcounts; purge of a
  never-written run is a no-op; `_connect` propagates real infra errors (no swallow).
- **Run-bound artifact precision (AK6/MED-8):** delete keyed `(story_id, run_id)`;
  other-run envelope proven to survive in both stores; no `project_key` column invented.
- **Production reachability:** `build_runtime_execution_purge_port` /
  `build_runtime_execution_residue_probe` exist in `bootstrap/composition_root.py` and
  are what the tests construct through; the consumer (AG3-071 `StoryResetService`) is
  correctly NOT built here (per story §2.2). AG3-071's spec consumes the port
  generically (no fixed domain-count pin), so the F1 domain extension is compatible.
- **ARCH-55:** all identifiers, comments, wire keys (result-map keys = real English
  table names) are English; no German leaked into the new code.
- **Out-of-scope reset domains re-verified with owners:** locks/leases
  (`story_execution_locks`, `session_run_bindings`, control-plane ops) → §53.7.3
  (AG3-071/076); read-models/analytics → §53.7.6 (AG3-081/082); worktree/ephemera →
  §53.7.7/8 (D11). `compaction_epochs` (story-keyed monotonic counter) influences only
  event-compaction bookkeeping, not restart/resume/guard decisions — acceptable to
  leave, noted for AG3-071's inventory.
- **No SCHEMA_VERSION bump needed:** neither the original change nor the F1/F2 fixes
  touch any DDL (DELETE/COUNT only) — consistent with story AK8.

## Doc-only follow-ups (flagged, not silently absorbed)

1. **Story §1.3 mapping nachtrag:** `phase_snapshots` (PhaseState snapshot family) and
   `decision_records` (governance runtime / verify decision) belong in the §1.3 table;
   same drift class as the §1.2 entries (FK-18/FK-53 prose does not name these tables).
   Owner: story doc / FK-18-Doc follow-up already named by the story.
2. `.pyi` gap `load_execution_events_for_project_global` (pre-existing, non-AG3-109).

## Before/after (per fixed finding)

- **F1:** before — `RUNTIME_EXECUTION_PURGE_DOMAINS` had 8 domains; after a port purge,
  `backend_has_completed_snapshot(story_dir, "setup")` still returned `True` and
  `load_latest_verify_decision` still returned the purged run's decision (sqlite
  story-wide MAX(attempt_nr); postgres explicit story-wide fallback), while the residue
  probe reported `is_clean == True`. After — 10 domains; both tables purged via new
  owner facade APIs + both driver helpers; probe counts them; regression test proves
  the stale evidence is gone and the probe stays clean.
- **F2:** before — probe counted `flow_executions`/`node_execution_ledgers`/
  `override_records`/`guard_decisions`/`execution_events` with
  `WHERE project_key = ? AND story_id = ? AND run_id = ?` (same predicate as the
  delete); a wrong-project purge+probe pair certified clean over surviving rows.
  After — probe counts `(story_id, run_id)` (story-keyed tables by `story_id`);
  the mis-scoped scenario now fails closed (test red on old logic, green now).
- **F3:** before — 9 PUBLIC_API symbols invisible to mypy at the boundary; after —
  `.pyi` lists all 11 purge/residue symbols.
- **F4:** before — `purged_rows` defaulted to `{}` against its own documented
  invariant; after — required field; plus the missing `story_id` negative test.

## Gate evidence

(verbatim tails below)
