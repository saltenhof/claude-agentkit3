---
name: lookup-userstory
description: >
  Look up a user story by number. Use when the user asks to view, review, read,
  or familiarize with a user story — e.g. "schau dir Story 84 an", "US 084",
  "mach dich mit User Story 84 vertraut", "guck dir 84 an".
  Queries the local wiki files AND the AK3 Story-Backend (FK-91) for a complete picture.
argument-hint: "[story-number]"
allowed-tools: "Bash, Read, Glob, Grep"
---

# User Story Lookup: {{project_prefix}}-$ARGUMENTS

## Step 1: Normalize the Number

Extract the bare number from `$ARGUMENTS`. Strip any leading `{{project_prefix}}-`, `US-`, `{{project_prefix}}-FIX-` prefix and leading zeros.

Examples:
- `84`, `084`, `0084`, `{{project_prefix}}-084`, `US-084` → bare number = `84`
- `FIX-001`, `{{project_prefix}}-FIX-001` → bare number = `1`, prefix = `FIX`
- `081a`, `{{project_prefix}}-081a` → bare number = `81`, suffix = `a`

Build the canonical Story-ID variants: `{{project_prefix}}-{NNN}` (3-digit zero-padded) and `{{project_prefix}}-FIX-{NNN}` if the input contains "FIX".

## Step 2: Query BOTH Sources in Parallel

Story information is split across two locations. You MUST query BOTH simultaneously using parallel tool calls in a single response. Neither source alone is complete.

GitHub is the **code backend only** (branches, PRs) — it is NOT a story tracker.
Story identity, status, attributes and lifecycle live in the **AK3 Story-Backend**
(FK-12 §12.1.1, FK-91). Never query a GitHub Project board or `gh issue` for story data.

### Source A — Local Wiki (story content, QA reports, protocol)

Story definitions, QA reports, and implementation protocols live here:

```
{{wiki_stories_dir}}/
```

Directory naming: `{{project_prefix}}-{NNN}_{slug}` or `{{project_prefix}}-FIX-{NNN}_{slug}`

Find the matching directory:
```bash
ls {{wiki_stories_dir}}/ | grep -i "{{project_prefix}}-.*{bare_number}"
```

Then Read the files inside:
- `story.md` — full story definition (context, scope, acceptance criteria, technical details)
- `protocol.md` — implementation protocol (design decisions, LLM reviews, test results)
- `qa-report-r1.md` (and r2, r3...) — QA review reports per round

Quick overview of all stories, if the index exists:
```
{{wiki_stories_dir}}/INDEX.md
```

### Source B — AK3 Story-Backend (live status, metadata; FK-91 §91.1a)

The authoritative story status, attributes and runtime/telemetry references are
owned by the AK3 Story-Read-Service (`StoryService.list_stories` / `get_story`,
FK-91 §91.1a read endpoints `/v1/projects/{project_key}/stories`,
`/v1/projects/{project_key}/stories/{story_id}`,
`/v1/projects/{project_key}/stories/search?q=`). All story access is
project-scoped; the bare `/v1/stories...` paths are legacy and not routed.

The deterministic export keeps a **1:1 local mirror** of the backend story in
Source A: `agentkit export-story-md` writes `story.md` directly from the backend
story at creation time. So the story content + attributes are already available
locally via Source A. For the **live** lifecycle/run status, query the Story-Read
endpoint of the running AK3 control plane (the control-plane base URL is
configured in the project's `control-plane.json`):

```bash
# Detail view of a single story (GET /v1/projects/{key}/stories/{story_id}, FK-91 §91.1a).
# CONTROL_PLANE_URL is the base URL from control-plane.json.
curl -sS "$CONTROL_PLANE_URL/v1/projects/{{project_key}}/stories/{{project_prefix}}-{NNN}"
```

The detail response returns, per story:
`story_id`, `title`, `story_type`, `lifecycle_status`, `active_phase`,
`phase_status`, `story_size`, `current_run`, `latest_metrics`
(QA rounds, processing time, completion), `labels`, `participating_repos`,
`created_at` and recent events.

If the bare number does not resolve to a known Story-ID locally and the live
read returns no story, report that the story is unknown — do NOT fall back to a
GitHub Project board. If the control plane is not reachable, rely on the Source A
local mirror and note that live status could not be retrieved (do NOT fabricate a
status).

## Step 3: Present Combined Results

After both sources return, present a unified summary:

1. **Title + Status** — `lifecycle_status` + `active_phase` / `phase_status` from the Story-Backend, plus completion date from `latest_metrics`
2. **Type / Size** — `story_type`, `story_size` from the Story-Backend
3. **Kontext** — the problem being solved (from story.md, 1-2 sentences)
4. **Scope** — in-scope / out-of-scope summary (from story.md)
5. **Acceptance criteria** — abbreviated list if >10 items (from story.md)
6. **QA status** — from qa-report if exists: PASS/FAIL + findings count + round number; cross-check `latest_metrics.qa_rounds`
7. **Local file paths** — so the user can open them directly

## Reference: Repository Layout

The repository layout is derived deterministically from `config.repositories[]`
in `.agentkit/config/project.yaml`. Render one row per configured repository:

```
| Repo (name) | Path | Language |
|-------------|------|----------|
| <repositories[i].name> | <repositories[i].path> | <repositories[i].language> |
```

Story identity, status and attributes are owned by the AK3 Story-Backend
(FK-91), not by any external project board.
