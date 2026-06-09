CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: FAIL
- AC-Schaerfe: WEAK
- Klarheit: PASS for round-1 corrections
- Kontext-Sinnhaftigkeit: FAIL

**Round-1 ERROR Resolution**
All six explicit round-1 ERRORs are textually resolved in `story.md`:
- `AreClient` HTTP body is now in scope.
- `CoverageVerdict` gets `reason` and `uncovered_requirements`.
- `are_gate.json` is correctly described as audit/output, not Layer-1 input.
- `AreBundleSignal`/`AreBundleStatus` are typed into `SetupPayload`.
- `ScopeMapping` is specified.
- partial evidence trigger is explicit via `EvidenceCoverage.PARTIAL`.

**Remaining Must-Fix ERROR**
ERROR: AG3-077 still does not make the real ARE path buildable because the runtime `AreClient` wiring is missing from scope/ACs. The existing implementation QA path loads `ProjectConfig`, but `_resolve_structural_evidence_ports` passes `None` into `build_structural_are_provider` unconditionally (`src/agentkit/implementation/phase.py:576-582`). The config model already has `ProjectConfig.are` and `AreConfig.rest_base_url/auth_token` (`src/agentkit/config/models.py:45-60`, `:443`), but the story only says to implement `AreClient` HTTP bodies and keep the provider path unchanged. Without an AC to instantiate and inject `AreClient(project_config.are.rest_base_url, auth_token)` for Setup and Layer-1/Implementation, `features.are: true` still produces an unavailable gate in the real path.

Fix: add AG3-077 scope/AC for productive `AreClient` construction and injection from `ProjectConfig.are` into both `load_are_bundle`/Setup and `_resolve_structural_evidence_ports`/`build_structural_are_provider`, including fail-closed behavior when `features.are=true` but `rest_base_url` is absent.
