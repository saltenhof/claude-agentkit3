"""External-boundary fixtures for installer tests with mandatory VectorDB."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.unit.vectordb.corpus_doubles import RecordingWeaviateClient

from agentkit.backend.installer.mcp_registration import (
    ProbedRegistration,
    RenderedRegistration,
)
from agentkit.backend.installer.vectordb_preflight import VectorDbPreflightReceipt

if TYPE_CHECKING:
    from pytest import MonkeyPatch

    from agentkit.backend.config.models import ProjectConfig

HTTP_ENDPOINT = "http://weaviate.test.invalid:9903"
GRPC_ENDPOINT = "weaviate.test.invalid:50051"


class ReadyVectorDbPreflight:
    """Reachable/compatible Weaviate fake at the external preflight port."""

    def check(self, config: ProjectConfig) -> VectorDbPreflightReceipt:
        vectordb = config.pipeline.vectordb
        assert vectordb is not None
        assert vectordb.weaviate_http_endpoint is not None
        assert vectordb.weaviate_grpc_endpoint is not None
        return VectorDbPreflightReceipt(
            http_endpoint=vectordb.weaviate_http_endpoint,
            grpc_endpoint=vectordb.weaviate_grpc_endpoint,
            server_version="1.25.9",
        )


def passing_mcp_probe(
    rendered: RenderedRegistration,
) -> tuple[ProbedRegistration | None, tuple[str, str] | None]:
    """Return a receipt value-bound to the registration being probed."""
    return (
        ProbedRegistration(
            rendered=rendered,
            digest_at_probe=rendered.digest(),
            tool_names=tuple((server.name, ("story_sync", "concept_sync")) for server in rendered.servers),
        ),
        None,
    )


def wire_ready_vectordb(monkeypatch: MonkeyPatch) -> RecordingWeaviateClient:
    """Wire only the external Weaviate/MCP-process boundaries for CLI tests."""
    from agentkit.backend.installer.bootstrap_checkpoints import cp10, orchestrator
    from agentkit.backend.vectordb import engine

    ready = ReadyVectorDbPreflight()
    client = RecordingWeaviateClient()
    monkeypatch.setattr(orchestrator.HttpVectorDbPreflight, "check", ready.check)
    monkeypatch.setattr(engine, "connect_real_client", lambda _binding: client)
    monkeypatch.setattr(cp10, "probe_registration", passing_mcp_probe)
    return client


def ready_vectordb_install_kwargs() -> dict[str, object]:
    """Return fresh external-boundary seams for one direct installer call."""
    return {
        "vectordb_http_endpoint": HTTP_ENDPOINT,
        "vectordb_grpc_endpoint": GRPC_ENDPOINT,
        "vectordb_preflight": ReadyVectorDbPreflight(),
        "vectordb_client": RecordingWeaviateClient(),
        "mcp_registration_probe": passing_mcp_probe,
    }


__all__ = [
    "GRPC_ENDPOINT",
    "HTTP_ENDPOINT",
    "ReadyVectorDbPreflight",
    "passing_mcp_probe",
    "ready_vectordb_install_kwargs",
    "wire_ready_vectordb",
]
