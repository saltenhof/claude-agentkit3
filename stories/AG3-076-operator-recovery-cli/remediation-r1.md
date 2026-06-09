# AG3-076 — Remediation of Codex Review R1

**Scope of this remediation:** only `story.md` was rewritten (and verified that `status.yaml` is correct). No production code, tests, or `concept/` files were touched. Every must-fix ERROR and every WARNING from `review-r1.md` is addressed below, with the exact resolution and the verified code anchors that replaced the wrong ones.

All resolutions stay strictly within the AG3-076 cut from `var/concept-gap-analysis/_STORY_INDEX.md` (Welle 3, row AG3-076): *"Operator-CLI an die existierenden Services andocken — kein Service-Neubau"*. No scope expansion: where a service does not exist, the story now produces a fail-closed CLI finding and routes the missing service to an owner instead of building it here.

---

## Code anchors verified against the real tree (used to fix wrong anchors)

| Capability | Verified anchor | Status |
|---|---|---|
| Single-phase dispatch | `control_plane/runtime.py:241` `ControlPlaneRuntimeService.start_phase` | exists |
| Transition enforcement | `pipeline_engine/engine.py:192` `_evaluate_transitions` | exists |
| ESCALATED status mapping | `pipeline_engine/engine.py:701-718` | exists |
| Resume PAUSED run | `pipeline_engine/engine.py:1119` `resume_phase` (PAUSED check `:1148`) | exists |
| Phase-state read | `governance/repository.py:265` `read_phase_state_record`, `:158` `has_valid_phase_state` | exists |
| Lock records | `state_backend/store/lock_record_repository.py:170` `LockRecordRepository` (`:184` `deactivate_locks_for_story`); `governance/locks.py` `DeactivationResult` | exists |
| Telemetry query | `telemetry/storage.py:89` `query`, `:192` `read_run_events` | exists |
| Telemetry export | `telemetry/audit_bundle.py:142` `export` | exists |
| `_check_preconditions` (claimed by old story) | — | **does NOT exist** (removed) |
| Integrity-override service | — | **does NOT exist** in `closure/` (only generic `OverrideRecord` in `pipeline_engine/runtime_state.py`, `phase_state_store/models.py`) |
| `reset-escalation` service | — | **does NOT exist** (only referenced as a future concept in docstrings `control_plane/runtime.py:777`, `control_plane/dispatch.py:235`) |
| PID/TTL stale-lock detection | — | **does NOT exist** (`no_stale_worktree.py:27` checks dir existence only; `LockRecordRepository` has no PID check); normed in FK-71 §67.3 / FK-02 §2.7 |
| `StoryResetService` / `StorySplitService` | — | **not in code**; AG3-071/072/073 are `draft`/`review_pending` |

---

## Must-Fix ERRORs

**ERROR 1 — FK-04 coverage: `backend health` cited but pushed out of scope.**
Resolved by narrowing the source-concept citation. The story header no longer cites `backend health` as an in-scope FK source; a dedicated note explains that no PostgreSQL-health service anchor exists (§1.1 C) and routes `backend health` as a **binding follow-up finding to AG3-070** (Config-Modell + Backend-Stanza owner). This is the review's option "narrow the citation + concrete owner with Pflichtcharakter" (`story.md` header note + §2.2). No new service is invented (stays in cut).

**ERROR 1b — FK-04 §4.4.2: `status` must render the weekly-review report.**
Added to scope (Befehl 5) and to AC 9: `status` renders the same Weekly-Review block through the **same renderer** as `weekly-review` (FK-04 §4.4.2: "Reports erscheinen automatisch bei jedem `agentkit status` oder explizitem Review-Aufruf"). Single renderer = no second report truth (SINGLE SOURCE OF TRUTH).

**ERROR 2 — AC 2: "existing service paths" not concretely named per command.**
Added a verbatim **Service-Anker-Tabelle (§2.3)** naming, per command, the exact module:line, function/class, input, return type, and error contract. AC 2 now points to it. Abstract "Surface/Read-Modell" wording replaced everywhere with concrete anchors (`read_phase_state_record`, `LockRecordRepository`, `telemetry/storage.query`, `audit_bundle.export`, etc.).

**ERROR 3 — `reset-escalation` contradiction (Scope says "only report", AC 4 demands functional ESCALATED→resumable).**
Resolved per the review's second option: confirmed there is **no** reset-escalation service in code, classified it as **Klasse C (service missing)**, and rewrote AC 4 to: missing service anchor → non-zero exit + explicit machine-readable finding + **no** CLI-side state mutation. The functional-recovery claim was removed. The missing service is routed as a binding follow-up (§2.2). `depends_on` is left as-is (the draft Reset/Split/Exit stories stay as cut-consistency deps, not as functional prerequisites for this contradictory command).

**ERROR 4 — Wrong `_check_preconditions` anchor.**
Removed. Verified `_check_preconditions` has zero hits in the tree. Replaced with the real transition owner `pipeline_engine/engine.py:192` `_evaluate_transitions` plus the ESCALATED mapping at `:701-718` (§1.1 A, §2.1 Befehl 1).

**ERROR 5 — AG3-071/072/073 claimed as existing Reset/Split/Exit services.**
Rewritten as **Klasse B (Dependency noch `draft`)** in §1.1, citing `stories/AG3-071-story-reset-service/status.yaml:4-5` (`status: draft`, `phase: review_pending`) and the absence of `StoryResetService`/`StorySplitService` in `src/agentkit`. These commands are explicitly **not** an anchoring target of this story; their CLI adapters belong to the owner stories. They remain only as `depends_on` cut-consistency.

**ERROR 6 — `cleanup` wrongly anchored to `_resume_merge_only`.**
Removed the `_resume_merge_only` anchor (confirmed it is a merge-resume inside the pre-merge/merge block, `merge_sequence.py:435`, not a PID/TTL stale-lock cleanup). `cleanup`'s lock deactivation is now anchored to the real `LockRecordRepository.deactivate_locks_for_story` (`lock_record_repository.py:184`). The PID/TTL liveness check is classified **Klasse C** (no anchor) and routed as a follow-up; AC 5 makes `cleanup` fail-closed (no deletion) when the PID anchor is absent.

**ERROR 7 — `override-integrity` claimed to delegate to an existing override path.**
Confirmed no authorized integrity-override service exists in `closure/`. Reclassified as **Klasse C**; AC 7 now: `--reason` missing → non-zero; `--reason` present but no override service → fail-closed non-zero + finding, no CLI-side integrity-gate bypass, no state/gate mutation. Missing service routed as a binding follow-up (§2.2).

---

## WARNINGs

**WARNING (1.3) — FK-10 §10.6.2 cleanup scope (Worktree/Branch/Locks/Artefakte) reduced.**
Added §2.1.1 defining the cleanup scope hard: Locks (in scope, real), Worktree (in scope, only after a passed PID-liveness check), **Branch + Artefakte (consciously excluded, owner = AG3-071** StoryReset purge domains). Branch/artifact cleanup is routed to AG3-071, not silently dropped.

**WARNING (2.3) — `query-state --locks` global (no story) collides with the story-scoped form.**
Added the global `agentkit query-state --locks` (no `--story`) form explicitly (Befehl 6) for the FK-04 §4.2.1 line, separate from the story-scoped `--story --locks`. AC 6 now requires a test for both the story-scoped and the global `--locks` case. The stale-candidate marking is described as descriptive-only while the PID anchor (Klasse C) is open.

**WARNING (3) — No AC checks that Agent/Control-Plane paths do not use the CLI (FK-45 §45.4 normative rule).**
Added AC 10: an architecture/import test asserts no productive agent/control-plane module imports `agentkit.cli.main` (or references the existing import guard if one already covers this boundary), plus an explicit non-goal citing FK-45 §45.4 + FK-91 §91.1a (agents go via `Project Edge Client` → Control-Plane-API).

---

## Klarheit/Kontext findings (review section 3 & 4)

- **ERROR (3) — "services exist" vs. "missing anchor as finding" was an unclear brief.**
  Resolved by §1.1: the service Ist-Zustand is now split into three hard classes — **(A) exists (verified)**, **(B) dependency still draft**, **(C) missing → must be reported**. Every command in §2.1 and the §2.3 table carries its class, removing the ambiguity.
- **PASS items** (CLI Ist-Zustand `cli/main.py:38-160`, `run-story` stub `:325-345`, `serve-control-plane` adapter `:369-382`) were kept and re-verified; the adapter pattern reference is retained.

---

## status.yaml

Reviewed against `_STORY_INDEX.md` (AG3-076 row): `type: implementation`, `size: M`, `depends_on: [AG3-054, AG3-071, AG3-072, AG3-073]`, `phase: review_pending`, `status: draft` all match the cut. **No field was wrong → status.yaml left unchanged.**

---

## ARCH-55

All CLI surface added/edited in the story is English (subcommand names, flags, help text, machine-readable finding texts e.g. "no authorized integrity-override service — reported as service gap"). German remains only in the concept/explanatory prose, per ARCH-55.

## Template fidelity

The AG3-057 template structure is preserved: header (Typ/Groesse/Bounded Context/Quell-Konzepte) → §1 Kontext/Ist-Zustand → §2 Scope (In/Out) → §3 Akzeptanzkriterien → §4 Definition of Done → §5 Guardrail-Referenzen → §6 Hinweise fuer den Sub-Agent. Added subsections (§1.1, §2.1.1, §2.3) are additive within that structure.

## Files written

- `stories/AG3-076-operator-recovery-cli/story.md` (rewritten)
- `stories/AG3-076-operator-recovery-cli/remediation-r1.md` (this report)
- `status.yaml`: not modified (verified correct)
