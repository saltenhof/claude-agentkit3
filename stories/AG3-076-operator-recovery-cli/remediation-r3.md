# AG3-076 — Remediation of Codex Review R3

**Scope of this remediation:** only `story.md` was rewritten. `status.yaml` was re-verified as correct and left unchanged. No production code, tests, or `concept/` files were touched, and no other stories' files were modified. Both remaining round-3 must-fix ERRORs are resolved below, each with the exact resolution and the real `file:line` anchor verified against the current tree. No WARNINGs were raised in R3.

All resolutions stay strictly within the AG3-076 cut (`var/concept-gap-analysis/_STORY_INDEX.md`, Welle 3, AG3-076): *"Operator-CLI an die existierenden Services andocken — kein Service-Neubau"*. Both R3 fixes re-point the story onto **already-existing** read paths; neither introduces a new service or a new cross-story prerequisite.

---

## R3 ERROR 1 — `resume` used false `StoryContext` / `PhaseEnvelope` anchors

**Finding (review):** The story claimed `StoryContext` is loaded via `story/repository.py:50` + `story/service.py:63` / `governance/repository.py:265`, and treated the phase-state record as the `PhaseEnvelope`. Real code:
- `story/repository.py:50` = `load_phase_state` (returns `PhaseState`, **not** `StoryContext`); the `StoryContext` loader is `story/repository.py:47` (`StoryRepository.load_story_context`).
- `story/service.py:63` loads phase state for summaries (`self._repo.load_phase_state(...)`), not a `StoryContext`.
- `governance/repository.py:265` returns a phase-state record, not a `StoryContext`/`PhaseEnvelope`.
- `resume_phase` requires a `StoryContext` + `PhaseEnvelope` (`pipeline_engine/engine.py:1119-1124`).

**Verification (real tree):**
- `state_backend/store/facade.py:171` `load_story_context(story_dir) -> StoryContext | None` — verified returns `StoryContext`.
- `story/repository.py:47` `StoryRepository.load_story_context` — verified (`:50` is `load_phase_state`, confirming the wrong anchor).
- `pipeline_engine/phase_envelope/store.py:60` `PhaseEnvelopeStore.load(story_id, phase) -> PhaseEnvelope | None` — verified returns `PhaseEnvelope` (`origin=LOADED`).
- `state_backend/store/phase_envelope_repository.py:46` `StateBackendPhaseEnvelopeRepository.load_state` — verified concrete repository wrapped by the store.

**Resolution (story.md):**
- §1.1 (A): added a distinct **StoryContext-Lesepfad** entry (`facade.py:171` / `story/repository.py:47`) with an explicit note that `story/repository.py:50` is `load_phase_state` (PhaseState, not StoryContext), and a separate **PhaseEnvelope-Lesepfad** entry (`phase_envelope/store.py:60` -> `phase_envelope_repository.py:46`). The pre-existing phase-state read path is relabeled "read-only Diagnose, **nicht** der Resume-Eingang".
- Befehl 2 (`resume`): rewritten to load `StoryContext` via `facade.py:171` / `story/repository.py:47` and `PhaseEnvelope` via `PhaseEnvelopeStore.load` -> `StateBackendPhaseEnvelopeRepository.load_state`; explicitly states the pure phase-state record is **not** the resume input.
- §2.3 table `resume` row: anchors corrected to the StoryContext loader + the PhaseEnvelope store/repository; error contract now keys on "kein ladbarer PAUSED-Envelope".
- AC 3: rewritten to the corrected anchors; tests now key on "ladbarer PAUSED-Envelope".
- Befehl 12 (Negativpfade) + §6 Sub-Agent hint: wording updated from "PAUSED-Phase-State" to "PAUSED-PhaseEnvelope" and corrected anchors.

## R3 ERROR 2 — `query-telemetry` had an invalid run/event scope contract

**Finding (review):** The story declared `--run` as Klasse A via `StateBackendExecutionEventReader.read_run_events`, but that reader is constructed with `project_key` + `story_id` and is story-scope bound; the CLI has no `--project` and no run-id→story resolver. It also claimed no project-wide event reader exists for story-/run-less queries — but `load_execution_events_for_project_global(project_key)` exists.

**Verification (real tree):**
- `telemetry/storage.py:187` `StateBackendExecutionEventReader.__init__(self, story_dir, *, project_key, story_id)` — verified story-scope bound; `read_run_events(run_id)` at `:192`.
- `state_backend/store/facade.py:626` `load_execution_events_for_project_global(project_key, *, limit=None)` — verified project-wide reader exists.
- `state_backend/store/public_api.py:32` exports `load_execution_events_for_project_global` — verified.

**Resolution (story.md):**
- §1.1 (A): the telemetry-query entry now names the project-wide reader (`facade.py:626` / `public_api.py:32`) and states a story-less project-scoped event read path **does** exist. The §1.1 (C) block does **not** (and did not) claim it is missing — no false "missing" claim remains anywhere.
- Befehl 7 (`query-telemetry`): added `[--project {project_key}]`; selector is now `--story`, `--run` **or** `--event`. `--run` and the story-/run-less `--event --since` form both read via the existing `load_execution_events_for_project_global(project_key)` with adapter-side `run_id`/`event_type`/`since` filtering. The story-scope-bound `read_run_events` is explicitly **not** used for `--run` resolution. `project_key` resolves from `--project` or `--config`/`AGENTKIT_PROJECT_KEY` (FK-68); missing both → fail-closed non-zero (no default project).
- §2.3 table: `query-telemetry --run` and `query-telemetry --event --since` rows reclassified **Klasse A** with anchor `facade.py:626` (`public_api.py:32`) + adapter-side filter; error contract keys on unresolvable `project_key`. The table note no longer calls the story-/run-less form Klasse C.
- AC 6: rewritten — all `query-telemetry` forms are read-only Klasse A; selector is `--story`/`--run`/`--event`; story-less forms use the project-wide reader; missing `project_key` → non-zero. Tests cover the `--run` and `--event --since` forms returning filtered events and the unresolvable-scope failure.
- Befehl 12 (Negativpfade): replaced the "story-lose Event-only-Form -> fail-closed Befund" item with "ohne aufloesbaren `project_key` -> non-zero".
- §5 Guardrail FAIL-CLOSED line + §6 Sub-Agent hints: removed the story-/run-less `query-telemetry` form from the Klasse-C list; added a Klasse-A hint that the story-less forms use the existing project-wide reader (no new query path, no service gap).

## status.yaml

Re-verified against `_STORY_INDEX.md` (AG3-076 row): `type: implementation`, `size: M`, `depends_on: [AG3-054, AG3-071, AG3-072, AG3-073]`, `phase: review_pending`, `status: draft`. Both R3 fixes re-point onto **existing** code (`load_story_context`, `PhaseEnvelopeStore`, `load_execution_events_for_project_global`), so no new functional dependency was introduced. **No field was wrong → status.yaml left unchanged.**

## Cross-story prerequisites

**None new from R3.** Both ERRORs were fixed by anchoring to existing code, not by depending on another story. The previously-routed Klasse-C follow-ups (unchanged, all still genuine service gaps owned elsewhere) remain:
- `reset-escalation` service (ESCALATED removal) — no owner service; routed for PO assignment (§2.2).
- `override-integrity` service (authorized integrity-gate override) — no owner service; routed for PO assignment (§2.2).
- PID/TTL stale-lock detection (FK-71 §67.3) — no code anchor; routed for PO assignment (§2.2).
- Lock-listing read repository (for `query-state --locks`) — no code anchor; routed for PO assignment (§2.2).
- Failure-Corpus pattern/check/effectiveness producers (for `weekly-review`/`status` review block) — Owner **AG3-078** (§2.2).
- `backend health` (PostgreSQL health) — Owner **AG3-070** (§2.2).
- Branch deletion + artifact purge in `cleanup` — Owner **AG3-071** (§2.1.1).

## ARCH-55

All CLI surface remains English (flags `--project`, finding texts, etc.). German remains only in explanatory/concept prose, per ARCH-55.

## Template fidelity (AG3-057)

Preserved: header (Typ/Groesse/Bounded Context/Quell-Konzepte) → §1 Kontext/Ist-Zustand (§1.1 A/B/C classes) → §2 Scope (§2.1 In, §2.1.1 cleanup, §2.2 Out-of-Scope-with-owner, §2.3 Service-Anker-Tabelle) → §3 Akzeptanzkriterien → §4 DoD → §5 Guardrail-Referenzen → §6 Sub-Agent-Hinweise. All R3 edits are additive/in-place within that structure.

## Files written

- `stories/AG3-076-operator-recovery-cli/story.md` (rewritten)
- `stories/AG3-076-operator-recovery-cli/remediation-r3.md` (this report)
- `status.yaml`: not modified (re-verified correct)
