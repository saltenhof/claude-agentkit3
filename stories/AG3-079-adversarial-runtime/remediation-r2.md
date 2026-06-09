# AG3-079 — Remediation of Codex Review R2

**Outcome of R2:** CHANGES-REQUESTED (round-2 re-review). The one remaining must-fix
ERROR and the new anchor issue resolved in `story.md`. `status.yaml` re-verified —
no field genuinely wrong, no change needed. No production code, tests, or `concept/`
files touched.

Scope guard: the fix stays strictly within the AG3-079 cut. `_STORY_INDEX.md` Welle 3
(line 80) defines AG3-079's source concepts as **`FK-48 §48.1-§48.2.5`** with
`depends_on: AG3-044, AG3-065`. The FK-48 §48.2.2/§48.2.3 derivation is FK-48 stuff —
i.e. already inside this story's own concept range — so absorbing it does NOT widen the
cut. No new dependency edge was added (AG3-067 is a downstream consumer in Welle 1, not
a predecessor).

---

## Remaining Must-Fix ERROR

### R2 ERROR 1 — §48.2.2 derivation falsely routed to AG3-067; status.yaml inconsistent
**Finding:** R1 routed the FK-48 §48.2.2 mandatory-target derivation (`assertion_weakness`
finding-typing, `addressed_part`, `extract_mandatory_targets`, prompt section) to
AG3-067/AG3-064, but (a) `status.yaml` still only declares `depends_on: AG3-044, AG3-065`,
and (b) AG3-067 does **not** own that derivation — its source concepts are FK-37/FK-38, and
its own `story.md:34/:41` explicitly states it only *consumes* `mandatory_target_results`
and routes the producer to AG3-079. Real code still derives per `Severity.BLOCKING`
(`spawn.py:147`) with no `addressed_part` and no `finding_type` on `Finding`
(`protocols.py:190-213`).

**Root-cause check:** The R1 routing was wrong. There is no existing story that owns
`extract_mandatory_targets`/`assertion_weakness`/`addressed_part`: AG3-067 = FK-37/38
consume-side, AG3-064 = FK-33 stage-registry typing. The derivation is FK-48 §48.2.2,
which is AG3-079's own authoritative concept (per `_STORY_INDEX.md` line 80).

**Resolution (Option A of the review — AG3-079 owns FK-48 §48.2.2/§48.2.3):**
- Added FK-48 §48.2.2 and §48.2.3 to the story's **source concepts** (header).
- Rewrote the Schnitt-Klarstellung block: the derivation is now **in scope**; only the
  FK-38 §38.1.4 *consume-side* (`feedback.json` round-2 feedback) stays at AG3-067, and the
  Layer-2 stage-registry typing stays at AG3-064.
- §1 Ist-Zustand: documented the real non-conformity (`Severity.BLOCKING` filter, missing
  `addressed_part`, `Finding` has no `finding_type`) and that this story pulls it onto the
  FK-48 §48.2.2 standard; adjusted the "do not rebuild" list (`derive_targets` is now
  "adapt, not from scratch"; `AdversarialTarget` only additively extended by `addressed_part`).
- New **In-Scope §2.1.0** + new **AC0** for the derivation: `assertion_weakness`-typed
  Findings (`FAIL`/`PASS_WITH_CONCERNS`) → targets with `addressed_part`; a plain BLOCKING
  finding without the type yields no target; §48.2.3 prompt section inserted only when
  targets exist. Two derivation tests mandated. DoD updated to "AK 0-9".
- §2.2 Out-of-Scope: replaced the false AG3-067 routing with the correct split —
  AG3-067 owns the FK-38 §38.1.4 consume-side only (cited `AG3-067 story.md:34/:41`),
  AG3-064 owns the stage-registry typing; the §48.2.2 derivation is explicitly noted as
  NOT belonging to AG3-067.
- Guardrails (ZERO DEBT) + §6 sub-agent hints flipped from "do NOT make the derivation
  FK-conform here" to "pull `derive_targets` → `extract_mandatory_targets` FK-48 §48.2.2-conform,
  additive `finding_type`/`addressed_part`", keeping the FK-38 consume-side at AG3-067.

**status.yaml:** No change. `depends_on: [AG3-044, AG3-065]` matches `_STORY_INDEX.md`
line 80; AG3-067 is a downstream consumer (earlier wave, abstracts against the
`adversarial.json` schema), not a hard predecessor of AG3-079, so no edge is added. The
title already references `FK-48 §48.1-§48.2.5`, which covers §48.2.2.

---

## Anchor Issue

### R2 ERROR 2 — wrong `_dimension_specs.py:37,83-90` anchor for "SSOT-Konstanten"
**Finding:** §6 cited `_dimension_specs.py:37,83-90` for "Dim `NO_ADVERSARIAL`, SSOT-Konstanten".
Verified: line 37 is the `NO_ADVERSARIAL` enum member (correct), but the producer/stage SSOT
constants are **imported** at `:15-17` and **re-exported** at `:111-114`; lines `83-90` are the
`CODE_ONLY_DIMENSIONS`/`CODE_ONLY_EVALUATED` code tables, not SSOT constants. The true SSOT
source is `core_types/qa_artifact_names.py:77,90`.

**Resolution:** Corrected the §6 anchor: `_dimension_specs.py:37` (Dim enum only); noted that
`ADVERSARIAL_PRODUCER`/`ADVERSARIAL_STAGE` are imported there (`:15-17`) and re-exported
(`:111-114`), with the source SSOT pointed at `qa_artifact_names.py:77,90`.

---

## Items not flagged but kept consistent
- All §2.1.x / §2.1.5 / §2.1.8 cross-references re-checked; the new §2.1.0 is prepended and
  did not renumber the existing items 1-9, so all internal references remain valid.
- Stale "consume `derive_targets` unchanged" wording in §2.2 and §6 removed (it contradicted
  the now-in-scope derivation rework).

## Files written
- `stories/AG3-079-adversarial-runtime/story.md` — targeted edits (AG3-057 template
  structure preserved: header Typ/Groesse/BC/Quell-Konzepte, §1 Kontext, §2 Scope (In/Out
  with owner), §3 Akzeptanzkriterien, §4 DoD, §5 Guardrails, §6 Sub-Agent-Hinweise).
- `stories/AG3-079-adversarial-runtime/remediation-r2.md` — this report.

## Files NOT touched
- `status.yaml` — re-reviewed; all fields correct (`depends_on: [AG3-044, AG3-065]` per
  `_STORY_INDEX.md`, `phase: review_pending`). No field genuinely wrong → no change.
- No production code, tests, or `concept/` files modified.
