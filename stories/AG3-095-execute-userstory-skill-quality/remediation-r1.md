# AG3-095 — Remediation of Codex Review R1

OVERALL R1 verdict: CHANGES-REQUESTED. All seven must-fix ERRORs and all
three WARNINGs are resolved below. Only `story.md` was rewritten;
`status.yaml` was reviewed (no field wrong) and left unchanged; this report
was added. No production code, tests, or `concept/` files touched.

Scope guard: AG3-095 cut per `var/concept-gap-analysis/_STORY_INDEX.md:126`
(execute-userstory-core bundle + Pflicht-/Optional-Katalog-Vollstaendigkeit
+ SkillQualityMetric/collect_quality_metrics from Telemetry+Failure-Corpus).
No scope expansion: telemetry/failure-corpus schema changes are routed to
their owner stories, not pulled in here.

---

## Must-Fix ERRORs

### 1. Optional-Katalog not covered in AC/Tests (Section 1, ERROR)
FK split: Pflicht `43_skills_system_task_automation.md:186-195`, Optional
`:197-203`. Story-AC2 only tested "Pflicht-Skills".
Resolution: Quell-Konzepte now list `§43.3.1`, `§43.3.2`, `§F-43-029`,
`§43.3.3`, `§43.6.2`. Scope 2.1.2 enumerates Pflicht
(`create-userstory-core`, `create-userstory-are`, `execute-userstory-core`,
`execute-userstory-are`, `lookup-userstory`, `llm-discussion`) and Optional
(`manage-requirements`, `semantic-review`), and explicitly excludes
`Research` as a non-bundle worker-prompt. AC2 now asserts all Pflicht AND
Optional bundles present plus `Research` confirmed not-a-bundle. Test bullet
in 2.1.5 mirrors this.

### 2. semantic-review normative content missing (Section 1, ERROR)
F-43-029 (`:211`) requires >=12 dimensions + per-dimension normalized score +
reasoning + structured QA artifact. Story only name-dropped `semantic-review`.
Resolution: New Scope item 2.1.3 and dedicated AC3 require the
`semantic-review` SKILL.md to describe the 12 named dimensions, a normalized
score plus reasoning per dimension, and the structured QA artifact feeding
the Implementation QA-Subflow. F-43-029 added to Quell-Konzepte.

### 3. SkillQualityMetric norm not operationalized (Section 1, ERROR)
FK requires telemetry projections + failure-corpus, incl. `experiment_tag`/
skill-version linkage (`:494-510`). AC said only "typisiertes
SkillQualityMetric".
Resolution: Scope 2.1.4 defines the full `SkillQualityMetric` schema
(fields, filter dimensions `skill_name`/`project_key`/`source_window`/
`bundle_version`, aggregation formulas, fail-closed rules). The
`experiment_tag`/skill-version part is explicitly flagged as not
source-derivable today (see ERROR 4/6) and routed to owners.

### 4. AC3 not testable (Section 2, ERROR)
"Nutzungshaeufigkeit/Erfolg/Incident-Bezug" reduced to "liefert ein
typisiertes SkillQualityMetric".
Resolution: AC4 now lists concrete fields with assertions: `usage_count`,
`successful_runs`, `failed_runs`, `avg_qa_rounds`, `remediation_count`,
`incident_count`, `incident_ids`, `bundle_version`, `source_window`,
`attribution`; success-rate denominator fixed to `usage_count`; aggregation
formulas spelled out in Scope 2.1.4.

### 5. AC1 "vollstaendig" without FK-43 §43.3.3 checklist (Section 2, ERROR)
FK §43.3.3 lists 8 concrete steps (`:218-230`).
Resolution: AC1 rewritten as eight enumerated bundle-content assertions
(story read, setup/start, state-read+worker spawn, wait, implementation/start
with in-subflow VerifySystem, awaiting_remediation loop, pass->closure/start,
escalation) plus the explicit "no standalone verify top-phase" assertion.

### 6. Quell-Konzept claim factually wrong (Section 3, ERROR)
Story claimed `§43.3.1` = "Pflicht-/Optional"; actually §43.3.1 = Pflicht
(`:186`), Optional = §43.3.2 (`:197`).
Resolution: Quell-Konzepte corrected to `§43.3.1` (Pflicht), `§43.3.2`
(Optional), `§F-43-029`, `§43.3.3`, `§43.6.2`.

### 7. Self-contradiction on missing data fields (Section 3, ERROR)
In-Scope demanded functional aggregation "from existing sources"; Out-of-Scope
+ Hinweis said "report missing fields, don't build a second model". Real
`StoryMetricsRecord` has no skill fields (`records.py:10-31`).
Resolution: contradiction removed by choosing ONE path — a fail-closed
metric skeleton with explicit owner hand-off. Ist-Zustand 1 now documents the
concept-to-code conflict (no `skill_name`/`skill_version`/`experiment_tag` in
`StoryMetricsRecord` `records.py:10-31`, no `experiment_tag` in `Incident`
`incident.py:178-195`). Scope 2.1.4 collects only source-available signals;
unattributable fields are `None`/`UNATTRIBUTABLE` (AC5), never zero. Field
extensions routed to AG3-081/083 (telemetry) and AG3-078 (failure-corpus) in
Out-of-Scope 2.2. No blocking dependency added (owners deliver the fields
later; this story ships the fail-closed skeleton now within its cut).

### 8 (Review item "Failure-Corpus-Top-Surface keine nutzbare Quelle", Section 4, ERROR)
`FailureCorpus` only has functional `record_incident` (`top.py:109-126`);
the rest raise `NotImplementedError` (`:128-204`). No read surface.
Resolution: Owner decision made explicit — `collect_quality_metrics` reads
via `Telemetry.ProjectionAccessor.read_projection(FC_INCIDENTS)` (Ist-Zustand
+ Scope 2.1.4 + Hinweis), and the conflict with FK-43 §43.6.2 (which names a
failure-corpus top-surface as the read source) is named and routed to AG3-078
in Out-of-Scope 2.2.

### 9 (Review item "Per-Skill-Metriken nicht ableitbar", Section 4, ERROR)
FK wants `experiment_tag` skill-version linkage (`:507-510`); `Incident` has
only `tags` (`incident.py:178-195`); `StoryMetricsRecord` has no
`skill_name`/`skill_version` (`records.py:10-31`).
Resolution: Ist-Zustand 1 documents this; `attribution=UNATTRIBUTABLE` and
`bundle_version=None` are the fail-closed outputs (AC5); the "where does
skill/experiment attribution originate" question is routed to owners
AG3-081/083 and AG3-078 (Out-of-Scope 2.2). No new field invented here.

### 10 (Review item "Ist-Zustand-Dateipfad falsch", Section 4, ERROR — same root as WARNING below)
Bundle path claimed `resources/skill_bundles/execute-userstory-core/4.0.0/`
(root) which does not exist; real is
`src/agentkit/resources/skill_bundles/execute-userstory-core/4.0.0/`
(`skill_name: execute-userstory`, `profile: CORE`).
Resolution: all bundle paths corrected to package-relative
`src/agentkit/resources/skill_bundles/...` throughout (BC line 5, Ist-Zustand,
Scope, Guardrails, Hinweise). Verified real bundles present:
`create-userstory-core`, `execute-userstory-core`, `llm-discussion-core`,
`lookup-userstory-core`; missing ones (`create-userstory-are`,
`execute-userstory-are`, `manage-requirements`, `semantic-review`) named as
the actual delta.

---

## WARNINGs

### W1. Pflichtbefehle too coarse ("vier Konzept-Gates") (Section 2)
Resolution: AC8 now names the four concept gates explicitly
(`check_architecture_conformance.py`, `check_concept_code_contracts.py`,
`check_concept_frontmatter.py`, `compile_formal_specs.py`) plus
`scripts/ci/check_remote_gates.ps1`. (Verified the four scripts exist under
`scripts/ci/`.)

### W2. Resource path unclear/dangerous (Section 3)
Resolution: same fix as ERROR 10 — every `resources/skill_bundles/` reference
made package-relative `src/agentkit/resources/skill_bundles/`.

### W3. (covered) — resource path / digest discipline
Resolution: Hinweis clarifies digest must be recomputed via the existing
`bundle_store` digest path after every bundle change, not hand-rolled.

---

## Corrected code anchors (verified file:line)
- `src/agentkit/skills/top.py:317-323` — empty `SkillQualityMetric`
  placeholder (was `:317`).
- `src/agentkit/skills/top.py:662-677` — `collect_quality_metrics` raises
  `NotImplementedError` (was `:662-675`).
- `src/agentkit/closure/post_merge_finalization/records.py:10-31` —
  `StoryMetricsRecord`, no skill fields.
- `src/agentkit/failure_corpus/incident.py:178-195` — `Incident`, no
  `experiment_tag` (was `:180-195`).
- `src/agentkit/failure_corpus/top.py:109-126` — `record_incident`;
  `:128-204` — NotImplemented read methods (was `:90-126`/`:128-204`).
- `src/agentkit/telemetry/projection_accessor.py` — the read surface used.
- `src/agentkit/resources/skill_bundles/execute-userstory-core/4.0.0/`
  (`SKILL.md` + `manifest.json`) — real bundle location.

## status.yaml
Reviewed: `type: implementation`, `phase: review_pending`, `size: L`,
`depends_on: [AG3-027, AG3-048]` all match `_STORY_INDEX.md:126`. No field
wrong; file left unchanged.

## Files written
- `stories/AG3-095-execute-userstory-skill-quality/story.md` (rewritten)
- `stories/AG3-095-execute-userstory-skill-quality/remediation-r1.md` (this)
- status.yaml: unchanged (no wrong field).
