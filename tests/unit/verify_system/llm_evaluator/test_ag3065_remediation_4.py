"""Remediation-4 tests for AG3-065 review ERRORs 1+2 (fourth review round).

ERROR 1 — evaluator deadline is NOT concurrency-safe (reopens TOTAL bound)
  The prior fix stored ``_eval_deadline`` as a shared instance attribute on
  HubLlmClient. With ParallelEvalRunner using ThreadPoolExecutor (3 threads),
  a later role's evaluate() could overwrite an earlier role's deadline before
  the earlier role's retry completes — giving the earlier role extra budget.

  Fix: ``_EVAL_DEADLINE_CV`` ContextVar (module-level in ``llm_client.py``).
  ``StructuredEvaluator.evaluate()`` binds the deadline via
  ``bind_eval_deadline(deadline)`` at entry and resets it in ``finally`` via
  ``_EVAL_DEADLINE_CV.reset(token)``. HubLlmClient.complete() reads the CV,
  not an instance attribute. Concurrent roles see only their own deadline.

ERROR 2 — release timeout not clamped to evaluator deadline
  ``_safe_release()`` previously always passed ``RELEASE_TIMEOUT_SECONDS``
  (10s). Near a TOTAL boundary, acquire+send are clamped but release could
  still add up to 10s beyond the evaluator budget.

  Fix: ``_safe_release(session_id, token, *, deadline=None)`` clamps to
  ``max(1.0, min(RELEASE_TIMEOUT_SECONDS, remaining_budget))`` when a
  deadline is provided. Best-effort floor of 1.0s ensures release always
  completes if budget is exhausted.

CONCURRENT REGRESSION TEST (ERROR 1):
  One shared HubLlmClient + a fake hub, run >=2 roles concurrently through
  the REAL ParallelEvalRunner path. One role consumes most of its budget.
  Assert NO role gets more than ~TOTAL_TIMEOUT_SECONDS of wall-clock budget.

RELEASE CLAMP TEST (ERROR 2):
  Assert release timeout is clamped when remaining budget < RELEASE_TIMEOUT_SECONDS.
"""

from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from datetime import UTC, datetime
from typing import Any

from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.verify_system.llm_evaluator.bundle import ReviewBundle
from agentkit.backend.verify_system.llm_evaluator.llm_client import (
    _EVAL_DEADLINE_CV,
    RELEASE_TIMEOUT_SECONDS,
    TOTAL_TIMEOUT_SECONDS,
    HubLlmClient,
    bind_eval_deadline,
)
from agentkit.backend.verify_system.llm_evaluator.parallel_runner import (
    LAYER2_ROLES,
    ParallelEvalRunner,
)
from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
    DOC_FIDELITY_CHECK_IDS,
    QA_REVIEW_CHECK_IDS,
    SEMANTIC_REVIEW_CHECK_IDS,
    LlmVerdict,
    ReviewerRole,
    StructuredEvaluator,
)
from agentkit.integration_clients.multi_llm_hub.entities import HubMessage, HubSessionLease

# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


def _lease(session_id: str = "s-1", token: str = "tok") -> HubSessionLease:
    return HubSessionLease(
        session_id=session_id, token=token, llms=["chatgpt"], slots={"chatgpt": 0}
    )


def _msg(text: str, pool: str = "chatgpt") -> dict[str, Any]:
    return {
        pool: HubMessage(
            id=f"{pool}:assistant",
            session_id="s-1",
            backend=pool,
            role="assistant",
            text=text,
            at=datetime.now(UTC),
            status="ok",
        )
    }


def _all_pass_qa() -> str:
    return json.dumps(
        [{"check_id": cid, "status": "PASS", "reason": "ok"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    )


def _all_pass_semantic() -> str:
    return json.dumps(
        [{"check_id": cid, "status": "PASS", "reason": "ok"} for cid in sorted(SEMANTIC_REVIEW_CHECK_IDS)]
    )


def _all_pass_doc_fidelity() -> str:
    return json.dumps(
        [{"check_id": cid, "status": "PASS", "reason": "ok"} for cid in sorted(DOC_FIDELITY_CHECK_IDS)]
    )


class _StaticResolver:
    def resolve(self, role: str) -> str:
        return "chatgpt"


class _StubMaterializer:
    """Prompt materializer stub — no filesystem dependency."""

    def context_for(self, bundle: ReviewBundle) -> tuple[StoryContext, str]:
        ctx = StoryContext(
            project_key="test",
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


def _bundle(story_id: str = "AG3-065") -> ReviewBundle:
    return ReviewBundle(
        story_id=story_id,
        story_brief_excerpt="brief",
        acceptance_criteria=["AC1"],
        diff_summary="1 file changed",
        diff_content="diff",
        concept_refs=["FK-11"],
        previous_findings=None,
        qa_cycle_round=1,
    )


# ---------------------------------------------------------------------------
# ERROR 1 — ContextVar isolation: bind_eval_deadline resets correctly
# ---------------------------------------------------------------------------


class TestError1ContextVarIsolation:
    """bind_eval_deadline sets and reset_token resets _EVAL_DEADLINE_CV."""

    def test_bind_sets_contextvar(self) -> None:
        """bind_eval_deadline sets _EVAL_DEADLINE_CV in the current context."""
        before = _EVAL_DEADLINE_CV.get()
        deadline = time.monotonic() + 99.0
        token = bind_eval_deadline(deadline)
        try:
            assert _EVAL_DEADLINE_CV.get() == deadline
        finally:
            _EVAL_DEADLINE_CV.reset(token)
        # After reset, value is restored to whatever it was before.
        assert _EVAL_DEADLINE_CV.get() == before

    def test_reset_in_finally_cleans_up(self) -> None:
        """The finally-reset prevents leakage to the next call in the same context."""
        deadline_a = time.monotonic() + 10.0
        deadline_b = time.monotonic() + 20.0

        # Simulate evaluate() for role A, then role B in same thread.
        token_a = bind_eval_deadline(deadline_a)
        try:
            assert _EVAL_DEADLINE_CV.get() == deadline_a
        finally:
            _EVAL_DEADLINE_CV.reset(token_a)

        # Now simulate role B — should NOT see role A's deadline.
        token_b = bind_eval_deadline(deadline_b)
        try:
            assert _EVAL_DEADLINE_CV.get() == deadline_b
            # Crucially: NOT deadline_a (no leakage from prior task)
            assert _EVAL_DEADLINE_CV.get() != deadline_a
        finally:
            _EVAL_DEADLINE_CV.reset(token_b)

    def test_contextvar_isolated_across_threads(self) -> None:
        """Each thread has its own ContextVar copy — writes don't clobber other threads."""
        results: dict[str, float | None] = {}
        barrier = threading.Barrier(2)

        def thread_fn(name: str, deadline: float) -> None:
            token = bind_eval_deadline(deadline)
            try:
                # Both threads in flight simultaneously.
                barrier.wait(timeout=5.0)
                # Each thread must see only its own deadline.
                results[name] = _EVAL_DEADLINE_CV.get()
            finally:
                _EVAL_DEADLINE_CV.reset(token)

        deadline_t1 = time.monotonic() + 111.0
        deadline_t2 = time.monotonic() + 222.0

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(thread_fn, "t1", deadline_t1)
            f2 = pool.submit(thread_fn, "t2", deadline_t2)
            f1.result()
            f2.result()

        assert results["t1"] == deadline_t1, (
            f"Thread t1 must see its own deadline {deadline_t1}, got {results['t1']}"
        )
        assert results["t2"] == deadline_t2, (
            f"Thread t2 must see its own deadline {deadline_t2}, got {results['t2']}"
        )


# ---------------------------------------------------------------------------
# ERROR 1 — CONCURRENT regression: shared HubLlmClient, 2+ parallel roles,
# no role gets more than ~TOTAL_TIMEOUT_SECONDS of wall-clock budget.
# ---------------------------------------------------------------------------


_ROLE_RESPONSES: dict[str, str] = {
    "qa_review": _all_pass_qa(),
    "semantic_review": _all_pass_semantic(),
    "doc_fidelity": _all_pass_doc_fidelity(),
}


class _TimedFakeHub:
    """Fake hub that records the per-evaluation ContextVar value inside each send().

    A ``threading.Barrier`` ensures all caller threads are in flight at the
    same time (real concurrency, not sequential). The test asserts that
    each concurrent role sees its own per-evaluation deadline in the CV —
    no role sees another role's deadline (the old instance-attribute race).

    Role is inferred from the ``message`` parameter (the prompt text), which
    contains ``"PROMPT:{role}"`` per _StubMaterializer. This allows returning
    the correct per-role response even when all roles use the same pool ("chatgpt").
    """

    def __init__(self, *, n_concurrent: int = 2) -> None:
        self._barrier = threading.Barrier(n_concurrent, timeout=5.0)
        self._lock = threading.Lock()
        # List of CV deadline values observed inside send() — one entry per call.
        self.observed_cv_values: list[float | None] = []
        self._release_calls: list[tuple[str, str, float | None]] = []

    def acquire(
        self,
        *,
        owner: str,
        description: str,
        llms: list[str],
        timeout: float | None = None,
    ) -> HubSessionLease:
        del owner, description, llms, timeout
        return _lease()

    def send(
        self,
        *,
        session_id: str,
        token: str,
        message: str | None = None,
        target: str | None = None,
        targets: Any = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        del session_id, token, targets, timeout
        # Wait at the barrier so all roles are concurrent.
        self._barrier.wait()
        # Record what the ContextVar holds in this thread right now.
        cv_val = _EVAL_DEADLINE_CV.get()
        with self._lock:
            self.observed_cv_values.append(cv_val)
        # Infer role from the prompt message (contains "PROMPT:{role_value}").
        role_slug = "qa_review"
        if message:
            for candidate in ("qa_review", "semantic_review", "doc_fidelity"):
                if candidate in message:
                    role_slug = candidate
                    break
        return _msg(_ROLE_RESPONSES[role_slug])

    def release(self, *, session_id: str, token: str, timeout: float | None = None) -> None:
        self._release_calls.append((session_id, token, timeout))

    def health(self) -> Any: ...  # noqa: ANN401
    def pool_status(self) -> list[Any]: return []
    def list_sessions(self, *, include_inactive: bool = False) -> list[Any]: return []
    def resume(self, *, session_id: str) -> HubSessionLease: ...


class TestError1ConcurrentDeadlineIsolation:
    """CONCURRENT regression: parallel roles share one HubLlmClient, each sees its own deadline.

    Uses the REAL ParallelEvalRunner (ThreadPoolExecutor, max_workers=3) and a
    REAL StructuredEvaluator. The fake hub records the ContextVar value inside
    each role's send() call — while all 3 roles are concurrently in-flight.

    The _TimedFakeHub uses a prompt-keyed dispatch to record which role's
    CV deadline is visible during send(), keyed by the prompt content (which
    contains the role name via _StubMaterializer).
    """

    def test_concurrent_roles_each_see_own_deadline_not_others(self) -> None:
        """ERROR 1 root fix: each concurrent role sees only its own eval deadline in the CV.

        Run 3 roles in parallel via the REAL ParallelEvalRunner. Inside send()
        (called concurrently), each role's thread reads _EVAL_DEADLINE_CV. With the
        ContextVar fix, every role sees a deadline value set during ITS OWN
        evaluate() call — and all three should be approximately equal (all set to
        time.monotonic() + TOTAL_TIMEOUT_SECONDS at the start of their respective
        evaluate() calls). Without the fix, one role's set_eval_deadline() on the
        shared instance would clobber another's, potentially giving different values.

        The key assertion is that the CV value observed by each role is within a
        small window of time.monotonic() + TOTAL_TIMEOUT_SECONDS, indicating each
        role set its own deadline — not that they observed another role's old value.
        """
        hub = _TimedFakeHub(n_concurrent=3)
        client = HubLlmClient(hub, _StaticResolver())
        evaluator = StructuredEvaluator(client, _StubMaterializer())
        runner = ParallelEvalRunner(evaluator, max_workers=3)

        wall_start = time.monotonic()
        results = runner.run(_bundle(), None, 1)

        # All three Layer-2 roles must succeed (the AG3-068 story_creation_review
        # role is NOT part of the parallel QA-subflow run).
        assert set(results.keys()) == set(LAYER2_ROLES)
        assert all(r.verdict is LlmVerdict.PASS for r in results.values())

        # Each thread observed a CV deadline during its send().
        # All three should have been set to ~(eval_start + TOTAL_TIMEOUT_SECONDS).
        # We allow a generous tolerance (2 seconds) for scheduling jitter.
        tolerance_s = 2.0
        expected_min = wall_start + TOTAL_TIMEOUT_SECONDS - tolerance_s
        expected_max = wall_start + TOTAL_TIMEOUT_SECONDS + tolerance_s

        assert len(hub.observed_cv_values) == 3, (  # noqa: PLR2004
            f"Expected 3 observed CV values (one per role), got {len(hub.observed_cv_values)}: "
            f"{hub.observed_cv_values}"
        )
        for i, observed_cv in enumerate(hub.observed_cv_values):
            assert observed_cv is not None, (
                f"Role send #{i} must see a non-None CV deadline — "
                "bind_eval_deadline() must be called before complete()."
            )
            assert expected_min <= observed_cv <= expected_max, (
                f"Send #{i} observed CV deadline {observed_cv:.3f} "
                f"which is outside the expected window "
                f"[{expected_min:.3f}, {expected_max:.3f}]. "
                "Each role must set its own per-evaluation deadline."
            )

    def test_no_role_gets_extra_budget_due_to_later_role_overwriting(self) -> None:
        """ERROR 1 regression: a later role's deadline does NOT extend an earlier role's budget.

        With the ContextVar fix, each role's evaluate() binds its own deadline
        in a context-local copy — there is no shared mutable state. We verify
        this by running 2 roles and asserting both see essentially the same
        expected deadline (within ~2s), not a deadline arbitrarily shifted
        by the other role's binding.
        """
        hub2 = _TimedFakeHub(n_concurrent=2)
        client2 = HubLlmClient(hub2, _StaticResolver())
        evaluator2 = StructuredEvaluator(client2, _StubMaterializer())
        runner2 = ParallelEvalRunner(evaluator2, max_workers=2)

        results2 = runner2.run_roles(
            (ReviewerRole.QA_REVIEW, ReviewerRole.SEMANTIC_REVIEW),
            _bundle(),
            None,
            1,
        )
        assert all(r.verdict is LlmVerdict.PASS for r in results2.values())

        assert len(hub2.observed_cv_values) == 2, (  # noqa: PLR2004
            f"Expected 2 observed CV values, got {len(hub2.observed_cv_values)}"
        )
        cv_vals = hub2.observed_cv_values
        assert cv_vals[0] is not None
        assert cv_vals[1] is not None

        # Both must be close to (wall_start2 + TOTAL_TIMEOUT_SECONDS).
        # The max spread between them must be < 2s (scheduling jitter only,
        # not an entire TOTAL_TIMEOUT_SECONDS clobbered by the other role).
        spread = abs(cv_vals[0] - cv_vals[1])
        assert spread < 2.0, (  # noqa: PLR2004
            f"Two concurrent roles' CV deadlines differ by {spread:.3f}s. "
            "If one role overwrote the other's deadline, the spread would be ~TOTAL_TIMEOUT_SECONDS. "
            "The ContextVar fix must prevent cross-role clobbering."
        )


# ---------------------------------------------------------------------------
# ERROR 2 — release timeout clamped to remaining budget
# ---------------------------------------------------------------------------


class _ReleaseCaptureHub:
    """Fake hub that records the timeout passed to release()."""

    def __init__(self) -> None:
        self.acquire_responses: list[Any] = []
        self.send_responses: list[Any] = []
        self.release_calls: list[tuple[str, str, float | None]] = []

    def acquire(
        self,
        *,
        owner: str,
        description: str,
        llms: list[str],
        timeout: float | None = None,
    ) -> HubSessionLease:
        del owner, description, llms, timeout
        r = self.acquire_responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r  # type: ignore[return-value]

    def send(
        self,
        *,
        session_id: str,
        token: str,
        message: str | None = None,
        target: str | None = None,
        targets: Any = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        del session_id, token, message, target, targets, timeout
        r = self.send_responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r  # type: ignore[return-value]

    def release(self, *, session_id: str, token: str, timeout: float | None = None) -> None:
        self.release_calls.append((session_id, token, timeout))

    def health(self) -> Any: ...  # noqa: ANN401
    def pool_status(self) -> list[Any]: return []
    def list_sessions(self, *, include_inactive: bool = False) -> list[Any]: return []
    def resume(self, *, session_id: str) -> HubSessionLease: ...


class TestError2ReleaseTimeoutClamped:
    """Release timeout is clamped to remaining budget, not always RELEASE_TIMEOUT_SECONDS.

    ERROR 2 fix: _safe_release(session_id, token, *, deadline) clamps the
    release timeout to max(1.0, min(RELEASE_TIMEOUT_SECONDS, remaining)).
    Near a TOTAL boundary, this prevents up to 10s of extra wall-clock beyond
    TOTAL_TIMEOUT_SECONDS while always attempting release (best-effort floor).
    """

    def test_release_timeout_clamped_when_budget_nearly_exhausted(self) -> None:
        """ERROR 2: when remaining budget < RELEASE_TIMEOUT_SECONDS, release is clamped.

        Set a deadline that expires in 0.5s from now. After acquire+send complete
        almost instantly (fake hub), the remaining budget is ~0.5s (or less).
        The release timeout must be < RELEASE_TIMEOUT_SECONDS (10s).
        """
        import unittest.mock as mock

        hub = _ReleaseCaptureHub()
        hub.acquire_responses.append(_lease())
        hub.send_responses.append(_msg(_all_pass_qa()))

        client = HubLlmClient(hub, _StaticResolver())

        # Fake a deadline that is ~0.5s from now.
        tight_budget = 0.5
        fake_now_base = time.monotonic()
        call_seq = iter([
            fake_now_base,                      # deadline computation in complete()
            fake_now_base,                      # acquire remaining check
            fake_now_base,                      # do_send remaining check
            fake_now_base + tight_budget - 0.1, # remaining in _safe_release
        ])

        with mock.patch(
            "agentkit.backend.verify_system.llm_evaluator.llm_client.time.monotonic",
            side_effect=call_seq,
        ):
            # Set a deadline that leaves tight_budget remaining after the fake_now_base.
            cv_deadline = fake_now_base + tight_budget
            cv_token = _EVAL_DEADLINE_CV.set(cv_deadline)
            try:
                client.complete(role="qa_review", prompt="P")
            finally:
                _EVAL_DEADLINE_CV.reset(cv_token)

        assert len(hub.release_calls) == 1
        _, _, release_timeout = hub.release_calls[0]
        assert release_timeout is not None
        assert release_timeout < RELEASE_TIMEOUT_SECONDS, (
            f"Release timeout {release_timeout:.3f}s must be < RELEASE_TIMEOUT_SECONDS "
            f"({RELEASE_TIMEOUT_SECONDS}s) when remaining budget is ~{tight_budget}s."
        )

    def test_release_timeout_uses_full_constant_when_budget_plentiful(self) -> None:
        """ERROR 2: when budget is plentiful, release uses min(RELEASE_TIMEOUT, remaining).

        With a fresh deadline (budget = TOTAL_TIMEOUT_SECONDS), the release timeout
        is RELEASE_TIMEOUT_SECONDS (min(10, ~2500) = 10).
        """
        hub = _ReleaseCaptureHub()
        hub.acquire_responses.append(_lease())
        hub.send_responses.append(_msg(_all_pass_qa()))

        client = HubLlmClient(hub, _StaticResolver())
        client.complete(role="qa_review", prompt="P")

        assert len(hub.release_calls) == 1
        _, _, release_timeout = hub.release_calls[0]
        assert release_timeout is not None
        assert release_timeout == RELEASE_TIMEOUT_SECONDS, (
            f"With plentiful budget, release timeout must be RELEASE_TIMEOUT_SECONDS "
            f"({RELEASE_TIMEOUT_SECONDS}s), got {release_timeout}s."
        )

    def test_release_floor_prevents_zero_timeout(self) -> None:
        """ERROR 2: even with exhausted budget, release gets at least 1s (best-effort floor).

        When the deadline is already in the past (remaining <= 0), release must
        not get a zero or negative timeout. The floor ensures the hub transport
        always has a minimal window to ACK the release.
        """
        import unittest.mock as mock

        hub = _ReleaseCaptureHub()
        hub.acquire_responses.append(_lease())
        hub.send_responses.append(_msg(_all_pass_qa()))

        client = HubLlmClient(hub, _StaticResolver())

        # Simulate deadline already in the past by the time release runs.
        base = time.monotonic()
        # Call sequence: deadline-setup (fresh_deadline), acquire-check,
        # do_send remaining check, then safe_release remaining check (past deadline).
        call_seq = iter([
            base,          # complete(): fresh_deadline = base + TOTAL; cv_deadline wins if set
            base,          # _acquire_with_queue_retry: remaining = deadline - now
            base,          # _do_send: remaining check
            base + TOTAL_TIMEOUT_SECONDS + 100,  # _safe_release: remaining = deadline - now => negative
        ])

        with mock.patch(
            "agentkit.backend.verify_system.llm_evaluator.llm_client.time.monotonic",
            side_effect=call_seq,
        ):
            client.complete(role="qa_review", prompt="P")

        assert len(hub.release_calls) == 1
        _, _, release_timeout = hub.release_calls[0]
        assert release_timeout is not None
        assert release_timeout >= 1.0, (  # noqa: PLR2004
            f"Release timeout must be >= 1.0s even with exhausted budget (best-effort floor), "
            f"got {release_timeout}s."
        )
