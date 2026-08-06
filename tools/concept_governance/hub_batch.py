"""Epoch-rotating single-backend Hub transport for governance batches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError
from concept_governance.hub_lease import acquire_epoch_lease, release_epoch_lease
from concept_governance.transport_retry import TRANSPORT_RETRYABLE_EXCEPTIONS

if TYPE_CHECKING:
    from agentkit.integration_clients.multi_llm_hub.client import HubClientProtocol
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName, HubSessionLease

GOVERNANCE_SEND_TIMEOUT_SECONDS = 180.0
GOVERNANCE_EPOCH_ITEM_LIMIT = 4


class HubBatchSession:
    """Use one lazy routed-backend lease per bounded, checkpointed epoch."""

    def __init__(
        self,
        hub: HubClientProtocol,
        models: tuple[HubBackendName, ...],
        *,
        owner: str,
        description: str = "concept authority prose",
        epoch_chunk_limit: int | None = None,
    ) -> None:
        """Initialize the closed epoch lifecycle."""
        limit = GOVERNANCE_EPOCH_ITEM_LIMIT if epoch_chunk_limit is None else epoch_chunk_limit
        if limit < 1:
            raise ValueError("epoch_chunk_limit must be positive")
        self._hub = hub
        self._models = models
        self._owner = owner
        self._description = description
        self._limit = limit
        self._lease: HubSessionLease | None = None
        self._leased_model: HubBackendName | None = None
        self._active = False
        self._epoch = 0
        self._completed = 0
        self._fence = 0

    def open(self) -> None:
        """Start the run without requiring every routed backend to be ready."""
        if self._active:
            raise RuntimeError("governance Hub epoch lifecycle is already open")
        self._active = True

    def send(self, model: HubBackendName, prompt: str) -> str:
        """Send on the active epoch and fence any failed or stale response."""
        if not self._active:
            raise RuntimeError("governance Hub epoch lifecycle is not open")
        if model not in self._models:
            raise ValueError(f"governance Hub epoch model={model!r} is not configured")
        if self._lease is not None and self._leased_model != model:
            self._retire(self._lease)
        if self._lease is None:
            self._acquire(model)
        lease = self._lease
        assert lease is not None
        fence = self._fence
        try:
            messages = self._hub.send(
                session_id=lease.session_id,
                token=lease.token,
                message=prompt,
                target=model,
                timeout=GOVERNANCE_SEND_TIMEOUT_SECONDS,
            )
            message = messages.get(model)
            if message is None or message.status != "ok" or not message.text:
                detail = (
                    "missing response"
                    if message is None
                    else f"status={message.status!r}: {message.text!r}"
                )
                raise LlmClientError(
                    f"governance Hub epoch model={model!r} returned {detail}"
                )
        except TRANSPORT_RETRYABLE_EXCEPTIONS as exc:
            self._retire(lease)
            if isinstance(exc, LlmClientError):
                raise
            raise LlmClientError(
                f"governance Hub epoch send failed for model={model!r}"
            ) from exc
        if fence != self._fence or self._lease is not lease:
            raise LlmClientError("governance Hub epoch response was fenced as stale")
        return message.text

    def checkpoint(self, chunk_id: str) -> None:
        """Commit a processed chunk and rotate at the bounded epoch limit."""
        del chunk_id
        if self._lease is None:
            raise RuntimeError("governance Hub checkpoint has no active epoch lease")
        self._completed += 1
        if self._completed >= self._limit:
            self._retire(self._lease)

    def close(self) -> None:
        """Fence the lifecycle and release its current epoch best-effort."""
        self._active = False
        if self._lease is not None:
            self._retire(self._lease)

    def _acquire(self, model: HubBackendName) -> None:
        self._epoch += 1
        self._lease = acquire_epoch_lease(
            self._hub, model, self._owner, self._description, self._epoch
        )
        self._leased_model = model
        self._completed = 0
        self._fence += 1

    def _retire(self, lease: HubSessionLease) -> None:
        if self._lease is lease:
            self._lease = None
            self._leased_model = None
        self._fence += 1
        release_epoch_lease(self._hub, lease)
