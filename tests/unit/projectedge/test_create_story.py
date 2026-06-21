"""Unit tests for ``ProjectEdgeClient.create_story`` (AG3-114, FK-91 §91.1a).

The agent-facing native create operation is the §91.1a Regel #3 path: agents
create stories ONLY through the official client against the actually exposed,
tenant-scoped create route ``POST /v1/projects/{project_key}/stories`` (§91.1a
Regel #1 / FK-72 §72.8.1 — the single canonical story truth). These tests pin the
request shape (incl. the tenant-scoped path derived from the master data), the
idempotency behaviour (Regel #5), the ``correlation_id`` propagation (Regel #7)
and the fail-closed stable error contract (Regel #8) using a fake transport at the
wire edge ONLY — the request model, the wire body, the reconciliation evidence and
the response model are real.

Codex R2 finding #1+#2: the official surface no longer ACCEPTS a caller-supplied
``ReconciliationOutcome`` / evidence, and it no longer takes a SEPARATE
``base_input`` next to ``inputs`` (the split-input seam). It takes the SINGLE typed
story ``inputs`` plus the REAL reconcile runtime (``StoryCreationReconciler``) and
drives ``reconcile_only_from_inputs`` INSIDE the boundary, deriving the reconciler
input from the SAME ``inputs`` that is persisted and building the wire body from
the resulting outcome. A caller therefore cannot hand in a fabricated outcome /
evidence and persist, nor reconcile object A while object B is persisted (FK-21
§21.4, FIX-THE-MODEL). The reconciliation here runs over a real
``StoryCreationReconciler`` whose ONLY fakes are at the genuine external edge
(Weaviate adapter + LLM evaluator) — the CLAUDE.md mocks exception.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    VectorDbConfig,
)
from agentkit.backend.control_plane.models import CreateStoryInputs
from agentkit.backend.exceptions import ControlPlaneApiError
from agentkit.backend.story_creation.create_flow import StoryCreationReconciler
from agentkit.backend.verify_system.llm_evaluator.roles import LlmVerdict, ReviewerRole
from agentkit.harness_client.projectedge import LocalEdgePublisher, ProjectEdgeClient
from agentkit.integration_clients.vectordb import StorySearchHit, VectorDbUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


_STORY_BODY = "## Betroffene Dateien\n- services/api/x.py\n"


# ---------------------------------------------------------------------------
# External-edge fakes ONLY (Weaviate adapter + LLM evaluator) — mocks exception
# ---------------------------------------------------------------------------


class _FakeAdapter:
    def __init__(
        self, hits: list[StorySearchHit], *, raise_search: bool = False
    ) -> None:
        self._hits = hits
        self._raise = raise_search

    def story_search(
        self,
        query: str,
        *,
        search_mode: str = "hybrid",
        project_id: str,
        limit: int = 20,
    ) -> list[StorySearchHit]:
        del query, search_mode, project_id, limit
        if self._raise:
            raise VectorDbUnavailableError("weaviate down")
        return self._hits


class _FakeResult:
    def __init__(self, verdict: LlmVerdict) -> None:
        self.verdict = verdict


class _FakeEvaluator:
    def __init__(self, verdict: LlmVerdict) -> None:
        self._verdict = verdict

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: object,
        previous_findings: object,
        qa_cycle_round: int,
    ) -> _FakeResult:
        del role, bundle, previous_findings, qa_cycle_round
        return _FakeResult(self._verdict)


def _project_config() -> ProjectConfig:
    return ProjectConfig(
        project_key="ak3",
        project_name="AgentKit 3",
        repositories=[RepositoryConfig(name="ak3-backend", path="services/api")],
        story_types=["concept"],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            vectordb=VectorDbConfig(host="weaviate.local", port=8080),
        ),  # type: ignore[call-arg]
    )


def _reconciler(
    *,
    hits: list[StorySearchHit] | None = None,
    verdict: LlmVerdict = LlmVerdict.PASS,
    raise_search: bool = False,
) -> StoryCreationReconciler:
    """A REAL reconciler with fakes ONLY at the external Weaviate/LLM edge."""
    return StoryCreationReconciler(
        adapter=_FakeAdapter(hits or [], raise_search=raise_search),  # type: ignore[arg-type]
        evaluator=_FakeEvaluator(verdict),  # type: ignore[arg-type]
        vectordb_config=VectorDbConfig(similarity_threshold=0.7, max_llm_candidates=5),
        project_config=_project_config(),
    )


def _inputs(**overrides: object) -> CreateStoryInputs:
    body: dict[str, object] = {
        "project_key": "ak3",
        "title": "Add a native create surface",
        "type": "implementation",
        "repos": ["ak3-backend"],
    }
    body.update(overrides)
    return CreateStoryInputs.model_validate(body)


def _create(
    client: ProjectEdgeClient,
    *,
    reconciler: StoryCreationReconciler | None = None,
    inputs: CreateStoryInputs | None = None,
    op_id: str,
    correlation_id: str = "",
) -> object:
    """Drive the new boundary signature (reconciliation runs INSIDE the client)."""
    return client.create_story(
        inputs or _inputs(),
        reconciler=reconciler or _reconciler(),
        story_body=_STORY_BODY,
        op_id=op_id,
        correlation_id=correlation_id,
    )


class _RecordingTransport:
    """Wire-edge double: records the single send and returns a canned summary."""

    def __init__(self, response: dict[str, object]) -> None:
        self.calls: list[tuple[str, str, Mapping[str, object] | None]] = []
        self.headers: list[Mapping[str, str] | None] = []
        self._response = response

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        self.calls.append((method, path, payload))
        self.headers.append(headers)
        return self._response


class _ReplayTransport:
    """Wire-edge double simulating the service's op_id idempotency replay.

    The FIRST call commits and returns the created summary; EVERY repeat with the
    SAME ``op_id`` returns the SAME summary (the route's service-side replay), and
    crucially never produces a second distinct story.
    """

    def __init__(self) -> None:
        self._by_op: dict[str, dict[str, object]] = {}
        self._seq = 0
        self.commit_count = 0
        self.calls: list[Mapping[str, object] | None] = []

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        del method, path, headers
        self.calls.append(payload)
        assert payload is not None
        op_id = str(payload["op_id"])
        if op_id not in self._by_op:
            self._seq += 1
            self.commit_count += 1
            self._by_op[op_id] = {
                "story_id": f"AK3-{self._seq:03d}",
                "project_key": payload["project_key"],
                "title": payload["title"],
                "type": payload["type"],
                "status": "Backlog",
            }
        return self._by_op[op_id]


def _summary(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "story_id": "AK3-042",
        "project_key": "ak3",
        "title": "Add a native create surface",
        "type": "implementation",
        "status": "Backlog",
    }
    body.update(overrides)
    return body


def _client(transport: object, tmp_path: Path) -> ProjectEdgeClient:
    return ProjectEdgeClient(
        transport=transport,  # type: ignore[arg-type]
        publisher=LocalEdgePublisher(project_root=tmp_path),
    )


# ---------------------------------------------------------------------------
# AC1: the client posts the correct request (method/path/body/op_id)
# ---------------------------------------------------------------------------


def test_create_story_posts_to_tenant_scoped_route_with_wire_body(
    tmp_path: Path,
) -> None:
    """AC1: POST the tenant-scoped create route with the typed body/op_id/evidence.

    The client targets the ACTUALLY EXPOSED route
    ``POST /v1/projects/{project_key}/stories`` (§91.1a Regel #1 / FK-72 §72.8.1),
    with the ``project_key`` taken from the single ``CreateStoryInputs`` master
    data (it can never diverge from the persisted story). The bare ``/v1/stories``
    is NOT a production-exposed route (the ControlPlaneApplication only dispatches
    story POSTs at the tenant-scoped path).
    """
    transport = _RecordingTransport(_summary())
    client = _client(transport, tmp_path)

    result = _create(client, op_id="op-create-001", correlation_id="corr-xyz")

    assert len(transport.calls) == 1
    method, path, payload = transport.calls[0]
    assert (method, path) == ("POST", "/v1/projects/ak3/stories")
    assert payload is not None
    # op_id (Regel #5) and the typed reconciliation evidence ride on the body —
    # the evidence was produced INSIDE the boundary by the real reconcile run.
    assert payload["op_id"] == "op-create-001"
    assert payload["reconciliation"]["weaviate_ready"] is True
    assert payload["reconciliation"]["verdict"] == "PASS"
    # Story content keys use the wire name ``type`` (alias of story_type).
    assert payload["type"] == "implementation"
    assert payload["project_key"] == "ak3"
    # The authoritative repos come from the reconciliation outcome, not the input.
    assert payload["repos"] == ["ak3-backend"]
    # Backend-allocated id is surfaced typed (never client-assigned).
    assert result.summary.story_id == "AK3-042"  # type: ignore[attr-defined]
    assert result.summary.status == "Backlog"  # type: ignore[attr-defined]
    # Codex R2 residual #3: the §21.4.2 counters are surfaced on the result.
    assert result.reconciliation_counters["search_mode"] == "hybrid"  # type: ignore[attr-defined]


def test_create_story_runs_reconciliation_inside_boundary(tmp_path: Path) -> None:
    """Codex R2 #1: the evidence is built from the REAL in-boundary reconciliation.

    A real candidate hit above threshold (the fake evaluator returns PASS) drives
    the §21.4.2 counters that ride on the wire body — proving the reconciliation
    truly ran inside the client, not handed in by the caller.
    """
    transport = _RecordingTransport(_summary())
    client = _client(transport, tmp_path)
    hits = [StorySearchHit(story_id="AK3-009", title="prior", score=0.91, snippet="x")]

    result = _create(
        client, reconciler=_reconciler(hits=hits, verdict=LlmVerdict.PASS), op_id="op-r"
    )

    _, _, payload = transport.calls[0]
    assert payload is not None
    recon = payload["reconciliation"]
    assert recon["total_hits"] == 1
    assert recon["hits_above_threshold"] == 1
    assert recon["candidates_evaluated"] == 1
    assert recon["verdict"] == "PASS"
    assert result.reconciliation_counters["sent_to_llm"] == 1  # type: ignore[attr-defined]


def test_create_story_weaviate_outage_fails_closed_no_post(tmp_path: Path) -> None:
    """AC2: a Weaviate outage during the in-boundary reconciliation blocks the
    create fail-closed BEFORE any POST (no story persisted)."""
    transport = _RecordingTransport(_summary())
    client = _client(transport, tmp_path)

    with pytest.raises(VectorDbUnavailableError):
        _create(client, reconciler=_reconciler(raise_search=True), op_id="op-down")

    # Fail-closed: the reconciliation raised before any wire call.
    assert transport.calls == []


def test_create_story_uses_outcome_participating_repos(tmp_path: Path) -> None:
    """The authoritative repos are the reconciliation outcome's (repo-affinity)."""
    transport = _RecordingTransport(_summary())
    client = _client(transport, tmp_path)

    # The caller proposes a bogus repo; the in-boundary reconciliation derives the
    # authoritative participating_repos from the body / project config (affinity).
    _create(
        client,
        inputs=_inputs(repos=["caller-proposed"]),
        op_id="op-repos",
    )

    _, _, payload = transport.calls[0]
    assert payload is not None
    # services/api -> ak3-backend (longest-prefix repo affinity over the body).
    assert payload["repos"] == ["ak3-backend"]


def test_create_story_returns_backend_allocated_summary_typed(tmp_path: Path) -> None:
    """AC1: the created story is returned as a typed CreatedStorySummary."""
    transport = _RecordingTransport(_summary(story_id="AK3-777", status="Backlog"))
    client = _client(transport, tmp_path)

    result = _create(client, op_id="op-1")

    assert result.summary.story_id == "AK3-777"  # type: ignore[attr-defined]
    assert result.summary.project_key == "ak3"  # type: ignore[attr-defined]
    assert result.summary.type == "implementation"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC1 / Regel #7: correlation_id propagation (sent as X-Correlation-Id, surfaced)
# ---------------------------------------------------------------------------


def test_create_story_sends_correlation_header(tmp_path: Path) -> None:
    """Regel #7: the call's correlation id rides as the X-Correlation-Id header so
    the control plane ADOPTS and audits the same id (no divergent req-<uuid>)."""
    transport = _RecordingTransport(_summary())
    client = _client(transport, tmp_path)

    _create(client, op_id="op-h", correlation_id="corr-sent")

    assert transport.headers[0] == {"X-Correlation-Id": "corr-sent"}


def test_create_story_surfaces_server_correlation_id(tmp_path: Path) -> None:
    """Regel #7: the id the SERVER echoes (response body) is surfaced, not invented.

    The transport injects the server's ``X-Correlation-Id`` into the response body;
    the client surfaces that on the summary.
    """
    transport = _RecordingTransport(_summary(correlation_id="corr-from-server"))
    client = _client(transport, tmp_path)

    result = _create(client, op_id="op-s", correlation_id="corr-call")

    assert result.summary.correlation_id == "corr-from-server"  # type: ignore[attr-defined]


def test_create_story_propagates_correlation_id_when_absent_on_summary(
    tmp_path: Path,
) -> None:
    """Regel #7: a summary that omits correlation_id inherits the call's id."""
    transport = _RecordingTransport(_summary())  # no correlation_id in body
    client = _client(transport, tmp_path)

    result = _create(client, op_id="op-p", correlation_id="corr-propagated")

    assert result.summary.correlation_id == "corr-propagated"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC1 / AC2 / Regel #8: fail-closed stable error contract
# ---------------------------------------------------------------------------


def test_create_story_surfaces_reconciliation_evidence_missing(
    tmp_path: Path,
) -> None:
    """AC2/Regel #8: a fail-closed evidence rejection surfaces typed; no story."""

    class _RejectingTransport:
        def send(
            self,
            *,
            method: str,
            path: str,
            payload: object = None,
            headers: object = None,
        ) -> dict[str, object]:
            del method, path, payload, headers
            raise ControlPlaneApiError(
                "reconciliation evidence is invalid",
                error_code="reconciliation_evidence_missing",
                correlation_id="corr-reject",
                http_status=422,
            )

    client = _client(_RejectingTransport(), tmp_path)

    with pytest.raises(ControlPlaneApiError) as exc_info:
        _create(client, op_id="op-x", correlation_id="corr-call")

    assert exc_info.value.error_code == "reconciliation_evidence_missing"
    assert exc_info.value.http_status == 422


# ---------------------------------------------------------------------------
# AC1 / Regel #5: op_id idempotency (repeat => same story, no second mutation)
# ---------------------------------------------------------------------------


def test_create_story_op_id_idempotency_no_second_mutation(tmp_path: Path) -> None:
    """Regel #5: repeating the same op_id returns the same story; the boundary
    commits exactly once (no duplicate story)."""
    transport = _ReplayTransport()
    client = _client(transport, tmp_path)

    first = _create(client, op_id="op-stable")
    second = _create(client, op_id="op-stable")

    assert first.summary.story_id == second.summary.story_id  # type: ignore[attr-defined]
    assert transport.commit_count == 1
    # Both calls carried the SAME op_id (the idempotency key, Regel #5).
    assert {str(p["op_id"]) for p in transport.calls if p is not None} == {
        "op-stable"
    }


def test_create_story_distinct_op_ids_create_distinct_stories(
    tmp_path: Path,
) -> None:
    """Two distinct op_ids produce two distinct backend-allocated stories."""
    transport = _ReplayTransport()
    client = _client(transport, tmp_path)

    first = _create(client, op_id="op-a")
    second = _create(client, op_id="op-b")

    assert first.summary.story_id != second.summary.story_id  # type: ignore[attr-defined]
    assert transport.commit_count == 2


# ---------------------------------------------------------------------------
# Wire-body serialisation invariants (ARCH-55 / non-bypassable evidence)
# ---------------------------------------------------------------------------


def test_create_story_request_wire_body_omits_empty_labels(tmp_path: Path) -> None:
    """An empty labels default is dropped so it cannot mask server policy."""
    transport = _RecordingTransport(_summary())
    client = _client(transport, tmp_path)

    _create(client, op_id="op-l")

    _, _, payload = transport.calls[0]
    assert payload is not None
    assert "labels" not in payload


def test_create_story_signature_takes_no_caller_outcome_or_split_input() -> None:
    """Codex R2 #1+#2: the create surface accepts NO outcome/evidence and NO
    SEPARATE ``base_input`` next to ``inputs``.

    The forgery surface is closed at the signature: ``create_story`` has no
    ``outcome`` / ``evidence`` parameter (#1), so a caller cannot hand in a
    fabricated reconciliation and persist; and it has no ``base_input`` parameter
    (#2), so there is no split-input seam where a caller could reconcile object A
    while object B is persisted. The reconciler input is derived INTERNALLY from
    the single ``inputs``. The only evidence that can reach the boundary is what
    the in-boundary ``reconcile_only_from_inputs`` produced.
    """
    import inspect

    params = set(inspect.signature(ProjectEdgeClient.create_story).parameters)
    assert "outcome" not in params
    assert "evidence" not in params
    assert "base_input" not in params
    # The real reconcile runtime IS required (it produces the evidence in-boundary).
    assert "reconciler" in params
    assert "story_body" in params
    assert "inputs" in params


def test_create_story_url_encodes_project_key_in_path(tmp_path: Path) -> None:
    """Regel #1: the project_key is URL-encoded into the tenant-scoped path so a
    key with reserved characters cannot break out of the path segment."""
    transport = _RecordingTransport(_summary(project_key="team/ak3"))
    client = _client(transport, tmp_path)

    _create(client, inputs=_inputs(project_key="team/ak3"), op_id="op-enc")

    _, path, _ = transport.calls[0]
    assert path == "/v1/projects/team%2Fak3/stories"


def test_create_story_request_rejects_hand_built_evidence_dict() -> None:
    """The typed request mandates a typed ReconciliationEvidence (non-bypassable).

    A raw dict cannot be passed where a self-validating ``ReconciliationEvidence``
    is required: an internally inconsistent attestation is rejected at the model
    boundary, so a forged self-consistent dict cannot reach the create surface.
    """
    from agentkit.backend.control_plane.models import CreateStoryRequest

    with pytest.raises(ValueError, match="reconciliation|weaviate"):
        CreateStoryRequest.model_validate(
            {
                "op_id": "op-x",
                "project_key": "ak3",
                "title": "forged",
                "type": "implementation",
                "repos": ["ak3-backend"],
                # A Weaviate outage cannot coexist with a "ready" attestation:
                # the typed evidence model fail-closes this hand-built dict.
                "reconciliation": {
                    "weaviate_ready": False,
                    "total_hits": 0,
                    "hits_above_threshold": 0,
                    "hits_classified_conflict": 0,
                    "threshold_value": 0.7,
                    "verdict": "PASS",
                },
            }
        )
