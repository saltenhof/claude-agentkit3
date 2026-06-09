# AG3-091 — Remediation R4 (post hostile Codex review, round 4)

Scope of this remediation: `story.md` only. No `status.yaml` field was genuinely
wrong this round (all fields verified correct — see below). No production code, tests,
concept/formal files, or other stories' files were touched. The single remaining
must-fix ERROR was re-verified against the real formal spec before fixing.
AG3-057 template structure preserved; ARCH-55 English wire-field discipline kept;
AC count stays 9.

Only AG3-091 files written:
- `stories/AG3-091-frontend-read-models-execution-input-surface/story.md`
- `stories/AG3-091-frontend-read-models-execution-input-surface/remediation-r4.md` (this file)

---

## Remaining Must-Fix ERRORs (review-r4.md)

### ERROR 1 — AC1 internally inconsistent with the formal `execution_limits` contract
- **Finding (review-r4.md:15):** AC1 said `ExecutionLimits` has "allen sechs Caps"
  (`story.md:55`), but `frontend-contracts.entity.execution_limits` defines `project_key`
  plus **five** cap fields: `repo_parallel_cap`, `merge_risk_cap`,
  `max_parallel_agent_cap`, `llm_pool_cap`, `ci_capacity_cap` (`entities.md:728`). The
  matching command `update_execution_limits` has the same five cap inputs
  (`commands.md:349`). Fix AC1 to "five caps plus `project_key`" unless a sixth cap is
  intentionally being added.
- **Re-verified against the CURRENT formal spec (the finding is correct):**
  - `frontend-contracts.entity.execution_limits` (`entities.md:728-753`):
    `identity: project_key` plus exactly five integer caps —
    `repo_parallel_cap` (`:737`), `merge_risk_cap` (`:740`), `max_parallel_agent_cap`
    (`:743`), `llm_pool_cap` (`:746`), `ci_capacity_cap` (`:749`). No sixth cap exists.
  - `frontend-contracts.command.update_execution_limits` (`commands.md:349-396`): inputs
    are the same five caps (`:360-374`) plus `project_key` (`:357`) and `op_id` (`:375`,
    command-only idempotency token, not a cap). Confirms five caps, no sixth.
  - No intent to add a sixth cap exists anywhere in the AG3-091 cut — §2.1 item 1
    (`story.md:35`) and §5 ARCH-55 (`story.md:73`) **already** name exactly the five
    canonical caps. AC1 was the lone stale "sechs" left over from an earlier draft, so it
    was a pure internal-consistency defect, not a scope question.
- **Resolution (in-story, no scope change, no spec touch):** AC1 (`story.md:55`) rewritten
  from "mit allen sechs Caps als non-negative Integer (`execution_limits`-Wire-Shape)" to
  "mit `project_key` plus den fuenf Caps
  `repo_parallel_cap`/`merge_risk_cap`/`max_parallel_agent_cap`/`llm_pool_cap`/`ci_capacity_cap`
  als non-negative Integer (`execution_limits`-Wire-Shape, `entities.md:728-753`)". AC1
  now matches §2.1 item 1, §5, and the formal entity exactly. No formal spec was modified
  (the entity already specifies five caps; the story now reflects it).
- **Internal-consistency sweep:** grepped the full story for `sechs|six|6 Caps|6 caps` —
  **no remaining matches**. The cap count is now uniform (five caps + `project_key`)
  across §1, §2.1, §3 AC1, and §5.

---

## status.yaml — re-verification (no change needed)
All fields re-checked against the current state; none is genuinely wrong, so the file was
**not** touched:
- `title` — `... (Frontend-Read-Models + Execution-Limits-Read)`: matches the read-layer
  cut and the H1 in `story.md:1`. (Fixed in R3; still correct.)
- `depends_on` — `[AG3-090, AG3-098, AG3-100, AG3-077]`: AG3-090 (routing shell), AG3-098
  (caps source), AG3-100 (snapshot/next surface consumed read-only + `next`-Reason entity
  owner), AG3-077 (`StoryAreLink` write-paths / coverage read-source). All four are real
  read/consume dependencies asserted in the body. Correct.
- `status: draft` / `phase: review_pending` — story still under review; unchanged.
- `type: implementation`, `size: L` — consistent with body. Unchanged.

## Round-3 ERROR carry-over (review-r4.md confirmed resolved)
review-r4.md explicitly verified the three R3 ERRORs as resolved (R3-ERROR-1 `next`-route
grounded in AG3-100 actual scope; R3-ERROR-2 title/scope read-layer-consistent + AG3-077
in `depends_on`; R3-ERROR-3 coverage entity owned by AG3-091, `StoryAreLink` writes routed
to AG3-077). No further action required; no regression introduced by the AC1 edit.

## Anchor re-verification touched this round (no stale file:line)
- `entities.md:728-753` `execution_limits` (identity `project_key` + five caps) — confirmed.
- `commands.md:349-396` `update_execution_limits` (five caps + `project_key` + `op_id`) —
  confirmed; no sixth cap.
- `story.md:35` §2.1 item 1 five-cap list — confirmed already correct.
- `story.md:73` §5 ARCH-55 five-cap wire-field list — confirmed already correct.

## Routing correctness check (no false claims about other stories)
No routing changed this round. The AC1 fix is purely internal to AG3-091's own
`limits` read-model and its existing `execution_limits` binding; it neither adds nor
removes any cross-story claim. AG3-100 (snapshot/next + `next`-Reason) and AG3-077
(`StoryAreLink` writes) routes are untouched and remain as re-verified in R3.

## Template-Treue
AG3-057 template preserved: Title/Scope-Label/Meta/Quell-Konzepte -> §1 Kontext/
Ist-Zustand (belegt) -> §2 Scope (2.1 In Scope / 2.2 Out-of-Scope mit Owner) -> §3
Akzeptanzkriterien -> §4 DoD -> §5 Guardrail-Referenzen -> §6 Hinweise + Cross-Story-
Voraussetzungen. AC count stays 9 (only AC1 wording corrected; no AC added/removed). DoD
"AK 1-9" unchanged. ARCH-55 English wire-field discipline kept.
