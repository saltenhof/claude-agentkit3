"""LLM-client port for Layer-2 evaluations (FK-34 / FK-11 §11.5.1).

Layer 2 of the QA-subflow (FK-27 §27.5) runs three parallel LLM evaluations
through the :class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`.
The evaluator must not know *which* concrete LLM provider answers a given
role -- that routing is resolved via the injected :class:`RolePoolResolver` port
(owner: AG3-070 for the productive implementation; FK-75 §75.3).

This module defines the **port** (``LlmClient`` protocol), the
``FailClosedLlmClient`` placeholder, the concrete ``HubLlmClient`` adapter
(injectable, fail-closed until a productive ``RolePoolResolver`` is injected),
and the ``RolePoolResolver`` port (FK-75 §75.3).

Quelle:
  - FK-34 -- LLM-Bewertungen-Runtime (StructuredEvaluator, drei Rollen)
  - FK-11 §11.5.1 -- StructuredEvaluator (CheckResult-basiert)
  - FK-34 §34.5.1 -- Fehlerbehandlung (fail-closed: Pool/Antwort-Fehler -> FAIL)
  - FK-11 §11.2.3 -- Acquire/Send/Release-Fehlerprotokoll
  - FK-11 §11.6.1 -- Timeouts (acquire 30s / send 2400s / release 10s)
  - FK-75 §75.3 -- Routing-Owner (Resolver injiziert, nicht im Transport)
"""

from __future__ import annotations

import contextvars
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.verify_system.errors import VerifySystemError

if TYPE_CHECKING:
    from agentkit.multi_llm_hub.client import HubClientProtocol
    from agentkit.multi_llm_hub.entities import HubBackendName, HubSessionLease

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-evaluation deadline ContextVar (ERROR 1 concurrency fix, AG3-065 rem-4)
# ---------------------------------------------------------------------------

#: Per-evaluation monotonic deadline (ContextVar, concurrency-safe).
#:
#: Each :meth:`StructuredEvaluator.evaluate` call sets this ContextVar at
#: entry and resets it in a ``finally`` block via :func:`bind_eval_deadline`.
#: Because :class:`~concurrent.futures.ThreadPoolExecutor` *copies* the
#: calling context into each worker thread at submit-time, and each
#: ``evaluate()`` resets the var on exit, concurrent roles on SHARED threads
#: never see each other's deadline value — no instance-attribute race.
#:
#: :class:`HubLlmClient.complete` reads this var (falling back to a fresh
#: per-call budget when unset). The ``LlmClient`` Protocol port
#: ``complete(*, role, prompt)->str`` stays unchanged.
_EVAL_DEADLINE_CV: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "agentkit_eval_deadline", default=None
)

# ---------------------------------------------------------------------------
# Per-operation timeout constants (FK-11 §11.6.1)
# ---------------------------------------------------------------------------

#: Acquire operation timeout in seconds (FK-11 §11.6.1).
ACQUIRE_TIMEOUT_SECONDS: float = 30.0

#: Send operation timeout in seconds (FK-11 §11.6.1 — LLM can take a long time).
SEND_TIMEOUT_SECONDS: float = 2400.0

#: Release operation timeout in seconds (FK-11 §11.6.1).
RELEASE_TIMEOUT_SECONDS: float = 10.0

#: Total evaluator-call timeout in seconds across all retries (FK-11 §11.6.1).
TOTAL_TIMEOUT_SECONDS: float = 2500.0

#: Maximum number of acquire retries when the Hub returns a queued response.
#: (FK-11 §11.6.1 Zeile 553/556: "max 5 Versuche")
MAX_ACQUIRE_RETRIES: int = 5

#: Best-effort release floor in seconds (ERROR 2 fix, AG3-065 rem-4): even
#: when the evaluator budget is exhausted, release is attempted with at
#: least this much time so the hub can ACK the release and not leak sessions.
_RELEASE_FLOOR_SECONDS: float = 1.0


class LlmClientError(VerifySystemError):
    """Raised when the LLM transport itself fails (FK-34 §34.5.1).

    Distinct from
    :class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluatorError`
    (which signals an *invalid response shape*): this error means the call did
    not produce any usable text at all (pool unreachable, timeout, empty
    completion). Both are fail-closed -- the evaluator never silently treats a
    failed LLM call as a PASS (FK-34 §34.5.1: "Jedes FAIL ist fail-closed").
    """


class LoginRequiredError(LlmClientError):
    """Raised when the Hub pool requires operator login (FK-11 §11.2.3 Zeile 191).

    Distinct transport exit: the operator MUST log in before the pipeline can
    proceed. Subclasses :class:`LlmClientError` so existing fail-closed catch
    statemements (Layer-2 integration) continue to block -- the distinct TYPE
    carries the information needed for a future pipeline-pause wiring.

    The Pipeline-Pause wiring itself (new PauseReason member + phase-runner
    PAUSED state) is an open, uncut concept gap (story §2.2 / §7); this class
    delivers only the typed, abgreifbaren transport exit.

    Attributes:
        operator_hint: Human-readable hint indicating which pool needs login.
    """

    def __init__(self, message: str, *, operator_hint: str = "") -> None:
        super().__init__(message)
        self.operator_hint: str = operator_hint


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
            LoginRequiredError: If the Hub signals that operator login is
                required. Subclass of :class:`LlmClientError` — existing
                fail-closed catches block, but the distinct type is abgreifbar.
        """
        ...


@runtime_checkable
class RolePoolResolver(Protocol):
    """Port resolving a reviewer role to a Hub backend pool name (FK-75 §75.3).

    The productive implementation (parsing ``llm_roles`` from config) is owned
    by AG3-070. AG3-065 defines this port and consumes it — no config-parsing
    logic here.

    Missing resolver / no pool for a role → :class:`LlmClientError` (fail-closed,
    no default pool). The verify transport NEVER falls back silently.
    """

    def resolve(self, role: str) -> HubBackendName:
        """Resolve a reviewer role to a Hub backend pool name.

        Args:
            role: The reviewer role wire-string (e.g. ``"qa_review"``).

        Returns:
            The :data:`~agentkit.multi_llm_hub.entities.HubBackendName` for
            the given role.

        Raises:
            LlmClientError: If no pool is configured for the role
                (fail-closed, no default pool).
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


class HubLlmClient:
    """Concrete LLM transport adapter onto the Multi-LLM Hub (FK-11 / AG3-065).

    Implements the narrow :class:`LlmClient` port (``complete(*, role, prompt)
    -> str``) by orchestrating acquire → send → release over the injected
    :class:`~agentkit.multi_llm_hub.client.HubClientProtocol`.

    Role → pool routing is delegated exclusively to the injected
    :class:`RolePoolResolver` port (FK-75 §75.3). No config-parsing here.

    Error protocol (FK-11 §11.2.3):
    - Queued-acquire: re-acquire with the same owner up to ``MAX_ACQUIRE_RETRIES``
      times; exhaustion → :class:`LlmClientError`.
    - Send-timeout: exactly 1 retry with a new slot.
    - ``lease_expired`` / session-not-found: 1 re-acquire + 1 send.
    - Login-required: :class:`LoginRequiredError` (subclass, abgreifbar).
    - Pool unreachable / rejected: :class:`LlmClientError` (fail-closed).
    - Release: always in a ``finally`` block.

    Attributes:
        _hub: The Hub client (protocol, injectable test double).
        _resolver: Role → pool resolver (protocol).
        _owner: Stable owner string identifying this agent.
    """

    def __init__(
        self,
        hub: HubClientProtocol,
        resolver: RolePoolResolver,
        *,
        owner: str = "agentkit-verify",
    ) -> None:
        """Initialise the Hub LLM adapter.

        Args:
            hub: The Hub client to acquire/send/release through.
            resolver: The role→pool resolver port. Missing pool → fail-closed.
            owner: The stable owner identifier embedded in the session
                description (defaults to ``"agentkit-verify"``).
        """
        self._hub = hub
        self._resolver = resolver
        self._owner = owner

    def set_eval_deadline(self, deadline: float) -> None:
        """Set the evaluator-level monotonic deadline via the per-evaluation ContextVar.

        **Deprecated direct caller** — the preferred path is
        :func:`~agentkit.verify_system.llm_evaluator.llm_client.bind_eval_deadline`
        used by :class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`
        which resets the ContextVar in a ``finally`` block (concurrency-safe).
        Calling this method directly from test code is safe for single-threaded
        unit tests; the ContextVar value is visible only in the calling thread's
        context copy.

        The ``LlmClient`` Protocol port ``complete(*, role, prompt)->str`` stays
        unchanged; this method is an optional capability on the concrete class.

        Args:
            deadline: Monotonic-clock deadline (from ``time.monotonic()``).
        """
        _EVAL_DEADLINE_CV.set(deadline)

    def complete(self, *, role: str, prompt: str) -> str:
        """Run a single LLM completion via the Multi-LLM Hub.

        Implements FK-11 §11.2.3 error protocol:
        acquire → send → release (in finally), with queued-acquire retry,
        send-timeout retry with new slot, and lease-expired re-acquire.

        The TOTAL_TIMEOUT_SECONDS budget is maintained from the moment this
        method is entered; every acquire/send/release sub-operation is
        clamped to min(per_op_constant, remaining_budget). A retry is
        refused (fail-closed → LlmClientError) when the remaining budget
        cannot cover the next operation.

        When an evaluator-level deadline has been set via :meth:`set_eval_deadline`,
        the per-call deadline is further clamped to the remaining evaluator budget
        (NEAR-BOUNDARY fix, ERROR 1).

        Args:
            role: The reviewer role wire-string.
            prompt: The materialized prompt text.

        Returns:
            The raw response text from the Hub backend.

        Raises:
            LlmClientError: On transport failure, pool unreachable,
                exhausted retries, or TOTAL_TIMEOUT_SECONDS exceeded.
            LoginRequiredError: If the Hub requires operator login.
        """
        from agentkit.multi_llm_hub.errors import (
            HubSessionNotFoundError,
            HubUnavailableError,
            MultiLlmHubError,
        )

        pool = self._resolver.resolve(role)
        description = f"agentkit-verify role={role}"
        # Clamp deadline to the per-evaluation deadline from the ContextVar
        # (concurrency-safe NEAR-BOUNDARY fix, ERROR 1, AG3-065 rem-4):
        # _EVAL_DEADLINE_CV is set per-evaluation in StructuredEvaluator.evaluate()
        # and reset in finally, so concurrent roles on the same ThreadPoolExecutor
        # thread never share a deadline value — each call sees only its own
        # evaluation's deadline.
        fresh_deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
        cv_deadline = _EVAL_DEADLINE_CV.get()
        deadline = min(fresh_deadline, cv_deadline) if cv_deadline is not None else fresh_deadline

        lease = self._acquire_with_queue_retry(pool, description, deadline=deadline)
        send_retries_used = 0
        try:
            return self._send_with_retry(
                lease=lease,
                pool=pool,
                prompt=prompt,
                description=description,
                send_retries_used=send_retries_used,
                deadline=deadline,
            )
        except (HubSessionNotFoundError, HubUnavailableError, MultiLlmHubError) as exc:
            raise LlmClientError(
                f"HubLlmClient send failed for role={role!r} pool={pool!r}: {exc}"
            ) from exc
        finally:
            self._safe_release(lease.session_id, lease.token, deadline=deadline)

    def _acquire_with_queue_retry(
        self,
        pool: HubBackendName,
        description: str,
        *,
        deadline: float,
    ) -> HubSessionLease:
        """Acquire a session lease, retrying up to MAX_ACQUIRE_RETRIES if queued.

        Each attempt's timeout is clamped to ``min(ACQUIRE_TIMEOUT_SECONDS,
        remaining_budget)``. A new attempt is refused with
        :class:`LlmClientError` when the remaining budget is exhausted.

        Args:
            pool: The target pool backend.
            description: Human-readable session description.
            deadline: Monotonic clock deadline for the overall call budget.

        Returns:
            A granted :class:`~agentkit.multi_llm_hub.entities.HubSessionLease`.

        Raises:
            LlmClientError: After MAX_ACQUIRE_RETRIES exhaustion, budget
                exhaustion, or Hub error.
        """
        from agentkit.multi_llm_hub.errors import (
            HubAcquireQueuedError,
            HubLoginRequiredError,
            MultiLlmHubError,
        )

        for attempt in range(1, MAX_ACQUIRE_RETRIES + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LlmClientError(
                    f"HubLlmClient TOTAL_TIMEOUT_SECONDS exhausted before acquire "
                    f"(attempt {attempt}, pool={pool!r}) — fail-closed"
                )
            effective_timeout = min(ACQUIRE_TIMEOUT_SECONDS, remaining)
            try:
                return self._hub.acquire(
                    owner=self._owner,
                    description=description,
                    llms=[pool],
                    timeout=effective_timeout,
                )
            except HubAcquireQueuedError as exc:
                wait = exc.estimated_wait_seconds
                logger.info(
                    "HubLlmClient acquire queued (attempt %d/%d) pool=%r est_wait=%s",
                    attempt,
                    MAX_ACQUIRE_RETRIES,
                    pool,
                    wait,
                )
                if attempt == MAX_ACQUIRE_RETRIES:
                    raise LlmClientError(
                        f"HubLlmClient acquire exhausted {MAX_ACQUIRE_RETRIES} "
                        f"retries (pool={pool!r} always queued) — fail-closed"
                    ) from exc
                # Brief sleep between retries (not specified in FK-11 but
                # necessary to avoid tight-loop hammering the Hub).
                time.sleep(min(wait or 1.0, 5.0))
            except HubLoginRequiredError as exc:
                raise LoginRequiredError(
                    f"Hub pool {pool!r} requires operator login",
                    operator_hint=f"pool={pool!r}: login required",
                ) from exc
            except MultiLlmHubError as exc:
                raise LlmClientError(
                    f"HubLlmClient acquire failed for pool={pool!r}: {exc}"
                ) from exc
        # Should never reach here; kept for type-checker.
        raise LlmClientError(f"HubLlmClient acquire unreachable (pool={pool!r})")  # pragma: no cover

    def _send_with_retry(
        self,
        *,
        lease: HubSessionLease,
        pool: HubBackendName,
        prompt: str,
        description: str,
        send_retries_used: int,
        deadline: float,
    ) -> str:
        """Send the prompt, retrying once on timeout or lease-expired.

        Handles FK-11 §11.2.3 send error protocol:
        - Timeout → release, new acquire (with queue handling), second send.
        - lease_expired/session-not-found → new acquire, second send.
        Both count under the send max-1 retry budget (hard cap).

        Each send is clamped to ``min(SEND_TIMEOUT_SECONDS, remaining_budget)``.
        A retry is refused when the remaining budget cannot cover the next
        operation (fail-closed → :class:`LlmClientError`).

        Args:
            lease: The current active session lease.
            pool: The target pool backend.
            prompt: The materialized prompt.
            description: Session description for re-acquire.
            send_retries_used: Number of send retries already used.
            deadline: Monotonic time deadline for the entire call budget.

        Returns:
            The raw response text.

        Raises:
            LlmClientError: On exhausted retries, budget exhaustion, or
                unrecoverable Hub error.
            LoginRequiredError: On Hub login-required error.
        """
        from agentkit.multi_llm_hub.errors import (
            HubLoginRequiredError,
            HubSessionNotFoundError,
            HubUnavailableError,
            MultiLlmHubError,
        )

        try:
            return self._do_send(lease, pool, prompt, deadline=deadline)
        except HubLoginRequiredError as exc:
            raise LoginRequiredError(
                f"Hub pool {pool!r} requires operator login during send",
                operator_hint=f"pool={pool!r}: login required",
            ) from exc
        except (HubUnavailableError, HubSessionNotFoundError) as exc:
            if send_retries_used >= 1:
                raise LlmClientError(
                    f"HubLlmClient send failed after max retries for pool={pool!r}: {exc}"
                ) from exc
            # One retry: release old slot, acquire new, send again.
            self._safe_release(lease.session_id, lease.token, deadline=deadline)
            remaining_after_release = deadline - time.monotonic()
            # Need budget for at least acquire + send.
            if remaining_after_release <= ACQUIRE_TIMEOUT_SECONDS:
                raise LlmClientError(
                    f"HubLlmClient TOTAL_TIMEOUT_SECONDS budget insufficient for "
                    f"retry acquire+send (remaining={remaining_after_release:.1f}s, "
                    f"pool={pool!r}) — fail-closed"
                ) from exc
            new_lease = self._acquire_with_queue_retry(pool, description, deadline=deadline)
            try:
                return self._do_send(new_lease, pool, prompt, deadline=deadline)
            except HubLoginRequiredError as exc2:
                raise LoginRequiredError(
                    f"Hub pool {pool!r} requires operator login during retry send",
                    operator_hint=f"pool={pool!r}: login required",
                ) from exc2
            except (HubUnavailableError, HubSessionNotFoundError, MultiLlmHubError) as exc2:
                raise LlmClientError(
                    f"HubLlmClient retry send also failed for pool={pool!r}: {exc2}"
                ) from exc2
            finally:
                self._safe_release(new_lease.session_id, new_lease.token, deadline=deadline)
        except MultiLlmHubError as exc:
            raise LlmClientError(
                f"HubLlmClient send hub-error for pool={pool!r}: {exc}"
            ) from exc

    def _do_send(
        self,
        lease: HubSessionLease,
        pool: HubBackendName,
        prompt: str,
        *,
        deadline: float,
    ) -> str:
        """Execute a single send and extract the text response.

        The send timeout is clamped to ``min(SEND_TIMEOUT_SECONDS,
        remaining_budget)``; if the remaining budget has already expired,
        :class:`LlmClientError` is raised immediately (fail-closed).

        Args:
            lease: Active session lease.
            pool: Target backend pool.
            prompt: Prompt text.
            deadline: Monotonic clock deadline for the overall call budget.

        Returns:
            The raw response text from the pool backend.

        Raises:
            LlmClientError: If the response is missing, has an error status,
                or the total budget is already exhausted.
        """
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LlmClientError(
                f"HubLlmClient TOTAL_TIMEOUT_SECONDS exhausted before send "
                f"(pool={pool!r}) — fail-closed"
            )
        effective_send_timeout = min(SEND_TIMEOUT_SECONDS, remaining)
        messages = self._hub.send(
            session_id=lease.session_id,
            token=lease.token,
            message=prompt,
            target=pool,
            timeout=effective_send_timeout,
        )
        msg = messages.get(pool)
        if msg is None:
            raise LlmClientError(
                f"HubLlmClient: no response from pool={pool!r} in send reply"
            )
        if msg.status == "error":
            raise LlmClientError(
                f"HubLlmClient: pool={pool!r} returned error status: {msg.text!r}"
            )
        return msg.text

    def _safe_release(
        self,
        session_id: str,
        token: str,
        *,
        deadline: float | None = None,
    ) -> None:
        """Release the session lease, swallowing errors (best-effort).

        FK-11 §11.2.3 Zeile 192: release is always attempted, even on error.
        Failures here are logged but never re-raised.

        The release timeout is clamped to ``min(RELEASE_TIMEOUT_SECONDS,
        remaining_budget)`` when a ``deadline`` is provided (ERROR 2 fix,
        AG3-065 rem-4): near a TOTAL boundary, acquire/send are already
        clamped but an unclamped release could still add up to 10s beyond
        the evaluator budget. A best-effort floor of 1.0s is preserved so
        release is never passed a zero/negative timeout that could cause
        the hub transport to hang or error without completing the release
        (release MUST always be attempted in ``finally``).

        Args:
            session_id: Session identifier.
            token: Authentication token.
            deadline: Monotonic-clock deadline for the overall call budget.
                When ``None`` (legacy call-site without deadline), falls
                back to the full ``RELEASE_TIMEOUT_SECONDS``.
        """
        if deadline is not None:
            remaining = deadline - time.monotonic()
            effective_timeout = max(
                _RELEASE_FLOOR_SECONDS,
                min(RELEASE_TIMEOUT_SECONDS, remaining),
            )
        else:
            effective_timeout = RELEASE_TIMEOUT_SECONDS
        try:
            self._hub.release(
                session_id=session_id,
                token=token,
                timeout=effective_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "HubLlmClient release failed for session=%r: %s", session_id, exc
            )


def bind_eval_deadline(deadline: float) -> contextvars.Token[float | None]:
    """Bind the per-evaluation deadline in the current execution context.

    Called by :meth:`StructuredEvaluator.evaluate` at entry; the returned
    token MUST be reset in a ``finally`` block via
    ``_EVAL_DEADLINE_CV.reset(token)`` so the deadline never leaks to
    subsequent tasks on the same thread.

    Because :class:`~concurrent.futures.ThreadPoolExecutor` copies the
    calling context into each worker thread at submit-time, but tasks on
    the same reused thread share the same context copy, leakage is only
    prevented by explicit reset. This function sets the var and returns
    the token needed for reset.

    Args:
        deadline: Monotonic-clock deadline for the whole ``evaluate()``
            call (``time.monotonic() + TOTAL_TIMEOUT_SECONDS``).

    Returns:
        A :class:`~contextvars.Token` that must be passed to
        ``_EVAL_DEADLINE_CV.reset(token)`` in the ``finally`` block.
    """
    return _EVAL_DEADLINE_CV.set(deadline)


__all__ = [
    "ACQUIRE_TIMEOUT_SECONDS",
    "FailClosedLlmClient",
    "HubLlmClient",
    "LlmClient",
    "LlmClientError",
    "LoginRequiredError",
    "MAX_ACQUIRE_RETRIES",
    "RELEASE_TIMEOUT_SECONDS",
    "RolePoolResolver",
    "SEND_TIMEOUT_SECONDS",
    "TOTAL_TIMEOUT_SECONDS",
    "_EVAL_DEADLINE_CV",
    "bind_eval_deadline",
]
