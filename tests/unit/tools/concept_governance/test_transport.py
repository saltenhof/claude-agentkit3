"""Bounded epoch lifecycle tests for productive W2 Hub transport."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from concept_governance.chunks import load_chunks
from concept_governance.hub_batch import W2_SEND_TIMEOUT_SECONDS
from concept_governance.runner import run_authority_check
from concept_governance.transport import DEFAULT_MODELS, MODEL_ENV, build_hub_evaluator
from tests.unit.tools.concept_governance.helpers import write_doc, write_empty_baseline

from agentkit.integration_clients.multi_llm_hub.entities import HubMessage, HubSessionLease

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from agentkit.integration_clients.multi_llm_hub.client import HubClientProtocol
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName


class _RecordingHub:
    def __init__(self) -> None:
        self.acquire_calls = 0
        self.release_calls = 0
        self.send_calls = 0
        self.send_timeout: float | None = None
        self.acquired_models: list[list[HubBackendName]] = []
        self.sent_sessions: list[str] = []

    def acquire(
        self,
        *,
        owner: str,
        description: str,
        llms: list[HubBackendName],
        timeout: float | None = None,
    ) -> HubSessionLease:
        del owner, description, timeout
        self.acquire_calls += 1
        self.acquired_models.append(llms)
        return HubSessionLease(
            session_id=f"batch-{self.acquire_calls}",
            token=f"token-{self.acquire_calls}",
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
        del token, message, targets
        assert target is not None
        self.send_calls += 1
        self.send_timeout = timeout
        self.sent_sessions.append(session_id)
        response = '{"has_normative_statements":false,"assertions":[]}'
        return {
            target: HubMessage(
                id=f"message-{self.send_calls}", session_id=session_id, backend=target,
                role="assistant", text=response, at=datetime.now(UTC), status="ok",
            )
        }

    def release(self, *, session_id: str, token: str, timeout: float | None = None) -> None:
        del session_id, token, timeout
        self.release_calls += 1


def test_run_uses_one_multi_backend_lease_per_bounded_epoch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    for index in range(5):
        write_doc(concept, f"owner-{index}.md", f"OWNER-{index}", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)
    hub = _RecordingHub()
    monkeypatch.delenv(MODEL_ENV, raising=False)
    evaluator = build_hub_evaluator(cast("HubClientProtocol", hub), epoch_chunk_limit=2)

    result = run_authority_check(concept, baseline, evaluator, parallelism=evaluator.parallelism)

    assert result.ok
    assert hub.acquire_calls == 3
    assert hub.acquired_models == [list(DEFAULT_MODELS)] * 3
    assert hub.send_calls == len(load_chunks(concept))
    assert hub.sent_sessions == ["batch-1", "batch-1", "batch-2", "batch-2", "batch-3"]
    assert hub.send_timeout == W2_SEND_TIMEOUT_SECONDS
    assert hub.release_calls == 3
