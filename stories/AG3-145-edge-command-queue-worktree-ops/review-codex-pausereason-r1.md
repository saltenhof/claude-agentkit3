# Consistency Check Across All Sites

Reviewed commit `31ee9f6b` via `git show` / `git diff` and a broad `git grep` sweep over `concept/`, `src/`, and `tests/`.

- PASS: FK-39 §39.2.2 carries `AWAITING_EDGE_PROVISIONING` in the glossary description, glossary `values:` list, enum code block, value table, prose count (`vier`), and lowercase wire-format list.
- PASS: FK-20 §20.6.1 adds the setup pause trigger row for edge provisioning/preflight.
- PASS: FK-45 §45.3 adds the `setup` PAUSED outcome row with `awaiting_edge_provisioning`.
- ERROR: The code enum has the member and synonym-map entries, but surrounding doc text still says the enum has three values.
- ERROR: The contract map and `expected_count=4` are updated, and `test_pause_reason.py` iteration order is updated; however other tests in the same file still enumerate only the old three cases.

# Broad-Sweep Result

Findings that still assume exactly three PauseReason values or omit `AWAITING_EDGE_PROVISIONING`:

- ERROR: `concept/technical-design/20_workflow_engine_state_machine.md:605` still says "Definition der drei PauseReason-Werte"; the resume table at `concept/technical-design/20_workflow_engine_state_machine.md:608` lists only the three old PAUSED reasons. Fix: change the prose to four values and add a PAUSED `AWAITING_EDGE_PROVISIONING` setup row with resume after the Project Edge report/service resume.
- ERROR: `concept/technical-design/37_verify_context_und_qa_bundle.md:322` says the PauseReason enum has only three values and lists only `AWAITING_DESIGN_REVIEW`, `AWAITING_DESIGN_CHALLENGE`, and `GOVERNANCE_INCIDENT`. Fix: update this to four values including `AWAITING_EDGE_PROVISIONING`, or reword to avoid a count while preserving that none of the PauseReason values is a Layer-2 QA state.
- ERROR: `src/agentkit/backend/core_types/pause_reason.py:6` says "Exactly three normalized values" and `src/agentkit/backend/core_types/pause_reason.py:28` says the synonym table maps onto three members. Fix: update both to four or remove the hard-coded count.
- ERROR: `src/agentkit/backend/pipeline_engine/engine.py:78` says the handler contract permits "only three" pause reasons. Fix: update to four or remove the count.
- ERROR: `src/agentkit/backend/pipeline_engine/phase_envelope/errors.py:19` says the handler contract allows "exactly three PauseReason values". Fix: update to four or remove the count.
- ERROR: `tests/contract/core_types/test_enum_wire_values.py:15` still documents `PauseReason | 3 | FK-39 §39.2.2` in the enum count table. Fix: change the count to 4.
- ERROR: `tests/unit/core_types/test_pause_reason.py:10` claims `test_each_value_constructable` but constructs only the old three enum values. Fix: add `PauseReason("AWAITING_EDGE_PROVISIONING") is PauseReason.AWAITING_EDGE_PROVISIONING`.
- ERROR: `tests/unit/core_types/test_pause_reason.py:50` verifies the synonym table row-wise but omits the three new synonym-map entries (`awaiting_edge_provisioning`, `edge_provisioning`, `edge_provisioning_pending`). Fix: add them with expected `PauseReason.AWAITING_EDGE_PROVISIONING`.
- ERROR: `tests/unit/core_types/test_pause_reason.py:69` verifies canonical wire values but omits `AWAITING_EDGE_PROVISIONING`. Fix: add the canonical value, preferably with a mixed-case variant as with the design-review case.

No non-exhaustive `match`/`case` over `PauseReason` was found in `src/` or `tests/`.

# Semantic Soundness

PASS: The new reason is semantically coherent with FK-39's `PAUSED` framing as a temporary cooperative control handoff, not inherently a human-wait state. The description is also consistent with the synchronous decision: setup pauses fail-closed while the agent drives its own Project Edge command loop, then resumes on the edge report. This does not model an idle async backend job.

VERDICT: REJECT
