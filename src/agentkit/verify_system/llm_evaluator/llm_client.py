"""LLM-client port for Layer-2 evaluations (FK-34 / FK-11 §11.5.1).

Layer 2 of the QA-subflow (FK-27 §27.5) runs three parallel LLM evaluations
through the :class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`.
The evaluator must not know *which* concrete LLM provider answers a given
role -- that routing is a follow-up story (story.md §2.2: "LLM-Pool-Auswahl
... Sub-Story; diese Story arbeitet mit ``LlmClient``-Abstraktion").

This module therefore defines only the **port**: a narrow, synchronous
protocol the evaluator depends on. The concrete adapter onto the
``MultiLlmHub`` (``agentkit.multi_llm_hub.client.HubClient``) is wired in the
follow-up story; the Hub's richer session/lease API is intentionally NOT
leaked into the verify-system BC here.

Quelle:
  - FK-34 -- LLM-Bewertungen-Runtime (StructuredEvaluator, drei Rollen)
  - FK-11 §11.5.1 -- StructuredEvaluator (CheckResult-basiert)
  - FK-34 §34.5.1 -- Fehlerbehandlung (fail-closed: Pool/Antwort-Fehler -> FAIL)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agentkit.verify_system.errors import VerifySystemError


class LlmClientError(VerifySystemError):
    """Raised when the LLM transport itself fails (FK-34 §34.5.1).

    Distinct from
    :class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluatorError`
    (which signals an *invalid response shape*): this error means the call did
    not produce any usable text at all (pool unreachable, timeout, empty
    completion). Both are fail-closed -- the evaluator never silently treats a
    failed LLM call as a PASS (FK-34 §34.5.1: "Jedes FAIL ist fail-closed").
    """


@runtime_checkable
class LlmClient(Protocol):
    """Synchronous LLM evaluation port (FK-34 / FK-11 §11.5.1).

    A single-shot text-in/text-out call. The
    :class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`
    renders a role-specific prompt (the materialized template plus the
    serialized :class:`~agentkit.verify_system.llm_evaluator.bundle.ReviewBundle`)
    and passes it here; the implementation returns the raw model completion as
    text. The evaluator owns all JSON-schema validation downstream
    (fail-closed), so the port deliberately stays free of any response
    structure.
    """

    def complete(self, *, role: str, prompt: str) -> str:
        """Run a single LLM completion for an evaluation role.

        Args:
            role: The reviewer role wire-string (e.g. ``"qa_review"``). The
                adapter uses it to route to the configured pool/model for that
                role (FK-11 §11.5.1 ``llm_roles``); the evaluator passes it
                through opaquely.
            prompt: The fully materialized prompt text (template + serialized
                bundle). The implementation MUST NOT mutate or re-template it.

        Returns:
            The raw model completion as text. Never ``None``.

        Raises:
            LlmClientError: If the transport fails or yields no text
                (pool unreachable, timeout, empty completion) -- fail-closed
                (FK-34 §34.5.1).
        """
        ...


@dataclass(frozen=True)
class FailClosedLlmClient:
    """A ``LlmClient`` that always fails closed (no LLM pool configured yet).

    AG3-043 E6 / story.md §2.2: the concrete LLM-pool adapter (which pool /
    provider answers a role) is a follow-up story. Until it is wired, the
    composition root still wires Layer 2 to RUN (FK-27 §27.5 "Reviews finden
    IMMER statt") -- with this client. Every ``complete`` call raises
    :class:`LlmClientError`, so Layer 2 fails closed (the QA-subflow blocks the
    story, NO ERROR BYPASSING) instead of silently falling back to the
    deterministic stub reviewers. This is the correct fail-closed default per
    FK-34 §34.5.1 ("Pool nicht erreichbar -> FAIL"): a missing transport is a
    hard FAIL, never a silent skip or a quietly-degraded review.

    Attributes:
        reason: The fail-closed reason embedded in the raised error.
    """

    reason: str = (
        "No LLM pool is configured for Layer-2 evaluations yet "
        "(FK-11 LLM-Pool-Auswahl is a follow-up story, story.md §2.2). "
        "Layer 2 fails closed (FK-34 §34.5.1 'Pool nicht erreichbar -> FAIL')."
    )

    def complete(self, *, role: str, prompt: str) -> str:
        """Always raise :class:`LlmClientError` (fail-closed).

        Args:
            role: The reviewer role wire-string (unused; fail-closed).
            prompt: The materialized prompt (unused; fail-closed).

        Raises:
            LlmClientError: Always, with the configured fail-closed reason.
        """
        del prompt  # fail-closed: no transport; nothing to send.
        raise LlmClientError(f"{self.reason} (role={role!r})")


__all__ = ["FailClosedLlmClient", "LlmClient", "LlmClientError"]
