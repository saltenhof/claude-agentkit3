"""Single-lease Hub transport for one W2 corpus batch."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.llm_evaluator.llm_client import (
    ACQUIRE_TIMEOUT_SECONDS,
    MAX_ACQUIRE_RETRIES,
    RELEASE_TIMEOUT_SECONDS,
    LlmClientError,
)
from agentkit.integration_clients.multi_llm_hub.errors import (
    HubAcquireQueuedError,
    HubUnavailableError,
)

if TYPE_CHECKING:
    from agentkit.integration_clients.multi_llm_hub.client import HubClientProtocol
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName, HubSessionLease

logger = logging.getLogger(__name__)
W2_SEND_TIMEOUT_SECONDS = 180.0


class HubBatchSession:
    """Acquire once, send sequentially, and release once for a corpus run."""

    def __init__(
        self,
        hub: HubClientProtocol,
        models: tuple[HubBackendName, ...],
        *,
        owner: str,
    ) -> None:
        """Initialize the unopened batch session."""
        self._hub = hub
        self._models = models
        self._owner = owner
        self._lease: HubSessionLease | None = None

    def open(self) -> None:
        """Acquire one lease containing every configured healthy backend."""
        if self._lease is not None:
            raise LlmClientError("W2 Hub batch session is already open")
        for attempt in range(1, MAX_ACQUIRE_RETRIES + 1):
            try:
                self._lease = self._hub.acquire(
                    owner=self._owner,
                    description="concept authority prose corpus batch",
                    llms=list(self._models),
                    timeout=ACQUIRE_TIMEOUT_SECONDS,
                )
                return
            except HubAcquireQueuedError as exc:
                if attempt == MAX_ACQUIRE_RETRIES:
                    raise LlmClientError(
                        f"W2 Hub batch acquire exhausted {MAX_ACQUIRE_RETRIES} attempts"
                    ) from exc
                time.sleep(min(exc.estimated_wait_seconds or 1.0, 5.0))
        raise LlmClientError("W2 Hub batch acquire did not return a lease")  # pragma: no cover

    def send(self, model: HubBackendName, prompt: str) -> str:
        """Send one prompt with a bounded timeout on the active batch lease."""
        if self._lease is None:
            raise LlmClientError("W2 Hub batch session is not open")
        try:
            messages = self._hub.send(
                session_id=self._lease.session_id, token=self._lease.token,
                message=prompt, target=model, timeout=W2_SEND_TIMEOUT_SECONDS,
            )
        except HubUnavailableError as exc:
            raise LlmClientError(f"W2 Hub batch send unavailable for model={model!r}") from exc
        message = messages.get(model)
        if message is None:
            raise LlmClientError(f"W2 Hub batch returned no response for model={model!r}")
        if message.status != "ok":
            raise LlmClientError(
                f"W2 Hub batch model={model!r} returned status={message.status!r}: {message.text!r}"
            )
        return message.text

    def close(self) -> None:
        """Release the single lease once, swallowing release errors best-effort."""
        lease, self._lease = self._lease, None
        if lease is None:
            return
        try:
            self._hub.release(
                session_id=lease.session_id,
                token=lease.token,
                timeout=RELEASE_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 -- release is explicitly best-effort
            logger.warning("W2 Hub batch release failed for session=%r: %s", lease.session_id, exc)
