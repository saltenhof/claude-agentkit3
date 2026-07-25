"""Configuration for the concept ingester."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class IngesterConfig:
    """Runtime configuration of the ingester.

    All values can be overridden via environment variables so the same
    config object works for the CLI, tests, and the MCP server.
    """

    repo_root: Path
    concept_root: Path
    weaviate_host: str
    weaviate_http_port: int
    weaviate_grpc_port: int
    collection_name: str
    chunk_max_chars: int

    @classmethod
    def from_env(cls) -> IngesterConfig:
        repo = _repo_root()
        host = os.environ.get("AK3_WEAVIATE_HOST")
        http_port = os.environ.get("AK3_WEAVIATE_HTTP_PORT")
        grpc_port = os.environ.get("AK3_WEAVIATE_GRPC_PORT")
        # No localhost default (R06 / D2): the endpoint must come from explicit
        # configuration. A missing endpoint fails closed at connect time.
        if not host or not http_port or not grpc_port:
            raise RuntimeError(
                "concept_ingester requires AK3_WEAVIATE_HOST, AK3_WEAVIATE_HTTP_PORT "
                "and AK3_WEAVIATE_GRPC_PORT to be set explicitly (no localhost default)."
            )
        return cls(
            repo_root=repo,
            concept_root=repo / "concept",
            weaviate_host=host,
            weaviate_http_port=int(http_port),
            weaviate_grpc_port=int(grpc_port),
            collection_name=os.environ.get("AK3_CONCEPT_COLLECTION", "Ak3ConceptChunk"),
            chunk_max_chars=int(os.environ.get("AK3_CONCEPT_CHUNK_MAX", "12000")),
        )
