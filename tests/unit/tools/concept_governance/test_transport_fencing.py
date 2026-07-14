"""Stale-epoch fencing tests for the productive W2 Hub boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest
from concept_governance.hub_batch import HubBatchSession
from concept_governance.transport import DEFAULT_MODELS

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.integration_clients.multi_llm_hub.entities import HubMessage, HubSessionLease

if TYPE_CHECKING:
    from agentkit.integration_clients.multi_llm_hub.client import HubClientProtocol
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName


class _FailThenPassHub:
    def __init__(self) -> None:
        self.acquires = 0
        self.releases: list[str] = []

    def acquire(
        self,
        *,
        owner: str,
        description: str,
        llms: list[HubBackendName],
        timeout: float | None = None,
    ) -> HubSessionLease:
        del owner, description, timeout
        self.acquires += 1
        return HubSessionLease(
            session_id=f"epoch-{self.acquires}",
            token=f"token-{self.acquires}",
            llms=llms,
            slots={},
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
        del token, message, targets, timeout
        assert target is not None
        ok = self.acquires > 1
        return {
            target: HubMessage(
                id=session_id,
                session_id=session_id,
                backend=target,
                role="assistant",
                text='{"has_normative_statements":false,"assertions":[]}' if ok else "stuck",
                at=datetime.now(UTC),
                status="ok" if ok else "error",
            )
        }

    def release(self, *, session_id: str, token: str, timeout: float | None = None) -> None:
        del token, timeout
        self.releases.append(session_id)


def test_failed_send_fences_epoch_before_fresh_retry() -> None:
    hub = _FailThenPassHub()
    session = HubBatchSession(
        cast("HubClientProtocol", hub), DEFAULT_MODELS, owner="test", epoch_chunk_limit=2
    )
    session.open()

    with pytest.raises(LlmClientError, match="status='error': 'stuck'"):
        session.send("chatgpt", "prompt")
    response = session.send("chatgpt", "prompt")
    session.checkpoint("chunk-1")
    session.close()

    assert response.startswith("{")
    assert hub.acquires == 2
    assert hub.releases == ["epoch-1", "epoch-2"]
