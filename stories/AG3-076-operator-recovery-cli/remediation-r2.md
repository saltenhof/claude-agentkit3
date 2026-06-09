# AG3-076 — Remediation of Codex Review R2

**Scope of this remediation:** only `story.md` was rewritten (and `status.yaml` re-verified as correct — unchanged). No production code, tests, or `concept/` files were touched. Every remaining round-2 must-fix ERROR, the round-2 Konzept-Vollstaendigkeit (WEAK) finding, and the per-dimension FAIL verdicts are addressed below, each with the exact resolution and the real `file:line` anchor verified against the current tree.

All resolutions stay strictly within the AG3-076 cut from `var/concept-gap-analysis/_STORY_INDEX.md` (Welle 3, row AG3-076): *"Operator-CLI an die existierenden Services andocken — kein Service-Neubau"*. Where a read path / data producer does not exist, the story now emits a fail-closed service-gap finding and routes the missing service to its owner story instead of inventing it here.

---

## Code anchors re-verified against the real tree (round-2)

| Capability | Verified anchor | Status |
|---|---|---|
| `start_phase` signature | `control_plane/runtime.py:241` `start_phase(*, run_id, phase, request)` | exists; requires `run_id` + `PhaseMutationRequest` |
| `PhaseMutationRequest` required fields | `control_plane/models.py:63` (extends `_ControlPlaneRequest:53`): `project_key`, `story_id`, `session_id`, `principal_type`, `worktree_roots` (all `min_length>=1`) | exists |
| `resume_phase` signature | `pipeline_engine/engine.py:1119` `resume_phase(ctx, envelope, trigger)`; PAUSED check `:1148`; invalid-trigger `status="failed"` `:1185` | exists; requires `StoryContext`, `PhaseEnvelope`, `trigger` |
| Lock repository surface | `state_backend/store/lock_record_repository.py:184` `deactivate_locks_for_story` (only method; mutating) | exists, but **no** list/read method |
| Lock listing read path | — (grep: only `deactivate_locks_for_story`; `StoryExecutionLockView` `models.py:119` is a serialization view, no repo query) | **does NOT exist** |
| `AuditBundleExporter.export` signature | `telemetry/audit_bundle.py:142` `export(story_id, run_id, output_dir)`; fail-closed on non-completed run `:165-177` | exists; requires all three inputs |
| Telemetry `query` | `telemetry/storage.py:89` `query(story_id, event_type=None)` — `story_id` positional/required | exists; cannot do story-less event-only filter |
| Telemetry `read_run_events` | `telemetry/storage.py:192` on `StateBackendExecutionEventReader` (story-scope bound `:190`) | exists; needs resolvable story scope |
| FailureCorpus review producers | `failure_corpus/top.py:128` `suggest_patterns`, `:159` `derive_check`, `:192` `report_effectiveness` | all raise `NotImplementedError` (failure-corpus.A4/A5/A7) |
| FC read models | `telemetry/projection_accessor.py:394` `FC_PATTERNS`/`FC_CHECK_PROPOSALS` → `ProjectionKindNotAccessorOwnedError` | fail-closed externally-owned (Owner: AG3-078) |
| FK-04 §4.3.2 query-telemetry forms | `concept/.../04_betrieb_monitoring_audit_runbooks.md:108/111/114/117` | shows `--run` and `--event --since 7d` **without** `--story` |

---

## Remaining round-2 Must-Fix ERRORs

**ERROR 1 — `query-state --locks` falsely anchored as an existing read path.**
Verified: `LockRecordRepository` exposes **only** the mutating `deactivate_locks_for_story` (`lock_record_repository.py:184`); there is no story/global lock-listing read method, and `StoryExecutionLockView` (`models.py:119`) is a serialization view, not a repo query. Resolution = the review's option "classify `query-state --locks` as Klasse C fail-closed with owner":
- §1.1 C now lists the missing **Lock-Listing-Lesepfad** explicitly.
- Befehl 6 splits `query-state` into Klasse A (Phase-State via `governance/repository.py:265`) and **Klasse C** (`--locks`, story-scoped *and* global) → fail-closed service-gap finding ("no lock-listing read repository — reported as service gap"), no state-read surrogate.
- §2.3 table: separate Klasse-A `query-state --story` row and Klasse-C `query-state --locks` row.
- §2.2: new binding follow-up routing a Lock-Read-Repository to its owner.
- AC 6 rewritten: both the story-scoped and global `--locks` cases must test the fail-closed finding (not a listing).

**ERROR 2 — `run-phase`/`resume` unsatisfied service inputs.**
Verified signatures above. Resolution = define exact CLI flags / sanctioned derivation paths:
- **`run-phase`** (Befehl 1) now declares `--run --session --principal --worktree (repeatable) [--project] [--config]` and specifies that the CLI builds the full `PhaseMutationRequest` (`models.py:63`: `project_key`, `story_id`, `session_id`, `principal_type`, `worktree_roots`) from those named flags; `op_id` is not exposed (the request default mints it; a re-call is a new dispatch, correct for a manual recovery path). Missing required input → non-zero.
- **`resume`** (Befehl 2) now declares `--trigger` and specifies that `StoryContext`/`PhaseEnvelope` are **loaded** deterministically from the persisted story-state (`story/service.py:63`, `governance/repository.py:265`) — the CLI mints nothing. No loadable PAUSED state → fail-closed non-zero + finding; invalid trigger → service `status="failed"` (`engine.py:1185`).
- §2.3 table rows for `run-phase` and `resume` updated with the full input contract; AC 1 and AC 3 rewritten accordingly.

**ERROR 3 — `export-telemetry` omits required export inputs.**
Verified `export(story_id, run_id, output_dir)`. Resolution: Befehl 10 now declares `--story --run --output-dir [--dry-run]` and specifies the CLI passes all three through; missing any → non-zero; `--dry-run` only checks reachability/writability of `--output-dir` (no `export` call); non-completed/reset run → `AuditBundleExportError` → non-zero. §2.3 row + AC 8 updated.

**ERROR 4 — `weekly-review` claimed to render from existing read models that do not exist.**
Verified: `suggest_patterns`/`derive_check`/`report_effectiveness` are `NotImplementedError` (`top.py:128/159/192`); `FC_PATTERNS`/`FC_CHECK_PROPOSALS` are fail-closed externally-owned (`projection_accessor.py:394`). Resolution = the review's option "make unavailable sections explicit service-gap findings instead of silent empty reports":
- Befehl 8 reclassified to **Klasse C for the Failure-Corpus sections / Klasse A only for the renderer frame**. The sections are emitted as an explicit machine-readable service-gap finding (with Owner AG3-078), **never** as a silent empty report (that would misread a missing data source as "no findings" — a FAIL-CLOSED violation).
- §1.1 C now lists the missing FC review data producers with the exact anchors and Owner AG3-078.
- Befehl 5 (`status`) updated: the `status` review block uses the same renderer frame and the same service-gap marking.
- §2.2 FC entry updated; clarified this is a routed follow-up, **not** a `depends_on` extension (the cut from `_STORY_INDEX.md` holds; AG3-076 deliberately renders only the frame instead of blocking on AG3-078).
- §2.3 row + AC 9 rewritten.

## Round-2 Konzept-Vollstaendigkeit (WEAK) — `query-telemetry` forms

Verified FK-04 §4.3.2 shows `--story`, `--story --event`, `--run` (no `--story`), and `--event --since 7d` (no `--story`). The previous story forced `--story` as mandatory. Resolution: Befehl 7 now declares `[--story] [--run] [--event] [--since]` with the selector rule "`--story` **or** `--run` is required". `--story`(+`--event`) → `query(story_id, event_type)`; `--run` → `read_run_events(run_id)` (noting the reader is story-scope bound at `storage.py:190`, so a resolvable scope is required). The story-/run-less governance-incident form (`--event ... --since` alone) has **no** existing read path (`query` requires `story_id`; `read_run_events` needs a scope) → it is a fail-closed service-gap finding, routed in §2.2. §2.3 split into three query-telemetry rows; AC 6 covers the selector rule + the story-less fail-closed case.

## Per-dimension FAIL verdicts

- **AC-Schaerfe / Klarheit / Kontext-Sinnhaftigkeit:** resolved by the four ERROR fixes above — every command now carries (a) the full CLI flag contract, (b) the correct semantic service anchor at the real `file:line`, and (c) the right Klasse (A real / C fail-closed), so no Klasse-A claim survives on a non-existent read path.

---

## status.yaml

Re-verified against `_STORY_INDEX.md` (AG3-076 row): `type: implementation`, `size: M`, `depends_on: [AG3-054, AG3-071, AG3-072, AG3-073]`, `phase: review_pending`, `status: draft` all match the cut. ERROR 4 was resolved via the explicit-service-gap route (not the "depend on AG3-078" route), so AG3-078 is **not** a functional dependency and is correctly left out of `depends_on`. **No field was wrong → status.yaml left unchanged.**

## ARCH-55

All newly added/edited CLI surface in the story is English (flags `--run/--session/--principal/--worktree/--trigger/--output-dir`, finding texts "no lock-listing read repository — reported as service gap", etc.). German remains only in explanatory/concept prose, per ARCH-55.

## Template fidelity (AG3-057)

Preserved: header (Typ/Groesse/Bounded Context/Quell-Konzepte) → §1 Kontext/Ist-Zustand (incl. §1.1 A/B/C classes) → §2 Scope (§2.1 In, §2.1.1 cleanup, §2.2 Out-of-Scope-with-owner, §2.3 Service-Anker-Tabelle) → §3 Akzeptanzkriterien → §4 DoD → §5 Guardrail-Referenzen → §6 Sub-Agent-Hinweise. All round-2 edits are additive/in-place within that structure.

## Files written

- `stories/AG3-076-operator-recovery-cli/story.md` (rewritten)
- `stories/AG3-076-operator-recovery-cli/remediation-r2.md` (this report)
- `status.yaml`: not modified (re-verified correct)
