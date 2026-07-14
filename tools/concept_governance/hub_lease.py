"""Bounded acquire and best-effort release for W2 Hub epochs."""

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
from agentkit.integration_clients.multi_llm_hub.errors import HubAcquireQueuedError

if TYPE_CHECKING:
    from agentkit.integration_clients.multi_llm_hub.client import HubClientProtocol
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName, HubSessionLease

logger = logging.getLogger(__name__)


def acquire_epoch_lease(
    hub: HubClientProtocol,
    models: tuple[HubBackendName, ...],
    owner: str,
    description: str,
    epoch: int,
) -> HubSessionLease:
    """Acquire exactly one slot for every configured backend in an epoch."""
    for attempt in range(1, MAX_ACQUIRE_RETRIES + 1):
        try:
            lease = hub.acquire(
                owner=owner,
                description=f"{description} epoch {epoch}",
                llms=list(models),
                timeout=ACQUIRE_TIMEOUT_SECONDS,
            )
            if set(lease.llms) != set(models):
                release_epoch_lease(hub, lease)
                raise LlmClientError("W2 Hub epoch lease omitted a configured backend")
            return lease
        except HubAcquireQueuedError as exc:
            if attempt == MAX_ACQUIRE_RETRIES:
                raise LlmClientError(
                    f"W2 Hub epoch acquire exhausted {MAX_ACQUIRE_RETRIES} attempts"
                ) from exc
            time.sleep(min(exc.estimated_wait_seconds or 1.0, 5.0))
    raise LlmClientError("W2 Hub epoch acquire returned no lease")  # pragma: no cover


def release_epoch_lease(hub: HubClientProtocol, lease: HubSessionLease) -> None:
    """Release an epoch lease without hiding the primary run outcome."""
    try:
        hub.release(
            session_id=lease.session_id,
            token=lease.token,
            timeout=RELEASE_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 -- release is explicitly best-effort
        logger.warning("W2 Hub epoch release failed for session=%r: %s", lease.session_id, exc)
