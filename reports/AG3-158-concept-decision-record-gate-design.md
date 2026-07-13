# AG3-158 — Concept-Decision-Record-Gate (W4): DESIGN FREEZE

Authoritative design contract for the Codex worker. Story:
`stories/AG3-158-concept-decision-record-gate/story.md`. Size S, ONE story — ships as one unit,
the review→fix loop is normal. This freeze FIXES the decisions the story delegates
("festzulegen in dieser Story"): diff-acquisition model, the fail-closed normativity heuristic,
the two satisfaction paths, the commit-trailer syntax, the convention's documentation home, and the
dogfood record. Grounded in the scout brief (all facts file:line-cited there); do not re-derive.

## 0. What this gate is
A NEW deterministic CI gate `scripts/ci/check_concept_decision_record.py` that enforces META
§5/W4: a change to a **normative** concept document must be accompanied by a Concept-Decision-Record
(under `concept/_meta/decisions/`) — either the record is in the same diff, or a machine-readable
commit trailer references an existing record. Blood types: normativity/scope rules + satisfaction
logic = **A** (pure, deterministic, AT-free); git diff/commit-message harvest = **T** (thin adapter);
finding serialization = **R**. LLM-free. K5 not applicable (repo/CI tool, no schema).

## 1. Testability-first architecture (MANDATORY shape)
Split so the A-core is unit-testable WITHOUT a real git repo:
- **Pure core** `evaluate_decision_record_compliance(diff: ConceptDiff, commit_messages: tuple[str, ...]) -> DecisionRecordResult`.
  `ConceptDiff` is an injected value object: for each changed file its repo-relative path, change kind
  (A/M/D/R), and the added+removed **body lines** (frontmatter and fenced code blocks separated out),
  plus the set of record files present in the post-diff tree under `concept/_meta/decisions/`.
- **Thin git adapter (T)** builds `ConceptDiff` + `commit_messages` from a `(base, head)` range.
  Isolated in its own function/module so the pure core never shells out.
- **CLI (R)** wires adapter→core→render, exit `0` pass / `1` on findings, `raise SystemExit(main())`.
Follow the AG3-157 gate STYLE (do NOT import its code — "Anschlussfähigkeit ohne technische Kopplung"):
frozen `@dataclass(order=True)` finding with `path,line,code,message,severity="ERROR"`; byte-stable
render `[SEVERITY] CODE path:line - message` + summary footer. Use the canonical shared frontmatter
parser `concept_compiler.loader.try_load_frontmatter` for record validation — do NOT re-implement.

## 2. Scope of "normative concept document" (the geltungsbereich)
A changed file is IN scope iff its path is under `concept/` AND NOT under `concept/_meta/decisions/`
(record maintenance is never itself a normative concept diff — AC5). Diffs with no `concept/`
in-scope portion never emit a finding (AC5). `concept/_meta/decisions/**` and non-`concept/` files
(code/tests/stories/reports) are ignored by the scope filter.

## 3. Normativity heuristic — deterministic + FAIL-CLOSED (AC1, AC3)
Classify every changed **body** line (added or removed; exclude YAML frontmatter block and fenced
code) of an in-scope file into exactly one class:
- **IGNORABLE**: whitespace-only delta, pure-punctuation delta, or a markdown anchor/link-only change
  (heading-anchor / `](#...)` / bare-URL edits with no other word changes). Precedent for anchors:
  `PROSE_ANCHOR_RE` usage in the reference-integrity lib.
- **NORMATIVE**: matches `NORMATIVE_MODAL_RE` (reuse the exact regex from
  `check_concept_frontmatter.py:49-54` — bilingual modal markers; lift it to a shared location or
  duplicate with a citation comment, your call, but keep ONE source of the pattern).
- **AMBIGUOUS**: any other substantive text change.

Decision per in-scope file: a record is REQUIRED if the file has ≥1 NORMATIVE **or** ≥1 AMBIGUOUS
changed line. It is EXEMPT only if ALL changed body lines are IGNORABLE. (Fail-closed: uncertain =
normative — AC3.)

**Documented exception marker (auditable, NON-bypassing):** a commit message in the range may carry
`Concept-Format-Only: <reason>` (reason non-empty). It downgrades AMBIGUOUS lines to exempt for the
range — BUT it NEVER downgrades a NORMATIVE (modal-hit) line. So a genuine normative edit can never be
waved through; only true typo/reword-without-normative-modal changes can be marked format-only. If a
file still has ≥1 NORMATIVE line, a record is required regardless of any Format-Only marker.

## 4. Two satisfaction paths (AC2) + dead-reference (AC2 tail)
A range that contains ≥1 record-requiring file is SATISFIED iff EITHER:
- **(a) in-diff record**: the same diff adds or modifies ≥1 file under `concept/_meta/decisions/`
  whose filename matches `^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$`; OR
- **(b) trailer reference**: a commit message in the range carries a trailer
  `Concept-Decision: <slug>` where `<slug>` (or `<slug>.md`) resolves to an EXISTING file
  `concept/_meta/decisions/<slug>.md` matching the filename schema.

Findings (all severity ERROR, exit 1):
- `MISSING_DECISION_RECORD` — record-requiring change, neither path satisfied.
- `DEAD_DECISION_RECORD_REFERENCE` — a `Concept-Decision:` trailer whose target file does not exist.
- `MALFORMED_DECISION_RECORD_NAME` — a referenced (or in-diff) record filename violates the schema.
- `EMPTY_FORMAT_ONLY_REASON` — a `Concept-Format-Only:` trailer with no reason (reject; fail-closed).
Anchor each finding to a real path:line (the first triggering changed line for MISSING; the record
path for the record findings). Multiple findings may coexist; render all, deterministically ordered.

## 5. Commit-trailer syntax (NEW convention this story defines)
- `Concept-Decision: YYYY-MM-DD-<slug>` — the record filename stem (case-sensitive, one per line;
  multiple allowed). Parsed as a git trailer (line at the message foot, `Key: value`); accept it
  anywhere in the message body to be lenient, but document the trailer form.
- `Concept-Format-Only: <reason>` — the exception marker of §3.
ARCH-55: trailer KEYS and finding CODES are English; the reason value is free prose.

## 6. Documentation home (AC6) — NO new top-level dir
- **Normative owner**: append the concrete trailer syntax + the two satisfaction paths + the
  Format-Only exception to `concept/_meta/konzept-konsistenz-governance.md` §5/W4 (:193-201) as the
  concretization of "Commit-Konvention". This is the SSOT of the rule.
- **Developer-facing**: add a short "Concept-Decision trailer" note + the W4 review-checklist point to
  `AGENTS.md` "Pflicht-Gates vor 'fertig'" (:31-63), where pre-commit/gate mechanics already live.
- Do NOT invent a guardrails file or top-level doc.

## 7. Dogfood — the introduction must satisfy its own gate (ZERO DEBT)
Editing `konzept-konsistenz-governance.md` §5/W4 is itself an in-scope normative concept change
(the governance doc carries authority; concretizing the convention is normative). Therefore the story
delivery MUST author a Concept-Decision-Record
`concept/_meta/decisions/<today>-concept-decision-record-gate.md` (frontmatter EXACTLY per the two
precedents: `doc_kind: decision-record`, `module: meta`, `cross_cutting: true`, `authority_over: []`,
`formal_scope: prose-only`, `concept_id: META-DEC-<DATE>-CONCEPT-DECISION-RECORD-GATE`; body sections
Anlass / Entscheidung / Alternativen / Impact-Sweep (P3) / Betroffenheitsmatrix table) documenting the
W4 gate + trailer decision, included in the same delivery so the gate passes green on its own
introduction (path (a)). Mind AG3-157 reference-integrity: any §-anchor/doc-id/path you add must
resolve, and add the new record's `concept_id` wherever the corpus indexes records if required — run
that gate too.

## 8. CI wiring (AC6) — deterministic base
Add a 6th Jenkins stage cloning the existing `sh` pattern (`. .venv/bin/activate` +
`PYTHONPATH=src python scripts/ci/check_concept_decision_record.py ...`), same `dir('agentkit-src')`
+ `when{}` guard (Jenkinsfile:251-303). CLI args: `--base <ref>` (default `origin/main`), `--head`
(default `HEAD`), `--repo-root`. In the Jenkins step pass
`--base "${GIT_PREVIOUS_SUCCESSFUL_COMMIT:-HEAD~1}"` so the evaluated range is the newly-integrated
push, with a first-build fallback. The gate evaluates only the range (no retroactive history sweep —
AC "grüne Einführung"). It must be deterministic: identical (base,head,tree) → identical output.
A pre-commit `--staged` mode (diff `--cached` + the prepared message file if available) is OPTIONAL;
only add it if it stays within scope and time — the CI stage is the required deliverable.

## 9. Tests (AC1-5) — fixtures without a live repo
Unit-test the pure core with SYNTHETIC `ConceptDiff` + `commit_messages` (no git needed) — the whole
point of §1. Cover: (1) normative-sentence change, no record, no trailer → `MISSING_DECISION_RECORD`
exit 1; (2a) in-diff `decisions/` entry → PASS; (2b) valid `Concept-Decision:` trailer to an existing
record → PASS; (2c) trailer to a nonexistent record → `DEAD_DECISION_RECORD_REFERENCE`; (2d) schema-
violating record name → `MALFORMED_DECISION_RECORD_NAME`; (3) pure typo/format (all IGNORABLE) → PASS
without record; (3b) AMBIGUOUS change, no marker → treated normative (finding); (3c) AMBIGUOUS +
valid `Concept-Format-Only:` → PASS; (3d) NORMATIVE line + `Concept-Format-Only:` → STILL finding
(non-bypass); (4) the two existing records validate as schema-conform (regression pin — assert the
real files pass name+frontmatter); (5) code/tests/stories-only diff and decisions/-only diff → no
finding. Add ONE integration test that builds a throwaway git repo in `tmp_path`, commits a normative
concept change without a record, and asserts the CLI exits 1 (proves the T-adapter + range wiring).
Follow the committed-fixture style only where a real corpus doc is needed (AC4); synthetic objects
elsewhere. Do NOT commit generated files under tests/fixtures/ (hand-authored only; CLAUDE.md:268).

## 10. Green-on-main + review plan
Worker owns green: `.venv\Scripts\python -m pytest --ignore=tests/e2e`, ruff, mypy strict native +
`--platform linux`, all SIX concept gates (the 5 existing + the new one on its own introduction),
coverage ≥85%. Then Codex read-only review + orchestrator code-adjudication → whole-story Fable
finale (focus: heuristic determinism, fail-closed non-bypass of the Format-Only marker, dead-ref
detection, dogfood record validity) → Jenkins + Sonar 0/0/0 on the final commit. Serialize: no
orchestrator git/gate ops while the worker is active on the shared tree.
