# AG3-101 — Remediation R3 (hostile Codex review-r3)

Doc-only/concept-alignment story. Third remediation round. The two remaining
must-fix ERRORs from `review-r3.md` are resolved by editing only `story.md` in
this folder. `status.yaml` reviewed: no genuinely-wrong field (see Note A).

review-r3 verdicts going in (OVERALL CHANGES-REQUESTED):
- Konzept: ERROR (finding 2)
- AC-Schaerfe: ERROR (finding 2)
- Klarheit: PASS (kept)
- Kontext: ERROR (finding 2 fallout)

review-r3 explicitly noted R2 substantially resolved: §37.1.0:137-138 +
§37.1.5:282-283 in scope; AC7 routing-fidelity (IMPLEMENTATION full vs
EXPLORATION reduced). Those are untouched and kept.

## Finding -> Resolution

### 1. story.md DoD "AK 1-6" stale after AC7 was added (ERROR)

review-r3 #1: `story.md` §4 DoD said "AK 1-6 erfuellt" but AC7 already exists
(§3) -> DoD must cover all ACs.

**Resolution:** §4 DoD changed to "AK 1-8 erfuellt". Note: review-r3 named
"AK 1-7" assuming 7 ACs; because finding 2 adds a new AC8 (see below), the
correct count is now 1-8. The DoD now covers every acceptance criterion,
which is exactly the intent of finding 1 (DoD must enumerate all ACs).

### 2. §37.1.0-§37.1.2 stale "Exploration NICHT via QA-Subflow / Implementation-only triggers" prose contradicts the new EXPLORATION_* routing (ERROR)

review-r3 #2: The story introduces `EXPLORATION_INITIAL`/`EXPLORATION_REMEDIATION`
routing but scoped the FK-37 invariant rewrite only for §37.1.4/§37.1.5. FK-37
§37.1.0-§37.1.2 still carries categorical "Exploration not via QA-Subflow /
Implementation-only triggers" prose that contradicts the new routing +
`bc-cut-decisions.md:78` + `routing.py:71`.

**Verified against the real concept file + code:**
- `37_verify_context_und_qa_bundle.md:140` — "...der QA-Subflow innerhalb der
  Implementation-Phase wird **nie direkt nach Exploration aufgerufen**
  (§37.1.1, FK-29 §29.1.1)" and "Trigger sind jetzt Subflow-interne Schritte
  innerhalb der Implementation-Phase, keine Top-Phase-Wechsel mehr". Confirmed.
- `37_..._md:153-154` — "Dokumententreue-Pruefung nach Exploration ist Teil
  der Exploration-Phase selbst (FK-23 §23.5), **nicht via QA-Subflow**".
  Confirmed.
- `37_..._md:173` — "`VerifyContext` ist jetzt ein StrEnum **mit genau zwei
  Werten**. `post_exploration` entfaellt — Dokumententreue nach Exploration
  laeuft in der Exploration-Phase selbst (FK-23 §23.5)". Confirmed; carries
  BOTH the two-value enum drift (already in §1.2 scope) AND the eligibility
  drift.
- `37_..._md:137-138` (§37.1.0 trigger table) and `:180-181` (§37.1.2
  depth table) list only Implementation-internal triggers and do not know the
  Exploration invocation contexts at all -> incomplete vs. the four-context
  routing.
- `concept/_meta/bc-cut-decisions.md:76-79` — "Output-QA wird interner Subflow
  innerhalb produktiver Phasen (**Exploration** und Implementation)".
  Confirmed: Exploration IS served by the QA-Subflow.
- `src/agentkit/verify_system/routing.py:12-14,74-75` — `EXPLORATION_INITIAL`/
  `EXPLORATION_REMEDIATION` are real `QaContext` routing keys mapping to the
  reduced layer set. Confirmed (file:line corrected from the review's
  shorthand `routing.py:71` to the precise `_ROUTING_TABLE` Exploration rows
  `:74-75`; the table block is `:71-76`).

**Resolution (story scope EXTENDED, not a code mandate — doc-only):**
- New §1.5 "§37.1.0-§37.1.2 tragen eine stale 'Exploration NICHT via
  QA-Subflow'-Prosa..." — grounds the eligibility drift against
  `bc-cut-decisions.md:76-79` and `routing.py:12-14,74-75`, lists the precise
  stale lines (`:140`, `:153-154`, `:173`) and the incomplete tables
  (`:137-138`, `:180-181`). Adds an explicit narrowing: the §37.1.1 `mode`
  argument (BB2-057) and the Implementation-internal trigger logic stay
  factually intact; only the categorical "never via Exploration" claim is
  reconciled. Allows EITHER precise restatement ("the *Implementation*-internal
  subflow is not triggered by a top-phase switch out of Exploration;
  Exploration has its own `EXPLORATION_*` invocation context") OR removal of
  the no-longer-true blanket statement — i.e. per-line justification of any
  statement that legitimately stays.
- §2.1.1 (Scope): added "Eligibility-Treue in §37.1.0-§37.1.2 beachten (§1.5)"
  — the rewrite must align the stale eligibility prose and make the trigger/
  depth tables cover all four `QaContext` contexts, without damaging the valid
  `mode` argument.
- New AC8 "Eligibility-Treue von §37.1.0-§37.1.2 (§1.5)": after the later FK
  edit, §37.1.0-§37.1.2 contains no categorical "Exploration never/not via
  QA-Subflow" claim; documents four invocation contexts (Implementation +
  Exploration reduced); tables cover all four contexts; `mode` argument and
  Implementation-internal trigger logic unchanged; no eligibility statement
  contradicting the `EXPLORATION_*` reality remains.
- "Quell-Konzepte" header (§37.1 line): extended to name the eligibility
  dimension (four invocation contexts incl. `EXPLORATION_*`) and ground it
  against `bc-cut-decisions.md:76-79` + §1.5.
- §6 Sub-Agent hint: added an eligibility-fidelity instruction mirroring §1.5
  (precise lines, do-not-damage `mode`/BB2-057).

This is strictly a concept/-prose deliverable description. No `src/` or
`tests/` change is mandated; `routing.py` remains explicitly no-touch (§6, §2.2)
and is documented as the authoritative code the FK must follow.

## Must-Fix List (review-r3)
1. **DoD "AK 1-6" -> covers all ACs** — DONE (§4 -> "AK 1-8"; AC count grew to 8
   via finding 2).
2. **§37.1.0-§37.1.2 eligibility prose reconciled to context-dependent
   routing** — DONE (§1.5, §2.1.1, AC8, Quell-Konzepte header, §6).

## Anchor corrections / new anchors (wrong -> real file:line)
- New grounded anchors: `37_...:140` (§37.1.0 "nie direkt nach Exploration"
  correction note), `37_...:153-154` (§37.1.1 "nicht via QA-Subflow"),
  `37_...:173` (§37.1.2 "genau zwei Werte / post_exploration entfaellt"),
  `37_...:180-181` (§37.1.2 depth table), `bc-cut-decisions.md:76-79`
  (Output-QA als Subflow in Exploration UND Implementation).
- Routing anchor precision: review-r3 referenced `routing.py:71`; the precise
  Exploration routing rows are `_ROUTING_TABLE` `:74-75` (table block `:71-76`),
  docstring `:12-14`. Used the precise lines in §1.5/AC8/§6.
- No previously-correct anchor was changed; all R1/R2 anchors remain valid
  (`qa_context.py:15-31`, `bc-cut-decisions.md:84-101`, `routing.py:8-14,56-76`,
  `37_...:137-138`, `37_...:266`, `37_...:282-283`).

## ARCH-55
All identifiers/enum values English (`QaContext`, the four UPPER_SNAKE values,
`QALayerKind`, `VerifyContext`/`VerifyContextBundle` distinction preserved). No
German keys introduced; concept prose tone unchanged.

## AG3-057 template structure preserved
Section structure intact (1 Kontext / 2 Scope / 3 AC / 4 DoD / 5 Guardrails /
6 Hinweise). §1.5 added as a sub-section of §1 (after §1.4); AC8 appended after
AC7 (existing AC numbers and cross-refs preserved); §4 DoD count corrected.

## Self-consistency
- The §37.1.1 `mode`/BB2-057 argument is explicitly preserved, not contradicted:
  §1.5/AC8/§6 narrow the finding to the categorical "never via Exploration"
  claim only.
- No code change mandated: `routing.py`/`bundle.py`/`qa_context.py`/`contract.py`
  remain no-touch; the routing reality is the authoritative source the FK
  follows.
- The DoD AK count (1-8) matches the AC list length (AC1-AC8).

## Note A — status.yaml
Reviewed, left unchanged. review-r3 flagged no status.yaml field. Title
("VerifyContext -> QaContext und ContextBundle/ReviewBundle") accurate;
`depends_on: [AG3-067]` and `unblocks: []` correct. No genuinely-wrong field,
so per the doc-only constraint status.yaml was not edited.

## Files written (this story only)
- `stories/AG3-101-concept-nachzug-qacontext-reviewbundle/story.md` (edited)
- `stories/AG3-101-concept-nachzug-qacontext-reviewbundle/remediation-r3.md` (this file)
- `status.yaml`: not modified (Note A).
