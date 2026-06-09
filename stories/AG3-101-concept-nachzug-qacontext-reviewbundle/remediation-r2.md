# AG3-101 — Remediation R2 (hostile Codex review-r2)

Doc-only/concept-alignment story. Second remediation round. The two remaining
must-fix ERRORs from `review-r2.md` are resolved by aligning the (later) FK
prose to the real code (`routing.py`, `qa_context.py`) without mandating code
changes. Only `story.md` in this folder was rewritten. `status.yaml` reviewed:
no genuinely-wrong field (see Note A).

review-r2 verdicts going in:
- Konzept-Vollstaendigkeit: ERROR (finding 1)
- AC-Schaerfe: ERROR (finding 2)
- Klarheit: PASS (kept)
- Kontext-Sinnhaftigkeit: ERROR (finding 2 fallout)

## Finding -> Resolution

### 1. Konzept-Vollstaendigkeit (ERROR) — §37.1 value-only stale occurrences still missing

review-r2 #1: AG3-101 listed §37.1 stale anchors through §37.1.4 but missed
value-only stale occurrences inside the same §37.1 scope:
- `37_...:137`/`:138` — lowercase `post_implementation`/`post_remediation`
  (§37.1.0 trigger table cells)
- `37_...:282`/`:283` — uppercase `POST_IMPLEMENTATION`/`POST_REMEDIATION`
  (§37.1.5 invariant)

**Verified against real concept file:**
- `37_verify_context_und_qa_bundle.md:137-138` — the trigger table maps to
  lowercase `post_implementation` / `post_remediation`. Confirmed.
- `37_verify_context_und_qa_bundle.md:282-283` — "ob `POST_IMPLEMENTATION`
  oder `POST_REMEDIATION` — laeuft die volle 4-Schichten-Pipeline".
  Confirmed; this is §37.1.5, which the story did not previously scope.

**Resolution:**
- §1.2: added the §37.1.0 table cells `:137-138` (value-only lowercase) and a
  new bullet for §37.1.5 `:282-283`, flagging that §37.1.5 carries TWO drifts
  (two-value set + a routing claim — see finding 2).
- Top "Quell-Konzepte" header: §37.1.5 added to the §37.1 sub-section list.
- §2.1.1 (Scope): §37.1.0 table `:137-138` and §37.1.5 `:282-283` added to the
  explicit rewrite list.
- AC1: now names §37.1.0 (incl. `:137-138`) and §37.1.5 (`:282-283`), and
  explicitly requires the lowercase table values be replaced; "kein
  verbleibender ... Zwei-Werte-Treffer".
- §6 Sub-Agent hint expanded: §37.1.5 + §37.1.0 table cells flagged as stale.

### 2. AC-Schaerfe / Kontext-Sinnhaftigkeit (ERROR) — §37.1.5 must not be blindly generalized to "all four = full 4-layer QA"

review-r2 #2: Real code routes `IMPLEMENTATION_*` to the full implementation
layer set, but `EXPLORATION_*` to reduced LLM+Policy only:
`routing.py:8`, `:12`, `:71`. AG3-101 must require FK prose aligned to that
routing, not just enum renaming.

**Verified against real code:**
- `routing.py:8-14` (module docstring): `IMPLEMENTATION_INITIAL` /
  `IMPLEMENTATION_REMEDIATION` -> all four layers; `EXPLORATION_INITIAL` /
  `EXPLORATION_REMEDIATION` -> "Reduced layer set: LLM-Evaluator (2) + Policy
  (4). Design-review only; no structural or adversarial checks".
- `routing.py:56-76`: `_IMPLEMENTATION_LAYERS` = (STRUCTURAL, LLM_EVALUATOR,
  ADVERSARIAL, SONARQUBE_GATE, POLICY); `_EXPLORATION_LAYERS` =
  (LLM_EVALUATOR, POLICY); `_ROUTING_TABLE` binds each context accordingly.

**Resolution:**
- New §1.4 "QA-Tiefe ist kontextabhaengig — kein blindes 'vier Werte = volle
  4-Schichten-QA'": states explicitly that the enum widening from 2 to 4 must
  NOT mechanically generalize the §37.1.4/§37.1.5 invariant to "all four
  values trigger full 4-layer QA", because that contradicts `routing.py`.
  Grounds the IMPLEMENTATION (full) vs EXPLORATION (reduced LLM+Policy) split
  against `routing.py:8-14,56-76`. Keeps the IMPLEMENTATION "always full
  4-layer" statement factually intact; adds the EXPLORATION reduced path as
  new+correct. Includes a layer-count note (SONARQUBE_GATE is a sequenced
  Layer-1 stage, FK-33 §33.8.3) declared out of scope — referenced, not rewritten.
- §2.1.1 (Scope): added "Routing-Treue beachten (§1.4)" — invariant rewrite
  must mirror the context-dependent routing, not blindly generalize.
- New AC7 "Routing-Treue der Invariante": §37.1.4 (`:266`) and §37.1.5
  (`:280-289`) must NOT claim all four values trigger full QA; must mirror
  `routing.py:8-14,56-76` (IMPLEMENTATION full / EXPLORATION reduced); no
  depth statement contradicting code may remain.
- §6 Sub-Agent hint: added routing-fidelity instruction.

## Must-Fix List (review-r2)
1. **§37.1 value-only stale occurrences (`:137-138`, `:282-283`) in
   scope/AC** — DONE (§1.2, Quell-Konzepte, §2.1.1, AC1, §6).
2. **§37.1.5 routing-faithful rewrite, not blind 2->4 generalization** —
   DONE (§1.4, §2.1.1, AC7, §6).

review-r2 explicitly accepted as-is (left unchanged): ReviewBundle
re-grounding after AG3-067, `VerifyContextBundle` separation (Klarheit PASS),
status dependency on AG3-067.

## Anchor corrections / new anchors (wrong -> real file:line)
- New grounded anchors: `37_...:137-138` (lowercase value cells, §37.1.0
  table), `37_...:282-283` (§37.1.5 two-value sentence), `routing.py:8-14`
  (routing rules docstring), `routing.py:56-76` (`_IMPLEMENTATION_LAYERS` /
  `_EXPLORATION_LAYERS` / `_ROUTING_TABLE`), `routing.py:37-49`
  (`SONARQUBE_GATE` doc, layer-count note).
- §37.1.5 section body referenced as `:280-289` (section header at 270, 4-layer
  list 285-288, two-value sentence 282-283). Consistent with the §1.2 anchor.
- No previously-correct anchor was changed; all R1 anchors remain valid
  (`qa_context.py:15-31`, `bc-cut-decisions.md:84-101` confirmed: §QA-Subflow-
  Vertrag header at 84, QaContext values at 100-101, contract block 86-99).

## ARCH-55
All identifiers/enum values English (`QaContext`, the four UPPER_SNAKE values,
`QALayerKind`, `VerifyContextBundle`, `ReviewBundle`, `STRUCTURAL`/
`LLM_EVALUATOR`/`ADVERSARIAL`/`SONARQUBE_GATE`/`POLICY`). No German keys
introduced. Concept prose tone unchanged. AG3-057 section structure preserved
(1 Kontext / 2 Scope / 3 AC / 4 DoD / 5 Guardrails / 6 Hinweise); §1.4 added as
a sub-section of §1, AC7 appended (existing AC numbers/cross-refs preserved).

## Self-consistency
- Story does not over-claim AG3-067 scope (unchanged from R1).
- No code change mandated by AG3-101: `routing.py` declared no-touch (§6); the
  routing reality is documented as the authoritative code the FK must follow,
  not as a code-need.
- §37.1.5 EXPLORATION path is grounded in the real `_ROUTING_TABLE`, so the FK
  alignment asserts only what the code actually routes.

## Note A — status.yaml
Reviewed, left unchanged. `depends_on: [AG3-067]` correct (R1 finding-2
resolution, untouched by review-r2). `unblocks: []` correct. Title refers to
the enum rename, accurate. No genuinely-wrong field, so per the doc-only
constraint status.yaml was not edited.

## Files written (this story only)
- `stories/AG3-101-concept-nachzug-qacontext-reviewbundle/story.md` (edited)
- `stories/AG3-101-concept-nachzug-qacontext-reviewbundle/remediation-r2.md` (this file)
- `status.yaml`: not modified (Note A).
