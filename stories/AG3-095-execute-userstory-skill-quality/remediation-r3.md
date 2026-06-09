# AG3-095 — Remediation of Codex Review R3

OVERALL R3 verdict: CHANGES-REQUESTED. The single remaining must-fix ERROR
(skill-catalog identity internally inconsistent / non-buildable tests) is
resolved below. No WARNINGs were open in R3 (the only R2 ERROR —
`SkillQualityMetric` `final_status`/`remediation_count` aggregation — was
confirmed RESOLVED in `review-r3.md`). Only `story.md` was rewritten;
`status.yaml` reviewed and left unchanged; this report added. No production
code, tests, or `concept/` files touched. Scope stays strictly within the
AG3-095 cut (`var/concept-gap-analysis/_STORY_INDEX.md:126`).

---

## Must-Fix ERROR

### 1. Skill-catalog identity internally inconsistent (could produce non-buildable tests)

R3 evidence (`review-r3.md`):
- `story.md:23` correctly recorded the real existing bundles as
  `*-core` **bundle IDs** (matching the filesystem).
- But `story.md:35` and `story.md:69` then required catalog "Bundles"
  `lookup-userstory` / `llm-discussion` **without** `-core`, conflating
  the `bundle_id` identity with the `skill_name` identity. A test built
  against that wording would look for non-existent bundle directories.

Root cause (FIX-THE-MODEL): a bundle carries **two distinct identities**
that the story mixed. Verified against the real code and filesystem:
- **`bundle_id`** = directory name = `manifest.json:bundle_id`; it **must**
  equal the directory (mismatch = corruption,
  `src/agentkit/skills/bundle_store.py:546-565`
  `_manifest_bundle_id_mismatch`). All four real bundles are `-core`
  suffixed: `create-userstory-core`, `execute-userstory-core`,
  `llm-discussion-core`, `lookup-userstory-core`
  (`src/agentkit/resources/skill_bundles/*/4.0.0/manifest.json`).
- **`skill_name`** = harness-facing skill identity (`/lookup-userstory`),
  also mirrored in `variants[CORE]`
  (`bundle_store.py:588-599`); it is **suffix-free**.
- Profile rule (`SkillProfile = {CORE, ARE}`, `bundle_store.py:196-203`):
  ARE vs. non-ARE are **separate bundles** (own `bundle_id`, own profile),
  not an in-skill branch.
- FK-43 §43.3.1 itself lists the *skill identities* and an internally
  inconsistent "Verzeichnis" column (`create-userstory-core/` but
  `lookup-userstory/`) — confirmed at
  `concept/technical-design/43_skills_system_task_automation.md:186-203`.
  The authoritative on-disk `bundle_id` layout is uniformly `-core`.

Resolution (all in `story.md`, no code/concept touched):

1. **New explicit identity-model block** in Ist-Zustand (story.md §1):
   defines `bundle_id` (profile-suffixed, must match directory) vs.
   `skill_name` (suffix-free, harness identity) vs. the profile rule, each
   with a verified `bundle_store.py` anchor.
2. **Ist-Zustand bundle inventory rewritten** to list every existing
   bundle as `bundle_id: …-core` / `skill_name: …`, and the missing
   bundles as new `bundle_id`s (`create-userstory-are`,
   `execute-userstory-are` Profile `ARE`; `manage-requirements-core`,
   `semantic-review-core` Profile `CORE`).
3. **Scope 2.1.2 rewritten** so the catalog-completeness criterion is
   stated once, consistently: `bundle_id` profile-suffixed, `skill_name`
   = FK-43 identity; missing-vs-present bundles enumerated by `bundle_id`.
4. **AC2 rewritten** to check **manifest `skill_name`** for the FK-43
   identities (CORE *and* ARE for create/execute) while `bundle_id` stays
   profile-suffixed, plus `bundle_id`/directory consistency
   (`bundle_store.py:546-565`) and per-bundle digest. This is the option
   the reviewer offered ("AC2 checks manifest `skill_name` … while bundle
   IDs remain suffixed").
5. **Test bullet (Scope 2.1.5) aligned**: catalog completeness via
   `skill_name` presence + `bundle_id`/directory consistency; explicitly
   requires both CORE and ARE bundles for create/execute.
6. **Quell-Konzepte header (story.md §0)** annotated: FK table lists
   `skill_name` identities; `bundle_id` maps profile-suffixed.
7. **Scope 2.1.3 + AC3** now name the semantic-review bundle as
   `bundle_id: semantic-review-core` (`skill_name: semantic-review`).
8. **Sub-agent Hinweise** add a "do not mix identity" rule and explain
   the FK "Verzeichnis"-column inconsistency vs. the real `-core` layout.

"Bundle" no longer mixes the two identities anywhere in the story; a test
written from the story now targets real directories (`*-core` / `*-are`)
and checks the FK identities via `skill_name`.

---

## Corrected / added code anchors (verified file:line)
- `src/agentkit/skills/bundle_store.py:196-203` — `SkillProfile`
  (`CORE`/`ARE`); ARE = separate bundle.
- `src/agentkit/skills/bundle_store.py:546-565` —
  `_manifest_bundle_id_mismatch`: directory name is authoritative
  `bundle_id`; mismatch = corruption.
- `src/agentkit/skills/bundle_store.py:588-599` — `variants` parsing
  (`variants[CORE]` mirrors `skill_name`).
- `src/agentkit/resources/skill_bundles/{create,execute,llm-discussion,
  lookup}-*-core/4.0.0/manifest.json` — real `bundle_id` (`*-core`) +
  `skill_name` (suffix-free) on disk.
- `concept/technical-design/43_skills_system_task_automation.md:186-203` —
  FK-43 §43.3.1/§43.3.2 tables (identities + inconsistent dir column).

R2 anchors carried over unchanged and re-confirmed accurate:
`records.py:23`, `metrics.py:67`, `phase.py:1015`, `runner.py:39-41`,
`audit_bundle.py:49-50`.

## status.yaml
Reviewed: `type: implementation`, `phase: review_pending`, `size: L`,
`depends_on: [AG3-027, AG3-048]` all match `_STORY_INDEX.md:126`. No field
wrong; file left unchanged.

## Files written (AG3-095 only)
- `stories/AG3-095-execute-userstory-skill-quality/story.md` (rewritten)
- `stories/AG3-095-execute-userstory-skill-quality/remediation-r3.md` (this)
- status.yaml: unchanged (no wrong field).
