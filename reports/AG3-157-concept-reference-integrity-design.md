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

---

## R1→R2 correction (2026-07-12): defers_to has TWO canonical forms

The R1 defect review found 5 real ERRORs (2 normative-doc corruptions disguised as ref fixes,
3 fail-open gate holes). The R1 worker correctly STOPPED because the ERROR-4 fix as first
specified ("every defers_to edge needs target+scope+reason else ERROR") CONFLICTS with the
canonical contract: `00_index.md:250` defines `defers_to: [FK-NN, ...]` — a SCALAR list of
doc-IDs — and 47 legitimate entries in 14 docs use it. Forcing target/scope/reason onto them
would be a normative mass-migration. This was an orchestrator over-specification.

CORRECTED defers_to model (the gate accepts BOTH forms; fail-closed only where an edge is truly
unformable):
- **Scalar** `- FK-NN` (canonical, 00_index:250) = a DOCUMENT-LEVEL (scope-less) deferral →
  feeds DOCUMENT-LEVEL cycle detection (report + justified baseline; NOT a per-scope ERROR).
- **Mapping** `{target, scope, reason}` = scope-qualified → feeds PER-SCOPE cycle detection (ERROR).
- Fail-closed rule (closes the real ERROR-4 hole = "silent drop hides a cycle"): a mapping with a
  determinable (target, scope) MUST be included in the per-scope graph — a MISSING/non-string
  `reason` does NOT drop it (reason is documentation, not edge identity) → so it can never hide a
  cycle. A mapping MISSING/non-string `target` OR `scope` (cannot form the edge) → ERROR. A value
  that is neither a valid scalar string nor a valid mapping → ERROR. Scalar strings are always valid.
- This closes the cycle-hiding hole WITHOUT flagging the 47 canonical scalar entries.

Path triage (after the ERROR-3 fix recognizes all repo-tracked-root paths): newly-surfaced findings
(tools/agentkit, tools/hooks/*, prompts/…, etc.) are deployed target-project / bundle / example /
generated / runtime paths → BASELINE with justification (same category as the existing baseline).
Genuine AK3-repo dead path → fix inline. NORMATIVE issue → STOP.

---

## AG3-157 — CLOSED (2026-07-12)

CLOSED at code SHA `ce2eaca9` (gate lives at scripts/ci/check_concept_reference_integrity.py +
tools/concept_compiler/reference_integrity.py). Jenkins #1862 SUCCESS, Sonar 0/0/0, 9382 tests,
all 5 concept gates green (I ran the new gate on main → 0 errors). Additive-only; no concept
content falsified.

Journey (each round a distinct, real, narrower finding — convergent, not a loop):
- Gate built (14d9bec5): on its FIRST run it caught a REAL pre-existing concept defect — a
  same-scope defers_to cycle closure-payload (FK-29↔FK-39). Orchestrator resolved it factually
  (FK-29 §29.1.0 owns ClosurePayload; FK-39 owns the generic phase-payload union) → re-scoped the
  wrong edge + decision-record (commit cd0697cc). Immediate story value.
- Defect review found 5 ERRORs: 2 normative-doc corruptions disguised as ref fixes (syntax-contract
  §8 README, 11-review basename example) + 3 fail-open gate holes (unrecognized-path bypass,
  malformed defers_to silently dropped, dangling IGNORE at EOF).
- R1 correctly STOPPED: the orchestrator's ERROR-4 spec conflicted with the canonical SCALAR
  defers_to form (`[FK-NN,...]`, 47 legit entries). Orchestrator over-spec → corrected to a
  two-forms model.
- R2 (a2e81936) fixed all 5 with the corrected two-forms handling (scalar=document-level;
  mapping=scope; reason-less mapping kept in graph so it can't hide a cycle; missing target/scope=
  INVALID); path recognition from git ls-files; dangling-IGNORE=ERROR; ERROR 1/2 fixed WITHOUT
  falsifying content (README pattern marked, basename example made self-consistent); 29 prompts/
  target-project paths baselined with justification.
- Convergence re-review found 2 residual fail-open holes → R3 (ce2eaca9): case-variant tracked
  root now recognized case-insensitively (final git-path check stays exact) so a case-variant dead
  path is reported; `defers_to: null` (present-non-list) → INVALID_DEFERS_TO_EDGE (absent key stays
  empty default).

Lesson (recorded): for a FAIL-CLOSED integrity gate, "green" is nearly meaningless — fail-OPEN
holes are green-and-broken and only adversarial layered review finds them. The orchestrator's
"green + low-risk → close" instinct was wrong twice here; the layered reviews (2 Codex adversarial
passes + a convergence pass) + code-adjudication are what made the gate genuinely fail-closed.
This meta-gate justified more rounds than a normal story precisely because of that. Non-blocking:
none. Follow-on: AG3-158 (sequence edge).
