from __future__ import annotations

from agentkit.backend.governance.protocols import GuardVerdict, ViolationType
from agentkit.harness_client.harness_adapters.codex.decision_mapping import (
    codex_exit_code,
    to_codex_output,
)


def test_allow_verdict_maps_to_codex_allow_output() -> None:
    output = to_codex_output(GuardVerdict.allow("guard_evaluation"))

    assert output.decision == "allow"
    assert output.guard == "guard_evaluation"
    assert output.message is None
    assert output.detail is None
    assert codex_exit_code(output) == 0


def test_block_verdict_maps_to_codex_block_output() -> None:
    output = to_codex_output(
        GuardVerdict.block(
            "branch_guard",
            ViolationType.BRANCH_VIOLATION,
            "blocked",
            detail={"command": "git push --force"},
        ),
    )

    assert output.decision == "block"
    assert output.guard == "branch_guard"
    assert output.message == "blocked"
    assert output.detail == {"command": "git push --force"}
    assert codex_exit_code(output) == 2
