---
name: lookup-userstory
description: >
  Look up a user story by number. Use when the user asks to view, review, read,
  or familiarize with a user story — e.g. "schau dir Story 84 an", "US 084",
  "mach dich mit User Story 84 vertraut", "guck dir 84 an".
  Queries both local wiki files AND GitHub for a complete picture.
argument-hint: "[story-number]"
allowed-tools: "Bash, Read, Glob, Grep"
---

# User Story Lookup: {{PROJECT_PREFIX}}-$ARGUMENTS

## Step 1: Normalize the Number

Extract the bare number from `$ARGUMENTS`. Strip any leading `{{PROJECT_PREFIX}}-`, `US-`, `{{PROJECT_PREFIX}}-FIX-` prefix and leading zeros.

Examples:
- `84`, `084`, `0084`, `{{PROJECT_PREFIX}}-084`, `US-084` → bare number = `84`
- `FIX-001`, `{{PROJECT_PREFIX}}-FIX-001` → bare number = `1`, prefix = `FIX`
- `081a`, `{{PROJECT_PREFIX}}-081a` → bare number = `81`, suffix = `a`

Build search variants: no padding, 3-digit zero-padded, 4-digit zero-padded.
Also check `{{PROJECT_PREFIX}}-FIX-` prefix if the input contains "FIX".

## Step 2: Query BOTH Sources in Parallel

Story information is split across two locations. You MUST query BOTH simultaneously using parallel tool calls in a single response. Neither source alone is complete.

### Source A — Local Wiki (story content, QA reports, protocol)

Story definitions, QA reports, and implementation protocols live here:

```
{{WIKI_STORIES_DIR}}/
```

Directory naming: `{{PROJECT_PREFIX}}-{NNN}_{slug}` or `{{PROJECT_PREFIX}}-FIX-{NNN}_{slug}`

Find the matching directory:
```bash
ls {{WIKI_STORIES_DIR}}/ | grep -i "{{PROJECT_PREFIX}}-.*{bare_number}"
```

Then Read the files inside:
- `story.md` — full story definition (context, scope, acceptance criteria, technical details)
- `protocol.md` — implementation protocol (design decisions, LLM reviews, test results)
- `qa-report-r1.md` (and r2, r3...) — QA review reports per round

{{#IF_WIKI_INDEX}}
Quick overview of all stories:
```
{{WIKI_STORIES_INDEX}}
```
{{/IF_WIKI_INDEX}}

### Source B — GitHub Issue + Project Board (live status, metadata)

CRITICAL: GitHub issue numbers DO NOT match story numbers! Issue #84 is NOT {{PROJECT_PREFIX}}-084.

**B1 — Find via Story ID custom field (preferred) or title fallback:**

Query the GitHub Project and match by the `storyId` custom field. This is more reliable than
title matching because the Story ID field is set explicitly at creation.

```bash
{{GH_CONFIG_EXPORT}}
cd {{GH_REPO_LOCAL_PATH}} && gh project item-list {{GH_PROJECT_NUMBER}} --owner {{GH_OWNER}} --format json | python -c "
import sys, json, re
bare = '{N}'
padded = bare.zfill(3)
data = json.loads(sys.stdin.read())

for item in data.get('items', []):
    # Primary: match by Story ID custom field
    story_id = (item.get('story ID', '') or item.get('storyId', '') or '').upper()
    # Fallback: match by title (for items without Story ID field)
    title = item.get('title', '').upper()
    search_text = story_id if story_id else title

    if (f'{{PROJECT_PREFIX}}-{bare}' in search_text
        or f'{{PROJECT_PREFIX}}-{padded}' in search_text
        or f'{{PROJECT_PREFIX}}-FIX-{bare}' in search_text
        or f'{{PROJECT_PREFIX}}-FIX-{padded}' in search_text):
        print(json.dumps(item, indent=2, ensure_ascii=False))
        break
"
```

From the matched item, extract the issue number to get the full issue body:
```bash
{{GH_CONFIG_EXPORT}}
cd {{GH_REPO_LOCAL_PATH}} && gh issue view {ISSUE_NUMBER} --json number,title,body,state,labels
```

Project fields: `status` (e.g. "Approved", "In Progress", "Done"), `storyId`, `epic`, `module`, `size`, `qA Rounds`, `completed At`, `labels`.

## Step 3: Present Combined Results

After both sources return, present a unified summary:

1. **Title + Status** — GitHub issue state (OPEN/CLOSED) + project board status (e.g. "Done") + completion date
2. **Epic / Module / Size** — from GitHub project metadata
3. **Kontext** — the problem being solved (from story.md, 1-2 sentences)
4. **Scope** — in-scope / out-of-scope summary (from story.md)
5. **Acceptance criteria** — abbreviated list if >10 items (from story.md or issue body)
6. **QA status** — from qa-report if exists: PASS/FAIL + findings count + round number
7. **Local file paths** — so the user can open them directly

## Reference: Repository Layout

{{REPO_LAYOUT_TABLE}}

GitHub Project: `{{GH_OWNER}}/projects/{{GH_PROJECT_NUMBER}}` ({{PROJECT_NAME}}) — project board with status tracking.
