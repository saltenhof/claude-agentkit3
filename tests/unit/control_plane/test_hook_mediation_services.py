"""Unit tests for the AG3-129 hook-mediation services, client and REST store.

Fast, backend-free coverage of the server-side services and the hook-side client
using first-class in-memory fakes (not mocks): a fake guard-counter repository,
a fake worker-health repository, and a fake control-plane transport.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.guard_counter import (
    ControlPlaneGuardCounterService,
)
from agentkit.backend.control_plane.models import (
    GuardCounterMutationRequest,
    WorkerHealthSaveAccepted,
    WorkerHealthStateResponse,
)
from agentkit.backend.control_plane.worker_health import (
    ControlPlaneWorkerHealthService,
)
from agentkit.backend.implementation.worker_health.models import AgentHealthState
from agentkit.backend.implementation.worker_health.rest_repository import (
    RestWorkerHealthRepository,
)
from agentkit.backend.state_backend.store.guard_counter_repository import (
    GuardCounterRecordOutcome,
)
from agentkit.harness_client.projectedge.governance_client import GovernanceEdgeClient

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentkit.backend.kpi_analytics.fact_store.models import GuardInvocationCounter

_NOW = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Guard-counter service
# ---------------------------------------------------------------------------


class _FakeGuardCounterRepo:
    """First-class in-memory atomic guard-counter store (counter + idempotency)."""

    def __init__(self) -> None:
        self.upserts: list[tuple[str, str, str, bool]] = []
        self.housekeeping_calls = 0
        self._idem: dict[str, tuple[str, dict[str, object]]] = {}

    def upsert_invocation(
        self, *, project_key: str, story_id: str, guard_key: str,
        week_start: str, blocked: bool, updated_at: datetime,
    ) -> None:
        self.upserts.append((project_key, story_id, guard_key, blocked))

    def record_invocation_idempotent(
        self, *, op_id: str, body_hash: str, result_payload: dict[str, object],
        project_key: str, story_id: str, guard_key: str, week_start: str,
        blocked: bool, updated_at: datetime, created_at: datetime,
        correlation_id: str = "",
    ) -> GuardCounterRecordOutcome:
        existing = self._idem.get(op_id)
        if existing is not None:
            if existing[0] != body_hash:
                return GuardCounterRecordOutcome(status="mismatch")
            return GuardCounterRecordOutcome(
                status="replayed", cached_result=dict(existing[1])
            )
        # Atomic in the real adapter; here counter + key move together.
        self.upserts.append((project_key, story_id, guard_key, blocked))
        self._idem[op_id] = (body_hash, dict(result_payload))
        return GuardCounterRecordOutcome(status="recorded")

    def read_counters_for_story_before_week(
        self, project_key: str, story_id: str, week_start: str
    ) -> list[GuardInvocationCounter]:
        return []

    def delete_counters_for_story_before_week(
        self, project_key: str, story_id: str, week_start: str
    ) -> int:
        return 0

    def read_counters_stale(self, cutoff: datetime) -> list[GuardInvocationCounter]:
        self.housekeeping_calls += 1
        return []

    def delete_counters_stale(self, cutoff: datetime) -> int:
        return 0

    # Unused reader methods to satisfy the Protocol surface.
    def read_counters_for_story(
        self, project_key: str, story_id: str
    ) -> list[GuardInvocationCounter]:
        return []

    def delete_counters_for_story(self, project_key: str, story_id: str) -> int:
        return 0


def _guard_counter_service(
    repo: _FakeGuardCounterRepo,
) -> ControlPlaneGuardCounterService:
    return ControlPlaneGuardCounterService(store_factory=lambda: repo)


def _record_request(*, op_id: str = "op-fixed-1", blocked: bool = True) -> GuardCounterMutationRequest:
    return GuardCounterMutationRequest(
        operation="record",
        occurred_at=_NOW,
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-129",
        guard_key="orchestrator_guard",
        blocked=blocked,
    )


def test_guard_counter_service_record() -> None:
    repo = _FakeGuardCounterRepo()
    accepted = _guard_counter_service(repo).apply(_record_request())

    assert accepted.operation == "record"
    assert repo.upserts == [("tenant-a", "AG3-129", "orchestrator_guard", True)]


def test_guard_counter_service_housekeeping() -> None:
    repo = _FakeGuardCounterRepo()
    accepted = _guard_counter_service(repo).apply(
        GuardCounterMutationRequest(
            operation="housekeeping", occurred_at=_NOW, op_id="op-housekeeping-001"
        )
    )

    assert accepted.operation == "housekeeping"
    assert repo.housekeeping_calls == 1


def test_guard_counter_replayed_op_id_does_not_double_count() -> None:
    # FK-91 §91.1a Regel 5 (FUND 2): a replayed op_id is processed exactly once --
    # the counter is NOT incremented a second time.
    repo = _FakeGuardCounterRepo()
    service = _guard_counter_service(repo)

    first = service.apply(_record_request())
    second = service.apply(_record_request())  # same op_id + body -> replay

    assert first.operation == "record"
    assert second.operation == "record"
    # Exactly ONE upsert despite two applies with the same op_id.
    assert repo.upserts == [("tenant-a", "AG3-129", "orchestrator_guard", True)]


def test_guard_counter_distinct_op_ids_both_count() -> None:
    # A fresh op_id per request (the default factory) is NOT deduped.
    repo = _FakeGuardCounterRepo()
    service = _guard_counter_service(repo)
    service.apply(_record_request(op_id="op-a"))
    service.apply(_record_request(op_id="op-b"))
    assert len(repo.upserts) == 2


def test_guard_counter_same_op_id_different_body_raises_mismatch() -> None:
    # FUND 1: a reused op_id with a DIFFERENT body hash is a fail-closed conflict,
    # NOT a silent replay of the old result.
    from agentkit.backend.story_context_manager.errors import (
        IdempotencyMismatchError,
    )

    repo = _FakeGuardCounterRepo()
    service = _guard_counter_service(repo)
    service.apply(_record_request(op_id="op-x", blocked=True))
    with pytest.raises(IdempotencyMismatchError):
        service.apply(_record_request(op_id="op-x", blocked=False))  # body differs
    # The conflicting second call did NOT increment the counter.
    assert len(repo.upserts) == 1


def test_guard_counter_record_requires_scope() -> None:
    with pytest.raises(ValueError, match="record requires"):
        GuardCounterMutationRequest(
            operation="record", occurred_at=_NOW, op_id="op-requires-scope-001"
        )


# ---------------------------------------------------------------------------
# Worker-health service
# ---------------------------------------------------------------------------


class _FakeWorkerHealthRepo:
    def __init__(self) -> None:
        self.saved: list[AgentHealthState] = []
        self._store: dict[tuple[str, str], AgentHealthState] = {}

    def save(self, state: AgentHealthState) -> None:
        self.saved.append(state)
        self._store[(state.story_id, state.worker_id)] = state

    def load(self, *, story_id: str, worker_id: str) -> AgentHealthState | None:
        return self._store.get((story_id, worker_id))


def test_worker_health_service_save_and_load() -> None:
    repo = _FakeWorkerHealthRepo()
    service = ControlPlaneWorkerHealthService(repository_factory=lambda: repo)
    state = AgentHealthState(worker_id="w1", story_id="AG3-129", total_score=5)

    accepted = service.save(state.model_dump(mode="json"))
    assert isinstance(accepted, WorkerHealthSaveAccepted)
    assert accepted.story_id == "AG3-129"

    loaded = service.load(story_id="AG3-129", worker_id="w1")
    assert loaded.state is not None
    assert loaded.state["total_score"] == 5


def test_worker_health_service_load_missing_is_none() -> None:
    repo = _FakeWorkerHealthRepo()
    service = ControlPlaneWorkerHealthService(repository_factory=lambda: repo)
    result = service.load(story_id="none", worker_id="none")
    assert result == WorkerHealthStateResponse(state=None)


# ---------------------------------------------------------------------------
# Governance edge client + REST worker-health store (over a fake transport)
# ---------------------------------------------------------------------------


class _FakeTransport:
    """In-memory control-plane transport backed by a live service pair."""

    def __init__(self) -> None:
        self.guard_service = ControlPlaneGuardCounterService(
            store_factory=_FakeGuardCounterRepo
        )
        self.health_repo = _FakeWorkerHealthRepo()
        self.health_service = ControlPlaneWorkerHealthService(
            repository_factory=lambda: self.health_repo
        )

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        _ = headers
        if path == "/v1/governance/guard-counters":
            request = GuardCounterMutationRequest.model_validate(payload)
            return self.guard_service.apply(request).model_dump(mode="json")
        if path == "/v1/governance/worker-health" and method == "POST":
            return self.health_service.save(payload).model_dump(mode="json")
        if path.startswith("/v1/governance/worker-health"):
            # GET load with query string story_id=&worker_id=
            params = dict(
                pair.split("=", 1)
                for pair in path.split("?", 1)[1].split("&")
            )
            return self.health_service.load(
                story_id=params["story_id"], worker_id=params["worker_id"]
            ).model_dump(mode="json")
        raise AssertionError(f"unexpected path {path}")


def test_rest_worker_health_repository_round_trip() -> None:
    client = GovernanceEdgeClient(transport=_FakeTransport())
    repo = RestWorkerHealthRepository(client)
    state = AgentHealthState(worker_id="w1", story_id="AG3-129", total_score=7)

    repo.save(state)
    loaded = repo.load(story_id="AG3-129", worker_id="w1")

    assert loaded is not None
    assert loaded.total_score == 7


def test_rest_worker_health_repository_missing_is_none() -> None:
    client = GovernanceEdgeClient(transport=_FakeTransport())
    repo = RestWorkerHealthRepository(client)
    assert repo.load(story_id="none", worker_id="none") is None


def test_governance_client_mutate_guard_counter() -> None:
    client = GovernanceEdgeClient(transport=_FakeTransport())
    accepted = client.mutate_guard_counter(
        GuardCounterMutationRequest(
            operation="record",
            occurred_at=_NOW,
            op_id="op-governance-client-001",
            project_key="tenant-a",
            story_id="AG3-129",
            guard_key="orchestrator_guard",
            blocked=False,
        )
    )
    assert accepted.status == "accepted"
    assert accepted.operation == "record"
