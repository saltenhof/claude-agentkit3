# Execute User Story — 4-Phase Deterministic Pipeline

Orchestrator skill that manages the complete execution cycle for a user story:
Setup, Exploration, Implementation including the QA subflow, and Closure.
Mechanical checks and closure are handled by deterministic Python modules.
Agents do only creative work (implementation, semantic code review).

There is explicitly no standalone `verify` top-phase. `VerifySystem` is a
capability called inside the Implementation-phase QA subflow. When QA requires
remediation, the orchestrator stays inside the Implementation phase and repeats
`POST /phases/implementation/start`; it does not switch to a verify phase.

**Invocation:** `/execute-userstory <STORY-ID>`

**Mode:** Orchestrator — this skill implements NOTHING itself. It spawns and coordinates
sub-agents exclusively. Source code is NEVER read by the orchestrator.

---

## FK-43 §43.3.3 Canonical Eight-Step Orchestration

The orchestration sequence is exactly this eight-step flow:

1. Liest freigegebene Story aus dem AK3-Story-Backend.
2. Ruft `POST /phases/setup/start` auf.
3. Liest Phase-State -> spawnt Worker (oder Exploration-Worker).
4. Wartet auf Worker-Ende.
5. Ruft `POST /phases/implementation/start` auf — der QA-Subflow laeuft Subflow-intern in der Implementation-Phase und ruft die Capability `VerifySystem` (FK-27).
6. Liest Phase-State -> bei `qa_cycle_status: awaiting_remediation`: spawnt Remediation-Worker und ruft `POST /phases/implementation/start` erneut auf (Subflow-Loop, kein Phasenwechsel).
7. Bei `qa_cycle_status: pass` (Implementation COMPLETED): ruft `POST /phases/closure/start` auf.
8. Bei Eskalation: stoppt und informiert Mensch.

This eight-step flow is the top-level contract for `/execute-userstory`. The
only top-level phases are Setup, Exploration, Implementation, and Closure. The
implementation QA loop is a subflow; `VerifySystem` is a capability within that
subflow, not a fifth phase.

---

### !!! VERBOTEN: ORCHESTRATOR KOMMENTIERT KEINE SUB-AGENT-NOTIFICATIONS !!!

Wenn ein Sub-Agent im Hintergrund laeuft (`run_in_background: true`), liefert Claude Code
Notifications fuer jeden Background-Command des Sub-Agents an den Orchestrator zurueck
(Test-Laeufe, Server-Starts, Datei-Reads, fehlgeschlagene Unit-Tests, etc.).

**Der Orchestrator ignoriert diese Notifications STILLSCHWEIGEND.**

- **KEINE Textausgabe** fuer Worker-interne Tool-Aufrufe oder deren Ergebnisse.
- **KEINE Kommentare** wie "Worker hat Test gestartet", "Test fehlgeschlagen, Worker arbeitet daran",
  "Mock-Server gestartet", "Weiterer interner Check abgeschlossen".
- **KEINE Statusmeldungen** zwischen Agent-Spawn und Agent-Completion.

Der Orchestrator reagiert ausschliesslich auf:

1. **"Agent X completed"** — die finale Completion-Notification. Dann weiter im Pipeline-Ablauf.
2. **"Agent X failed"** oder Agent-Crash/Timeout — ein echter Phasenfehler. Dann Fehlerbehandlung
   gemaess Error Handling Tabelle (siehe unten).

**Unterscheidung: Worker-interner Fehler vs. Phasenfehler:**

| Situation | Orchestrator-Reaktion |
|-----------|----------------------|
| Unit-Test im Worker schlaegt fehl | IGNORIEREN — das ist Red-Green-Zyklus, Worker handhabt das |
| Worker-Server startet/stoppt | IGNORIEREN — Worker-interne Infrastruktur |
| Worker liest/schreibt Dateien | IGNORIEREN — normale Arbeit |
| Background-Command exit code != 0 | IGNORIEREN — Worker-internes Tooling |
| **Agent Completion (success)** | **REAGIEREN** — naechste Phase starten |
| **Agent Completion (failure/crash)** | **REAGIEREN** — Fehlerbehandlung, User informieren |
| **Agent Timeout** | **REAGIEREN** — als FAIL behandeln, verify-Phase starten |

Jede Textausgabe zwischen Spawn und Completion ist verschwendeter Kontext. Der Orchestrator
wartet schweigend und handelt erst wenn der Agent fertig ist oder stirbt.

---

**Key Metrics:**
- Agent spawns per story: 1-3 (Worker + QA-Semantic + QA-Guardrail if configured)
- Mechanical checks: 100% deterministic (no hallucination risk)
- Token savings: ~50-70% vs. previous multi-agent QA approach

## Mandatory Agent Spawn Header

Every `Agent(...)` call made by this orchestrator skill must begin its `description`
with this exact schema header:

```text
AGENTKIT-SUBAGENT-V1 mode=<freestyle|story_execution> role=<general|story-worker|story-qa|story-adversarial|story-remediation> story_id=<STORY-ID|null> skill_proof=<token|null>
```

For all story execution spawns created by this skill:

- `mode=story_execution`
- `story_id=<STORY-ID>`
- `skill_proof={{AGENT_SPAWN_SKILL_PROOF}}`
- `prompt_file` must come from `agents_to_spawn[*].prompt_file`

This header is mandatory. The governance hook blocks non-conformant spawns.

---

## Input

The skill receives a story ID as argument (e.g. `{{project_prefix}}-042`).

## Step 0: Load Orchestrator System Prompt

All prompt-template paths below are **relative to this skill bundle**
(the directory holding this `SKILL.md`), e.g. `prompts/orchestrator-system.md`.

Read and internalize the orchestrator role definition:

```
prompts/orchestrator-system.md
```

This defines what the orchestrator may and may not do. Follow it strictly.

---

## PHASE 1: SETUP (100% deterministic)

### [1] Run Setup Phase

```bash
agentkit run-phase setup \
  --story <STORY-ID> \

```

Read `_temp/qa/<STORY-ID>/phase-state.json`:

- `status`: `SUCCESS` → continue. `FAIL` → **HARD STOP**, report errors to user.
- `context.issue_nr` → `<ISSUE-NR>`
- `context.item_id` → `<ITEM-ID>`
- `context.story_dir` → `<STORY-DIR>`
- `context.story_type` → `<STORY-TYPE>`
- `context.worktree_path` → `<WORKTREE-PATH>`
- `agents_to_spawn[0].prompt_file` → Worker prompt path
- `agents_to_spawn[0].config_file` → Agent config path
- `agents_to_spawn[0].model` → Model selection

---

## Mode-Routing nach Setup

After reading `phase-state.json`, check the `mode` field:

```
IF mode == "execution":
  → Proceed to Phase 2: IMPLEMENTATION
  → Spawn implementation worker from agents_to_spawn

IF mode == "exploration":
  → Proceed to Phase 1b: EXPLORATION
  → Spawn exploration worker from agents_to_spawn
  → AFTER worker completion: call run_phase("exploration")
  → Complete the Exploration lifecycle (see Phase 1b below)
  → Only after COMPLETED: proceed to Phase 2: IMPLEMENTATION
```

**HARD RULE:** Do NOT call `run_phase("implementation")` if `mode == "exploration"`.
The exploration phase must reach COMPLETED status first.

---

## PHASE 1b: EXPLORATION (only when mode == "exploration")

### When Is Exploration Active?

Exploration is active when `run_phase("setup")` writes `mode: "exploration"` to `phase-state.json`.
This happens for implementing story types (implementation, bugfix) when the setup phase
determines that a design artifact is required before implementation begins.

### [1b-1] Spawn Exploration Worker

Read `agents_to_spawn[0]` from `phase-state.json`. The entry has `type: "worker-exploration"`.
Spawn the exploration worker:

```
Agent(
  description: "AGENTKIT-SUBAGENT-V1 mode=story_execution role=story-worker story_id=<STORY-ID> skill_proof={{AGENT_SPAWN_SKILL_PROOF}}\nExploration worker for <STORY-ID>",
  prompt_file: <prompt_file from agents_to_spawn[0]>,
  model: <model from agents_to_spawn[0].model>,
  run_in_background: true
)
```

Wait for the exploration worker to complete. Then proceed to step [1b-2].

### [1b-2] Call Exploration Phase (signal worker completion)

After the worker completes:

```bash
agentkit run-phase exploration \
  --story <STORY-ID> \

```

The phase runner detects the design artifact and evaluates it through the multi-stage exit gate:
- Stage 1: Document Fidelity Level 2 (architecture conformance check — deterministic)
- Stage 2a: Design Review (independent LLM review of design quality)
- Stage E2: Premise Challenge (mandatory after Design Review — premise-challenger agent)
- Stage 2b: Design Challenge (optional, triggered by risk factors)
- Stage 2c: Aggregation + Gate-Decision

Read `_temp/qa/<STORY-ID>/phase-state.json` after the call and check `status`:

```
COMPLETED → exploration_gate_status = "approved_for_implementation" → proceed to Phase 2
PAUSED    → gate requires agent work or human input → follow [1b-3]
ESCALATED → gate failure (non-remediable) → HARD STOP, inform user
IN_PROGRESS → not expected here (worker already completed) → investigate
```

### [1b-3] Gate Lifecycle (PAUSED states)

When `status == "PAUSED"`, read `pause_reason` from `phase-state.json` and react:

| `pause_reason` | Agent to spawn (from `agents_to_spawn`) | After completion |
|---|---|---|
| `awaiting_design_review` | type: `design-reviewer` | Call `run_phase("exploration")` again |
| `awaiting_premise_challenge` | type: `premise-challenger` | Call `run_phase("exploration")` again |
| `awaiting_design_challenge` | type: `design-challenger` | Call `run_phase("exploration")` again |
| `awaiting_exploration_remediation` | type: `worker-exploration` | Call `run_phase("exploration")` again |
| `awaiting_mandate_classification` | type: `mandate-classifier` | Call `run_phase("exploration")` again |
| `awaiting_feindesign` | type: `worker-feindesign` | Call `run_phase("exploration")` again |
| `mandate_escalation_human_required` | No agent — Klasse 1/3/4 Eskalation an Benutzer | Benutzer klärt Mandatsfrage, dann `run_phase("exploration")` |
| `design_review_non_remediable` | No agent — nicht-behebbare Design-Failure an Benutzer | Benutzer entscheidet Re-Scoping/Konzeptänderung, dann `run_phase("exploration")` |
| `human_approval_required` | No agent — escalate to user | After user confirms: call `run_phase("exploration")` again |

For each PAUSED resume cycle:

1. Spawn the required agent from `agents_to_spawn` (same pattern as [1b-1])
2. Wait for agent completion
3. Call `agentkit run-phase exploration --story <STORY-ID>` again
4. Read `phase-state.json` status again — repeat until COMPLETED or ESCALATED

**The PAUSED/resume cycle can repeat multiple times** (e.g. review → challenge → remediation → review again).
Continue until the exploration phase reaches COMPLETED or ESCALATED.

### [1b-4] Exploration COMPLETED — Transition to Implementation

When `status == "COMPLETED"` and `exploration_gate_status == "approved_for_implementation"`:

- The `agents_to_spawn` list now contains the implementation worker spawn contract.
- Proceed to **Phase 2: IMPLEMENTATION**.
- The `mode` field in `phase-state.json` will remain `"exploration"` — this is expected.

---

## Phase-State Fields Glossary

The following fields in `phase-state.json` are relevant for the Orchestrator:

| Field | Values | Meaning |
|---|---|---|
| `mode` | `"execution"` \| `"exploration"` | Pipeline path after Setup. `"exploration"` means Phase 1b runs before Phase 2. |
| `exploration_gate_status` | `""` \| `"doc_compliance_passed"` \| `"design_review_passed"` \| `"approved_for_implementation"` | Current gate progress within Phase 1b. Non-empty only during exploration. |
| `pause_reason` | string | Reason for PAUSED status. Determines which agent to spawn. |
| `agents_to_spawn` | list of objects | Complete spawn contracts (prompt_file, model, spawn_key, type). Always consumed from here — never recomposed by the orchestrator. |
| `suggested_reaction` | string | Human-readable action directive. Always follow this; it reflects the ORCHESTRATOR_REACTION_REGISTRY. |

---

## PHASE 2: IMPLEMENTATION (Agent)

### [2] Spawn Worker Agent

The setup phase has already composed the prompt and written it to disk.
Read `agents_to_spawn[0]` from `phase-state.json`:

- `prompt_file` → Absolute path to the fully composed prompt (all placeholders resolved)
- `config_file` → Absolute path to agent-config.json (model selection, metadata)
- `spawn_key` → Compound spawn key in `{base}--story={story_id}--r{round}` format (DD-06, FK-36). Example: `worker-implementation--story=BB2-042--r1`
- `model` → Model to use for spawning
- `worktree_path` → Working directory for the agent
- `worktree_paths` → All repo worktree paths (multi-repo)

Pass the prompt_file PATH to the Agent tool and spawn the agent:

```
Agent(
  description: "AGENTKIT-SUBAGENT-V1 mode=story_execution role=story-worker story_id=<STORY-ID> skill_proof={{AGENT_SPAWN_SKILL_PROOF}}\nImplement <STORY-ID>",
  prompt_file: <prompt_file path from agents_to_spawn[0]>,
  model: <model from agents_to_spawn[0].model>,
  run_in_background: true
)
```

**IMPORTANT:** The orchestrator does NOT compose, modify, or re-derive the prompt.
The prompt_file from phase-state.json is authoritative and complete. The orchestrator passes
the file path to the Agent tool — the Agent tool reads the file content. The orchestrator
NEVER reads prompt file contents itself.

### [2b] Bugfix Evidence Directory (bugfix stories only)

If `story_type == "bugfix"`, create the evidence directory before spawning the Worker:

```bash
mkdir -p _temp/evidence/<STORY-ID>
```

The Worker will write `bugfix-reproducer.json` and the `agentkit.bugfix.verify_reproducer`
module will populate `red/`, `green/`, `suite/` subdirectories with evidence.

### [3] Clarification Loop (concept and research stories only)

This step applies ONLY when `story_type == "concept"` or `story_type == "research"`. For other types, skip to [4].

After the Worker agent returns, read `<STORY-DIR>/worker-manifest.json` and check the
`status` field:

```
IF "status" == "NEEDS_CLARIFICATION":

  1. Read `_temp/qa/<STORY-ID>/clarification-request.json`

  2. Present the assessment and questions to the user via AskUserQuestion:
     - Show the complexity/invasiveness assessment
     - Show the preliminary analysis summary
     - Present each question with its context and default assumption
     - Let the user answer each question

  3. Write user answers to `_temp/qa/<STORY-ID>/clarification-answers.json`:
     ```json
     {
       "schema_version": "1.0",
       "story_id": "<STORY-ID>",
       "answers": [
         { "question_id": "Q1", "answer": "<user-answer>" }
       ],
       "additional_context": "<any extra info the user provided>"
     }
     ```

  4. Re-compose the worker prompt (worker-concept.md or worker-research.md, based on story_type)
     with the additional placeholder:
     - Set `<CLARIFICATION-ANSWERS>` = `_temp/qa/<STORY-ID>/clarification-answers.json`
     - Activate the `{{#IF_CLARIFICATION_ANSWERS}}` section in the prompt
       (supported by both worker-concept.md and worker-research.md)
     - Increment round counter

  5. Re-spawn Worker agent with the updated prompt
     → Return to [3] (repeated clarification is theoretically possible)

IF "status" == "COMPLETED" OR "status" field is absent:
  → Proceed to [4]
```

**IMPORTANT:** The orchestrator does NOT evaluate or filter the questions. It acts as a
structured pass-through between the Worker's questions and the user's answers. This is
the ONLY case where the orchestrator may use AskUserQuestion.

---

## PHASE 3: VERIFICATION (primarily deterministic)

### [4] Run Verify Phase

```bash
agentkit run-phase verify \
  --story <STORY-ID> \
  --attempt <ROUND> \
  --story-dir <STORY-DIR> \

```

Read `_temp/qa/<STORY-ID>/phase-state.json`:

- `status` + `verify_result` together determine the next action:
  - `status = "PAUSED"` + `verify_result = "RUN_SEMANTIC"`: spawn QA agents from `agents_to_spawn`, then call `agentkit run-phase verify` again (see step [5])
  - `status = "PAUSED"` + `pause_reason = "awaiting_qa_agents"` (second call): QA artifacts not yet available — wait and retry
  - `status = "COMPLETED"`: verification passed — proceed to Phase 5
  - `status = "FAILED"`: verification failed — go to remediation loop (Phase 4)
  - `verify_result = "SKIP_SEMANTIC"`: blocking structural failures — go to remediation loop
- `agents_to_spawn` → for each agent: read prompt file, spawn agent

For each agent in `agents_to_spawn`:

```
Agent(
  description: "AGENTKIT-SUBAGENT-V1 mode=story_execution role=story-qa story_id=<STORY-ID> skill_proof={{AGENT_SPAWN_SKILL_PROOF}}\n<type> <STORY-ID> round <ROUND>",
  prompt_file: <prompt_file path from agents_to_spawn entry>,
  model: <model>,
  run_in_background: true
)
```

**Spawn QA-Semantic and QA-Guardrail in parallel** — they are independent.

### [5] Resume Verify Phase (after QA agents complete)

Wait for all QA agents to complete, then call `run-phase verify` a second time:

```bash
agentkit run-phase verify \
  --story <STORY-ID> \
  --attempt <ROUND> \
  --story-dir <STORY-DIR> \

```

The phase runner detects `qa_cycle_status = "awaiting_qa"` in the persisted state and:
1. Checks that `semantic.json` (and `guardrail.json` if configured) are present
2. Runs the policy engine deterministically
3. Writes `decision.json`
4. Sets `status = "COMPLETED"` (PASS) or `status = "FAILED"` (FAIL)

**Do NOT run `python -m agentkit.qa.policy_engine` separately** — `run-phase verify` handles this in the resume path.

Read `_temp/qa/<STORY-ID>/phase-state.json` after the second verify call:
- `status = "COMPLETED"` → proceed to Phase 5
- `status = "FAILED"` → go to remediation loop (Phase 4)
- `status = "PAUSED"` → QA artifacts still missing; wait and retry step [5]
- `status = "ESCALATED"` + `escalation_reason = "qa_deadlock"` → QA agents did not produce artifacts within the allowed retry window; human intervention required

---

## PHASE 4: LOOP (on FAIL)

### [6] Remediation Loop

```
IF phase-state status == FAILED AND round < 3:
  → The verify phase has already composed the remediation prompt and populated
    agents_to_spawn with the remediation worker entry (including prompt_file,
    config_file, model). Read agents_to_spawn from phase-state.json.
  → Spawn Worker agent using prompt_file and model from agents_to_spawn, with:
    `AGENTKIT-SUBAGENT-V1 mode=story_execution role=story-remediation story_id=<STORY-ID> skill_proof={{AGENT_SPAWN_SKILL_PROOF}}`
  → Return to [4]

IF phase-state status == FAILED AND round == 3:
  → ESCALATION

IF phase-state status == COMPLETED:
  → Proceed to Phase 5
```

---

## PHASE 5: CLOSURE (100% deterministic)

### [7] Run Closure Phase

```bash
agentkit run-phase closure \
  --story <STORY-ID> \
  --issue-nr <ISSUE-NR> \
  --item-id <ITEM-ID> \
  --attempt <ROUND> \
  --story-dir <STORY-DIR> \

```

Read `_temp/qa/<STORY-ID>/phase-state.json`:

- `status`: `SUCCESS` → continue. `FAIL` → **STOP**, report merge failure to user.
- `closure_completed`: `true` → story is closed.
- `warnings` → report any closure/post-flight warnings to user.

### [8] Report to User

Report to user: Story `<STORY-ID>` completed. QA Rounds: N. Processing Time: X min.

---

## Escalation (on 3x FAIL)

After 3 failed QA rounds, inform the user:

```
Story <STORY-ID> has FAILED 3 QA rounds.

Latest reports:
- Structural: _temp/qa/<STORY-ID>/structural.json
- Semantic: _temp/qa/<STORY-ID>/semantic.json
- Guardrail: _temp/qa/<STORY-ID>/guardrail.json (if present)
- Decision: _temp/qa/<STORY-ID>/decision.json

Recurring issues:
- [summarize blocking/major failures across rounds]

Recommended next steps:
- Review the QA findings manually
- Consider simplifying the story scope
- Consider breaking into smaller stories
```

Deactivate orchestrator guard: `rm -f _temp/governance/.story-execution-active`

The user decides whether and how to continue.

---

## Prompt Template Paths

```
prompts/orchestrator-system.md
prompts/worker-implementation.md       (implementation stories)
prompts/worker-bugfix.md               (bugfix stories)
prompts/worker-concept.md              (concept stories)
prompts/worker-research.md             (research stories)
prompts/worker-remediation.md          (all types, rounds 2+)
prompts/qa-semantic.md                 (implementation stories)
prompts/qa-semantic-bugfix.md          (bugfix stories)
prompts/qa-semantic-concept.md         (concept stories)
prompts/qa-semantic-research.md        (research stories)
prompts/qa-guardrail.md                (all types, if guardrails configured)
prompts/sparring/  (used by Worker, not by Orchestrator)
```

---

## Script / Module Paths

```
agentkit run-phase {setup|exploration|implementation|verify|closure}
tools/orchestration/compose-prompt.py
agentkit preflight                           (was: tools/governance/pre-flight-check.sh)
agentkit postflight                          (was: tools/governance/post-flight-check.sh)
agentkit.governance.github_status            (was: tools/governance/set-github-status.sh)
agentkit.core.context                        (was: tools/governance/compute-story-context.sh)
agentkit.governance.artifacts                (was: tools/governance/verify-worker-artifacts.sh)
python -m agentkit.qa.structural_check
python -m agentkit.qa.policy_engine
python -m agentkit.bugfix.verify_reproducer   (was: tools/bugfix/verify-reproducer.sh)
agentkit.closure.closure                     (was: tools/closure/story-closure.sh)
agentkit.worktree.setup                      (was: tools/worktree/story-worktree-setup.sh)
agentkit.worktree.teardown                   (was: tools/worktree/story-worktree-teardown.sh)
agentkit.worktree.merge                      (was: tools/worktree/story-merge.sh)
agentkit.worktree.multi_repo                 (was: tools/worktree/story-multi-repo-merge.sh)
```

---

## Governance Integration

| Phase | Tool | Type |
|-------|------|------|
| Phase 1 | `agentkit run-phase setup` | Deterministic (phase orchestration) |
| Phase 1 | `agentkit preflight` | Deterministic (hard stop) |
| Phase 1 | `agentkit.core.context` | Deterministic (context extraction) |
| Phase 1 | `agentkit.governance.github_status` | Deterministic (status update) |
| Phase 2 | `orchestrator-guard.py` | Hook (blocks code reads) |
| Phase 2 | `bugfix-test-guard.py` | Hook (blocks direct test execution in bugfix stories) |
| Phase 2 | `python -m agentkit.bugfix.verify_reproducer` | Python module (red/green/suite TDD verification) |
| Phase 3 | `agentkit run-phase verify` | Deterministic (phase orchestration) |
| Phase 3 | `agentkit.governance.artifacts` | Deterministic (artifact check) |
| Phase 3 | `python -m agentkit.qa.structural_check` | Deterministic (25+ mechanical checks) |
| Phase 3 | `qa-semantic.md` agent | LLM-based (semantic review) |
| Phase 3 | `qa-guardrail.md` agent | LLM-based (guardrail compliance, if configured) |
| Phase 3 | `python -m agentkit.qa.policy_engine` | Deterministic (PASS/FAIL decision) |
| Phase 5 | `agentkit run-phase closure` | Deterministic (phase orchestration) |
| Phase 5 | `agentkit.worktree.multi_repo` | Deterministic (saga merge, multi-repo) |
| Phase 5 | `agentkit.worktree.teardown` | Deterministic (per-repo cleanup) |
| Phase 5 | `agentkit.closure.closure` | Deterministic (metrics+close) |
| Phase 5 | `agentkit postflight` | Deterministic (validation) |
| Always | `story-telemetry.py` | Hook (observational logging) |
| Phase 2 | `web-call-budget.py` | Hook (research web-call budget enforcement) |
| Phase 3 | `auto-copy-semantic.py` | Hook (auto-copy semantic report to policy engine path) |

---

## Error Handling

| Scenario | Action |
|----------|--------|
| Pre-flight check fails | HARD STOP, report details to user |
| Worker crashes / timeout | Treat as FAIL, run verify phase to assess |
| Structural check finds blockers | Skip semantic agent, go straight to policy engine |
| QA-Semantic crashes / timeout | Run policy engine without semantic input |
| QA-Guardrail crashes / timeout | Run policy engine without guardrail input |
| GitHub API error | Retry once, then inform user |
| Telemetry file missing | Log warning, checks skip telemetry dimensions |
| Issue not found | STOP immediately, inform user |
| Dependencies not met | STOP immediately, inform user which dep blocks |
| Post-flight check fails | Report warnings, do NOT revert closure |
| Multi-repo merge partial failure | STOP, report which repos succeeded/failed, require manual intervention |
