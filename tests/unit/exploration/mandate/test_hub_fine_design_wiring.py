"""Productive hub fine-design collaborators (AG3-097).

Covers the productive ``ChangeFrameFineDesignPromptBuilder`` (deterministic round
prompt) and the ``LlmConvergenceJudge`` (delegates the convergence verdict to an
injected ``LlmClient``; NEVER fabricates a verdict -- a transport failure or an
unparseable / wrong-shaped verdict fails closed via
``FineDesignEvaluatorUnavailableError``, mapped to D4 FAILED upstream).

The only doubled seam is the ``LlmClient`` boundary (the LLM grenze, MOCKS
exception); the prompt builder + judge logic are real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.exploration_change_frame_fixture import example_change_frame

from agentkit.backend.exploration.mandate.fine_design import (
    FineDesignEvaluatorUnavailableError,
)
from agentkit.backend.exploration.mandate.hub_fine_design_wiring import (
    ChangeFrameFineDesignPromptBuilder,
    LlmConvergenceJudge,
)
from agentkit.backend.verify_system.llm_evaluator.llm_client import (
    FailClosedLlmClient,
    LlmClientError,
)

if TYPE_CHECKING:
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName

_RESPONSES: dict[HubBackendName, str] = {"chatgpt": "use one key", "qwen": "agree"}


class _ScriptedLlm:
    """Boundary double returning a fixed verdict completion (MOCKS exception)."""

    def __init__(self, completion: str) -> None:
        self._completion = completion
        self.seen_role: str | None = None

    def complete(self, *, role: str, prompt: str) -> str:
        del prompt
        self.seen_role = role
        return self._completion


def test_prompt_builder_renders_open_points_and_previous_responses() -> None:
    """The round prompt carries the open points + prior round positions."""
    frame = example_change_frame()
    builder = ChangeFrameFineDesignPromptBuilder()

    prompt = builder.build(frame, round_number=2, previous_responses=_RESPONSES)

    assert "Round: 2" in prompt
    assert frame.story_id in prompt
    # The previous-round positions are echoed for the next round.
    assert "chatgpt: use one key" in prompt
    assert "Previous round positions:" in prompt


def test_prompt_builder_round_one_has_no_previous_block() -> None:
    """On round 1 (no prior responses) there is no previous-positions block."""
    prompt = ChangeFrameFineDesignPromptBuilder().build(
        example_change_frame(), round_number=1, previous_responses={}
    )

    assert "Previous round positions:" not in prompt


def test_judge_converges_on_valid_verdict() -> None:
    """A valid verdict JSON yields a converged outcome carrying the decisions."""
    completion = (
        '{"converged": true, "decisions": [{"decision_id": "FD-001", '
        '"question": "one key?", "decision": "single key", '
        '"rationale": "consistent", "normative_basis": ["FK-25"]}]}'
    )
    llm = _ScriptedLlm(completion)
    judge = LlmConvergenceJudge(llm)

    outcome = judge.judge(example_change_frame(), round_number=1, responses=_RESPONSES)

    assert outcome.converged is True
    assert len(outcome.decisions) == 1
    decision = outcome.decisions[0]
    assert decision.decision_id == "FD-001"
    # The per-advisor positions are recorded verbatim on the decision.
    assert decision.llm_responses == ("chatgpt: use one key", "qwen: agree")
    assert llm.seen_role == "fine_design_convergence"


def test_judge_not_converged_verdict() -> None:
    """A ``converged: false`` verdict yields a non-converged outcome."""
    llm = _ScriptedLlm('{"converged": false, "decisions": []}')

    outcome = LlmConvergenceJudge(llm).judge(
        example_change_frame(), round_number=1, responses=_RESPONSES
    )

    assert outcome.converged is False
    assert outcome.decisions == ()


def test_judge_fails_closed_on_transport_error() -> None:
    """A verdict transport failure (pool unreachable) fails closed (D4)."""

    class _DownLlm:
        def complete(self, *, role: str, prompt: str) -> str:
            del role, prompt
            raise LlmClientError("pool unreachable")

    with pytest.raises(FineDesignEvaluatorUnavailableError, match="transport failed"):
        LlmConvergenceJudge(_DownLlm()).judge(
            example_change_frame(), round_number=1, responses=_RESPONSES
        )


def test_judge_fails_closed_with_fail_closed_default_client() -> None:
    """The productive fail-closed default client -> fail-closed verdict (D4)."""
    with pytest.raises(FineDesignEvaluatorUnavailableError):
        LlmConvergenceJudge(FailClosedLlmClient()).judge(
            example_change_frame(), round_number=1, responses=_RESPONSES
        )


def test_judge_fails_closed_on_non_json_verdict() -> None:
    """An unparseable (non-JSON) verdict fails closed -- no fabricated verdict."""
    with pytest.raises(FineDesignEvaluatorUnavailableError, match="not valid JSON"):
        LlmConvergenceJudge(_ScriptedLlm("not json at all")).judge(
            example_change_frame(), round_number=1, responses=_RESPONSES
        )


def test_judge_fails_closed_on_wrong_shape_verdict() -> None:
    """A wrong-shaped verdict (missing required keys) fails closed (no convergence)."""
    # Missing the mandatory ``decisions`` key -> ValidationError -> fail-closed.
    with pytest.raises(FineDesignEvaluatorUnavailableError, match="invalid shape"):
        LlmConvergenceJudge(_ScriptedLlm('{"converged": true}')).judge(
            example_change_frame(), round_number=1, responses=_RESPONSES
        )


def test_judge_fails_closed_on_extra_keys_verdict() -> None:
    """Extra keys in the verdict (``extra=forbid``) fail closed (strict contract)."""
    completion = '{"converged": true, "decisions": [], "sneaky": 1}'

    with pytest.raises(FineDesignEvaluatorUnavailableError, match="invalid shape"):
        LlmConvergenceJudge(_ScriptedLlm(completion)).judge(
            example_change_frame(), round_number=1, responses=_RESPONSES
        )
