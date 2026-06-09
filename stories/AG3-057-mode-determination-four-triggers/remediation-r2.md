# AG3-057 — Remediation r2 (review-r2.md, second round)

Scope of this remediation: `story.md` only. No production code, tests, concept
files, or other stories' files touched. `status.yaml` left unchanged (no field is
genuinely wrong; `phase: review_pending`, `depends_on` incl. AG3-054 stay correct).
Every code anchor below was re-verified against the real tree at remediation time.

## Remaining Must-Fix ERRORs (from review-r2.md)

### ERROR 1 — Trigger 2 was bound to false real-code evidence
**Finding:** AG3-057 (r1) claimed `ChangeImpact` has **no** `"Architecture Impact"`
value and (wrongly) bound Trigger 2 to `ChangeImpact.CROSS_COMPONENT`, framing the
FK-22 literal as "string drift" to be reported doc-only.
**Real code:** `ChangeImpact.ARCHITECTURE_IMPACT = "Architecture Impact"` exists at
`src/agentkit/story_context_manager/story_model.py:106` (enum `:97-106`).
**Concepts:** FK-22 §22.8.1 reference code is `context.change_impact == "Architecture Impact"`;
FK-25 §25.7.1 / DK-02 §Issue-Schema list `Architecture Impact` as the canonical
impact level 4. There is no drift — the typed enum and the FK literal agree exactly.
**Resolution (in-story):**
- `story.md` Ist-Zustand field-owner bullet (~:27): removed the false "kein Wert
  Architecture Impact" / drift claim; now states `ChangeImpact.ARCHITECTURE_IMPACT =
  "Architecture Impact"` (`story_model.py:106`) exists and matches FK-22/FK-25/DK-02.
- Trigger 2 spec (~:55): bound to `change_impact == ChangeImpact.ARCHITECTURE_IMPACT`
  (typed enum, no string compare).
- Sub-agent hint (~:107): rewritten — both FK literals (`"Architecture Impact"`,
  `"Low"`) exist in the real enums (`story_model.py:106` / `:114`); bind Trigger 2 to
  `ChangeImpact.ARCHITECTURE_IMPACT`, Trigger 4 to `ConceptQuality.LOW`; the spurious
  "doc-only drift nachzug" for Trigger 2 was deleted.
- Result: the story is now buildable against current code/concepts; no concept change
  away from FK-22/FK-03/FK-25 is asserted.

### ERROR 2 — VektorDB flag producer/consumer contract name inconsistent
**Finding:** AG3-057 consumed `vectordb_conflict` while AG3-068 produces/persists
`vectordb_conflict_resolved` (AG3-068 §2.1.5, FK-21 §21.12) — an unnamed mapping.
**Decision:** Producer ownership stays in AG3-068 (confirmed `_STORY_INDEX.md:152`:
"Der `vectordb_conflict`-Konsument bleibt bei AG3-057, der Produzent ist AG3-068").
The single authoritative, persisted field name is the producer's
`vectordb_conflict_resolved`. AG3-057 now consumes under that **exact same name** —
one contract truth across producer and consumer, no second field name, no shadow
field, no rename. The FK-22 §22.8.1 pseudocode short-name `context.vectordb_conflict`
is the same boolean ("conflict detected AND resolved -> force exploration",
FK-21 §21.12); the real persisted field is `vectordb_conflict_resolved`, and the
FK-22 short-form is flagged as a doc-only follow-up to the FK-22-owning unit — not
fixed in the AG3-057 code cut.
**Resolution (in-story):** renamed every AG3-057 reference of the consumed flag to
`vectordb_conflict_resolved` and made the producer↔consumer contract + FK-22 mapping
explicit, at:
- StoryContext-missing-fields bullet (~:24)
- In-Scope 1 field definition (~:45) — now carries the producer-name contract +
  FK-22 mapping note
- determine_mode VektorDB precedence step (~:53)
- In-Scope 6 SSOT bullet (~:67/:69)
- Out-of-Scope producer owner (~:74) — incl. the index short-name vs. authoritative
  field-name note
- AC8 (~:92)
- Guardrail FIX-THE-MODEL bullet (~:100)
- new sub-agent hint (~:110) on the flag name + doc-only routing of the FK-22 short form

## WARNINGs
review-r2.md lists no separate open WARNING beyond the per-dimension verdicts; the R1
WARNING (`project_root: Path | None = None`) was already marked resolved in review-r2
"Resolved From R1" and is unchanged.

## Verified code/concept anchors (re-checked against real tree)
- `story_model.py:106` `ChangeImpact.ARCHITECTURE_IMPACT = "Architecture Impact"` (real).
- `story_model.py:97-106` `ChangeImpact` enum; `:109-114` `ConceptQuality` (`LOW = "Low"` :114).
- FK-22 §22.8.1 Trigger 2 = `change_impact == "Architecture Impact"`; FK-25 §25.7.1 /
  DK-02 = canonical impact level 4 `Architecture Impact` (confirmed via concept search).
- AG3-068 §2.1.5 + FK-21 §21.12: producer/persistence of `vectordb_conflict_resolved`.
- `_STORY_INDEX.md:152` dedup note (consumer AG3-057 / producer AG3-068).

## Cut fidelity
All changes stay strictly within the AG3-057 cut. Producer ownership of
`vectordb_conflict_resolved` remains with AG3-068 (only the consumer-side field name was
aligned to the producer). No claim that another story delivers something outside its
scope. The only items routed out are genuine doc-only FK-prose follow-ups (FK-22 §22.8.1
pseudocode short-name) routed to the FK-22-owning unit, never to a code story.

## Files written
- `stories/AG3-057-mode-determination-four-triggers/story.md` (edited)
- `stories/AG3-057-mode-determination-four-triggers/remediation-r2.md` (this file)
Only AG3-057 files written.
