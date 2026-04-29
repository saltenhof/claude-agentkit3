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
        return cls(
            repo_root=repo,
            concept_root=repo / "concept",
            weaviate_host=os.environ.get("AK3_WEAVIATE_HOST", "127.0.0.1"),
            weaviate_http_port=int(os.environ.get("AK3_WEAVIATE_HTTP_PORT", "9903")),
            weaviate_grpc_port=int(os.environ.get("AK3_WEAVIATE_GRPC_PORT", "50051")),
            collection_name=os.environ.get("AK3_CONCEPT_COLLECTION", "Ak3ConceptChunk"),
            chunk_max_chars=int(os.environ.get("AK3_CONCEPT_CHUNK_MAX", "12000")),
        )
