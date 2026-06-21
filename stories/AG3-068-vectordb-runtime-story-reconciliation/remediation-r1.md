# AG3-068 — Remediation r1 (Codex Review CHANGES-REQUESTED)

Scope of this remediation: only `story.md` rewritten. `status.yaml` checked — already
correct (`depends_on: AG3-070` is the hard dependency the config-owner fix requires),
no field changed. No production code, tests, or `concept/` files touched.

All code anchors below were re-verified against the real tree; corrected file:line
references are reflected in the rewritten `story.md`.

---

## 1. Konzept-Vollstaendigkeit

### ERROR — Concept-Corpus-Freshness (FK-21 §21.11.4 Step 0 #2) fehlte
**Resolution: routed OUT to owner.** §21.11.4 Step 0 has two preflight checks.
Check 1 (Weaviate-Readiness) is genuinely this story's runtime concern and is now an
explicit in-scope item: §2.1.2 + AC2 add the canonical `agentkit.backend.vectordb.wait_for_weaviate`
entrypoint with Exit 0/1 fail-closed semantics. Check 2 (Concept-Corpus-Freshness) is
explicitly Concept-Graph/dev-tooling (Kap. 13.9.9, `concept_graph.json`/`corpus_revision`,
`agentkit concept build`), deterministic and **independent of the VectorDB** — outside this
story's cut (`_STORY_INDEX.md:64` scopes AG3-068 to the Weaviate/VectorDB runtime only). It
is now Out-of-Scope **with named owner** = ConceptContext / Concept-KB-Dev-Tooling (§2.2),
consistent with the already-excluded `concept_*` tooling. No scope expansion.

### ERROR — Repo-Affinity (FK-21 §21.9) verwaessert
**Resolution: fixed in story.** §2.1.6 + AC6 now specify the full §21.9 contract:
Strong-Evidence parser over `## Betroffene Dateien` only (logs/examples/refs ignored,
§21.9.1), Longest-Prefix-Match against `repositories[]` (§21.9.2), Root/Docs fallback via the
Module field (§21.9.3), exact deterministic sort "hits descending, then lexicographic" with
first entry as Spawn-CWD anchor only (§21.9.5), and human-correction preservation (§21.9.2).
Return type tightened to `RepoAffinityResult`.

### WARNING — FK-21 §21.4 protocol unvollstaendig
**Resolution: aligned to code contract + doc-only routed.** The binding protocol is the
typed `VECTORDB_SEARCH` telemetry event whose mandatory fields are fixed in code
(`events.py:186-191`). §2.1.10 + AC9 pin those exact fields and state that the FK-prose JSON
fields (`above_threshold`/`sent_to_llm`/`llm_conflicts`/`threshold_used`/`search_mode`) are
superseded by the code contract and to be reconciled doc-only — code is not bent to stale
prose (CONTRACT-DISZIPLIN guardrail added in §5).

## 2. AC-Schaerfe

### ERROR — `StoryMdExportResult` nicht testbar spezifiziert
**Resolution: fixed in story.** §2.1.8 + AC8 name the exact fields/types
(`success: bool`, `story_md_path: str`, `file_size_bytes: int`, `error: str`) and the error
semantics (success→`error=""`; any blocker→`success=False` + populated `error`).

### ERROR — Konfliktbestaetigung unklar
**Resolution: fixed in story.** §2.1.5 + AC5 define the set-rule per FK §21.12/§21.4.1:
flag becomes `true` only when Stage-2 verdict is `FAIL` (conflict) **and** the conflict was
cleared by adapting (not discarding) the story; confirmed by the story creator within the
mandatory story-creation step. `PASS` or an unresolved/unadapted conflict leaves it
`false`/absent. Two tests required.

### WARNING — `story_sync`/`repair-story-md`/`story_search`-Payload zu grob
**Resolution: fixed in story.** `story_search` signature now carries
`search_mode="hybrid"`, `project_id`, `limit=20` (§2.1.1, AC1). `repair-story-md` flow
specified (scan/validate/reexport, report N/M/K, §2.1.7, AC7). CLI args and the frozen
result model are pinned.

## 3. Klarheit/Eindeutigkeit

### ERROR — Config-Ownership widerspruechlich (zweiter Owner)
**Resolution: fixed — single hard owner.** §2.1.9 + §2.2 make AG3-070 the **sole** owner
of the `vectordb` stanza (`_STORY_INDEX.md:66`); `status.yaml` keeps the **hard**
`depends_on: AG3-070`. The previous "minimal-define if AG3-070 not merged" escape clause is
removed — this story consumes only and is blocked (not decoupled) if AG3-070 is unmerged.
No second owner.

### ERROR — `StoryMdExportResult` Typ-Konflikt (dataclass vs Pydantic)
**Resolution: aligned to FK.** FK (`21_story_creation_pipeline.md:687`) shows
`@dataclass(frozen=True)`. Story now mandates the FK-conform frozen dataclass (§2.1.8, AC8,
§5), dropping the wrong "frozen Pydantic" demand.

### WARNING — Modulpfad Weaviate-Readiness unklar
**Resolution: fixed — canonical path pinned.** §2.1.2 + AC2 set the canonical FK module
path `agentkit.backend.vectordb.wait_for_weaviate` (§21.11.4) as a thin App-layer CLI shim that
consumes the `integrations/vectordb` adapter — satisfies both the FK-named entrypoint and
the "integrations bleibt duenn" rule.

## 4. Kontext-Sinnhaftigkeit

### ERROR — `story_creation_review` fehlt im Code-`StructuredEvaluator`
**Resolution: explicitly modelled in scope.** Verified: `ReviewerRole` has only
`qa_review`/`semantic_review`/`doc_fidelity` (`structured_evaluator.py:126-137`); FK-11
§11.5.1 (`:486`) and FK-21 §21.4.1 require `story_creation_review`. New §2.1.4 + AC4 scope
the extension inside the existing evaluator (enum value `STORY_CREATION_REVIEW`, check-id
whitelist `{"conflict_assessment"}`, `_ROLE_CHECK_IDS`/`_ROLE_TEMPLATE` entries, template
`vectordb-conflict`) with contract/golden tests pulled along — no second evaluator path.
Anchors corrected to `structured_evaluator.py:126/143/165/172` and `:299-301`.

### ERROR — Telemetrie-AC passt nicht zum Event-Contract
**Resolution: AC aligned to existing contract.** AC9 + §2.1.10 now require exactly the
code's mandatory fields `total_hits`, `hits_above_threshold`, `hits_classified_conflict`,
`threshold_value` (`events.py:186-191`); the vague "Query/Trefferanzahl/Konflikt-Verdikt"
wording is gone. No event-contract change.

### WARNING — AG3-057 nennt stale Produzent AG3-066
**Resolution: routed to owner story + noted as precondition.** The stale reference lives in
AG3-057 `story.md:49` (not in AG3-068) and the index sets AG3-068 as producer
(`_STORY_INDEX.md:152`). Per the "only this story's story.md" constraint, AG3-068 §2.2 and
§6 now name this as a known precondition/follow-up to be cleaned up in AG3-057 — not edited
here.

---

## Corrected code anchors (verified)
- `participating_repos` consumer: `src/agentkit/governance/setup_preflight_gate/context_builder.py:174` (issue path) / `:255` (story path) — the story previously wrote a bare `context_builder.py:174/255` without the real package path; now fully qualified.
- `ReviewerRole` enum + maps: `structured_evaluator.py:126-137` / `:143` / `:165` / `:172`; `evaluate(role: ReviewerRole, …)` `:299-301`.
- `VECTORDB_SEARCH` EventType `events.py:78`; mandatory payload `events.py:186-191`.
- Config models (no `vectordb`): `src/agentkit/config/models.py` (Grep confirmed absent).
- `vectordb/__init__.py` 0 bytes; `story_creation/` absent — re-confirmed.
- FK anchors confirmed: §21.4.1/§21.4.2/§21.4.3, §21.9.1-§21.9.5, §21.11.4, `StoryMdExportResult` dataclass `21_story_creation_pipeline.md:687`, FK-11 role table `11_…:486`.

## Files written
- `stories/AG3-068-vectordb-runtime-story-reconciliation/story.md` (rewritten)
- `stories/AG3-068-vectordb-runtime-story-reconciliation/remediation-r1.md` (this report)
- `status.yaml`: reviewed, unchanged (already correct).
