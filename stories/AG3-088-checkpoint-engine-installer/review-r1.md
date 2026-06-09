OVERALL: CHANGES-REQUESTED

Story type is `implementation` (`status.yaml:3`), not concept-only; frontend prototype check does not apply.

**1) Konzept-Vollstaendigkeit — FAIL**

- **ERROR**: CP10c is omitted. FK-50 defines `CP 10c: ARE-Scope-Validierung` with requirements for `are_scope`, `are.module_scope_map`, interactive/agentic resolution, and `resolve_pending_scope_mapping()` (`concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:421-433`). Story scope lists only “CP10/10a/10b” (`story.md:35`) and tests do not mention CP10c (`story.md:40`, `story.md:51`).  
  **Fix**: Add CP10c as in-scope checkpoint, branch it under `branch_are_enabled`, define result/status behavior including `PENDING_SELECTION` mapping, and add AC/tests for missing mappings, resolved mappings, and idempotent skip.

- **ERROR**: Reserved CP3/CP4 are not specified as flow nodes, although FK-50 keeps them for numbering stability (`concept/...50...md:136-139`, `174-178`, `224-236`). Story says “jeder Checkpoint ein `step`-Knoten” (`story.md:29`, `49`) and “alle 12 CP real als Knoten” (`story.md:68`), but never names `cp_03_reserved` / `cp_04_reserved`.  
  **Fix**: Require explicit `cp_03_reserved` and `cp_04_reserved` no-op step nodes with deterministic `CheckpointResult` semantics.

- **ERROR**: CP8 is incomplete. FK-50 CP8 includes both `Skills.bind_skill(...)` and `PromptRuntime.update_binding(...)` (`concept/...50...md:304-318`, `595-619`). Story reduces CP8 to skill links (`story.md:17`, `23`, `73`).  
  **Fix**: Add preservation/transfer of prompt bundle binding via `PromptRuntime.update_binding` to scope and tests.

**2) AC-Schaerfe — FAIL**

- **ERROR**: AC7 uses non-existent status vocabulary: “SKIPPED/UPGRADED” (`story.md:55`). FK-50 status set is `PASS, CREATED, UPDATED, SKIPPED, FAILED` (`concept/...50...md:579-585`); code has `CheckpointStatus.UPDATED`, not `UPGRADED` (`src/agentkit/installer/registration.py:43-50`, `runner.py:1343-1344`).  
  **Fix**: Replace `UPGRADED` with `UPDATED` everywhere in story/AC.

- **ERROR**: AC1 says “Grep `install_agentkit`-God-Funktion ist durch Flow + Step-Handler ersetzt” (`story.md:49`). This is not test-sharp: a public `install_agentkit` facade may legitimately remain while no longer being a God-function.  
  **Fix**: Specify measurable structure: `install_agentkit` is either removed or is a thin facade delegating to `CheckpointEngine.run(...)`; assert max responsibility and flow execution via tests, not grep wording.

- **ERROR**: Dry-run expected result semantics are underspecified. Story says dry-run “liefert aber den geplanten CheckpointResult-Satz” (`story.md:54`), but does not define whether would-create/would-update statuses are reported as `CREATED/UPDATED`, `SKIPPED`, or annotated by `reason`.  
  **Fix**: Define dry-run result contract per CP: status values, `reason` codes, and whether details must mark planned/no-mutation.

**3) Klarheit/Eindeutigkeit — FAIL**

- **ERROR**: Direct contradiction around `.mcp.json`. Scope requires CP10 MCP registration (`story.md:35`), and FK-50 says CP10 registers in `.mcp.json` (`concept/...50...md:365-383`). But the sub-agent note says “`.mcp.json` NICHT anfassen” (`story.md:76`).  
  **Fix**: Clarify that production CP10 may mutate target-project `.mcp.json` in register mode, while dry-run/verify must not; or move CP10 out of scope with owner. With FK-50 §50.3 in scope, the first fix is the coherent one.

- **ERROR**: “alle 12 CP real als Knoten” (`story.md:68`) is ambiguous against FK-50’s actual minimal flow, which includes reserved CP3/CP4 and CP10a/10b/10c/10d sub-checkpoints (`concept/...50...md:171-190`).  
  **Fix**: List the exact required node IDs in the story and AC.

**4) Kontext-Sinnhaftigkeit — FAIL**

- **ERROR**: False code-location claim. Story says `Governance.register_hooks` is at `governance/hook_registration.py` (`story.md:24`). That file contains hook data models (`src/agentkit/governance/hook_registration.py:1-5`, `70-107`); the method is in `src/agentkit/governance/runner.py:193-229`.  
  **Fix**: Correct the reference and AC to `governance/runner.py:193`.

- **WARNING**: The AG3-088 story index row itself omits CP10c while claiming FK-50 §50.2-§50.4 coverage (`var/concept-gap-analysis/_STORY_INDEX.md:104`).  
  **Fix**: Update the index row together with the story so the planning source does not keep re-seeding the same concept gap.

- **PASS evidence for checked anchors/code**: FK anchors exist: §50.2 (`concept/...50...md:114`), §50.3 (`:130`), §50.3.1 (`:150`), §50.4 (`:567`). The claimed God-function exists at `src/agentkit/installer/runner.py:1014`; `FlowDefinition` exists at `src/agentkit/process/language/model.py:175`; `FlowLevel.COMPONENT` and `NodeKind.STEP/BRANCH` exist at `model.py:40`, `46-49`; CLI currently lacks `register-project` / `verify-project` (`src/agentkit/cli/main.py:40-160`).

**Must-Fix ERROR List**

1. Add CP10c scope, AC, and tests.
2. Add explicit CP3/CP4 reserved flow nodes.
3. Add CP8 `PromptRuntime.update_binding` preservation.
4. Replace invalid `UPGRADED` status with `UPDATED`.
5. Define dry-run `CheckpointResult` semantics.
6. Resolve `.mcp.json` contradiction.
7. Replace grep-based God-function AC with structural test criteria.
8. Correct `Governance.register_hooks` source reference to `governance/runner.py`.
