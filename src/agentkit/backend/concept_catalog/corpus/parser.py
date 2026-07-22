"""Public parser facade — owner of ``discover_concept_files`` (FK-13 §13.9.13).

Re-exports the discovery SSOT so consumers import from
``agentkit.backend.concept_catalog.corpus.parser`` as mandated by the concept.
"""

from __future__ import annotations

from agentkit.backend.concept_catalog.corpus.chunking import ChunkOverflowFinding, TextChunk, chunk_markdown
from agentkit.backend.concept_catalog.corpus.discovery import ConceptDocument, DiscoveryResult, discover_concept_files
from agentkit.backend.concept_catalog.corpus.frontmatter import ConceptFrontmatter
from agentkit.backend.concept_catalog.corpus.hashing import corpus_revision, sha256_text
from agentkit.backend.concept_catalog.corpus.profiles import IngestProfile, IngestProfileId, get_profile

PARSER_VERSION = "1.0.0"

__all__ = [
    "PARSER_VERSION",
    "ChunkOverflowFinding",
    "ConceptDocument",
    "ConceptFrontmatter",
    "DiscoveryResult",
    "IngestProfile",
    "IngestProfileId",
    "TextChunk",
    "chunk_markdown",
    "corpus_revision",
    "discover_concept_files",
    "get_profile",
    "sha256_text",
]
