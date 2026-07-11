# AG3-157 — Concept-reference-integrity gate (W1): frozen design

**Status:** FROZEN implementation contract. Feasibility verified at main@c7ca0cdb (scout +
orchestrator code-adjudication: `CompiledFormalSpec.declared_ids` SSOT exists at
`tools/concept_compiler/compiler.py:50`; the self-referential negative examples "FK-71 §67.x"/
"FK-02 §67.x" exist in `concept/_meta/konzept-konsistenz-governance.md:120/:225`; the new gate
script + module do not exist yet — purely additive). Concept mandate: the P5 anchor-class of
errors (dead cross-refs) must die deterministically. Additive TOOLING only — NO src/ backend,
schema, or state-backend changes. Covers the AG3-157 SOLL/W1 (concept-reference resolvability +
scope-qualified defers_to acyclicity), unblocks AG3-158.

## 0. Adjudicated coordinates (HEAD)
- Gate pattern: `scripts/ci/*.py` are thin argparse-default CLIs (`sys.path`-inject src/+tools/,
  `return 0/1`, `raise SystemExit(main())`); logic in `tools/concept_compiler/`. New:
  `scripts/ci/check_concept_reference_integrity.py` + `tools/concept_compiler/reference_integrity.py`.
- Reuse (no second compile-truth, AC6): `compile_formal_specs()` → `CompiledFormalSpec.declared_ids:
  frozenset[str]` (compiler.py:59/65) for the formal.* class; `loader.try_load_frontmatter()` +
  `discover_formal_spec_files()`; `drift.PROSE_ANCHOR_RE`. Do NOT re-parse the formal specs.
- CI wiring: Jenkinsfile stages `:247-288` (Concept Frontmatter Lint / Formal Spec Compile /
  Concept Contract Checks), form `. .venv/bin/activate; PYTHONPATH=src python scripts/ci/<gate>.py`,
  gated on `params.agentkit_mode != 'cp10d_branch_plugin_self_test'`. Add a sibling stage.
- Tests: `tests/unit/tools/concept_compiler/` (add `test_reference_integrity.py`); fixtures under
  `tests/fixtures/concept_compiler/<scenario>/` — HAND-AUTHORED (CLAUDE.md forbids generated files
  in tests/fixtures).
- Existing partial coverage (do NOT modify these gates): frontmatter L7 checks FK/DK EXISTENCE only,
  non-recursive over technical-design/+domain-design/; drift validates doc-level PROSE-FORMAL anchors
  only; L9 acyclicity is over parent_concept_id and EXPLICITLY excludes defers_to
  (`check_concept_frontmatter.py:369-372`). So §-anchors, item-level formal.* IDs in free prose,
  file paths, _meta/** refs, and defers_to cycles are ALL currently unchecked — this gate adds them.

## 1. Settled design decisions

### Reference classes (over the WHOLE concept/ corpus, recursive — incl. _meta/**, decisions/, formal-spec prose)
1. **Doc-IDs** `FK-\d+` / `DK-\d+` / `META-[A-Z0-9-]+` (incl. `META-DEC-*`): must resolve to an
   existing concept `concept_id` (or the doc-number → doc mapping). Unresolvable → ERROR.
2. **§-anchors** `FK-NN §NN.x[.y]`: the target doc must contain a heading whose leading number
   matches (`## NN.x …` / `### NN.x.y …`). A `§`-anchor with no matching heading → ERROR
   (AC2: `FK-71 §67.3` dies; `FK-71 §71.3` resolves). Numbering convention: heading leading number
   == doc number.
3. **formal.* item IDs** in prose (`formal.<context>.<object>` incl. `.invariant.<id>` forms): must
   be in `CompiledFormalSpec.declared_ids` (REUSE — AC6). Unknown → ERROR.
4. **File paths** (backticked repo-relative paths): must exist in the repo. Missing → ERROR.

### Exclusion model (DETERMINISTIC — the top risk; "nie heuristisch geraten")
- **Fenced code blocks** (```` ``` ````…```` ``` ````) and indented code are stripped before ref scanning
  (refs inside code are not cross-refs). File-path class scans backticked tokens in prose only.
- **Deliberate negative examples** (e.g. the governance doc's own illustrative dead anchors
  "FK-71 §67.x"/"FK-02 §67.x"): an EXPLICIT inline marker — a documented HTML-comment directive
  (e.g. `<!-- REF-INTEGRITY:IGNORE-LINE reason -->` on the preceding line, or a
  `<!-- REF-INTEGRITY:IGNORE-BEGIN --> … <!-- REF-INTEGRITY:IGNORE-END -->` region). The gate skips
  refs on marked lines/regions ONLY. NO heuristic "this looks like an example" — the governance doc
  gets the marker added (that IS a legitimate anchor-only edit, Record-exempt). If a needed marker
  would require a normative change → STOP and report.
- **Baseline** `concept/_meta/reference-integrity-baseline.<ext>` (English keys, ARCH-55): an
  explicit, justified allowlist for pre-existing acknowledged unresolvables (prefer FIXING dead
  anchors over baselining; baseline only where a fix would be normative or a doc-level cycle is
  sanctioned). Fail-closed: any NEW unresolvable ref NOT in the baseline → ERROR.

### defers_to acyclicity (new semantic — W1 writes it)
- Build the defers_to edge graph from document frontmatter (`{target, scope, reason}` entries).
- **Per-scope cycle** (A→B→…→A all within one scope, incl. transitive) → ERROR.
- **Document-level cycle** (ignoring scope) → report-only + a JUSTIFIED baseline entry; fail-closed
  on an UNJUSTIFIED doc-level cycle (a doc-level cycle not in the baseline → ERROR). Seed the baseline
  with the existing justified pairs the scout named (FK-63↔FK-70, FK-02↔FK-71, transitive
  FK-20/27/29/54) after verifying each is genuinely scope-disjoint.

### Determinism (AC8)
Byte-identical output across runs; stable sort of findings (by file, line, class). No wall-clock,
no set-iteration-order leakage.

## 2. Implementation plan (single increment; sequence de-risks the exclusion model first)
1. Extractor + EXCLUSION MODEL first (code-fence stripping, the explicit negative-example marker,
   backtick-path detection) + the self-referential test: the gate MUST NOT fire on the governance
   doc's own "FK-71 §67.x"/"FK-02 §67.x" once marked. This de-risks the top risk up front.
2. Doc-ID + META-ID + file-path resolution (recursive corpus walk via try_load_frontmatter).
3. §-anchor→heading resolution (harvest headings per doc; match `§NN.x` to leading-number heading);
   pin AC2.
4. formal.* class consuming `declared_ids` (no new parse — AC6).
5. Per-scope defers_to graph + cycle check (ERROR) + doc-level report + justified baseline (AC4/AC5).
6. Run on real main → TRIAGE: fix dead anchors inline (anchor-only, Record-exempt); mark deliberate
   negative examples; baseline justified doc-level cycles. If the cleanup surfaces a NORMATIVE issue
   (not a mere dead anchor) or is unexpectedly large → STOP and report (do NOT make normative changes
   to force the gate green). Wire the Jenkins stage; add the determinism test (byte-identical) + the
   hand-authored positive/negative fixtures (dead doc-ref, dead §-anchor, unknown formal.*, dead path,
   per-scope-cycle=ERROR, doc-level-cycle=report).

### NOT in scope
- The AG3-155 code-token gap (`takeover_reconcile_clear`/`split_admin_freeze`/`reconcile_repair`
  code-only) — a DIFFERENT reference axis (code-token↔concept), owned elsewhere; tracked as tech-debt
  #26. Do NOT scope-creep it into 157.
- Any normative concept change; any modification to the existing 4 gates' logic.

## 3. Guardrails / ACs
Deterministic + documented exclusion rules (no heuristic guessing); fail-closed (new unresolvable →
ERROR; unjustified cycle → ERROR); reuse the formal-spec compile SSOT (no second compile-truth);
gate PASSES on real main (AC7) via anchor-only fixes + justified baseline; byte-identical determinism
(AC8); ARCH-55 English keys/ids; the 4 EXISTING concept gates stay green; new fixtures hand-authored
(not generated). Green-on-main loop: ruff / mypy src / mypy src --platform linux / pytest (incl. the
new gate unit tests) / the 4 existing concept gates + the NEW gate → push main → Jenkins
buildWithParameters (CSRF crumb + admin:password) SUCCESS + Sonar OK (0/0/0, new-code cov≥80). Sonar
http://localhost:9901 admin/meinSonarCube2026! key claude-agentkit3. Do NOT set status.yaml=completed.
