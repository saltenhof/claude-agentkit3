"""Concept ingester for AgentKit 3.

Reads the project's concept corpus (domain-design, formal-spec,
technical-design) and pushes typed chunks into a Weaviate collection
that exposes a single ranked result space across all three layers
while keeping the layer addressable via filters.
"""

from __future__ import annotations

from tools.concept_ingester.config import IngesterConfig
from tools.concept_ingester.discovery import ConceptChunk, discover_chunks
from tools.concept_ingester.ingester import IngestReport, IngestStrategy, run_ingest
from tools.concept_ingester.schema import COLLECTION_NAME, ensure_collection

__all__ = [
    "COLLECTION_NAME",
    "ConceptChunk",
    "IngestReport",
    "IngestStrategy",
    "IngesterConfig",
    "discover_chunks",
    "ensure_collection",
    "run_ingest",
]
