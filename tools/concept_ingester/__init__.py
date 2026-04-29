"""Concept ingester for AgentKit 3.

Reads the project's concept corpus (domain-design, formal-spec,
technical-design) and pushes typed chunks into Weaviate. Two
collections are kept in sync:

- ``Ak3ConceptChunk``: H2-section level chunks with bounded-context
  projection, reference-graph filters and migration tracking.
- ``Ak3GlossaryTerm``: glossary entries from contract docs, vectorised
  so semantic search lands directly on the canonical definition.
"""

from __future__ import annotations

from tools.concept_ingester.config import IngesterConfig
from tools.concept_ingester.discovery import (
    ConceptChunk,
    DiscoveryResult,
    GlossaryTerm,
    discover,
    discover_chunks,
)
from tools.concept_ingester.ingester import IngestReport, IngestStrategy, run_ingest
from tools.concept_ingester.schema import (
    CHUNK_COLLECTION_NAME,
    COLLECTION_NAME,
    GLOSSARY_COLLECTION_NAME,
    SCHEMA_PROJECTION_VERSION,
    drop_all_collections,
    drop_collection,
    ensure_all_collections,
    ensure_collection,
    ensure_glossary_collection,
)

__all__ = [
    "CHUNK_COLLECTION_NAME",
    "COLLECTION_NAME",
    "ConceptChunk",
    "DiscoveryResult",
    "GLOSSARY_COLLECTION_NAME",
    "GlossaryTerm",
    "IngestReport",
    "IngestStrategy",
    "IngesterConfig",
    "SCHEMA_PROJECTION_VERSION",
    "discover",
    "discover_chunks",
    "drop_all_collections",
    "drop_collection",
    "ensure_all_collections",
    "ensure_collection",
    "ensure_glossary_collection",
    "run_ingest",
]
