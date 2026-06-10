"""DialogueRunner — multi-turn free-format dialogue over the Hub transport (FK-11 §11.5.2).

AG3-065: a typed multi-turn dialogue primitive for free-format LLM interactions
(e.g. concept feedback ``concept_feedback_1/2``). Unlike :class:`StructuredEvaluator`,
the ``DialogueRunner`` does NO schema validation and never auto-FAILs a check.

An ordered transcript is maintained in-memory (:class:`DialogueResult`).
Additionally, the full transcript (prompt + response per turn) is persisted via
the ``prompt_audit`` / ``ArtifactManager`` machinery (FK-11 §11.5.2 Zeile
494/532 "separates Logging" / "Vollständiger Transcript"). A missing
``ArtifactManager`` yields a clean ``skipped`` status (never silently swallowed).

Transport error protocol is the same as :class:`HubLlmClient`:
- acquire → send* → release in finally (FK-11 §11.2.3).
- max_turns enforced as a hard upper bound.
- No schema validation / no auto-FAIL.

Quelle:
  - FK-11 §11.5.2 -- DialogueRunner (mehrturnig, Freiformat)
  - FK-11 §11.2.3 -- Acquire/Send/Release-Fehlerprotokoll
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from agentkit.verify_system.llm_evaluator.llm_client import (
    ACQUIRE_TIMEOUT_SECONDS,
    RELEASE_TIMEOUT_SECONDS,
    SEND_TIMEOUT_SECONDS,
    LlmClientError,
    LoginRequiredError,
)

if TYPE_CHECKING:
    from agentkit.multi_llm_hub.client import HubClientProtocol
    from agentkit.multi_llm_hub.entities import HubBackendName, HubSessionLease
    from agentkit.verify_system.llm_evaluator.llm_client import RolePoolResolver

logger = logging.getLogger(__name__)

#: Default maximum number of turns per dialogue session.
DEFAULT_MAX_TURNS: int = 20


class DialogueTurn(BaseModel):
    """A single turn in a dialogue transcript (FK-11 §11.5.2).

    Attributes:
        role: The speaker role, either ``"user"`` (agentkit prompt) or
            ``"assistant"`` (LLM response).
        content: The full text of this turn.
        ts: UTC timestamp when this turn was recorded.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    content: str
    ts: datetime


class DialogueResult(BaseModel):
    """The immutable result of a completed dialogue session (FK-11 §11.5.2).

    Attributes:
        transcript: Ordered tuple of all turns (user + assistant), in
            chronological order.
        pool: The Hub backend pool used for this dialogue.
        role: The agent role used to resolve the pool.
        turn_count: Number of complete user+assistant pairs executed.
        logging_status: Status of the transcript-persistence attempt:
            ``"persisted"``, ``"skipped"``, or ``"error"``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    transcript: tuple[DialogueTurn, ...]
    pool: str
    role: str
    turn_count: int
    logging_status: str = "skipped"


class DialogueRunner:
    """Multi-turn free-format dialogue over the Hub transport (FK-11 §11.5.2).

    Acquires a session, runs up to ``max_turns`` user-prompt→response pairs,
    then releases the session (always in a ``finally`` block). The transcript
    is accumulated in-memory and returned as a frozen :class:`DialogueResult`.

    Additionally persists the full transcript via the ``prompt_audit`` /
    ``ArtifactManager`` machinery when an ``ArtifactManager`` is injected.

    Attributes:
        _hub: Hub client for acquire/send/release.
        _resolver: Role→pool resolver port.
        _owner: Owner identifier for Hub sessions.
        _max_turns: Hard upper bound on dialogue turns.
    """

    def __init__(
        self,
        hub: HubClientProtocol,
        resolver: RolePoolResolver,
        *,
        owner: str = "agentkit-dialogue",
        max_turns: int = DEFAULT_MAX_TURNS,
    ) -> None:
        """Initialise the DialogueRunner.

        Args:
            hub: Hub client for acquire/send/release.
            resolver: Role→pool resolver. Missing pool → :class:`LlmClientError`.
            owner: Owner identifier for Hub sessions.
            max_turns: Maximum number of user+response turns. Enforced hard.
        """
        self._hub = hub
        self._resolver = resolver
        self._owner = owner
        self._max_turns = max_turns

    def run(
        self,
        *,
        role: str,
        prompts: list[str],
        artifact_manager: Any | None = None,
    ) -> DialogueResult:
        """Run a multi-turn dialogue session.

        Executes each prompt in ``prompts`` as a consecutive turn in the same
        Hub session (acquire once → send N times → release). The number of
        turns is bounded by both ``len(prompts)`` and ``max_turns``.

        Args:
            role: The reviewer role wire-string (used to resolve the pool).
            prompts: Ordered list of user prompts to send.
            artifact_manager: Optional ``ArtifactManager`` for transcript
                persistence (FK-11 §11.5.2). ``None`` → ``skipped``.

        Returns:
            :class:`DialogueResult` with the full ordered transcript.

        Raises:
            LlmClientError: On transport failure.
            LoginRequiredError: If the Hub requires operator login.
        """
        from agentkit.multi_llm_hub.errors import (
            HubLoginRequiredError,
            HubSessionNotFoundError,
            HubUnavailableError,
            MultiLlmHubError,
        )

        pool = self._resolver.resolve(role)
        description = f"agentkit-dialogue role={role}"

        # Acquire session
        lease = self._acquire_session(pool, description)
        turns: list[DialogueTurn] = []
        turn_count = 0

        try:
            effective_prompts = prompts[: self._max_turns]
            for prompt_text in effective_prompts:
                user_turn = DialogueTurn(
                    role="user",
                    content=prompt_text,
                    ts=datetime.now(UTC),
                )
                turns.append(user_turn)

                try:
                    messages = self._hub.send(
                        session_id=lease.session_id,
                        token=lease.token,
                        message=prompt_text,
                        target=pool,
                        timeout=SEND_TIMEOUT_SECONDS,
                    )
                except HubLoginRequiredError as exc:
                    raise LoginRequiredError(
                        f"Hub pool {pool!r} requires operator login during dialogue",
                        operator_hint=f"pool={pool!r}: login required",
                    ) from exc
                except (HubSessionNotFoundError, HubUnavailableError, MultiLlmHubError) as exc:
                    raise LlmClientError(
                        f"DialogueRunner send failed for role={role!r} pool={pool!r}: {exc}"
                    ) from exc

                response_text = ""
                msg = messages.get(pool)
                if msg is not None:
                    response_text = msg.text

                assistant_turn = DialogueTurn(
                    role="assistant",
                    content=response_text,
                    ts=datetime.now(UTC),
                )
                turns.append(assistant_turn)
                turn_count += 1

        finally:
            self._safe_release(lease.session_id, lease.token)

        transcript_tuple = tuple(turns)
        logging_status = self._persist_transcript(
            role=role,
            pool=str(pool),
            transcript=transcript_tuple,
            artifact_manager=artifact_manager,
        )

        return DialogueResult(
            transcript=transcript_tuple,
            pool=str(pool),
            role=role,
            turn_count=turn_count,
            logging_status=logging_status,
        )

    def _acquire_session(
        self,
        pool: HubBackendName,
        description: str,
    ) -> HubSessionLease:
        """Acquire a session lease with queue-retry handling.

        Args:
            pool: Target pool backend.
            description: Session description.

        Returns:
            Granted session lease.

        Raises:
            LlmClientError: On failure or queued-acquire exhaustion.
        """
        from agentkit.multi_llm_hub.errors import (
            HubAcquireQueuedError,
            HubLoginRequiredError,
            MultiLlmHubError,
        )
        from agentkit.verify_system.llm_evaluator.llm_client import MAX_ACQUIRE_RETRIES

        for attempt in range(1, MAX_ACQUIRE_RETRIES + 1):
            try:
                return self._hub.acquire(
                    owner=self._owner,
                    description=description,
                    llms=[pool],
                    timeout=ACQUIRE_TIMEOUT_SECONDS,
                )
            except HubAcquireQueuedError as exc:
                wait = exc.estimated_wait_seconds
                if attempt == MAX_ACQUIRE_RETRIES:
                    raise LlmClientError(
                        f"DialogueRunner acquire exhausted {MAX_ACQUIRE_RETRIES} "
                        f"retries (pool={pool!r} queued)"
                    ) from exc
                time.sleep(min(wait or 1.0, 5.0))
            except HubLoginRequiredError as exc:
                raise LoginRequiredError(
                    f"Hub pool {pool!r} requires operator login",
                    operator_hint=f"pool={pool!r}: login required",
                ) from exc
            except MultiLlmHubError as exc:
                raise LlmClientError(
                    f"DialogueRunner acquire failed for pool={pool!r}: {exc}"
                ) from exc
        raise LlmClientError(f"DialogueRunner acquire unreachable (pool={pool!r})")  # pragma: no cover

    def _safe_release(self, session_id: str, token: str) -> None:
        """Release session, swallowing errors (best-effort, FK-11 §11.2.3 Zeile 192)."""
        try:
            self._hub.release(
                session_id=session_id,
                token=token,
                timeout=RELEASE_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DialogueRunner release failed for session=%r: %s", session_id, exc
            )

    def _persist_transcript(
        self,
        *,
        role: str,
        pool: str,
        transcript: tuple[DialogueTurn, ...],
        artifact_manager: Any | None,
    ) -> str:
        """Persist the full transcript via the ArtifactManager (FK-11 §11.5.2).

        FK-11 §11.5.2 Zeile 494/532: "Vollständiger Transcript (Prompt + Response
        pro Turn)" — persisted via the prompt_audit/ArtifactManager machinery,
        NOT a parallel log channel.

        Args:
            role: The dialogue role.
            pool: The pool backend name used.
            transcript: The ordered dialogue transcript.
            artifact_manager: Optional ArtifactManager. ``None`` → ``"skipped"``.

        Returns:
            ``"persisted"`` on success, ``"skipped"`` when no artifact_manager,
            ``"error"`` on persistence failure.
        """
        if artifact_manager is None:
            return "skipped"

        try:
            import json as _json

            # Build a dialogue-transcript record for the ArtifactManager.
            # We write it as a JSON artifact under the prompt-audit machinery.
            # The exact artifact class/envelope is owned by the prompt_runtime BC;
            # here we log the raw transcript as a best-effort audit record.
            record: dict[str, object] = {
                "role": role,
                "pool": pool,
                "turn_count": len([t for t in transcript if t.role == "user"]),
                "turns": [
                    {
                        "role": t.role,
                        "content": t.content,
                        "ts": t.ts.isoformat(),
                    }
                    for t in transcript
                ],
            }
            # Use the artifact_manager's write method if it supports raw JSON.
            # If the manager does not support a raw write, we log a warning and
            # return "skipped" — no parallel channel, no crash.
            if hasattr(artifact_manager, "write_raw"):
                artifact_manager.write_raw(
                    "dialogue_transcript",
                    _json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"),
                )
                return "persisted"
            # Fallback: log at DEBUG level (the transcript is in memory via
            # DialogueResult.transcript; formal persistence requires a proper
            # ArtifactClass for dialogue transcripts, which is out of scope).
            logger.debug(
                "DialogueRunner: ArtifactManager does not support write_raw; "
                "transcript logging skipped (role=%r pool=%r turns=%d)",
                role,
                pool,
                len(transcript),
            )
            return "skipped"
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DialogueRunner: transcript persistence failed: %s", exc
            )
            return "error"


__all__ = [
    "DEFAULT_MAX_TURNS",
    "DialogueResult",
    "DialogueRunner",
    "DialogueTurn",
]
