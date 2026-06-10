"""Unit tests for ParallelEvalRunner (AG3-043 / FK-27 §27.5.1, FK-11 §11.7).

The runner core (ThreadPoolExecutor, result gathering, fail-closed wrapping)
is exercised for real. Only the LLM grenze is stubbed via a scripted client
behind a real :class:`StructuredEvaluator` -- the runner and evaluator logic
are NOT stubbed.
"""

from __future__ import annotations

import json
import threading

import pytest

from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
from agentkit.verify_system.llm_evaluator.parallel_runner import (
    ParallelEvalError,
    ParallelEvalRunner,
)
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    LlmVerdict,
    ReviewerRole,
    StructuredEvaluator,
)

_PASS_BY_ROLE: dict[str, str] = {
    "qa_review": json.dumps([
        {"check_id": cid, "status": "PASS"}
        for cid in (
            "ac_fulfilled", "impl_fidelity", "scope_compliance", "impact_violation",
            "arch_conformity", "proportionality", "error_handling", "authz_logic",
            "silent_data_loss", "backward_compat", "observability", "doc_impact",
        )
    ]),
    "semantic_review": json.dumps([{"check_id": "systemic_adequacy", "status": "PASS"}]),
    "doc_fidelity": json.dumps([{"check_id": "impl_fidelity", "status": "PASS"}]),
}


class _StubMaterializer:
    def context_for(self, bundle: ReviewBundle) -> tuple[StoryContext, str]:
        ctx = StoryContext(
            project_key="test-project",
            story_id=bundle.story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )
        return ctx, bundle.story_id

    def render(
        self,
        role: ReviewerRole,
        ctx: StoryContext,
        story_id: str,
        template_override: str | None = None,
    ) -> tuple[str, str]:
        del ctx, story_id, template_override
        return f"PROMPT:{role.value}", "a" * 64


class _RoleScriptedClient:
    """Returns a per-role scripted response (external LLM grenze)."""

    def __init__(self, by_role: dict[str, str]) -> None:
        self.by_role = by_role

    def complete(self, *, role: str, prompt: str) -> str:
        del prompt
        return self.by_role[role]


class _ConcurrencyProbeClient:
    """Records max concurrent in-flight calls to prove parallelism.

    A :class:`threading.Barrier` (not a wall-clock sleep) deterministically forces
    all ``expected`` callers to be in flight simultaneously, so the assertion holds
    regardless of host load / xdist core oversubscription. A serial runner trips the
    barrier timeout (``BrokenBarrierError``) instead of silently observing fewer than
    ``expected`` concurrent calls.
    """

    def __init__(self, by_role: dict[str, str], *, expected: int = 3) -> None:
        self.by_role = by_role
        self._lock = threading.Lock()
        self._active = 0
        self.max_concurrent = 0
        self._barrier = threading.Barrier(expected)

    def complete(self, *, role: str, prompt: str) -> str:
        del prompt
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        # Block until all expected callers have arrived: proves real concurrency
        # without depending on timing. 5s is ample even on a saturated host.
        self._barrier.wait(timeout=5.0)
        with self._lock:
            self._active -= 1
        return self.by_role[role]


class _FailingRoleClient:
    """Fails for one role to prove fail-closed aggregation."""

    def __init__(self, by_role: dict[str, str], failing_role: str) -> None:
        self.by_role = by_role
        self.failing_role = failing_role

    def complete(self, *, role: str, prompt: str) -> str:
        del prompt
        if role == self.failing_role:
            return "not valid json"
        return self.by_role[role]


def _bundle() -> ReviewBundle:
    return ReviewBundle(
        story_id="AG3-043",
        story_brief_excerpt="brief",
        acceptance_criteria=["AC1"],
        diff_summary="stat",
        diff_content="diff",
        concept_refs=["FK-27"],
        previous_findings=None,
        qa_cycle_round=1,
    )


def test_run_returns_all_three_roles() -> None:
    evaluator = StructuredEvaluator(_RoleScriptedClient(_PASS_BY_ROLE), _StubMaterializer())
    runner = ParallelEvalRunner(evaluator)
    results = runner.run(_bundle(), None, 1)
    assert set(results.keys()) == set(ReviewerRole)
    assert all(r.verdict is LlmVerdict.PASS for r in results.values())


def test_run_executes_roles_in_parallel() -> None:
    """AK2: max concurrency observed must be 3 (all roles in flight at once)."""
    probe = _ConcurrencyProbeClient(_PASS_BY_ROLE)
    evaluator = StructuredEvaluator(probe, _StubMaterializer())
    runner = ParallelEvalRunner(evaluator, max_workers=3)
    runner.run(_bundle(), None, 1)
    assert probe.max_concurrent == 3  # noqa: PLR2004


def test_one_failing_role_fails_whole_run_closed() -> None:
    client = _FailingRoleClient(_PASS_BY_ROLE, failing_role="doc_fidelity")
    evaluator = StructuredEvaluator(client, _StubMaterializer())
    runner = ParallelEvalRunner(evaluator)
    with pytest.raises(ParallelEvalError, match="doc_fidelity"):
        runner.run(_bundle(), None, 1)


def test_max_workers_must_be_positive() -> None:
    evaluator = StructuredEvaluator(_RoleScriptedClient(_PASS_BY_ROLE), _StubMaterializer())
    with pytest.raises(ValueError, match="max_workers"):
        ParallelEvalRunner(evaluator, max_workers=0)
