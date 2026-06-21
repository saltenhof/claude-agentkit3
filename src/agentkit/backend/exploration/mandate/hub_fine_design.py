"""Concrete multi-LLM-hub fine-design evaluator (FK-25 §25.5.2 / §25.5.4).

AG3-097 wires the abstract :class:`~agentkit.backend.exploration.mandate.fine_design.FineDesignEvaluator`
port (the orchestration shell ``FineDesignSubprocess`` stays UNCHANGED) to the
external Multi-LLM Hub. It enforces the FK-25 §25.5 rules that are buildable in
this cut:

* **ChatGPT mandatory AND a second advisor mandatory** (Qwen preferred, then
  Gemini, then Grok) -- both acquired/sent/released over the hub. A missing
  ChatGPT slot or no second advisor is a deterministic, fail-closed abort
  (:class:`~agentkit.backend.exploration.mandate.fine_design.FineDesignEvaluatorUnavailableError`):
  no class-2 decision is made without the multi-perspective quorum.
* **10-round cap IN the adapter**: at most :data:`DEFAULT_MAX_ROUNDS` (10) sends
  per LLM. The shell already bounds the loop; this adapter ALSO refuses an 11th
  send per backend defensively (no 11th send originates from the impl). The
  real-time PostToolUse hook-block of the 11th send (``*_send``/``llm_send``)
  is a FK-30 gap with no current owner (see story §2.2) -- NOT built here.
* **Non-reachability == OPERATIONAL ERROR, not a pause** (D4-Override
  2026-06-09 / FK-25 §25.5.4 Z. 642-650): an acquired LLM that produces no
  answer -- detected live OR via the post-hoc ``llm_session_stats`` 0-answer
  check -- aborts fail-closed via ``FineDesignEvaluatorUnavailableError``. There
  is NO ``escalation_class``/``infra_unavailable``/``PAUSED`` triple. The caller
  edge maps this to a bounded-retry-then-``FAILED`` outcome.
* **Post-hoc ``llm_session_stats`` verification + release check**: after the
  discussion, :meth:`finalize` reads the read-only session stats, aborts on any
  0-answer acquired LLM, and writes a telemetry WARNING when the session was not
  correctly released (SEVERITY-semantics: aufschiebend, but never silent).

The LLM-semantic judgement (did the discussion converge, what is the decision)
stays an injected port (:class:`RoundConvergenceJudge`) so this deterministic
adapter performs transport + enforcement, never fabricates an LLM verdict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from agentkit.backend.exploration.mandate.fine_design import (
    DEFAULT_MAX_ROUNDS,
    FineDesignEvaluatorUnavailableError,
    FineDesignRoundOutcome,
)
from agentkit.backend.telemetry.events import Event, EventType
from agentkit.integration_clients.multi_llm_hub.errors import MultiLlmHubError

if TYPE_CHECKING:
    from agentkit.backend.exploration.change_frame import ChangeFrame
    from agentkit.backend.telemetry.emitters import EventEmitter
    from agentkit.integration_clients.multi_llm_hub.client import HubClientProtocol
    from agentkit.integration_clients.multi_llm_hub.entities import (
        HubBackendName,
        HubMessage,
        HubSessionLease,
        HubSessionStats,
    )

#: ChatGPT is the mandatory primary advisor (FK-25 §25.5.2).
_PRIMARY_ADVISOR: Final[HubBackendName] = "chatgpt"
#: Preference order for the mandatory SECOND advisor (Qwen preferred, then
#: Gemini, then Grok -- FK-25 §25.5.2).
_SECOND_ADVISOR_PREFERENCE: Final[tuple[HubBackendName, ...]] = (
    "qwen",
    "gemini",
    "grok",
)
#: Telemetry source component for the fine-design release WARNING.
_SOURCE: Final[str] = "exploration-fine-design-hub"
_PHASE: Final[str] = "exploration"


@runtime_checkable
class RoundConvergenceJudge(Protocol):
    """Injected port: turn the per-LLM round responses into a round outcome.

    Keeps the LLM-semantic verdict (converged? which decisions?) OUT of the
    deterministic transport adapter (FIX-THE-MODEL): the adapter sends + records
    the exchange, this port decides convergence from the recorded responses. The
    productive judge is a small, testable A-core; the unit tests inject a
    scripted one.
    """

    def judge(
        self,
        change_frame: ChangeFrame,
        *,
        round_number: int,
        responses: dict[HubBackendName, str],
    ) -> FineDesignRoundOutcome:
        """Decide the round outcome from the per-backend responses.

        Args:
            change_frame: The change-frame being refined.
            round_number: The 1-based round number.
            responses: The per-backend response text exchanged this round.

        Returns:
            The :class:`FineDesignRoundOutcome` (converged + decisions).
        """
        ...


@runtime_checkable
class FineDesignPromptBuilder(Protocol):
    """Injected port: build the per-round prompt for the advising LLMs."""

    def build(
        self,
        change_frame: ChangeFrame,
        *,
        round_number: int,
        previous_responses: dict[HubBackendName, str],
    ) -> str:
        """Build the round prompt sent to every advising LLM.

        Args:
            change_frame: The change-frame being refined.
            round_number: The 1-based round number.
            previous_responses: The previous round's per-backend responses (empty
                on round 1).

        Returns:
            The prompt text.
        """
        ...


class HubFineDesignEvaluator:
    """Multi-LLM-hub-backed :class:`FineDesignEvaluator` (FK-25 §25.5.2/§25.5.4).

    Lifecycle: the mandatory advisors (ChatGPT + a second) are acquired LAZILY on
    the first :meth:`run_round` so an aborted classification never holds a slot.
    :meth:`finalize` MUST be called by the driver after the bounded loop (in a
    ``finally``) -- it runs the post-hoc ``llm_session_stats`` verification, the
    release WARNING check, and releases the session. The driver is the
    exploration phase handler (it adapts the existing ``FineDesignSubprocess``
    shell, which is NOT rewritten).
    """

    def __init__(
        self,
        client: HubClientProtocol,
        *,
        emitter: EventEmitter,
        judge: RoundConvergenceJudge,
        prompt_builder: FineDesignPromptBuilder,
        owner: str,
        story_id: str,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
    ) -> None:
        """Initialise the evaluator.

        Args:
            client: The hub transport client (acquire/send/release/session_stats).
            emitter: Telemetry emitter for the release WARNING (SEVERITY).
            judge: The injected convergence judge (LLM-semantic verdict).
            prompt_builder: The injected per-round prompt builder.
            owner: Hub session owner id.
            story_id: The story display id (telemetry correlation).
            max_rounds: The per-LLM send cap (default 10, FK-25 §25.5.1). The
                adapter never sends more than this per backend.

        Raises:
            ValueError: If ``max_rounds`` is not >= 1 (fail-closed).
        """
        if max_rounds < 1:
            msg = f"max_rounds must be >= 1 (FK-25 §25.5.1); got {max_rounds}"
            raise ValueError(msg)
        self._client = client
        self._emitter = emitter
        self._judge = judge
        self._prompt_builder = prompt_builder
        self._owner = owner
        self._story_id = story_id
        self._max_rounds = max_rounds
        self._lease: HubSessionLease | None = None
        self._advisors: tuple[HubBackendName, ...] = ()
        self._send_counts: dict[HubBackendName, int] = {}
        self._last_responses: dict[HubBackendName, str] = {}

    def run_round(
        self, change_frame: ChangeFrame, *, round_number: int
    ) -> FineDesignRoundOutcome:
        """Run one fine-design round over the acquired advisors (FK-25 §25.5).

        Acquires the mandatory advisors on round 1, then sends the round prompt
        to BOTH advisors, records the responses, and asks the injected judge for
        the outcome. Enforces the per-LLM 10-send cap (no 11th send) and the
        live no-answer abort.

        Args:
            change_frame: The change-frame being refined.
            round_number: The 1-based round number.

        Returns:
            The :class:`FineDesignRoundOutcome` for this round.

        Raises:
            FineDesignEvaluatorUnavailableError: If the mandatory quorum cannot
                be acquired, an advisor produces no answer, or the per-LLM send
                cap would be exceeded (fail-closed; D4 -> the caller maps this to
                a bounded-retry-then-FAILED outcome, NOT a pause).
        """
        if self._lease is None:
            self._acquire_advisors()
        responses = self._send_round(change_frame, round_number=round_number)
        self._last_responses = responses
        return self._judge.judge(
            change_frame, round_number=round_number, responses=responses
        )

    def finalize(self) -> None:
        """Release the session, then post-hoc verify it (release + answers).

        Idempotent: a no-op when no session was ever acquired. The order is:
        release the lease (best-effort), THEN read the post-hoc
        ``llm_session_stats`` so the release-correctness check reflects the state
        AFTER this evaluator released -- a still-not-released session at that
        point is a real release violation (WARNING). The 0-answer check then
        aborts fail-closed (D4).

        Raises:
            FineDesignEvaluatorUnavailableError: If the post-hoc
                ``llm_session_stats`` shows any acquired LLM with 0 answers
                (fail-closed; no class-2 decision -- D4).
        """
        lease = self._lease
        if lease is None:
            return
        self._lease = None
        self._release(lease)
        stats = self._read_session_stats(lease.session_id)
        # WARNING (aufschiebend) before the hard 0-answer abort (ERROR) so the
        # release violation is never lost when an abort follows.
        self._warn_on_bad_release(stats)
        self._abort_on_zero_answer(stats)

    # -- internal helpers --------------------------------------------------

    def _acquire_advisors(self) -> None:
        """Acquire ChatGPT + a second advisor; fail-closed on a missing quorum."""
        try:
            available = self._available_backends()
        except MultiLlmHubError as exc:
            msg = "multi-LLM hub unavailable for fine-design quorum acquisition " \
                f"(FK-25 §25.5.4 non-reachability): {exc}"
            raise FineDesignEvaluatorUnavailableError(msg) from exc
        if _PRIMARY_ADVISOR not in available:
            msg = (
                "ChatGPT is a mandatory fine-design advisor but is not available "
                "on the hub (FK-25 §25.5.2): no class-2 decision without the "
                "primary advisor (fail-closed, D4 -> FAILED)"
            )
            raise FineDesignEvaluatorUnavailableError(msg)
        second = self._pick_second_advisor(available)
        if second is None:
            msg = (
                "no second fine-design advisor available (Qwen/Gemini/Grok all "
                "absent, FK-25 §25.5.2): the multi-LLM quorum is not reachable -- "
                "no class-2 decision without multi-perspective sicherung "
                "(fail-closed, D4 -> FAILED)"
            )
            raise FineDesignEvaluatorUnavailableError(msg)
        advisors = (_PRIMARY_ADVISOR, second)
        try:
            lease = self._client.acquire(
                owner=self._owner,
                description=f"fine-design discussion for {self._story_id}",
                llms=list(advisors),
            )
        except MultiLlmHubError as exc:
            msg = "could not acquire the fine-design advisor quorum over the hub " \
                f"(FK-25 §25.5.4 non-reachability): {exc}"
            raise FineDesignEvaluatorUnavailableError(msg) from exc
        # Fail-closed: the granted lease MUST cover BOTH mandatory advisors.
        granted = set(lease.llms)
        if not granted.issuperset(advisors):
            self._release(lease)
            missing = sorted(set(advisors) - granted)
            msg = (
                "the hub did not grant the full mandatory advisor quorum "
                f"(missing: {missing}, FK-25 §25.5.2): fail-closed (D4 -> FAILED)"
            )
            raise FineDesignEvaluatorUnavailableError(msg)
        self._lease = lease
        self._advisors = advisors
        self._send_counts = dict.fromkeys(advisors, 0)
        # A fresh acquisition starts a FRESH discussion: never leak the previous
        # (aborted) attempt's responses into the new attempt's round-1 prompt
        # (the caller's D4 bounded retry re-acquires through this path).
        self._last_responses = {}

    def _available_backends(self) -> frozenset[HubBackendName]:
        metrics = self._client.pool_status()
        return frozenset(
            metric.name for metric in metrics if metric.status != "unavailable"
        )

    @staticmethod
    def _pick_second_advisor(
        available: frozenset[HubBackendName],
    ) -> HubBackendName | None:
        for candidate in _SECOND_ADVISOR_PREFERENCE:
            if candidate in available:
                return candidate
        return None

    def _send_round(
        self, change_frame: ChangeFrame, *, round_number: int
    ) -> dict[HubBackendName, str]:
        lease = self._lease
        assert lease is not None  # noqa: S101 -- acquired in run_round before this
        self._guard_send_cap(round_number)
        prompt = self._prompt_builder.build(
            change_frame,
            round_number=round_number,
            previous_responses=dict(self._last_responses),
        )
        try:
            messages = self._client.send(
                session_id=lease.session_id,
                token=lease.token,
                message=prompt,
            )
        except MultiLlmHubError as exc:
            msg = "fine-design send failed over the hub (FK-25 §25.5.4 " \
                f"non-reachability): {exc}"
            raise FineDesignEvaluatorUnavailableError(msg) from exc
        for advisor in self._advisors:
            self._send_counts[advisor] += 1
        return self._collect_answers(messages)

    def _guard_send_cap(self, round_number: int) -> None:
        """Refuse an 11th send per backend (10-round adapter cap, FK-25 §25.5.1)."""
        if round_number > self._max_rounds or any(
            count >= self._max_rounds for count in self._send_counts.values()
        ):
            msg = (
                f"fine-design send cap reached ({self._max_rounds} sends per LLM, "
                "FK-25 §25.5.1): the adapter does not send an 11th time"
            )
            raise FineDesignEvaluatorUnavailableError(msg)

    def _collect_answers(
        self, messages: dict[HubBackendName, HubMessage]
    ) -> dict[HubBackendName, str]:
        """Collect per-advisor answers; live-abort on a non-answering advisor."""
        responses: dict[HubBackendName, str] = {}
        for advisor in self._advisors:
            message = messages.get(advisor)
            if message is None or message.status != "ok" or not message.text.strip():
                msg = (
                    f"fine-design advisor {advisor!r} produced no answer (FK-25 "
                    "§25.5.4 non-reachability): no class-2 decision without every "
                    "acquired LLM answering (fail-closed, D4 -> FAILED)"
                )
                raise FineDesignEvaluatorUnavailableError(msg)
            responses[advisor] = message.text
        return responses

    def _read_session_stats(self, session_id: str) -> HubSessionStats:
        try:
            return self._client.session_stats(session_id=session_id)
        except MultiLlmHubError as exc:
            msg = "could not read post-hoc llm_session_stats for fine-design " \
                f"verification (FK-25 §25.5.4): {exc}"
            raise FineDesignEvaluatorUnavailableError(msg) from exc

    def _abort_on_zero_answer(self, stats: HubSessionStats) -> None:
        """Fail-closed if any acquired advisor answered 0 times (FK-25 §25.5.4)."""
        by_backend = {row.backend: row for row in stats.backends}
        for advisor in self._advisors:
            row = by_backend.get(advisor)
            if row is None or not row.answered:
                msg = (
                    f"post-hoc llm_session_stats shows advisor {advisor!r} with 0 "
                    "answers (FK-25 §25.5.4): the class-2 decision is aborted "
                    "fail-closed (D4 -> FAILED)"
                )
                raise FineDesignEvaluatorUnavailableError(msg)

    def _warn_on_bad_release(self, stats: HubSessionStats) -> None:
        """Write a telemetry WARNING when the session was not correctly released.

        FK-25 §25.5.4 / SEVERITY-semantics: a not-correctly-released session is a
        WARNING (aufschiebend, but never silent). A correct release writes NO
        warning. The stats are read AFTER this evaluator's own release call (see
        :meth:`finalize`): a session the hub still reports as not released at
        that point is a real release violation.
        """
        if stats.released:
            return
        self._emitter.emit(
            Event(
                story_id=self._story_id,
                event_type=EventType.WARNING,
                phase=_PHASE,
                source_component=_SOURCE,
                severity="warning",
                payload={
                    "warning": "fine_design_session_not_released",
                    "session_id": stats.session_id,
                    "session_status": stats.status,
                    "detail": (
                        "the fine-design hub session was not correctly released "
                        "(FK-25 §25.5.4); review the hub session lifecycle"
                    ),
                },
            )
        )

    def _release(self, lease: HubSessionLease) -> None:
        """Best-effort release; a release failure never raises (slot cleanup)."""
        try:
            self._client.release(
                session_id=lease.session_id, token=lease.token
            )
        except MultiLlmHubError:
            # The release WARNING path already covers a not-released session; a
            # transport error on the cleanup release must not mask the discussion
            # outcome (ARCH-20: emitters/cleanup never raise business errors).
            return


__all__ = [
    "FineDesignPromptBuilder",
    "HubFineDesignEvaluator",
    "RoundConvergenceJudge",
]
