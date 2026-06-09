# AG3-095 — Remediation of Codex Review R2

OVERALL R2 verdict: CHANGES-REQUESTED. The single remaining must-fix ERROR
(SkillQualityMetric `final_status`/`remediation_count` aggregation not
deterministic) is resolved below. No WARNINGs were open in R2 (all R1
path/catalog/semantic-review/failure-corpus-routing items were already marked
resolved; cross-story routing to AG3-081/083/078 accepted). Only `story.md`
was rewritten; `status.yaml` reviewed and left unchanged; this report added.
No production code, tests, or `concept/` files touched. Scope stays strictly
within the AG3-095 cut (`_STORY_INDEX.md:126`).

---

## Must-Fix ERROR

### 1. `SkillQualityMetric` aggregation not deterministic for status/remediation counts

R2 evidence:
- `story.md:44` required `remediation_count` without a derivation rule.
- `story.md:47` said `successful_runs`/`failed_runs` come from `final_status`
  but did not define success vs failure vs unknown, nor how
  `remediation_count` derives from `StoryMetricsRecord.qa_rounds`.
- Real code makes this blocking: `final_status` is a free string passed
  through unvalidated (`metrics.py:29/93`, `records.py:23`, and
  `phase.py:1015` `final_status=status`). Two live vocabularies exist:
  `PipelineRunResult.final_status` (`runner.py:39-41`:
  `completed`/`failed`/`escalated`/`blocked`/`yielded`) and the terminal
  success set in `audit_bundle.py:50` (`COMPLETED`/`DONE`/`MERGED`/`CLOSED`).

Resolution (all in `story.md`):

1. **Normalization rule.** `collect_quality_metrics` normalizes every
   `final_status` via `final_status.strip().upper()` before classification
   (Scope 2.1.4 deterministic-classification block, AC4a).

2. **Closed, typed classification sets (no inline string cascades).**
   - Success-Set = the **existing** `_COMPLETED_STATUSES`
     (`{"COMPLETED","DONE","MERGED","CLOSED"}`, `audit_bundle.py:50`),
     imported/reused as the single source of truth for "successful run"
     (FIX-THE-MODEL / SINGLE-SOURCE-OF-TRUTH), not re-invented.
   - Failure-Set = `{"FAILED","ESCALATED","BLOCKED"}` (terminal fail/abort
     statuses from `runner.py`).
   - Unknown/fail-closed: anything outside both sets (e.g. `"YIELDED"` =
     non-terminal, or an unknown spelling) increments a new
     `unknown_status_runs` field and is **never** silently counted as
     success or failure (FAIL-CLOSED). New field added to the schema
     (Scope 2.1.4), to AC4, and to the test bullet (2.1.5).

3. **Counting invariant.** Added explicit invariant
   `successful_runs + failed_runs + unknown_status_runs == usage_count`
   with a dedicated test assertion (AC4a, test bullet 2.1.5).

4. **`remediation_count` derivation defined.** `qa_rounds` =
   `len(load_attempts(story_dir, "implementation"))` (`metrics.py:67`) =
   number of implementation QA attempts; the first attempt is not a
   remediation, so per entry `remediation_count = max(qa_rounds - 1, 0)`,
   window-summed; `0` (never `None`) for an empty window because the value
   is always source-derivable (Scope 2.1.4 aggregation rules, AC4b). The
   field is retained (not removed) because it is now deterministically
   derivable.

5. **Ist-Zustand made self-consistent.** Ist-Zustand bullet 1 now records
   that `final_status` is a free string (`records.py:23`, `phase.py:1015`)
   with the two divergent vocabularies, explaining why normalization +
   classification (not raw aggregation) is required.

6. **Guardrail + Hinweise updated.** FAIL-CLOSED guardrail covers the
   unknown-status bucket; FIX-THE-MODEL guardrail records the
   `_COMPLETED_STATUSES` reuse decision; sub-agent Hinweise spell out the
   normalize/classify/derive procedure with real anchors.

---

## Corrected / added code anchors (verified file:line)
- `src/agentkit/closure/post_merge_finalization/records.py:23` —
  `final_status: str` (free string).
- `src/agentkit/closure/post_merge_finalization/metrics.py:67` — `qa_rounds`
  source (`len(load_attempts(story_dir, "implementation"))`).
- `src/agentkit/closure/phase.py:1015` — `final_status=status` (status
  passed through unvalidated).
- `src/agentkit/pipeline_engine/runner.py:39-41` — `PipelineRunResult`
  status vocabulary (`completed`/`failed`/`escalated`/`blocked`/`yielded`).
- `src/agentkit/telemetry/audit_bundle.py:49-50` — existing
  `_COMPLETED_STATUSES` terminal-success set, reused as Success-Set.

## status.yaml
Reviewed: `type: implementation`, `phase: review_pending`, `size: L`,
`depends_on: [AG3-027, AG3-048]` all match `_STORY_INDEX.md:126`. No field
wrong; file left unchanged.

## Files written (AG3-095 only)
- `stories/AG3-095-execute-userstory-skill-quality/story.md` (rewritten)
- `stories/AG3-095-execute-userstory-skill-quality/remediation-r2.md` (this)
- status.yaml: unchanged (no wrong field).
