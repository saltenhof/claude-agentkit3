"""HubFineDesignEvaluator -- multi-LLM-hub fine-design wiring (AG3-097).

Covers AK3 (ChatGPT + second-advisor mandatory), AK4 (non-reachability ->
fail-closed signal, the caller maps to FAILED -- D4), AK5 (session_stats 0-answer
abort), AK6 (10-round adapter cap), AK8 (session-release WARNING / clean release
no warning).

Fakes live ONLY at the hub boundary (MOCKS exception). The fake hub is
PRODUCTION-FAITHFUL (CRITICAL LESSON AG3-072): it is NOT more lenient than the
real ``HubClient`` -- ``send`` returns a per-backend ``HubMessage`` map exactly
like the real client, ``acquire`` only grants the requested available backends,
``pool_status`` reports backend availability, and ``session_stats`` reflects the
real answered/release facts. A non-answering backend is reported faithfully so
the evaluator's fail-closed paths are exercised against real component behaviour,
not a lenient stub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.exploration_change_frame_fixture import example_change_frame

from agentkit.backend.exploration.mandate.fine_design import (
    FineDesignDecision,
    FineDesignEvaluatorUnavailableError,
    FineDesignRoundOutcome,
    FineDesignSubprocess,
)
from agentkit.backend.exploration.mandate.hub_fine_design import HubFineDesignEvaluator
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import EventType
from agentkit.integration_clients.multi_llm_hub.entities import (
    HubBackendMetric,
    HubBackendName,
    HubBackendSessionStats,
    HubMessage,
    HubSessionLease,
    HubSessionStats,
)
from agentkit.integration_clients.multi_llm_hub.errors import HubUnavailableError

if TYPE_CHECKING:
    from agentkit.backend.exploration.change_frame import ChangeFrame


# --------------------------------------------------------------------------
# Production-faithful fake hub (boundary only; MOCKS exception).
# --------------------------------------------------------------------------
@dataclass
class _FakeHub:
    """Faithful fake of the ``HubClientProtocol`` (NOT lenient).

    Models the real hub contract: only the available backends are grantable;
    ``send`` returns one ``HubMessage`` per granted backend; non-answering
    backends are reported faithfully (empty / error status + 0 answers in stats);
    release flips the session to ``released``.
    """

    available: tuple[HubBackendName, ...] = ("chatgpt", "qwen", "gemini", "grok")
    #: Backends that never answer (empty ``ok`` text -> the real hub's no-response).
    silent: tuple[HubBackendName, ...] = ()
    acquire_error: Exception | None = None
    send_counts: dict[HubBackendName, int] = field(default_factory=dict)
    granted: tuple[HubBackendName, ...] = ()
    released: bool = False
    _token: str = "tok"
    _session_id: str = "fd-1"

    def pool_status(self) -> list[HubBackendMetric]:
        return [
            HubBackendMetric(
                name=backend,
                label=backend,
                status="healthy",
                slots_total=1,
                slots_in_use=0,
                sends=0,
                responses=0,
                errors=0,
                avg_response_ms=None,
                holders=[],
            )
            for backend in self.available
        ]

    def acquire(
        self,
        *,
        owner: str,
        description: str,
        llms: list[HubBackendName],
        timeout: float | None = None,
    ) -> HubSessionLease:
        del owner, description, timeout
        if self.acquire_error is not None:
            raise self.acquire_error
        # Faithful: only the requested backends that ARE available are granted.
        granted = tuple(b for b in llms if b in self.available)
        self.granted = granted
        self.send_counts = {b: 0 for b in granted}
        return HubSessionLease(
            session_id=self._session_id,
            token=self._token,
            llms=list(granted),
            slots={b: i for i, b in enumerate(granted)},
        )

    def send(
        self,
        *,
        session_id: str,
        token: str,
        message: str | None = None,
        target: HubBackendName | None = None,
        targets: dict[HubBackendName, str] | None = None,
        timeout: float | None = None,
    ) -> dict[HubBackendName, HubMessage]:
        del target, targets, timeout
        assert session_id == self._session_id
        assert token == self._token
        result: dict[HubBackendName, HubMessage] = {}
        for backend in self.granted:
            self.send_counts[backend] += 1
            answered = backend not in self.silent
            result[backend] = HubMessage(
                id=f"{session_id}:{backend}",
                session_id=session_id,
                backend=backend,
                role="assistant",
                text=f"{backend} says {message}" if answered else "",
                at=datetime.now(UTC),
                status="ok" if answered else "error",
            )
        return result

    def release(
        self, *, session_id: str, token: str, timeout: float | None = None
    ) -> None:
        del timeout
        assert session_id == self._session_id
        assert token == self._token
        self.released = True

    def session_stats(
        self, *, session_id: str, timeout: float | None = None
    ) -> HubSessionStats:
        del timeout
        assert session_id == self._session_id
        rows = [
            HubBackendSessionStats(
                backend=backend,
                message_count=self.send_counts.get(backend, 0),
                answered=backend not in self.silent
                and self.send_counts.get(backend, 0) > 0,
            )
            for backend in self.granted
        ]
        return HubSessionStats(
            session_id=session_id,
            status="released" if self.released else "active",
            released=self.released,
            backends=rows,
        )


@dataclass
class _ScriptedJudge:
    """Injected convergence judge (LLM-semantic verdict stand-in)."""

    converge_on: int

    def judge(
        self,
        change_frame: ChangeFrame,
        *,
        round_number: int,
        responses: dict[HubBackendName, str],
    ) -> FineDesignRoundOutcome:
        del change_frame
        decision = FineDesignDecision(
            decision_id=f"FD-{round_number:03d}",
            question="how to resolve the contract?",
            decision="single key",
            rationale="consistent",
            normative_basis=("FK-25",),
            llm_responses=tuple(f"{k}: {v}" for k, v in sorted(responses.items())),
        )
        return FineDesignRoundOutcome(
            converged=round_number >= self.converge_on,
            decisions=(decision,),
        )


class _PromptBuilder:
    def build(
        self,
        change_frame: ChangeFrame,
        *,
        round_number: int,
        previous_responses: dict[HubBackendName, str],
    ) -> str:
        del change_frame, previous_responses
        return f"round {round_number}: resolve the fine-design question"


def _evaluator(
    hub: _FakeHub,
    *,
    emitter: MemoryEmitter | None = None,
    converge_on: int = 1,
    max_rounds: int = 10,
) -> HubFineDesignEvaluator:
    return HubFineDesignEvaluator(
        hub,  # type: ignore[arg-type]
        emitter=emitter or MemoryEmitter(),
        judge=_ScriptedJudge(converge_on=converge_on),
        prompt_builder=_PromptBuilder(),
        owner="main-agent",
        story_id="AG3-097",
        max_rounds=max_rounds,
    )


# -- AK3: ChatGPT + second advisor mandatory -------------------------------
def test_acquires_chatgpt_and_preferred_second_advisor() -> None:
    """Qwen is the preferred second advisor when available (FK-25 §25.5.2)."""
    hub = _FakeHub(available=("chatgpt", "qwen", "gemini"))
    evaluator = _evaluator(hub, converge_on=1)

    evaluator.run_round(example_change_frame(), round_number=1)

    assert hub.granted == ("chatgpt", "qwen")


def test_falls_back_to_gemini_then_grok_for_second_advisor() -> None:
    """Without Qwen the second advisor is Gemini, then Grok (FK-25 §25.5.2)."""
    hub = _FakeHub(available=("chatgpt", "grok"))
    evaluator = _evaluator(hub, converge_on=1)

    evaluator.run_round(example_change_frame(), round_number=1)

    assert hub.granted == ("chatgpt", "grok")


def test_missing_chatgpt_aborts_deterministically() -> None:
    """No ChatGPT -> fail-closed abort, no class-2 decision (AK3)."""
    hub = _FakeHub(available=("qwen", "gemini"))
    evaluator = _evaluator(hub)

    with pytest.raises(FineDesignEvaluatorUnavailableError, match="ChatGPT"):
        evaluator.run_round(example_change_frame(), round_number=1)


def test_missing_second_advisor_aborts_deterministically() -> None:
    """Only ChatGPT available -> fail-closed abort (no quorum, AK3)."""
    hub = _FakeHub(available=("chatgpt",))
    evaluator = _evaluator(hub)

    with pytest.raises(FineDesignEvaluatorUnavailableError, match="second"):
        evaluator.run_round(example_change_frame(), round_number=1)


# -- AK4: non-reachability -> fail-closed signal (caller maps to FAILED) ----
def test_acquire_unavailable_signals_non_reachability() -> None:
    """A hub-unavailable acquire raises the non-reachability signal (D4)."""
    hub = _FakeHub(acquire_error=HubUnavailableError("hub down"))
    evaluator = _evaluator(hub)

    with pytest.raises(FineDesignEvaluatorUnavailableError):
        evaluator.run_round(example_change_frame(), round_number=1)


def test_live_no_answer_aborts() -> None:
    """An acquired advisor that produces no answer aborts fail-closed (D4)."""
    hub = _FakeHub(available=("chatgpt", "qwen"), silent=("qwen",))
    evaluator = _evaluator(hub)

    with pytest.raises(FineDesignEvaluatorUnavailableError, match="no answer"):
        evaluator.run_round(example_change_frame(), round_number=1)


def test_pool_status_unavailable_signals_non_reachability() -> None:
    """A hub-unavailable pool_status raises the non-reachability signal (D4)."""

    class _PoolDownHub(_FakeHub):
        def pool_status(self) -> list[HubBackendMetric]:
            raise HubUnavailableError("pool down")

    evaluator = _evaluator(_PoolDownHub())
    with pytest.raises(FineDesignEvaluatorUnavailableError):
        evaluator.run_round(example_change_frame(), round_number=1)


def test_partial_grant_aborts_and_releases() -> None:
    """If the hub grants fewer than both mandatory advisors -> fail-closed abort.

    A faithful hub that grants only ChatGPT (slot pressure) must not yield a
    one-advisor quorum; the evaluator aborts AND releases the partial lease.
    """

    class _PartialGrantHub(_FakeHub):
        def acquire(
            self,
            *,
            owner: str,
            description: str,
            llms: list[HubBackendName],
            timeout: float | None = None,
        ) -> HubSessionLease:
            del owner, description, llms, timeout
            self.granted = ("chatgpt",)
            self.send_counts = {"chatgpt": 0}
            return HubSessionLease(
                session_id=self._session_id,
                token=self._token,
                llms=["chatgpt"],
                slots={"chatgpt": 0},
            )

    hub = _PartialGrantHub(available=("chatgpt", "qwen"))
    evaluator = _evaluator(hub)
    with pytest.raises(FineDesignEvaluatorUnavailableError, match="quorum"):
        evaluator.run_round(example_change_frame(), round_number=1)
    assert hub.released is True


def test_send_failure_signals_non_reachability() -> None:
    """A hub-unavailable send raises the non-reachability signal (D4)."""

    class _SendDownHub(_FakeHub):
        def send(self, **kwargs: object) -> dict[HubBackendName, HubMessage]:
            del kwargs
            raise HubUnavailableError("send down")

    evaluator = _evaluator(_SendDownHub(available=("chatgpt", "qwen")))
    with pytest.raises(FineDesignEvaluatorUnavailableError):
        evaluator.run_round(example_change_frame(), round_number=1)


def test_finalize_is_idempotent_without_acquire() -> None:
    """finalize() on an unused evaluator (no acquire) is a no-op (idempotent)."""
    evaluator = _evaluator(_FakeHub())
    evaluator.finalize()  # must not raise


def test_retry_attempt_starts_with_fresh_previous_responses() -> None:
    """A re-acquired attempt's round-1 prompt carries NO prior-attempt responses.

    AG3-097 second QA: the caller's D4 bounded retry drives ``run_round`` again
    after ``finalize`` released the first session. The fresh acquisition must
    reset the recorded responses -- the new attempt's round-1 prompt builder
    input is empty, never the previous (aborted) attempt's positions.
    """

    @dataclass
    class _RecordingPromptBuilder:
        seen: list[dict[HubBackendName, str]] = field(default_factory=list)

        def build(
            self,
            change_frame: ChangeFrame,
            *,
            round_number: int,
            previous_responses: dict[HubBackendName, str],
        ) -> str:
            del change_frame
            self.seen.append(dict(previous_responses))
            return f"round {round_number}"

    hub = _FakeHub(available=("chatgpt", "qwen"))
    builder = _RecordingPromptBuilder()
    evaluator = HubFineDesignEvaluator(
        hub,  # type: ignore[arg-type]
        emitter=MemoryEmitter(),
        judge=_ScriptedJudge(converge_on=999),
        prompt_builder=builder,
        owner="main-agent",
        story_id="AG3-097",
    )
    evaluator.run_round(example_change_frame(), round_number=1)
    evaluator.run_round(example_change_frame(), round_number=2)
    evaluator.finalize()  # releases; the retry re-acquires below

    evaluator.run_round(example_change_frame(), round_number=1)

    assert builder.seen[0] == {}  # attempt 1, round 1
    assert builder.seen[1] != {}  # attempt 1, round 2 carries round-1 positions
    assert builder.seen[2] == {}  # attempt 2, round 1 is FRESH (no leakage)


def test_non_positive_max_rounds_fails_closed() -> None:
    """A non-positive send cap is a fail-closed programming error."""
    with pytest.raises(ValueError, match="max_rounds must be >= 1"):
        _evaluator(_FakeHub(), max_rounds=0)


def test_release_transport_error_is_swallowed_clean_outcome() -> None:
    """A release transport error never masks the discussion outcome (ARCH-20).

    The release WARNING path already covers a not-released session; a transport
    error on the cleanup release is swallowed so finalize still completes (the
    session reports released in stats here -> no warning, no abort).
    """

    class _ReleaseErrorHub(_FakeHub):
        def release(
            self, *, session_id: str, token: str, timeout: float | None = None
        ) -> None:
            del session_id, token, timeout
            self.released = True  # the hub DID release; the ACK transport failed
            raise HubUnavailableError("release ack failed")

    hub = _ReleaseErrorHub(available=("chatgpt", "qwen"))
    emitter = MemoryEmitter()
    evaluator = _evaluator(hub, emitter=emitter, converge_on=1)
    evaluator.run_round(example_change_frame(), round_number=1)

    evaluator.finalize()  # must not raise despite the release transport error

    assert emitter.query("AG3-097", EventType.WARNING) == []


# -- AK5: post-hoc session_stats 0-answer abort ----------------------------
def test_finalize_aborts_on_zero_answer_in_stats() -> None:
    """finalize() fail-closed when stats show an acquired LLM with 0 answers.

    The judge is scripted to converge so the live send path passes; the hub then
    faithfully reports 0 answers for a silent backend in the post-hoc stats.
    """

    class _SilentInStatsHub(_FakeHub):
        def send(self, **kwargs: object) -> dict[HubBackendName, HubMessage]:
            # Both answer live, but stats will report qwen as 0-answer below.
            return super().send(**kwargs)  # type: ignore[arg-type]

        def session_stats(
            self, *, session_id: str, timeout: float | None = None
        ) -> HubSessionStats:
            del timeout
            return HubSessionStats(
                session_id=session_id,
                status="released" if self.released else "active",
                released=self.released,
                backends=[
                    HubBackendSessionStats(
                        backend="chatgpt", message_count=1, answered=True
                    ),
                    HubBackendSessionStats(
                        backend="qwen", message_count=1, answered=False
                    ),
                ],
            )

    hub = _SilentInStatsHub(available=("chatgpt", "qwen"))
    evaluator = _evaluator(hub, converge_on=1)
    evaluator.run_round(example_change_frame(), round_number=1)

    with pytest.raises(FineDesignEvaluatorUnavailableError, match="0\nanswers|0 answers"):
        evaluator.finalize()
    # The session is still released despite the abort (no slot leak).
    assert hub.released is True


# -- AK6: 10-round adapter cap (no 11th send) ------------------------------
def test_adapter_caps_at_ten_sends_per_llm() -> None:
    """A never-converging discussion sends at most 10x per LLM (AK6)."""
    hub = _FakeHub(available=("chatgpt", "qwen"))
    evaluator = _evaluator(hub, converge_on=999, max_rounds=10)
    subprocess = FineDesignSubprocess(evaluator)

    result = subprocess.run(example_change_frame(), max_rounds=10)

    assert result.status == "max_rounds_exceeded"
    assert hub.send_counts["chatgpt"] == 10
    assert hub.send_counts["qwen"] == 10


def test_adapter_refuses_eleventh_send() -> None:
    """An explicit round 11 call is refused by the adapter cap (no 11th send)."""
    hub = _FakeHub(available=("chatgpt", "qwen"))
    evaluator = _evaluator(hub, converge_on=999, max_rounds=10)
    for round_number in range(1, 11):
        evaluator.run_round(example_change_frame(), round_number=round_number)

    with pytest.raises(FineDesignEvaluatorUnavailableError, match="cap"):
        evaluator.run_round(example_change_frame(), round_number=11)
    assert hub.send_counts["chatgpt"] == 10


# -- AK8: session-release WARNING / clean release no warning ---------------
def test_finalize_warns_when_session_not_released() -> None:
    """A not-correctly-released session writes a telemetry WARNING (AK8)."""

    class _NoReleaseHub(_FakeHub):
        def release(
            self, *, session_id: str, token: str, timeout: float | None = None
        ) -> None:
            # The hub never marks the session released -> stats stay ``active``.
            del session_id, token, timeout

    hub = _NoReleaseHub(available=("chatgpt", "qwen"))
    emitter = MemoryEmitter()
    evaluator = _evaluator(hub, emitter=emitter, converge_on=1)
    evaluator.run_round(example_change_frame(), round_number=1)

    evaluator.finalize()

    warnings = [e for e in emitter.query("AG3-097", EventType.WARNING)]
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert warnings[0].payload["warning"] == "fine_design_session_not_released"


def test_finalize_clean_release_writes_no_warning() -> None:
    """A correct release writes NO warning (AK8)."""
    hub = _FakeHub(available=("chatgpt", "qwen"))
    emitter = MemoryEmitter()
    evaluator = _evaluator(hub, emitter=emitter, converge_on=1)
    evaluator.run_round(example_change_frame(), round_number=1)

    evaluator.finalize()

    assert emitter.query("AG3-097", EventType.WARNING) == []
    assert hub.released is True
