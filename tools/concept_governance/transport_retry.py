"""Bounded retry for unanswered concept-governance evaluations."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.integration_clients.multi_llm_hub.errors import MultiLlmHubError

if TYPE_CHECKING:
    from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClient

logger = logging.getLogger(__name__)

# Four total attempts span the measured 32-second transient window while
# remaining a fixed, non-configurable bound. A response ends retry eligibility.
TRANSPORT_RETRY_DELAYS_SECONDS: tuple[float, ...] = (5.0, 10.0, 20.0)
TRANSPORT_MAX_ATTEMPTS = len(TRANSPORT_RETRY_DELAYS_SECONDS) + 1
TRANSPORT_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    LlmClientError,
    MultiLlmHubError,
    ConnectionError,
    TimeoutError,
)


class EvaluationTransportExhaustedError(LlmClientError):
    """Name a transport-only retry exhaustion with its exact evaluation locus."""

    def __init__(
        self,
        *,
        backend: str,
        item_kind: str,
        item_id: str,
        attempts: int,
        cause: Exception,
    ) -> None:
        """Capture the backend, locus, attempt count, and final transport cause."""
        message = (
            "evaluation transport retry exhausted: "
            f"backend={backend!r} {item_kind}={item_id!r} attempts={attempts} "
            f"cause={type(cause).__name__}: {cause}"
        )
        super().__init__(message)
        self.backend = backend
        self.item_kind = item_kind
        self.item_id = item_id
        self.attempts = attempts
        self.cause = cause


def complete_with_transport_retry(
    llm_client: LlmClient,
    *,
    role: str,
    prompt: str,
    backend: str,
    item_kind: str,
    item_id: str,
) -> str:
    """Retry only calls that produced no response, using one pinned prompt."""
    for attempt in range(1, TRANSPORT_MAX_ATTEMPTS + 1):
        try:
            return llm_client.complete(role=role, prompt=prompt)
        except TRANSPORT_RETRYABLE_EXCEPTIONS as exc:
            if attempt == TRANSPORT_MAX_ATTEMPTS:
                raise EvaluationTransportExhaustedError(
                    backend=backend,
                    item_kind=item_kind,
                    item_id=item_id,
                    attempts=attempt,
                    cause=exc,
                ) from exc
            delay = TRANSPORT_RETRY_DELAYS_SECONDS[attempt - 1]
            logger.warning(
                "evaluation transport retry: backend=%r %s=%r "
                "failed_attempt=%d/%d delay_seconds=%.1f cause=%s: %s",
                backend,
                item_kind,
                item_id,
                attempt,
                TRANSPORT_MAX_ATTEMPTS,
                delay,
                type(exc).__name__,
                exc,
            )
            time.sleep(delay)
    raise AssertionError("bounded transport retry loop returned no outcome")  # pragma: no cover
