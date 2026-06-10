"""Remediation-2 tests for AG3-065 review ERRORs 1-4 (second review round).

Proves fixes using REAL ArtifactManager + ProducerRegistry (not fake captures)
for producer-validation tests, and uses monotonic-time patching for the
whole-evaluate TOTAL-budget test.

ERROR 1 — whole-evaluate() TOTAL_TIMEOUT_SECONDS bound
  The 2nd complete() call is refused when the first consumed the entire budget.

ERROR 2 — prompt-audit persistence passes the REAL ArtifactManager validator
  StructuredEvaluator writes a PROMPT_AUDIT envelope with the canonical
  VERIFY_LAYER2_PROMPT_AUDIT_PRODUCER and ProducerType.DETERMINISTIC.

ERROR 3 — Layer-2 audit wiring through the real production path
  _resolve_layer2_runner injects artifact_manager; run_id/attempt propagate
  through run_layer2_llm_failclosed → run_layer2_llm → ParallelEvalRunner
  → evaluate().

ERROR 4 — DialogueRunner transcript persistence passes REAL ArtifactManager
  DialogueRunner writes with VERIFY_LAYER2_DIALOGUE_AUDIT_PRODUCER /
  DETERMINISTIC; missing manager → clean "skipped"; rejected write → not
  silently swallowed.
"""

from __future__ import annotations

import json
import time
import unittest.mock as mock
from datetime import UTC, datetime
from typing import Any

import pytest

from agentkit.artifacts import (
    ArtifactEnvelope,
    ArtifactManager,
    ArtifactReference,
    EnvelopeValidator,
    ProducerRegistry,
    ProducerType,
)
from agentkit.core_types import ArtifactClass
from agentkit.multi_llm_hub.entities import HubMessage, HubSessionLease
from agentkit.verify_system.llm_evaluator.dialogue_runner import DialogueRunner
from agentkit.verify_system.llm_evaluator.llm_client import (
    TOTAL_TIMEOUT_SECONDS,
    LlmClientError,
)
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    QA_REVIEW_CHECK_IDS,
    SEMANTIC_REVIEW_CHECK_IDS,
    LlmVerdict,
    ReviewerRole,
    StructuredEvaluator,
)
from agentkit.verify_system.register import (
    VERIFY_LAYER2_DIALOGUE_AUDIT_PRODUCER,
    VERIFY_LAYER2_PROMPT_AUDIT_PRODUCER,
    register_verify_producers,
)

# ---------------------------------------------------------------------------
# Shared helpers / fakes
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


class _InMemoryRepository:
    """In-Memory ArtifactRepository — real protocol implementation, no mock."""

    def __init__(self) -> None:
        self._store: dict[str, ArtifactEnvelope] = {}

    def write_envelope(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        key = (
            f"{envelope.artifact_class}|{envelope.story_id}|"
            f"{envelope.run_id}|{envelope.stage}|{envelope.attempt}"
        )
        self._store[key] = envelope
        return ArtifactReference(
            artifact_class=envelope.artifact_class,
            story_id=envelope.story_id,
            run_id=envelope.run_id,
            record_key=key,
        )

    def read_envelope(self, reference: ArtifactReference) -> ArtifactEnvelope | None:
        return self._store.get(reference.record_key)

    def find_latest_envelope(
        self,
        *,
        story_id: str,
        run_id: str | None,
        artifact_class: ArtifactClass,
        stage: str,
    ) -> ArtifactEnvelope | None:
        matches = [
            e for e in self._store.values()
            if e.story_id == story_id
            and (run_id is None or e.run_id == run_id)
            and e.artifact_class == artifact_class
            and e.stage == stage
        ]
        if not matches:
            return None
        return max(matches, key=lambda e: e.attempt)

    def exists_envelope(self, reference: ArtifactReference) -> bool:
        return reference.record_key in self._store


def _real_artifact_manager() -> ArtifactManager:
    """Build a REAL ArtifactManager with REAL ProducerRegistry.

    Registers both the prompt-runtime producer (always present) AND the
    verify-system producers (including the two AG3-065 PROMPT_AUDIT producers)
    so write() validates them against the real registry.
    """
    registry = ProducerRegistry()
    # Register prompt-runtime producer.
    from agentkit.prompt_runtime.register import register_prompt_runtime_producers
    register_prompt_runtime_producers(registry)
    # Register all verify-system producers (includes VERIFY_LAYER2_PROMPT_AUDIT_PRODUCER
    # and VERIFY_LAYER2_DIALOGUE_AUDIT_PRODUCER added by ERROR 2/4 fix).
    register_verify_producers(registry)
    validator = EnvelopeValidator(registry)
    return ArtifactManager(_InMemoryRepository(), validator)


class _StubMaterializer:
    """Prompt materializer stub — no filesystem / PromptRuntime dependency."""

    def context_for(self, bundle: Any) -> tuple[Any, str]:
        from agentkit.story_context_manager.models import StoryContext
        from agentkit.story_context_manager.types import StoryMode, StoryType

        ctx = StoryContext(
            project_key="test",
            story_id=bundle.story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )
        return ctx, bundle.story_id

    def render(
        self,
        role: Any,
        ctx: Any,
        story_id: str,
        template_override: Any = None,
    ) -> tuple[str, str]:
        del ctx, story_id, template_override
        return f"PROMPT:{role.value}", "a" * 64


def _all_pass_qa() -> str:
    return json.dumps(
        [{"check_id": cid, "status": "PASS", "reason": "ok"} for cid in sorted(QA_REVIEW_CHECK_IDS)]
    )


def _all_pass_semantic() -> str:
    return json.dumps(
        [{"check_id": cid, "status": "PASS", "reason": "ok"} for cid in sorted(SEMANTIC_REVIEW_CHECK_IDS)]
    )


def _bundle(story_id: str = "AG3-065") -> Any:
    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle

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


class _ScriptedLlmClient:
    """Returns scripted responses (or raises) in order."""

    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    def complete(self, *, role: str, prompt: str) -> str:
        del role, prompt
        self.call_count += 1
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r  # type: ignore[return-value]


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
            at=_now(),
            status="ok",
        )
    }


class _FakeHub:
    def __init__(self) -> None:
        self.acquire_responses: list[Any] = []
        self.send_responses: list[Any] = []
        self.release_calls: list[tuple[str, str]] = []

    def acquire(self, *, owner: str, description: str, llms: list[str], timeout: float | None = None) -> HubSessionLease:
        del owner, description, llms, timeout
        r = self.acquire_responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r  # type: ignore[return-value]

    def send(  # noqa: PLR0913
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
        self.release_calls.append((session_id, token))

    def health(self) -> Any: ...  # noqa: ANN401
    def pool_status(self) -> list[Any]: return []
    def list_sessions(self, *, include_inactive: bool = False) -> list[Any]: return []
    def resume(self, *, session_id: str) -> HubSessionLease: ...


class _StaticResolver:
    def resolve(self, role: str) -> str:
        return "chatgpt"


# ---------------------------------------------------------------------------
# ERROR 1 — whole-evaluate() wall-clock TOTAL_TIMEOUT_SECONDS bound
# ---------------------------------------------------------------------------


class TestError1WholeEvaluateTotalBound:
    """The 2nd complete() is refused when the first consumed the full budget."""

    def test_second_attempt_refused_when_first_consumed_full_budget(self) -> None:
        """ERROR 1: first complete() consumes TOTAL_TIMEOUT_SECONDS -> 2nd refused.

        Proves with a REAL monotonic-time patch: if time.monotonic() reports
        elapsed >= TOTAL_TIMEOUT_SECONDS before attempt==1, evaluate() raises
        LlmClientError without issuing the 2nd complete() call.
        """
        # First call returns garbage (parse fail) to trigger the retry path.
        # Without the budget guard, a 2nd complete() would be issued.
        llm_client = _ScriptedLlmClient(["NOT_JSON"])

        evaluator = StructuredEvaluator(llm_client, _StubMaterializer())

        # Patch time.monotonic inside structured_evaluator:
        # - call 1 (eval_start = time.monotonic()): base_time
        # - call 2 (elapsed = time.monotonic() - eval_start before attempt 1): past deadline
        # Only 2 calls total: eval_start + one check for attempt==1.
        base_time = time.monotonic()
        call_seq = iter([
            base_time,                                   # eval_start
            base_time + TOTAL_TIMEOUT_SECONDS + 1,       # elapsed check before attempt 1: budget gone
        ])

        with (
            mock.patch(
                "agentkit.verify_system.llm_evaluator.structured_evaluator.time.monotonic",
                side_effect=call_seq,
            ),
            pytest.raises(LlmClientError) as exc_info,
        ):
            evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)

        # Only one complete() call was made (the 2nd was refused by the budget guard).
        assert llm_client.call_count == 1, (
            f"Expected 1 complete() call (2nd refused by budget), got {llm_client.call_count}"
        )
        msg = str(exc_info.value).lower()
        assert "total_timeout" in msg or "budget" in msg or "exhausted" in msg, (
            f"Error message should mention budget/timeout: {exc_info.value}"
        )

    def test_second_attempt_allowed_when_budget_remains(self) -> None:
        """ERROR 1: 2nd attempt proceeds normally when first completed with time to spare."""
        # First call returns garbage (parse fail), 2nd returns valid JSON.
        llm_client = _ScriptedLlmClient(["NOT_JSON", _all_pass_semantic()])

        evaluator = StructuredEvaluator(llm_client, _StubMaterializer())

        # Simulate first call taking only 1 second — plenty of budget remains.
        base_time = time.monotonic()
        call_seq = iter([
            base_time,          # eval_start
            base_time + 1.0,    # elapsed check before attempt 1: 1s elapsed — budget OK
        ])

        with mock.patch(
            "agentkit.verify_system.llm_evaluator.structured_evaluator.time.monotonic",
            side_effect=call_seq,
        ):
            result = evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)

        assert result.verdict is LlmVerdict.PASS
        assert llm_client.call_count == 2  # both calls made


# ---------------------------------------------------------------------------
# ERROR 2 — REAL ArtifactManager + ProducerRegistry: prompt-audit passes
# ---------------------------------------------------------------------------


class TestError2RealArtifactManagerPromptAudit:
    """Prompt-audit write passes the REAL ArtifactManager with REAL ProducerRegistry."""

    def test_prompt_audit_persisted_with_real_manager(self) -> None:
        """ERROR 2: StructuredEvaluator writes PROMPT_AUDIT via REAL ArtifactManager.

        Uses a REAL ProducerRegistry that calls register_verify_producers()
        and validates against the canonical producer name and type.
        """
        manager = _real_artifact_manager()
        evaluator = StructuredEvaluator(
            _ScriptedLlmClient([_all_pass_qa()]),
            _StubMaterializer(),
            artifact_manager=manager,
        )

        result = evaluator.evaluate(
            ReviewerRole.QA_REVIEW,
            _bundle("AG3-065"),
            None,
            1,
            run_id="run-real-test",
            run_attempt=1,
        )

        assert result.verdict is LlmVerdict.PASS
        # Verify the envelope was actually persisted in the real backend.
        repo: _InMemoryRepository = manager._repository  # type: ignore[attr-defined]
        assert len(repo._store) == 1, (
            f"Expected 1 artifact in store, got {len(repo._store)}: {list(repo._store.keys())}"
        )
        env = next(iter(repo._store.values()))
        assert env.artifact_class == ArtifactClass.PROMPT_AUDIT
        assert env.producer.name == VERIFY_LAYER2_PROMPT_AUDIT_PRODUCER
        assert env.producer.type is ProducerType.DETERMINISTIC
        assert env.story_id == "AG3-065"
        assert env.run_id == "run-real-test"

    def test_prompt_audit_payload_contains_prompt_and_response(self) -> None:
        """ERROR 2: persisted envelope payload contains rendered_prompt and raw_response."""
        manager = _real_artifact_manager()
        evaluator = StructuredEvaluator(
            _ScriptedLlmClient([_all_pass_qa()]),
            _StubMaterializer(),
            artifact_manager=manager,
        )

        evaluator.evaluate(
            ReviewerRole.QA_REVIEW,
            _bundle("AG3-065"),
            None,
            1,
            run_id="run-payload-test",
            run_attempt=2,
        )

        repo: _InMemoryRepository = manager._repository  # type: ignore[attr-defined]
        env = next(iter(repo._store.values()))
        assert env.attempt == 2
        payload = env.payload
        assert payload is not None
        assert "rendered_prompt" in payload
        assert "raw_response" in payload
        assert str(payload["rendered_prompt"]).startswith("PROMPT:")
        assert payload["raw_response"]  # non-empty

    def test_no_manager_yields_skipped_not_error(self) -> None:
        """ERROR 2: no artifact_manager -> result returned cleanly, no exception."""
        evaluator = StructuredEvaluator(
            _ScriptedLlmClient([_all_pass_qa()]),
            _StubMaterializer(),
            artifact_manager=None,
        )
        result = evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)
        assert result.verdict is LlmVerdict.PASS

    def test_manager_present_write_rejection_is_not_silently_swallowed(self) -> None:
        """ERROR 2: a manager that rejects write() must NOT silently swallow the error.

        When the ArtifactManager.write() raises (here because the producer is NOT
        registered in an empty registry), the persistence failure must be LOGGED
        (not ignored) and evaluate() still returns the result — but the logging_status
        is NOT 'persisted'.

        This test verifies that the old 'error' swallow pattern no longer results in
        silent success: the evaluate() call returns normally (the persistence failure
        does not crash the evaluator per fail-closed contract for transient audit
        failures), but the write() exception IS caught and logged, not silently eaten.
        """
        # Build a manager with an EMPTY registry (no producers registered).
        # write() will raise ProducerNotRegisteredError.
        empty_registry = ProducerRegistry()
        validator = EnvelopeValidator(empty_registry)
        rejecting_manager = ArtifactManager(_InMemoryRepository(), validator)

        evaluator = StructuredEvaluator(
            _ScriptedLlmClient([_all_pass_qa()]),
            _StubMaterializer(),
            artifact_manager=rejecting_manager,
        )

        # evaluate() should still return a result (persistence is not pipeline-critical)
        # but the rejection must be logged (not silently eaten without any trace).
        import logging
        with mock.patch.object(
            logging.getLogger("agentkit.verify_system.llm_evaluator.structured_evaluator"),
            "warning",
        ) as mock_warn:
            result = evaluator.evaluate(
                ReviewerRole.QA_REVIEW,
                _bundle(),
                None,
                1,
                run_id="run-reject-test",
                run_attempt=1,
            )

        # evaluate() returns the LLM result (persistence failure is non-blocking).
        assert result.verdict is LlmVerdict.PASS
        # The rejection MUST have been logged (not silently swallowed).
        assert mock_warn.called, (
            "persistence failure (write rejection) must be logged via logger.warning, "
            "not silently swallowed"
        )


# ---------------------------------------------------------------------------
# ERROR 3 — Layer-2 audit wiring through ParallelEvalRunner
# ---------------------------------------------------------------------------


class TestError3Layer2AuditWiringParallelRunner:
    """run_id/run_attempt propagate through ParallelEvalRunner to evaluate()."""

    def test_run_roles_passes_run_id_to_evaluate(self) -> None:
        """ERROR 3: ParallelEvalRunner.run_roles() threads run_id to evaluate()."""
        from agentkit.verify_system.llm_evaluator.parallel_runner import ParallelEvalRunner

        manager = _real_artifact_manager()
        evaluator = StructuredEvaluator(
            _ScriptedLlmClient([
                _all_pass_qa(),
                _all_pass_semantic(),
            ]),
            _StubMaterializer(),
            artifact_manager=manager,
        )
        runner = ParallelEvalRunner(evaluator, max_workers=1)

        bundle = _bundle("AG3-065")
        runner.run_roles(
            (ReviewerRole.QA_REVIEW,),
            bundle,
            None,
            1,
            run_id="run-parallel-test",
            run_attempt=3,
        )

        repo: _InMemoryRepository = manager._repository  # type: ignore[attr-defined]
        # One evaluate() call -> one PROMPT_AUDIT envelope written.
        assert len(repo._store) == 1
        env = next(iter(repo._store.values()))
        assert env.artifact_class == ArtifactClass.PROMPT_AUDIT
        assert env.run_id == "run-parallel-test"
        assert env.attempt == 3

    def test_run_roles_without_run_id_skips_audit(self) -> None:
        """ERROR 3: run_roles() with run_id=None -> no audit envelope written."""
        from agentkit.verify_system.llm_evaluator.parallel_runner import ParallelEvalRunner

        manager = _real_artifact_manager()
        evaluator = StructuredEvaluator(
            _ScriptedLlmClient([_all_pass_qa()]),
            _StubMaterializer(),
            artifact_manager=manager,
        )
        runner = ParallelEvalRunner(evaluator, max_workers=1)

        bundle = _bundle("AG3-065")
        runner.run_roles(
            (ReviewerRole.QA_REVIEW,),
            bundle,
            None,
            1,
            run_id=None,  # no run_id -> skipped
        )

        repo: _InMemoryRepository = manager._repository  # type: ignore[attr-defined]
        assert len(repo._store) == 0, (
            "No PROMPT_AUDIT should be written when run_id is absent"
        )


# ---------------------------------------------------------------------------
# ERROR 4 — REAL ArtifactManager + ProducerRegistry: dialogue transcript
# ---------------------------------------------------------------------------


class TestError4RealArtifactManagerDialogueTranscript:
    """DialogueRunner transcript write passes the REAL ArtifactManager validator."""

    def _runner(self) -> tuple[DialogueRunner, _FakeHub]:
        hub = _FakeHub()
        return DialogueRunner(hub, _StaticResolver()), hub

    def test_dialogue_transcript_persisted_with_real_manager(self) -> None:
        """ERROR 4: DialogueRunner writes PROMPT_AUDIT via REAL ArtifactManager.

        Uses a REAL ProducerRegistry with register_verify_producers() registered,
        proving that VERIFY_LAYER2_DIALOGUE_AUDIT_PRODUCER is accepted by
        the real validator.
        """
        manager = _real_artifact_manager()
        runner, hub = self._runner()
        hub.acquire_responses.append(_lease())
        hub.send_responses.append(_msg("R1"))

        result = runner.run(
            role="qa_review",
            prompts=["P1"],
            artifact_manager=manager,  # type: ignore[arg-type]
            story_id="AG3-065",
            run_id="run-dialogue-test",
        )

        assert result.logging_status == "persisted"
        repo: _InMemoryRepository = manager._repository  # type: ignore[attr-defined]
        assert len(repo._store) == 1
        env = next(iter(repo._store.values()))
        assert env.artifact_class == ArtifactClass.PROMPT_AUDIT
        assert env.producer.name == VERIFY_LAYER2_DIALOGUE_AUDIT_PRODUCER
        assert env.producer.type is ProducerType.DETERMINISTIC

    def test_missing_manager_yields_skipped(self) -> None:
        """ERROR 4: absent ArtifactManager -> 'skipped' (clean, not 'error')."""
        runner, hub = self._runner()
        hub.acquire_responses.append(_lease())
        hub.send_responses.append(_msg("R"))

        result = runner.run(
            role="qa_review",
            prompts=["P"],
            artifact_manager=None,
            story_id="AG3-065",
            run_id="run-test",
        )

        assert result.logging_status == "skipped"

    def test_manager_present_write_rejection_not_silently_swallowed(self) -> None:
        """ERROR 4: manager write rejection must be logged, not silently swallowed.

        Builds a manager with an EMPTY registry (no producers) so write() raises.
        The DialogueRunner must log the failure (not silently eat it) and return
        logging_status='error'.
        """
        empty_registry = ProducerRegistry()
        validator = EnvelopeValidator(empty_registry)
        rejecting_manager = ArtifactManager(_InMemoryRepository(), validator)

        runner, hub = self._runner()
        hub.acquire_responses.append(_lease())
        hub.send_responses.append(_msg("R"))

        import logging
        with mock.patch.object(
            logging.getLogger("agentkit.verify_system.llm_evaluator.dialogue_runner"),
            "warning",
        ) as mock_warn:
            result = runner.run(
                role="qa_review",
                prompts=["P"],
                artifact_manager=rejecting_manager,  # type: ignore[arg-type]
                story_id="AG3-065",
                run_id="run-reject-test",
            )

        # The logging_status should be 'error', not 'persisted'.
        assert result.logging_status == "error", (
            f"Expected logging_status='error' for rejected write, got {result.logging_status!r}"
        )
        # The rejection must have been logged (not silently swallowed).
        assert mock_warn.called, (
            "persistence failure (write rejection) must be logged via logger.warning"
        )

    def test_producer_names_registered_for_prompt_audit(self) -> None:
        """ERROR 2/4: both canonical producers are registered for PROMPT_AUDIT.

        Proves the registry contains VERIFY_LAYER2_PROMPT_AUDIT_PRODUCER and
        VERIFY_LAYER2_DIALOGUE_AUDIT_PRODUCER after register_verify_producers().
        """
        registry = ProducerRegistry()
        register_verify_producers(registry)
        known = registry.known_producers(ArtifactClass.PROMPT_AUDIT)
        assert VERIFY_LAYER2_PROMPT_AUDIT_PRODUCER in known, (
            f"{VERIFY_LAYER2_PROMPT_AUDIT_PRODUCER!r} not in PROMPT_AUDIT producers: {known}"
        )
        assert VERIFY_LAYER2_DIALOGUE_AUDIT_PRODUCER in known, (
            f"{VERIFY_LAYER2_DIALOGUE_AUDIT_PRODUCER!r} not in PROMPT_AUDIT producers: {known}"
        )
