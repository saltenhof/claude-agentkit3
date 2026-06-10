"""Unit tests for AG3-065: HubLlmClient adapter, error protocol, timeouts.

AC1, AC2, AC3 (hub-llm-client level), AC5 (prompt template contract),
AC6 (fail-closed observable), AC7 (DialogueRunner), AC8 (per-op timeout constants),
AC9 (logging/telemetry), AC10 (login/pool unreachable).

All tests use fake Hub/resolver doubles (the LLM boundary is the explicit Mock-Regel
exception per story guardrails — only LLM/Hub boundary is faked).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.multi_llm_hub.entities import HubMessage, HubSessionLease
from agentkit.multi_llm_hub.errors import (
    HubAcquireQueuedError,
    HubLoginRequiredError,
    HubSessionNotFoundError,
    HubUnavailableError,
)
from agentkit.verify_system.llm_evaluator.dialogue_runner import (
    DialogueResult,
    DialogueRunner,
)
from agentkit.verify_system.llm_evaluator.llm_client import (
    ACQUIRE_TIMEOUT_SECONDS,
    MAX_ACQUIRE_RETRIES,
    RELEASE_TIMEOUT_SECONDS,
    SEND_TIMEOUT_SECONDS,
    TOTAL_TIMEOUT_SECONDS,
    FailClosedLlmClient,
    HubLlmClient,
    LlmClientError,
    LoginRequiredError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeHubTransport:
    """Records calls with timeouts, returns scripted responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | None, float | None]] = []
        self.responses: list[dict[str, object] | Exception] = []

    def add_response(self, r: dict[str, object] | Exception) -> None:
        self.responses.append(r)

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, object]:
        payload_dict = dict(payload) if payload is not None else None
        self.calls.append((method, path, payload_dict, timeout))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class _FakeHub:
    """Minimal fake HubClientProtocol for unit tests."""

    def __init__(self) -> None:
        self.acquire_responses: list[object | Exception] = []
        self.send_responses: list[dict[str, object] | Exception] = []
        self.release_calls: list[tuple[str, str, float | None]] = []
        self.acquire_calls: list[tuple[str, str, list[str], float | None]] = []
        self.send_calls: list[tuple[str, str, str | None, str | None, float | None]] = []

    def _make_lease(self, session_id: str = "s-1", token: str = "tok") -> HubSessionLease:
        return HubSessionLease(session_id=session_id, token=token, llms=["chatgpt"], slots={"chatgpt": 0})

    def acquire(
        self,
        *,
        owner: str,
        description: str,
        llms: list[str],
        timeout: float | None = None,
    ) -> HubSessionLease:
        self.acquire_calls.append((owner, description, llms, timeout))
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
        targets: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]:
        self.send_calls.append((session_id, token, message, target, timeout))
        r = self.send_responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r  # type: ignore[return-value]

    def release(self, *, session_id: str, token: str, timeout: float | None = None) -> None:
        self.release_calls.append((session_id, token, timeout))

    def health(self) -> object: ...
    def pool_status(self) -> list[object]: return []
    def list_sessions(self, *, include_inactive: bool = False) -> list[object]: return []
    def resume(self, *, session_id: str) -> HubSessionLease: ...


class _StaticResolver:
    """Always resolves to a fixed pool."""

    def __init__(self, pool: str = "chatgpt") -> None:
        self._pool = pool

    def resolve(self, role: str) -> str:
        return self._pool


class _FailingResolver:
    """Always raises LlmClientError (no pool for any role)."""

    def resolve(self, role: str) -> str:
        raise LlmClientError(f"No pool configured for role={role!r}")


def _chat_response(text: str) -> dict[str, object]:
    msg = HubMessage(
        id="s-1:chatgpt:assistant",
        session_id="s-1",
        backend="chatgpt",
        role="assistant",
        text=text,
        at=datetime.now(UTC),
        status="ok",
    )
    return {"chatgpt": msg}


def _error_response(text: str) -> dict[str, object]:
    msg = HubMessage(
        id="s-1:chatgpt:assistant",
        session_id="s-1",
        backend="chatgpt",
        role="assistant",
        text=text,
        at=datetime.now(UTC),
        status="error",
    )
    return {"chatgpt": msg}


# ---------------------------------------------------------------------------
# AC1: HubLlmClient exists and complete() works (acquire→send→release)
# ---------------------------------------------------------------------------


def test_hub_llm_client_complete_happy_path() -> None:
    """AC1: complete() → acquire/send/release, returns raw response text."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("RESPONSE_TEXT"))
    client = HubLlmClient(hub, _StaticResolver("chatgpt"))

    result = client.complete(role="qa_review", prompt="PROMPT")

    assert result == "RESPONSE_TEXT"
    assert len(hub.acquire_calls) == 1
    assert len(hub.send_calls) == 1
    assert len(hub.release_calls) == 1  # release in finally


# ---------------------------------------------------------------------------
# AC2: Routing via resolver (no pool → fail-closed)
# ---------------------------------------------------------------------------


def test_hub_llm_client_no_resolver_raises_llm_client_error() -> None:
    """AC2: failing resolver → LlmClientError (fail-closed, no default pool)."""
    hub = _FakeHub()
    client = HubLlmClient(hub, _FailingResolver())

    with pytest.raises(LlmClientError):
        client.complete(role="qa_review", prompt="PROMPT")


def test_hub_llm_client_injects_pool_from_resolver() -> None:
    """AC2: HubLlmClient uses resolver.resolve(role) to pick pool."""
    class _RoleTrackingResolver:
        def __init__(self) -> None:
            self.resolved: list[str] = []

        def resolve(self, role: str) -> str:
            self.resolved.append(role)
            return "gemini"

    hub = _FakeHub()
    resolver = _RoleTrackingResolver()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("R"))

    # Patch send to return gemini key
    gemini_msg = HubMessage(
        id="s-1:gemini:assistant", session_id="s-1", backend="gemini",
        role="assistant", text="R", at=datetime.now(UTC), status="ok"
    )
    hub.send_responses.clear()
    hub.send_responses.append({"gemini": gemini_msg})

    client = HubLlmClient(hub, resolver)
    client.complete(role="semantic_review", prompt="P")

    assert resolver.resolved == ["semantic_review"]
    # target should be "gemini" in the send call
    _, _, _, target, _ = hub.send_calls[0]
    assert target == "gemini"


# ---------------------------------------------------------------------------
# AC3a: Release in every exit (success/error)
# ---------------------------------------------------------------------------


def test_hub_llm_client_release_on_send_error() -> None:
    """AC3a: release called in finally even when send raises."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(HubUnavailableError("hub down"))
    hub.send_responses.append(HubUnavailableError("hub down 2"))  # for retry
    # Give enough acquire responses for retry
    hub.acquire_responses.append(hub._make_lease("s-2", "tok2"))
    client = HubLlmClient(hub, _StaticResolver("chatgpt"))

    with pytest.raises(LlmClientError):
        client.complete(role="qa_review", prompt="P")

    # At least one release must have been called
    assert len(hub.release_calls) >= 1


def test_hub_llm_client_release_on_success() -> None:
    """AC3a: release called even on success."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("OK"))
    client = HubLlmClient(hub, _StaticResolver("chatgpt"))

    client.complete(role="qa_review", prompt="P")

    assert len(hub.release_calls) == 1


# ---------------------------------------------------------------------------
# AC3b: Send-timeout → 1 retry with new slot (2 acquires)
# ---------------------------------------------------------------------------


def test_hub_llm_client_send_timeout_retries_with_new_slot() -> None:
    """AC3b: first send UnavailableError → release + new acquire + second send → PASS."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease("s-1", "tok1"))
    hub.acquire_responses.append(hub._make_lease("s-2", "tok2"))
    hub.send_responses.append(HubUnavailableError("timeout"))
    hub.send_responses.append(_chat_response("RETRY_OK"))
    client = HubLlmClient(hub, _StaticResolver("chatgpt"))

    result = client.complete(role="qa_review", prompt="P")

    assert result == "RETRY_OK"
    assert len(hub.acquire_calls) == 2  # two acquires assertiert


# ---------------------------------------------------------------------------
# AC3c: Also second send fails → LlmClientError, no third attempt
# ---------------------------------------------------------------------------


def test_hub_llm_client_second_send_timeout_raises_no_third_attempt() -> None:
    """AC3c: both sends fail → LlmClientError, call count ≤ 2 sends."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease("s-1", "tok1"))
    hub.acquire_responses.append(hub._make_lease("s-2", "tok2"))
    hub.send_responses.append(HubUnavailableError("timeout1"))
    hub.send_responses.append(HubUnavailableError("timeout2"))
    client = HubLlmClient(hub, _StaticResolver("chatgpt"))

    with pytest.raises(LlmClientError):
        client.complete(role="qa_review", prompt="P")

    assert len(hub.send_calls) == 2  # ≤ 2 sends on transport level


# ---------------------------------------------------------------------------
# AC3d: Queued-acquire — HubLlmClient-level (success after queue wait)
# ---------------------------------------------------------------------------


def test_hub_llm_client_queued_acquire_retries_and_succeeds() -> None:
    """AC3e: HubAcquireQueuedError → re-acquire with same owner; success within 5."""
    hub = _FakeHub()
    # Queued twice, then granted
    hub.acquire_responses.append(HubAcquireQueuedError("queued", estimated_wait_seconds=0.0))
    hub.acquire_responses.append(HubAcquireQueuedError("queued", estimated_wait_seconds=0.0))
    hub.acquire_responses.append(hub._make_lease("s-3", "tok3"))
    hub.send_responses.append(_chat_response("SUCCESS"))

    import unittest.mock as mock
    with mock.patch("agentkit.verify_system.llm_evaluator.llm_client.time.sleep"):
        client = HubLlmClient(hub, _StaticResolver("chatgpt"))
        result = client.complete(role="qa_review", prompt="P")

    assert result == "SUCCESS"
    # All acquire calls have the same owner
    owners = [c[0] for c in hub.acquire_calls]
    assert len(set(owners)) == 1  # same owner across all retries


def test_hub_llm_client_queued_exhaustion_raises_llm_client_error() -> None:
    """AC3f: always queued → after MAX_ACQUIRE_RETRIES=5 → LlmClientError."""
    hub = _FakeHub()
    for _ in range(MAX_ACQUIRE_RETRIES + 2):
        hub.acquire_responses.append(HubAcquireQueuedError("q", estimated_wait_seconds=0.0))

    import unittest.mock as mock
    with mock.patch("agentkit.verify_system.llm_evaluator.llm_client.time.sleep"):
        client = HubLlmClient(hub, _StaticResolver("chatgpt"))
        with pytest.raises(LlmClientError):
            client.complete(role="qa_review", prompt="P")

    assert len(hub.acquire_calls) == MAX_ACQUIRE_RETRIES  # exactly 5, no 6th


# ---------------------------------------------------------------------------
# AC3h: lease_expired/session-not-found → 1 re-acquire + second send
# ---------------------------------------------------------------------------


def test_hub_llm_client_lease_expired_triggers_reacquire_and_second_send() -> None:
    """AC3h: HubSessionNotFoundError on send → 1 new acquire + 1 second send (PASS)."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease("s-1", "tok1"))
    hub.acquire_responses.append(hub._make_lease("s-2", "tok2"))
    hub.send_responses.append(HubSessionNotFoundError("lease expired"))
    hub.send_responses.append(_chat_response("AFTER_REACQUIRE"))

    client = HubLlmClient(hub, _StaticResolver("chatgpt"))
    result = client.complete(role="qa_review", prompt="P")

    assert result == "AFTER_REACQUIRE"
    assert len(hub.acquire_calls) == 2  # re-acquire assertiert


def test_hub_llm_client_lease_expired_second_send_also_fails() -> None:
    """AC3h: second send after reacquire also fails → LlmClientError, no third."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease("s-1", "tok1"))
    hub.acquire_responses.append(hub._make_lease("s-2", "tok2"))
    hub.send_responses.append(HubSessionNotFoundError("lease expired"))
    hub.send_responses.append(HubSessionNotFoundError("still expired"))

    client = HubLlmClient(hub, _StaticResolver("chatgpt"))
    with pytest.raises(LlmClientError):
        client.complete(role="qa_review", prompt="P")

    assert len(hub.send_calls) == 2  # at most 2 sends


# ---------------------------------------------------------------------------
# AC10a: Pool unreachable → LlmClientError (fail-closed)
# ---------------------------------------------------------------------------


def test_hub_llm_client_pool_unreachable_raises_llm_client_error() -> None:
    """AC10a: HubUnavailableError from acquire → LlmClientError (fail-closed)."""
    hub = _FakeHub()
    hub.acquire_responses.append(HubUnavailableError("pool unreachable"))

    client = HubLlmClient(hub, _StaticResolver("chatgpt"))
    with pytest.raises(LlmClientError):
        client.complete(role="qa_review", prompt="P")


# ---------------------------------------------------------------------------
# AC10b: Login error → LoginRequiredError (distinct, backward-compat)
# ---------------------------------------------------------------------------


def test_hub_llm_client_login_required_raises_login_required_error() -> None:
    """AC10b: HubLoginRequiredError → LoginRequiredError with operator_hint."""
    hub = _FakeHub()
    hub.acquire_responses.append(HubLoginRequiredError("login required for chatgpt"))

    client = HubLlmClient(hub, _StaticResolver("chatgpt"))

    with pytest.raises(LoginRequiredError) as exc_info:
        client.complete(role="qa_review", prompt="P")

    assert exc_info.value.operator_hint  # non-empty hint
    assert "chatgpt" in exc_info.value.operator_hint


def test_login_required_error_is_llm_client_error_subclass() -> None:
    """AC10b: LoginRequiredError IS-A LlmClientError (backward-compat for catches)."""
    err = LoginRequiredError("test", operator_hint="pool=x: login required")
    assert isinstance(err, LlmClientError)


def test_login_required_caught_as_llm_client_error_blocks() -> None:
    """AC10b: existing code catching LlmClientError still blocks (backward-compat)."""
    hub = _FakeHub()
    hub.acquire_responses.append(HubLoginRequiredError("login needed"))

    client = HubLlmClient(hub, _StaticResolver("chatgpt"))
    caught: LlmClientError | None = None
    try:
        client.complete(role="qa_review", prompt="P")
    except LlmClientError as e:
        caught = e

    assert caught is not None, "LlmClientError must be raised (backward-compat fail-closed)"
    assert isinstance(caught, LoginRequiredError), "Distinct type is preserved"


# ---------------------------------------------------------------------------
# AC1: no-resolver → FailClosedLlmClient stays active (composition-root)
# ---------------------------------------------------------------------------


def test_fail_closed_client_remains_default_without_resolver() -> None:
    """AC1/AC9 composition: FailClosedLlmClient raises LlmClientError (no HubLlmClient default)."""
    client = FailClosedLlmClient()
    with pytest.raises(LlmClientError):
        client.complete(role="qa_review", prompt="P")


# ---------------------------------------------------------------------------
# AC8: Per-operation timeout constants
# ---------------------------------------------------------------------------


def test_per_operation_timeout_constants_are_correct() -> None:
    """AC8: named constants match FK-11 §11.6.1 spec values."""
    assert ACQUIRE_TIMEOUT_SECONDS == 30.0  # noqa: PLR2004
    assert SEND_TIMEOUT_SECONDS == 2400.0  # noqa: PLR2004
    assert RELEASE_TIMEOUT_SECONDS == 10.0  # noqa: PLR2004
    assert TOTAL_TIMEOUT_SECONDS == 2500.0  # noqa: PLR2004


def test_hub_llm_client_passes_distinct_timeouts_to_transport() -> None:
    """AC8: HubLlmClient passes acquire/send/release distinct timeout values."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("R"))
    client = HubLlmClient(hub, _StaticResolver("chatgpt"))
    client.complete(role="qa_review", prompt="P")

    # acquire timeout
    _, _, _, acquire_timeout = hub.acquire_calls[0]
    assert acquire_timeout == ACQUIRE_TIMEOUT_SECONDS

    # send timeout
    _, _, _, _, send_timeout = hub.send_calls[0]
    assert send_timeout == SEND_TIMEOUT_SECONDS

    # release timeout
    _, _, release_timeout = hub.release_calls[0]
    assert release_timeout == RELEASE_TIMEOUT_SECONDS

    # All three are distinct
    assert acquire_timeout != send_timeout
    assert send_timeout != release_timeout


def test_hub_llm_client_acquire_send_release_timeouts_differ() -> None:
    """AC8: acquire (30s) ≠ send (2400s) ≠ release (10s) — all distinct."""
    assert ACQUIRE_TIMEOUT_SECONDS != SEND_TIMEOUT_SECONDS
    assert SEND_TIMEOUT_SECONDS != RELEASE_TIMEOUT_SECONDS
    assert ACQUIRE_TIMEOUT_SECONDS != RELEASE_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# AC7: DialogueRunner — multi-turn, max_turns, release on error, no auto-FAIL
# ---------------------------------------------------------------------------


def test_dialogue_runner_basic_turn() -> None:
    """AC7: DialogueRunner runs a single prompt and returns a transcript."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("RESPONSE"))

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    result = runner.run(role="qa_review", prompts=["Hello"])

    assert isinstance(result, DialogueResult)
    assert result.turn_count == 1
    assert len(result.transcript) == 2  # user + assistant
    user_turn = result.transcript[0]
    assistant_turn = result.transcript[1]
    assert user_turn.role == "user"
    assert user_turn.content == "Hello"
    assert assistant_turn.role == "assistant"
    assert assistant_turn.content == "RESPONSE"


def test_dialogue_runner_max_turns_limit() -> None:
    """AC7: max_turns bounds the number of turns (hard upper bound)."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    # Add more send responses than max_turns
    for i in range(5):
        hub.send_responses.append(_chat_response(f"R{i}"))

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"), max_turns=2)
    result = runner.run(role="qa_review", prompts=["P1", "P2", "P3", "P4", "P5"])

    assert result.turn_count == 2  # bounded by max_turns


def test_dialogue_runner_release_on_error() -> None:
    """AC7: release called in finally even when send raises."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(HubUnavailableError("boom"))

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    with pytest.raises(LlmClientError):
        runner.run(role="qa_review", prompts=["P"])

    assert len(hub.release_calls) == 1


def test_dialogue_runner_no_schema_validation() -> None:
    """AC7: DialogueRunner does NOT validate JSON schema or auto-FAIL."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("not json at all, free text"))

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    # Should NOT raise StructuredEvaluatorError
    result = runner.run(role="qa_review", prompts=["P"])

    assert result.turn_count == 1
    assert result.transcript[1].content == "not json at all, free text"


def test_dialogue_runner_ordered_transcript() -> None:
    """AC7: transcript is ordered (user then assistant, per turn, in order)."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("R1"))
    hub.send_responses.append(_chat_response("R2"))

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    result = runner.run(role="qa_review", prompts=["P1", "P2"])

    roles = [t.role for t in result.transcript]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert result.transcript[0].content == "P1"
    assert result.transcript[1].content == "R1"
    assert result.transcript[2].content == "P2"
    assert result.transcript[3].content == "R2"


def test_dialogue_runner_no_artifact_manager_returns_skipped() -> None:
    """AC7: missing ArtifactManager → logging_status='skipped' (not error)."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("R"))

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    result = runner.run(role="qa_review", prompts=["P"], artifact_manager=None)

    assert result.logging_status == "skipped"


def test_dialogue_runner_transcript_is_frozen_tuple() -> None:
    """AC7: DialogueResult.transcript is a frozen tuple (immutable)."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("R"))

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    result = runner.run(role="qa_review", prompts=["P"])

    assert isinstance(result.transcript, tuple)
    assert isinstance(result, DialogueResult)
    # Pydantic v2 frozen model raises ValidationError on mutation attempts
    from pydantic import ValidationError
    with pytest.raises((ValidationError, TypeError)):
        result.turn_count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC3 MAX_ACQUIRE_RETRIES constant
# ---------------------------------------------------------------------------


def test_max_acquire_retries_is_five() -> None:
    """AC3 FK-11 §11.6.1: MAX_ACQUIRE_RETRIES = 5."""
    assert MAX_ACQUIRE_RETRIES == 5  # noqa: PLR2004


# ---------------------------------------------------------------------------
# AC6: fail-closed observable — evaluate() propagates exception
# ---------------------------------------------------------------------------


def test_hub_llm_client_transport_failure_propagates_llm_client_error() -> None:
    """AC6: LlmClientError propagates from complete() (no swallowing)."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(HubUnavailableError("down"))
    hub.send_responses.append(HubUnavailableError("still down"))
    hub.acquire_responses.append(hub._make_lease("s-2", "tok2"))

    client = HubLlmClient(hub, _StaticResolver("chatgpt"))

    with pytest.raises(LlmClientError):
        client.complete(role="qa_review", prompt="P")


# ---------------------------------------------------------------------------
# DialogueRunner — error path coverage (AC7 extras)
# ---------------------------------------------------------------------------


def test_dialogue_runner_acquire_queued_then_succeeds() -> None:
    """AC7: DialogueRunner._acquire_session also retries on HubAcquireQueuedError."""
    hub = _FakeHub()
    hub.acquire_responses.append(HubAcquireQueuedError("q", estimated_wait_seconds=0.0))
    hub.acquire_responses.append(hub._make_lease("s-1", "tok1"))
    hub.send_responses.append(_chat_response("R"))

    import unittest.mock as mock
    with mock.patch("agentkit.verify_system.llm_evaluator.dialogue_runner.time.sleep"):
        runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
        result = runner.run(role="qa_review", prompts=["P"])

    assert result.turn_count == 1


def test_dialogue_runner_acquire_login_required_raises() -> None:
    """AC7: DialogueRunner._acquire_session raises LoginRequiredError on hub login."""
    hub = _FakeHub()
    hub.acquire_responses.append(HubLoginRequiredError("login needed"))

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    with pytest.raises(LlmClientError):
        runner.run(role="qa_review", prompts=["P"])


def test_dialogue_runner_acquire_hub_error_raises_llm_client_error() -> None:
    """AC7: general MultiLlmHubError on acquire → LlmClientError."""
    from agentkit.multi_llm_hub.errors import MultiLlmHubError
    hub = _FakeHub()
    hub.acquire_responses.append(MultiLlmHubError("generic error"))

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    with pytest.raises(LlmClientError):
        runner.run(role="qa_review", prompts=["P"])


def test_dialogue_runner_release_failure_not_propagated() -> None:
    """AC7: release errors are swallowed (best-effort, FK-11 §11.2.3)."""
    from agentkit.multi_llm_hub.errors import MultiLlmHubError

    class _FailingReleaseHub(_FakeHub):
        def release(self, *, session_id: str, token: str, timeout: float | None = None) -> None:
            raise MultiLlmHubError("release failed")

    hub = _FailingReleaseHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("R"))

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    # Should NOT raise even though release fails
    result = runner.run(role="qa_review", prompts=["P"])
    assert result.turn_count == 1


def test_dialogue_runner_persist_transcript_with_write_raw() -> None:
    """AC7: transcript persistence via write_raw ArtifactManager."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("R"))

    class _FakeArtifactManager:
        def __init__(self) -> None:
            self.written: list[tuple[str, bytes]] = []

        def write_raw(self, name: str, data: bytes) -> None:
            self.written.append((name, data))

    mgr = _FakeArtifactManager()
    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    result = runner.run(role="qa_review", prompts=["P"], artifact_manager=mgr)

    assert result.logging_status == "persisted"
    assert len(mgr.written) == 1
    assert mgr.written[0][0] == "dialogue_transcript"


def test_dialogue_runner_persist_transcript_error_returns_error_status() -> None:
    """AC7: persistence failure → 'error' status (not propagated)."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("R"))

    class _BrokenArtifactManager:
        def write_raw(self, name: str, data: bytes) -> None:
            raise RuntimeError("disk full")

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    result = runner.run(role="qa_review", prompts=["P"], artifact_manager=_BrokenArtifactManager())

    assert result.logging_status == "error"


def test_dialogue_runner_persist_transcript_no_write_raw_returns_skipped() -> None:
    """AC7: ArtifactManager without write_raw → 'skipped' (not crash)."""
    hub = _FakeHub()
    hub.acquire_responses.append(hub._make_lease())
    hub.send_responses.append(_chat_response("R"))

    class _NoWriteRawManager:
        pass  # No write_raw method

    runner = DialogueRunner(hub, _StaticResolver("chatgpt"))
    result = runner.run(role="qa_review", prompts=["P"], artifact_manager=_NoWriteRawManager())

    assert result.logging_status == "skipped"
