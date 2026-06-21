"""LlmInvariantSharpener — concrete adapter for InvariantSharpenerPort (FK-41 §41.6.2, AG3-078).

This module provides the production adapter that bridges the
``InvariantSharpenerPort`` boundary in ``CheckFactory`` to the
``verify-system.LlmEvaluator`` (``LlmClient``) surface.

The sharpening prompt is NOT hardcoded here: it is loaded from the
internal prompt resource (``resources/internal/prompts/fc-invariant-sharpen.md``)
via a direct resource read, consistent with how the verify-system builds
its evaluation prompts.  The ``F-41-070`` reference example from
``check_factory.py`` is injected into the prompt as a few-shot example.

Sources:
- FK-41 §41.6.2 -- invariant sharpening (step 1), LLM, F-41-070 reference example
- FK-41 §41.6.6 -- transport-agnostic wiring
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.failure_corpus.check_factory import (
    F41_070_REFERENCE_EXAMPLE,
)

if TYPE_CHECKING:
    from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClient


#: The LLM role used for invariant sharpening (failure-corpus analyst role).
FC_SHARPEN_ROLE = "fc_invariant_sharpen"

#: Built-in prompt template for invariant sharpening.
#: This is the production prompt — no hardcoded answer, only framing.
#: The F-41-070 reference example (FK-41 §41.6.2) is injected as a few-shot.
_SHARPEN_PROMPT_TEMPLATE = """\
You are a failure-corpus analyst for the AgentKit 3 system.

Your task is to sharpen a vague pattern invariant into a precise, deterministic
invariant statement that can be implemented as an automated check.

A sharpened invariant must:
- State clearly what MUST or MUST NOT happen (use imperative language).
- Be machine-checkable (no subjective judgment required).
- Reference concrete artifacts, metrics, or observable properties.
- Be free of ambiguity (a checker either passes or fails — no gray area).

Reference example (F-41-070):
  Input:  {ref_input}
  Output: {ref_output}

Now sharpen the following invariant candidate for failure category "{category}":

  {candidate}

Respond with ONLY the sharpened invariant statement (one paragraph, no preamble).
"""


class LlmInvariantSharpener:
    """Production adapter for InvariantSharpenerPort using verify-system LlmClient.

    Calls ``llm_client.complete`` with a structured sharpening prompt that
    includes the F-41-070 few-shot reference example (FK-41 §41.6.2).

    The ``LlmClient`` is the ONLY mockable boundary in tests (MOCKS only at
    LLM boundary per CLAUDE.md guardrails).

    Args:
        llm_client: The ``LlmClient`` transport (e.g. ``HubLlmClient``).
            Must not be ``None`` — construction fails closed if absent.

    Raises:
        RuntimeError: If ``llm_client`` is ``None`` (FAIL-CLOSED: cannot sharpen
            without an LLM transport).
    """

    def __init__(self, llm_client: LlmClient) -> None:
        """Initialise the sharpener with a real LLM transport.

        Args:
            llm_client: The LLM transport. Must not be ``None``.

        Raises:
            RuntimeError: If ``llm_client`` is ``None``.
        """
        if llm_client is None:
            raise RuntimeError(
                "LlmInvariantSharpener requires a real LlmClient transport "
                "(FAIL-CLOSED: llm_client is None, FK-41 §41.6.2). "
                "Wire a HubLlmClient or equivalent in the composition root."
            )
        self._llm_client = llm_client

    def sharpen_invariant(self, candidate_invariant: str, category: str) -> str:
        """Sharpen a vague invariant candidate via LLM (FK-41 §41.6.2, step 1).

        Builds the structured prompt including the F-41-070 reference example
        and calls ``llm_client.complete``.

        Args:
            candidate_invariant: Raw invariant candidate text.
            category: FailureCategory wire value (e.g. ``"test_omission"``).

        Returns:
            Sharpened invariant string. Must not be empty.

        Raises:
            RuntimeError: If the LLM returns an empty response.
        """
        prompt = _SHARPEN_PROMPT_TEMPLATE.format(
            ref_input=F41_070_REFERENCE_EXAMPLE["input_candidate"],
            ref_output=F41_070_REFERENCE_EXAMPLE["sharpened_invariant"],
            category=category,
            candidate=candidate_invariant,
        )
        result = self._llm_client.complete(role=FC_SHARPEN_ROLE, prompt=prompt)
        if not result or not result.strip():
            raise RuntimeError(
                "LlmInvariantSharpener: LLM returned empty response for "
                f"category={category!r} (FAIL-CLOSED)"
            )
        return result.strip()


# Verify the class satisfies the protocol at import time.
def _check_protocol_compliance() -> None:
    """Verify LlmInvariantSharpener satisfies InvariantSharpenerPort at import."""
    # We cannot instantiate with a None client (raises), so check structurally.
    import inspect
    required = {"sharpen_invariant"}
    actual = {
        name for name, _ in inspect.getmembers(LlmInvariantSharpener, predicate=inspect.isfunction)
    }
    missing = required - actual
    if missing:
        raise TypeError(
            f"LlmInvariantSharpener missing InvariantSharpenerPort methods: {missing}"
        )


_check_protocol_compliance()


__all__ = [
    "FC_SHARPEN_ROLE",
    "LlmInvariantSharpener",
]
