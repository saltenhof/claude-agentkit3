"""Stale-epoch fencing tests for the productive W2 Hub boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest
from concept_governance.hub_batch import HubBatchSession
from concept_governance.hub_batch_client import HubBatchLlmClient
from concept_governance.transport import DEFAULT_MODELS
from concept_governance.transport_retry import complete_with_transport_retry

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.integration_clients.multi_llm_hub.entities import HubMessage, HubSessionLease

if TYPE_CHECKING:
    from agentkit.integration_clients.multi_llm_hub.client import HubClientProtocol
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName


class _FailThenPassHub:
    def __init__(self) -> None:
        self.acquires = 0
        self.releases: list[str] = []
        self.acquired_models: list[list[HubBackendName]] = []

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
        self.acquired_models.append(llms)
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


class _ProgrammingDefectHub(_FailThenPassHub):
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
        del session_id, token, message, target, targets, timeout
        raise AssertionError("programming defect")


class _CountingBatchClient:
    def __init__(self, session: HubBatchSession) -> None:
        self._client = HubBatchLlmClient(session, "chatgpt")
        self.calls = 0

    def complete(self, *, role: str, prompt: str) -> str:
        self.calls += 1
        return self._client.complete(role=role, prompt=prompt)


def test_failed_send_fences_epoch_before_fresh_retry() -> None:
    hub = _FailThenPassHub()
    session = HubBatchSession(
        cast("HubClientProtocol", hub), DEFAULT_MODELS, owner="test", epoch_chunk_limit=2
    )
    session.open()

    assert hub.acquires == 0

    with pytest.raises(LlmClientError, match="status='error': 'stuck'"):
        session.send("chatgpt", "prompt")
    response = session.send("chatgpt", "prompt")
    session.checkpoint("chunk-1")
    session.close()

    assert response.startswith("{")
    assert hub.acquires == 2
    assert hub.acquired_models == [["chatgpt"], ["chatgpt"]]
    assert hub.releases == ["epoch-1", "epoch-2"]


def test_hub_programming_defect_is_not_reclassified_as_transport() -> None:
    hub = _ProgrammingDefectHub()
    session = HubBatchSession(
        cast("HubClientProtocol", hub), DEFAULT_MODELS, owner="test", epoch_chunk_limit=2
    )
    session.open()

    with pytest.raises(AssertionError, match="programming defect"):
        session.send("chatgpt", "prompt")

    assert hub.acquires == 1


def test_unopened_batch_session_contract_error_is_not_retried() -> None:
    hub = _FailThenPassHub()
    session = HubBatchSession(
        cast("HubClientProtocol", hub), DEFAULT_MODELS, owner="test", epoch_chunk_limit=2
    )
    client = _CountingBatchClient(session)

    with pytest.raises(RuntimeError, match="lifecycle is not open"):
        complete_with_transport_retry(
            client,
            role="concept_authority_prose",
            prompt="prompt",
            backend="chatgpt",
            item_kind="chunk",
            item_id="chunk-1",
        )

    assert hub.acquires == 0
    assert client.calls == 1
