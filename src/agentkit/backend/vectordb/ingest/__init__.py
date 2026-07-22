"""VectorDB ingest adapters over the transport-free concepts kernel (AG3-174)."""

from __future__ import annotations

from agentkit.backend.vectordb.ingest.engine import IngestEngine, IngestReport
from agentkit.backend.vectordb.ingest.identity import deterministic_chunk_uuid
from agentkit.backend.vectordb.ingest.models import ChunkRecord, SourceType
from agentkit.backend.vectordb.ingest.source_routing import (
    PRODUCER_BY_SOURCE,
    classify_markdown_path,
)

__all__ = [
    "PRODUCER_BY_SOURCE",
    "ChunkRecord",
    "IngestEngine",
    "IngestReport",
    "SourceType",
    "classify_markdown_path",
    "deterministic_chunk_uuid",
]
