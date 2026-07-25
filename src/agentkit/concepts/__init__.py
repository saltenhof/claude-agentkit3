"""Concept discovery / ingestion SSOT core (FK-13 §13.9.13).

Transport-free domain package. ``discover_concept_files()`` in
:mod:`agentkit.concepts.parser` is the SINGLE owner of validation, build, graph
and sync discovery. Backend vectordb consumers and ``tools/concept_ingester``
adapt to this core; there is no second parser path.
"""

from __future__ import annotations

from agentkit.concepts.frontmatter import (
    ConceptFrontmatter,
    FrontmatterError,
    parse_document_frontmatter,
)
from agentkit.concepts.parser import (
    ConceptChunk,
    ConceptDocument,
    DiscoveryResult,
    ParseError,
    discover_concept_files,
)
from agentkit.concepts.tokenizer import (
    TokenizerAssetError,
    chunk_token_count,
    load_bound_tokenizer,
)

__all__ = [
    "ConceptChunk",
    "ConceptDocument",
    "ConceptFrontmatter",
    "DiscoveryResult",
    "FrontmatterError",
    "ParseError",
    "TokenizerAssetError",
    "chunk_token_count",
    "discover_concept_files",
    "load_bound_tokenizer",
    "parse_document_frontmatter",
]
