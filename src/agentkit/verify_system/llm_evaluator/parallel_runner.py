"""ParallelEvalRunner -- three parallel Layer-2 evaluations (FK-27 §27.5.1 / FK-11 §11.7).

Layer 2 of the QA-subflow runs the three :class:`ReviewerRole` evaluations
concurrently over a :class:`concurrent.futures.ThreadPoolExecutor` with
``max_workers=3`` (FK-11 §11.7). Each role is a fail-closed
:class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`
call; the runner gathers all three
:class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluatorResult`
objects.

Fail-closed (story.md §2.1.2 / FK-34 §34.5.1): if **any** role raises (LLM
transport error, schema-violating response, unknown check-id), the run does
not silently drop that role. The exception is re-raised wrapped in
:class:`ParallelEvalError` so the caller (``VerifySystem``) turns Layer 2 into
a BLOCKING failure -- there is no partial / best-effort Layer-2 result.

Quelle:
  - FK-27 §27.5.1 -- drei parallele LLM-Bewertungen
  - FK-11 §11.7 -- ThreadPoolExecutor (technische Umsetzung)
  - FK-34 §34.5.1 -- fail-closed (kein stiller Skip)
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

from agentkit.verify_system.errors import VerifySystemError
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    ReviewerRole,
    StructuredEvaluator,
    StructuredEvaluatorResult,
)

if TYPE_CHECKING:
    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.verify_system.protocols import Finding

#: Layer-2 runs exactly the three FK-27 §27.5.1 roles in parallel.
_MAX_WORKERS: int = 3


class ParallelEvalError(VerifySystemError):
    """Raised when any of the three parallel Layer-2 evaluations fails.

    FK-34 §34.5.1 / story.md §2.1.2: a single failing role fails the whole
    Layer-2 run fail-closed -- there is no partial result. Wraps the original
    cause (an LLM transport error or a schema-violating response).
    """


class ParallelEvalRunner:
    """Runs the three Layer-2 roles in parallel, fail-closed (FK-27 §27.5.1)."""

    def __init__(
        self,
        evaluator: StructuredEvaluator,
        max_workers: int = _MAX_WORKERS,
    ) -> None:
        """Initialise the runner.

        Args:
            evaluator: The shared :class:`StructuredEvaluator` (one per role
                call; the evaluator itself is stateless beyond its injected
                client/materializer).
            max_workers: Thread-pool size; defaults to ``3`` (one per role,
                FK-11 §11.7). Must be >= 1 (fail-closed).

        Raises:
            ValueError: If ``max_workers`` < 1.
        """
        if max_workers < 1:
            msg = f"max_workers must be >= 1 (FK-11 §11.7); got {max_workers!r}"
            raise ValueError(msg)
        self._evaluator = evaluator
        self._max_workers = max_workers

    def run(
        self,
        bundle: ReviewBundle,
        previous_findings: list[Finding] | None,
        qa_cycle_round: int,
    ) -> dict[ReviewerRole, StructuredEvaluatorResult]:
        """Run all three roles in parallel and return their results.

        Args:
            bundle: The immutable review bundle (shared by all three roles).
            previous_findings: Prior-round findings for remediation mode
                (passed through to each role's evaluator). ``None`` initially.
            qa_cycle_round: 1-based QA-cycle round (``> 1`` => remediation).

        Returns:
            A mapping ``ReviewerRole -> StructuredEvaluatorResult`` with exactly
            the three roles.

        Raises:
            ParallelEvalError: If any role's evaluation raises (fail-closed;
                wraps the first encountered cause).
        """
        return self.run_roles(tuple(ReviewerRole), bundle, previous_findings, qa_cycle_round)

    def run_roles(
        self,
        roles: tuple[ReviewerRole, ...],
        bundle: ReviewBundle,
        previous_findings: list[Finding] | None,
        qa_cycle_round: int,
    ) -> dict[ReviewerRole, StructuredEvaluatorResult]:
        """Run selected roles in parallel and return their results."""
        results: dict[ReviewerRole, StructuredEvaluatorResult] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(self._max_workers, len(roles)),
            thread_name_prefix="layer2-eval",
        ) as pool:
            future_to_role = {
                pool.submit(
                    self._evaluator.evaluate,
                    role,
                    bundle,
                    previous_findings,
                    qa_cycle_round,
                ): role
                for role in roles
            }
            for future in concurrent.futures.as_completed(future_to_role):
                role = future_to_role[future]
                try:
                    results[role] = future.result()
                except Exception as exc:
                    detail = f"{type(exc).__name__}: {exc}"
                    msg = f"Layer-2 evaluation for role={role.value!r} failed (FK-34 §34.5.1 fail-closed): {detail}"
                    raise ParallelEvalError(msg) from exc
        return results

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: ReviewBundle,
        previous_findings: list[Finding] | None,
        qa_cycle_round: int,
        expected_check_ids: frozenset[str] | None = None,
        template_override: str | None = None,
    ) -> StructuredEvaluatorResult:
        """Evaluate one role through the shared StructuredEvaluator."""
        return self._evaluator.evaluate(
            role,
            bundle,
            previous_findings,
            qa_cycle_round,
            expected_check_ids,
            template_override,
        )


__all__ = ["ParallelEvalError", "ParallelEvalRunner"]
