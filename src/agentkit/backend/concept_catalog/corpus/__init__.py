"""Transport-free concept corpus domain kernel (FK-13 §13.9.13, AG3-174).

Discovery, frontmatter, heading chunking, hashing and excludes live here once.
``backend/vectordb/ingest`` and ``tools/concept_ingester`` are adapters on top.
"""

from __future__ import annotations

from agentkit.backend.concept_catalog.corpus.discovery import ConceptDocument, discover_concept_files
from agentkit.backend.concept_catalog.corpus.domain_errors import ConceptDomainError, ConceptParseError, ConceptValidationError

__all__ = [
    "ConceptDocument",
    "ConceptDomainError",
    "ConceptParseError",
    "ConceptValidationError",
    "discover_concept_files",
]
