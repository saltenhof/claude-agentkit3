"""Remediation tests for AG3-065 Codex hostile-review ERRORs 1-5.

Each test class covers exactly one ERROR with the fix proof required by the
review specification. Tests are kept to the LLM / Hub / ArtifactManager
boundary (the explicit Mock-Regel exception per story guardrails).

ERROR 1 -- TOTAL_TIMEOUT_SECONDS budget enforced end-to-end
ERROR 2 -- HubLoginRequiredError dispatched from _handle_send in routes.py
ERROR 3 -- rendered prompt + raw response persisted via ArtifactManager.write()
ERROR 4 -- one llm_call telemetry event emitted PER complete() attempt
ERROR 5 -- DialogueRunner uses ArtifactManager.write() (not write_raw)
"""

from __future__ import annotations

import json
import time
import unittest.mock as mock
import urllib.error
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from agentkit.backend.artifacts.envelope import ArtifactEnvelope
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.verify_system.llm_evaluator.dialogue_runner import DialogueRunner
from agentkit.backend.verify_system.llm_evaluator.llm_client import (
    ACQUIRE_TIMEOUT_SECONDS,
    SEND_TIMEOUT_SECONDS,
    TOTAL_TIMEOUT_SECONDS,
    HubLlmClient,
    LlmClientError,
    LoginRequiredError,
)
from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
    QA_REVIEW_CHECK_IDS,
    LlmVerdict,
    ReviewerRole,
    StructuredEvaluator,
    StructuredEvaluatorError,
)
from agentkit.integration_clients.multi_llm_hub.entities import HubMessage, HubSessionLease
from agentkit.integration_clients.multi_llm_hub.errors import (
    HubLoginRequiredError,
    HubUnavailableError,
)

# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


def _lease(session_id: str = "s-1", token: str = "tok") -> HubSessionLease:
    return HubSessionLease(
        session_id=session_id, token=token, llms=["chatgpt"], slots={"chatgpt": 0}
    )


def _msg(text: str, pool: str = "chatgpt", status: str = "ok") -> dict[str, Any]:
    return {
        pool: HubMessage(
            id=f"{pool}:assistant",
            session_id="s-1",
            backend=pool,
            role="assistant",
            text=text,
            at=datetime.now(UTC),
            status=status,
        )
    }


class _FakeHub:
    """Minimal scriptable HubClientProtocol double."""

    def __init__(self) -> None:
        self.acquire_responses: list[Any] = []
        self.send_responses: list[Any] = []
        self.release_calls: list[tuple[str, str]] = []
        self.acquire_calls: list[dict[str, Any]] = []
        self.send_calls: list[dict[str, Any]] = []
        self.send_timeouts: list[float | None] = []

    def acquire(
        self,
        *,
        owner: str,
        description: str,
        llms: list[str],
        timeout: float | None = None,
    ) -> HubSessionLease:
        self.acquire_calls.append({"owner": owner, "llms": llms, "timeout": timeout})
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
        self.send_calls.append({"session_id": session_id, "target": target})
        self.send_timeouts.append(timeout)
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


class _StubMaterializer:
    """Prompt materializer stub."""

    def context_for(self, bundle: Any) -> tuple[Any, str]:
        from agentkit.backend.story_context_manager.models import StoryContext
        from agentkit.backend.story_context_manager.types import StoryMode, StoryType

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


def _bundle(story_id: str = "AG3-065") -> Any:
    from agentkit.backend.verify_system.llm_evaluator.bundle import ReviewBundle

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
# ERROR 1 -- TOTAL_TIMEOUT_SECONDS budget enforced over the entire call
# ---------------------------------------------------------------------------


class TestError1TotalTimeoutBudget:
    """Total budget is enforced end-to-end; no second full send after near-exhaustion."""

    def test_deadline_passed_to_acquire(self) -> None:
        """ERROR 1: _acquire_with_queue_retry clamps acquire timeout to remaining budget."""
        hub = _FakeHub()
        hub.acquire_responses.append(_lease())
        hub.send_responses.append(_msg("OK"))

        client = HubLlmClient(hub, _StaticResolver())
        client.complete(role="qa_review", prompt="P")

        # acquire timeout must be <= ACQUIRE_TIMEOUT_SECONDS (clamped to remaining)
        acq_timeout = hub.acquire_calls[0]["timeout"]
        assert acq_timeout is not None
        assert acq_timeout <= ACQUIRE_TIMEOUT_SECONDS

    def test_deadline_passed_to_send(self) -> None:
        """ERROR 1: _do_send clamps send timeout to min(SEND_TIMEOUT, remaining)."""
        hub = _FakeHub()
        hub.acquire_responses.append(_lease())
        hub.send_responses.append(_msg("OK"))

        client = HubLlmClient(hub, _StaticResolver())
        client.complete(role="qa_review", prompt="P")

        send_timeout = hub.send_timeouts[0]
        assert send_timeout is not None
        assert send_timeout <= SEND_TIMEOUT_SECONDS

    def test_budget_exhausted_before_retry_send_raises(self) -> None:
        """ERROR 1: when remaining budget is insufficient for retry, fail-closed.

        A fake hub that consumes near-SEND_TIMEOUT on the first send leaves
        insufficient budget for the re-acquire+send retry -- the client must
        refuse the retry (fail-closed, LlmClientError) instead of starting a
        second full 2400s send.
        """
        hub = _FakeHub()
        hub.acquire_responses.append(_lease("s-1", "tok1"))
        hub.send_responses.append(HubUnavailableError("timeout"))

        client = HubLlmClient(hub, _StaticResolver())
        original_monotonic = time.monotonic
        call_count = 0

        def _fake_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            # First 3 calls (deadline setup + acquire checks): normal wall time.
            if call_count <= 3:
                return original_monotonic()
            # After send failure: report budget exhausted.
            return original_monotonic() + TOTAL_TIMEOUT_SECONDS + 100

        with (
            mock.patch(
                "agentkit.backend.verify_system.llm_evaluator.llm_client.time.monotonic",
                side_effect=_fake_monotonic,
            ),
            pytest.raises(LlmClientError) as exc_info,
        ):
            client.complete(role="qa_review", prompt="P")

        # Must fail-closed; no second full send attempted (budget refused the retry).
        assert len(hub.send_calls) <= 1
        msg = str(exc_info.value).lower()
        assert "total_timeout" in msg or "budget" in msg or "insufficient" in msg

    def test_budget_exhausted_in_acquire_retries(self) -> None:
        """ERROR 1: deadline enforced inside acquire retry loop.

        The first call to time.monotonic() (deadline = now + TOTAL) sets the
        deadline; every subsequent call returns a time far past the deadline so
        remaining <= 0 is detected inside _acquire_with_queue_retry on the
        first remaining-budget check, before the acquire attempt is made.
        """
        hub = _FakeHub()
        base_time = time.monotonic()
        # Call sequence:
        #   call 1 (in complete()): deadline = base_time + TOTAL  -> base_time
        #   call 2 (remaining check in _acquire): past deadline
        call_seq = iter([base_time, base_time + TOTAL_TIMEOUT_SECONDS + 100])

        with mock.patch(
            "agentkit.backend.verify_system.llm_evaluator.llm_client.time.monotonic",
            side_effect=call_seq,
        ):
            client = HubLlmClient(hub, _StaticResolver())
            with pytest.raises(LlmClientError) as exc_info:
                client.complete(role="qa_review", prompt="P")

        # No acquire was ever attempted (budget check fires first).
        assert len(hub.acquire_calls) == 0
        msg = str(exc_info.value).lower()
        assert "total_timeout" in msg or "exhausted" in msg or "budget" in msg

    def test_total_timeout_constant_is_2500(self) -> None:
        """ERROR 1: TOTAL_TIMEOUT_SECONDS == 2500 (FK-11 §11.6.1)."""
        assert TOTAL_TIMEOUT_SECONDS == 2500.0  # noqa: PLR2004


# ---------------------------------------------------------------------------
# ERROR 2 -- HubLoginRequiredError dispatched via routes._handle_send
# ---------------------------------------------------------------------------


class TestError2LoginRequiredRouteDispatch:
    """_handle_send must dispatch HubLoginRequiredError to hub_login_required, not hub_error."""

    def _make_routes(self, client: Any) -> Any:
        from agentkit.integration_clients.multi_llm_hub.http.routes import MultiLlmHubRoutes

        return MultiLlmHubRoutes(client=client)

    def test_send_login_required_yields_hub_login_required_code(self) -> None:
        """ERROR 2: HubLoginRequiredError on send -> error_code=hub_login_required."""
        mock_client = MagicMock()
        mock_client.send.side_effect = HubLoginRequiredError("login needed")

        routes = self._make_routes(mock_client)
        response = routes.handle_post(
            "/v1/hub/sessions/s-1/messages",
            {"token": "tok", "message": "hi"},
            "corr-1",
        )

        assert response is not None
        body = json.loads(response.body)
        assert body["error_code"] == "hub_login_required", (
            f"Expected hub_login_required, got {body['error_code']!r}. "
            "HubLoginRequiredError must NOT fall through to generic hub_error."
        )

    def test_send_login_required_status_500(self) -> None:
        """ERROR 2: hub_login_required returns HTTP 500 (canonical per FK-11 §11.2.3)."""
        mock_client = MagicMock()
        mock_client.send.side_effect = HubLoginRequiredError("needs login")

        routes = self._make_routes(mock_client)
        response = routes.handle_post(
            "/v1/hub/sessions/s-1/messages",
            {"token": "tok", "message": "hi"},
            "corr-1",
        )

        assert response is not None
        assert response.status_code == 500

    def test_send_login_required_not_hub_error_502(self) -> None:
        """ERROR 2: hub_login_required must NOT return 502 (which hub_error uses)."""
        mock_client = MagicMock()
        mock_client.send.side_effect = HubLoginRequiredError("login")

        routes = self._make_routes(mock_client)
        response = routes.handle_post(
            "/v1/hub/sessions/s-1/messages",
            {"token": "tok", "message": "hi"},
            "corr-1",
        )

        assert response is not None
        assert response.status_code != 502

    def test_send_hub_unavailable_still_hub_unavailable(self) -> None:
        """ERROR 2 backward-compat: HubUnavailableError still -> hub_unavailable (503)."""
        mock_client = MagicMock()
        mock_client.send.side_effect = HubUnavailableError("down")

        routes = self._make_routes(mock_client)
        response = routes.handle_post(
            "/v1/hub/sessions/s-1/messages",
            {"token": "tok", "message": "hi"},
            "corr-1",
        )

        assert response is not None
        body = json.loads(response.body)
        assert body["error_code"] == "hub_unavailable"

    def test_hub_llm_client_surfaces_login_required_error(self) -> None:
        """ERROR 2 end-to-end: route emits hub_login_required -> client raises LoginRequiredError."""
        from agentkit.integration_clients.multi_llm_hub.client import _hub_error_from_http_error

        # Simulate the route's hub_login_required response reaching the client.
        body = json.dumps({"error_code": "hub_login_required", "error": "login"}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        http_exc = urllib.error.HTTPError(
            url="http://hub/api", code=500, msg="", hdrs={}, fp=mock_resp  # type: ignore[arg-type]
        )
        http_exc.read = mock_resp.read

        hub_err = _hub_error_from_http_error(http_exc)
        assert isinstance(hub_err, HubLoginRequiredError), (
            f"Expected HubLoginRequiredError, got {type(hub_err).__name__!r}"
        )
        # And the HubLlmClient maps it to LoginRequiredError.
        hub = _FakeHub()
        hub.acquire_responses.append(HubLoginRequiredError("login needed"))
        client = HubLlmClient(hub, _StaticResolver())
        with pytest.raises(LoginRequiredError):
            client.complete(role="qa_review", prompt="P")


# ---------------------------------------------------------------------------
# ERROR 3 -- rendered prompt + raw response persisted via ArtifactManager.write()
# ---------------------------------------------------------------------------


class _CapturingManager:
    """ArtifactManager double that records write() calls.

    Uses isinstance(env, ArtifactEnvelope) at runtime so the import is not
    purely a type-annotation-only import and satisfies TCH rules.
    """

    def __init__(self) -> None:
        self.written: list[Any] = []

    def write(self, env: object) -> None:
        assert isinstance(env, ArtifactEnvelope), f"Expected ArtifactEnvelope, got {type(env)}"
        self.written.append(env)


class TestError3PromptAuditPersistence:
    """Full prompt+response must be persisted via ArtifactManager.write()."""

    def _evaluator(self, client: Any, manager: Any = None) -> StructuredEvaluator:
        return StructuredEvaluator(client, _StubMaterializer(), artifact_manager=manager)

    def test_prompt_and_response_persisted_via_write(self) -> None:
        """ERROR 3: rendered prompt + raw response appear in envelope.payload."""
        mgr = _CapturingManager()
        evaluator = self._evaluator(_ScriptedLlmClient(_all_pass_qa()), mgr)
        evaluator.evaluate(
            ReviewerRole.QA_REVIEW, _bundle(), None, 1, run_id="run-99", run_attempt=1
        )

        assert len(mgr.written) == 1
        env = mgr.written[0]
        assert env.payload is not None
        assert "rendered_prompt" in env.payload
        assert "raw_response" in env.payload
        assert str(env.payload["rendered_prompt"]).startswith("PROMPT:")
        assert env.payload["raw_response"]  # non-empty

    def test_story_id_and_run_id_in_envelope(self) -> None:
        """ERROR 3: envelope carries correct story_id, run_id, attempt, artifact_class."""
        mgr = _CapturingManager()
        evaluator = self._evaluator(_ScriptedLlmClient(_all_pass_qa()), mgr)
        evaluator.evaluate(
            ReviewerRole.QA_REVIEW,
            _bundle("AG3-065"),
            None,
            1,
            run_id="run-test",
            run_attempt=2,
        )

        env = mgr.written[0]
        assert env.story_id == "AG3-065"
        assert env.run_id == "run-test"
        assert env.attempt == 2
        assert env.artifact_class == ArtifactClass.PROMPT_AUDIT

    def test_no_artifact_manager_returns_result_without_error(self) -> None:
        """ERROR 3: no artifact_manager -> skipped cleanly (result still returned)."""
        evaluator = self._evaluator(_ScriptedLlmClient(_all_pass_qa()), None)
        result = evaluator.evaluate(ReviewerRole.QA_REVIEW, _bundle(), None, 1)
        assert result.verdict is LlmVerdict.PASS

    def test_no_run_id_skips_persistence(self) -> None:
        """ERROR 3: artifact_manager present but no run_id -> skipped (no write call)."""
        mgr = _CapturingManager()
        evaluator = self._evaluator(_ScriptedLlmClient(_all_pass_qa()), mgr)
        result = evaluator.evaluate(
            ReviewerRole.QA_REVIEW, _bundle(), None, 1, run_id=None
        )

        assert result.verdict is LlmVerdict.PASS
        assert len(mgr.written) == 0  # nothing persisted


# ---------------------------------------------------------------------------
# ERROR 4 -- per-call llm_call telemetry event emitted for EACH attempt
# ---------------------------------------------------------------------------


class _RecordingEmitter:
    """Captures emitted events."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def emit(self, event: Any) -> None:
        self.events.append(event)


class _MultiCallLlmClient:
    """Returns scripted responses per call."""

    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = list(responses)
        self.call_count = 0

    def complete(self, *, role: str, prompt: str) -> str:
        self.call_count += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r  # type: ignore[return-value]


def _sem_pass() -> str:
    return json.dumps([{"check_id": "systemic_adequacy", "status": "PASS", "reason": "ok"}])


def _llm_events(emitter: _RecordingEmitter) -> list[Any]:
    return [e for e in emitter.events if e.event_type.value == "llm_call"]


class TestError4PerCallTelemetry:
    """One llm_call event must be emitted per complete() attempt, including failures."""

    def test_two_attempts_two_events(self) -> None:
        """ERROR 4: parse fails on first -> retry -> 2 calls -> 2 llm_call events."""
        client = _MultiCallLlmClient(["NOT_JSON", _sem_pass()])
        emitter = _RecordingEmitter()
        evaluator = StructuredEvaluator(client, _StubMaterializer(), event_emitter=emitter)

        result = evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)

        assert result.verdict is LlmVerdict.PASS
        assert client.call_count == 2
        events = _llm_events(emitter)
        assert len(events) == 2, (
            f"Expected 2 llm_call events (one per attempt), got {len(events)}"
        )

    def test_both_attempts_fail_two_events(self) -> None:
        """ERROR 4: both parse attempts fail -> 2 complete() calls -> 2 llm_call events."""
        client = _MultiCallLlmClient(["NOT_JSON_1", "NOT_JSON_2"])
        emitter = _RecordingEmitter()
        evaluator = StructuredEvaluator(client, _StubMaterializer(), event_emitter=emitter)

        with pytest.raises(StructuredEvaluatorError):
            evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)

        events = _llm_events(emitter)
        assert len(events) == 2, (
            f"Expected 2 llm_call events for 2 failed parse attempts, got {len(events)}"
        )

    def test_transport_exception_emits_event(self) -> None:
        """ERROR 4: transport exception -> llm_call event with status='transport_error'."""
        client = _MultiCallLlmClient([LlmClientError("transport dead")])
        emitter = _RecordingEmitter()
        evaluator = StructuredEvaluator(client, _StubMaterializer(), event_emitter=emitter)

        with pytest.raises(LlmClientError):
            evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)

        events = _llm_events(emitter)
        assert len(events) == 1, (
            f"Expected 1 llm_call event even for transport exception, got {len(events)}"
        )
        assert events[0].payload["status"] == "transport_error"

    def test_retry_index_correct_in_events(self) -> None:
        """ERROR 4: retry field is 0 for first call, 1 for second."""
        client = _MultiCallLlmClient(["NOT_JSON", _sem_pass()])
        emitter = _RecordingEmitter()
        evaluator = StructuredEvaluator(client, _StubMaterializer(), event_emitter=emitter)
        evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)

        events = _llm_events(emitter)
        retries = [e.payload["retry"] for e in events]
        assert retries == [0, 1], f"Expected retry=[0, 1], got {retries}"

    def test_single_pass_emits_one_event(self) -> None:
        """ERROR 4: single successful attempt -> exactly 1 llm_call event."""
        client = _MultiCallLlmClient([_sem_pass()])
        emitter = _RecordingEmitter()
        evaluator = StructuredEvaluator(client, _StubMaterializer(), event_emitter=emitter)
        evaluator.evaluate(ReviewerRole.SEMANTIC_REVIEW, _bundle(), None, 1)

        events = _llm_events(emitter)
        assert len(events) == 1
        assert events[0].payload["status"] == "pass"
        assert events[0].payload["retry"] == 0


# ---------------------------------------------------------------------------
# ERROR 5 -- DialogueRunner uses ArtifactManager.write() (not write_raw)
# ---------------------------------------------------------------------------


class TestError5DialogueTranscriptWrite:
    """Transcript must be persisted via ArtifactManager.write() with full turns payload."""

    def _runner(self) -> tuple[DialogueRunner, _FakeHub]:
        hub = _FakeHub()
        return DialogueRunner(hub, _StaticResolver()), hub

    def test_transcript_persisted_via_write_with_all_turns(self) -> None:
        """ERROR 5: all turns (role/content/ts) appear in the envelope payload via write()."""
        mgr = _CapturingManager()
        runner, hub = self._runner()
        hub.acquire_responses.append(_lease())
        hub.send_responses.append(_msg("R1"))
        hub.send_responses.append(_msg("R2"))

        result = runner.run(
            role="qa_review",
            prompts=["P1", "P2"],
            artifact_manager=mgr,  # type: ignore[arg-type]
            story_id="AG3-065",
            run_id="run-test",
        )

        assert result.logging_status == "persisted"
        assert len(mgr.written) == 1
        env = mgr.written[0]
        assert env.payload is not None
        turns = env.payload["turns"]
        assert len(turns) == 4  # type: ignore[arg-type]
        assert turns[0]["role"] == "user"  # type: ignore[index]
        assert turns[0]["content"] == "P1"  # type: ignore[index]
        assert turns[1]["role"] == "assistant"  # type: ignore[index]
        assert turns[2]["role"] == "user"  # type: ignore[index]
        assert turns[3]["role"] == "assistant"  # type: ignore[index]
        # Every turn must have a ts field.
        for turn in turns:  # type: ignore[union-attr]
            assert "ts" in turn

    def test_write_raw_does_not_exist_on_real_api(self) -> None:
        """ERROR 5: ArtifactManager has no write_raw -- only write(ArtifactEnvelope)."""
        from agentkit.backend.artifacts import ArtifactManager

        assert not hasattr(ArtifactManager, "write_raw"), (
            "ArtifactManager.write_raw() must not exist -- real API is write(ArtifactEnvelope)."
        )

    def test_missing_artifact_manager_yields_skipped(self) -> None:
        """ERROR 5: absent ArtifactManager -> 'skipped' (clean, not 'error')."""
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

    def test_missing_story_id_yields_skipped(self) -> None:
        """ERROR 5: ArtifactManager present but no story_id -> 'skipped'."""
        mgr = _CapturingManager()
        runner, hub = self._runner()
        hub.acquire_responses.append(_lease())
        hub.send_responses.append(_msg("R"))

        result = runner.run(
            role="qa_review",
            prompts=["P"],
            artifact_manager=mgr,  # type: ignore[arg-type]
            story_id=None,  # missing
            run_id="run-test",
        )

        assert result.logging_status == "skipped"
        assert len(mgr.written) == 0


# ---------------------------------------------------------------------------
# Helper used in ERROR 3/4 tests
# ---------------------------------------------------------------------------


class _ScriptedLlmClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, *, role: str, prompt: str) -> str:
        del role, prompt
        return self.response
