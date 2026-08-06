"""Bounded epoch lifecycle tests for productive W2 Hub transport."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from concept_governance.chunks import load_chunks
from concept_governance.hub_batch import GOVERNANCE_SEND_TIMEOUT_SECONDS
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
    def __init__(self, *, omit_first_lease_backend: bool = False) -> None:
        self.acquire_calls = 0
        self.release_calls = 0
        self.send_calls = 0
        self.send_timeout: float | None = None
        self.acquired_models: list[list[HubBackendName]] = []
        self.sent_sessions: list[str] = []
        self.session_models: dict[str, tuple[HubBackendName, ...]] = {}
        self.omit_first_lease_backend = omit_first_lease_backend

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
        session_id = f"batch-{self.acquire_calls}"
        self.session_models[session_id] = tuple(llms)
        leased_models = [] if self.omit_first_lease_backend and self.acquire_calls == 1 else llms
        return HubSessionLease(
            session_id=session_id,
            token=f"token-{self.acquire_calls}",
            llms=leased_models,
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
        assert self.session_models[session_id] == (target,)
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


def test_run_lazily_leases_only_the_backend_routed_to_each_evaluation(
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
    assert hub.acquire_calls >= 1
    assert all(len(models) == 1 for models in hub.acquired_models)
    assert {models[0] for models in hub.acquired_models} <= set(DEFAULT_MODELS)
    assert hub.send_calls == len(load_chunks(concept))
    assert hub.send_timeout == GOVERNANCE_SEND_TIMEOUT_SECONDS
    assert hub.release_calls == hub.acquire_calls


def test_omitted_routed_backend_is_retried_as_transport_without_pool_wide_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)
    hub = _RecordingHub(omit_first_lease_backend=True)
    monkeypatch.setenv(MODEL_ENV, "gemini")
    delays: list[float] = []
    monkeypatch.setattr("concept_governance.transport_retry.time.sleep", delays.append)
    evaluator = build_hub_evaluator(cast("HubClientProtocol", hub))

    result = run_authority_check(concept, baseline, evaluator)

    assert result.ok
    assert hub.acquired_models == [["gemini"], ["gemini"]]
    assert hub.send_calls == 1
    assert hub.release_calls == 2
    assert delays == [5.0]
