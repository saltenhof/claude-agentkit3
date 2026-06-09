# AG3-061 — Remediation r2 (hostile Codex review-r2.md)

Scope of this remediation: `story.md` only. `status.yaml` untouched (every field
re-verified correct — see below). No production code, tests, or concept files
touched. All code/concept anchors below re-verified against the real tree at
remediation time and corrected to `file:line` / `§section`. AG3-057 template
structure preserved (title block → §1 Ist-Zustand → §2 Scope/Out-of-Scope →
§3 ACs → §4 DoD → §5 Guardrails → §6 Sub-Agent-Hinweise). ARCH-55 honoured
(all identifiers/paths English; concept-prose German per CLAUDE.md).

review-r2.md confirmed every r1 must-fix as **resolved** (3-stage model incl.
Worker-Hints, `ChangeEvidencePort` diff-owner, determinism vs. `evidence_epoch`,
`BundleEntry.repo_id`, `status.yaml.unblocks`). One remaining must-fix ERROR
stood; it is the only finding in this round.

## Remaining Must-Fix ERROR (review-r2 §"Remaining Must-Fix ERRORs")

### MF1 — `{{BUNDLE_MANIFEST_HEADER}}` / `render_prompt_header` routing not buildable against the real prompt-runtime cut

**Finding (review-r2):** r1 scoped placeholder insertion into five
`prompts/sparring/review-*.md` templates and routed runtime hydration to AG3-062.
But (a) the real prompt resources are registered as internal `qa-*` templates,
not those five `review-*` files (`manifest.json:29/33/37/41`), and (b) AG3-062
only owns `review-preflight.md` + its manifest entry — **not**
`BUNDLE_MANIFEST_HEADER` substitution. Fix: map FK-28 review templates to the
real prompt IDs/manifest **and** add explicit hydration ownership, **or** route
that exact work into AG3-062 with ACs.

**Re-verification of the real cut (load-bearing for the fix):**
- No `prompts/sparring/` directory and none of the five `review-*.md` files exist.
  Glob `resources/**/prompts/**/*.md` → only flat `internal/prompts/worker-*.md`
  + `qa-*.md`; Glob `**/sparring/**` → 0 hits.
- The real review templates are `qa-review` / `qa-semantic-review` /
  `qa-doc-fidelity` / `qa-adversarial-review`
  (`resources/internal/prompts/manifest.json:29/33/37/41`), role-mapped in
  `verify_system/llm_evaluator/structured_evaluator.py:172-176` (`_ROLE_TEMPLATE`).
- Placeholder hydration in AK3 is **not** a `{{...}}` double-brace substitution.
  It is `str.format_map` with single-brace keys from `_build_placeholder_map`
  (`prompt_runtime/composer.py:123-146`, applied at `:288-290` in
  `compose_named_prompt`). The hydration owner is the **prompt-runtime BC**,
  not the Evidence-Assembler and not a review-turn.
- AG3-062's scope confirms it owns **only** `review-preflight.md` + its manifest
  entry (`AG3-062 story.md:44`, AC9 `:74`, sub-agent hint `:95`) — it never
  claims `{{BUNDLE_MANIFEST_HEADER}}` substitution.
- `render_prompt_header()` is genuinely AG3-061's cut: it is a method **on**
  `BundleManifest` (FK-28 §28.5.3), real in the concept at
  `28_evidence_assembly_review_vorbereitung.md:746`.

**Resolution (FIX THE MODEL — chosen option: option 1 "map + ownership",
combined with drift-routing; deliberately NOT option 2):** Routing the work into
AG3-062 would be a false attribution — AG3-062's scope does not deliver
`BUNDLE_MANIFEST_HEADER` substitution, so claiming it does would break
cross-story self-consistency (the explicit prohibition in the task). Instead:

1. **Keep the Python producer in AG3-061.** `BundleManifest.render_prompt_header()`
   stays fully in scope as the owner of the header **text** — it belongs to the
   `BundleManifest` class this story owns (FK-28 §28.5.3). In-Scope item 6
   rewritten from "placeholder + template edits" to "**Header-Producer
   `render_prompt_header()`**" only. AC5 already tests this producer
   (determinism) and is unchanged and correct.
2. **Remove the unbuildable claim.** Dropped the assertion that AG3-061 inserts
   `{{BUNDLE_MANIFEST_HEADER}}` into five `prompts/sparring/review-*.md` files
   (those files / that directory do not exist) and dropped the wrong claim that
   AG3-062 performs the turn-side substitution.
3. **Route the drift correctly.** Added a new §1 paragraph
   "Header-Producer vs. Review-Template-Drift" documenting, with real anchors,
   that FK-28 §28.8.3's template set (`prompts/sparring/review-*`) and `{{...}}`
   convention do not match the real cut (`qa-*` flat templates + `format_map`
   hydration in the prompt-runtime BC). This is FK-vs-code drift — **exactly
   analogous to the §28.3.6 diff-owner drift already routed in r1** — and is
   routed to the **doc-only concept follow-up (Wave 10, `_STORY_INDEX.md:138-145`,
   FK-28-owning doc-only unit)**, not into this code cut.
4. **New Out-of-Scope bullet (with owner).** Added an explicit Out-of-Scope
   bullet for "`{{BUNDLE_MANIFEST_HEADER}}` placeholder insertion + turn
   hydration + the five `review-*` templates" → NOT buildable as AK3 code →
   doc-only Wave 10; and tightened the AG3-062 Out-of-Scope bullet to state
   explicitly that AG3-062 owns **only** `review-preflight.md`, **not** the
   `BUNDLE_MANIFEST_HEADER` substitution (owner-fidelity guard).
5. **Quell-Konzepte + §6 sub-agent hint** updated to match: the FK-28 §28.8
   reference now says only `render_prompt_header()` is in scope and the
   placeholder/templates are doc-only drift; a new §6 hint (parallel to the
   existing Diff-Owner hint) tells the implementer to build the producer but
   **not** the non-existent templates / `{{...}}` substitution, and not to
   attribute it to AG3-062.

(Resolved in-story; producer owned by AG3-061, drift routed to doc-only Wave 10,
no false attribution to AG3-062.)

## status.yaml
Unchanged. Re-verified: `status: draft` / `phase: review_pending` correct for the
running review cycle; `depends_on: [AG3-022, AG3-026, AG3-044]` matches
`_STORY_INDEX.md:52`; `unblocks: [AG3-062, AG3-063, AG3-067]` (set in r1) matches
`_STORY_INDEX.md:53/54/58`. No field is genuinely wrong, so none was changed.

## Cut-fidelity note
The chosen resolution does not invent an AG3-062 capability and does not create a
second prompt-template/manifest truth. The producer (`render_prompt_header()`)
stays with its rightful owner (`BundleManifest` in AG3-061); the template-wiring/
hydration belongs to the prompt-runtime BC and the naming/convention mismatch is
a documentation drift handled by the existing doc-only wave — the same pattern r1
used for the §28.3.6 `core/git.py` drift.

## Files written (this remediation)
- `stories/AG3-061-evidence-assembly-core/story.md` (rewritten per MF1)
- `stories/AG3-061-evidence-assembly-core/remediation-r2.md` (this file)

Only AG3-061 files were written. No production code, tests, concept files, or
other stories' files were touched. `status.yaml` not modified.
