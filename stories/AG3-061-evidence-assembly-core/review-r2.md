OVERALL CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: FAIL
- AC-Schaerfe: FAIL
- Klarheit: PASS
- Kontext-Sinnhaftigkeit: FAIL

**R1-Checks**
3-stage model incl. Worker-Hints: resolved. Diff owner via `ChangeEvidencePort`: resolved. Determinism vs. `evidence_epoch`: resolved. `BundleEntry.repo_id`: resolved. `status.yaml.unblocks`: resolved.

**Remaining Must-Fix ERRORs**
ERROR: `{{BUNDLE_MANIFEST_HEADER}}` / `render_prompt_header` routing is still not buildable against the real prompt-runtime cut. AG3-061 scopes placeholder insertion into five `prompts/sparring/review-*.md` templates and routes runtime hydration to AG3-062 (`stories/AG3-061-evidence-assembly-core/story.md:54`, `:58`). Real prompt resources are registered as internal `qa-*` templates, not those five `review-*` files (`src/agentkit/resources/internal/prompts/manifest.json:29`, `:33`, `:37`, `:41`), and AG3-062 only owns `review-preflight.md` plus its manifest entry (`stories/AG3-062-import-resolver-request-dsl-preflight/story.md:74`, `:95`), not `BUNDLE_MANIFEST_HEADER` substitution. Fix: map FK-28 review templates to the real prompt IDs/manifest and add explicit hydration ownership, or route that exact work into AG3-062 with ACs.
