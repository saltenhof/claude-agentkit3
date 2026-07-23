"""Concept corpus lifecycle (FK-13 §13.9): validate, build, graph, resolver, freshness.

All consumers use the SSOT :func:`agentkit.concepts.parser.discover_concept_files`
as their single discovery source. This package is transport-free.
"""

from __future__ import annotations

from agentkit.backend.vectordb.concept_corpus.builder import (
    BuildArtifacts,
    build_artifacts,
    write_artifacts,
)
from agentkit.backend.vectordb.concept_corpus.freshness import (
    Freshness,
    check_freshness,
)
from agentkit.backend.vectordb.concept_corpus.graph import (
    ConceptGraph,
    build_graph,
)
from agentkit.backend.vectordb.concept_corpus.resolver import (
    RankedHit,
    rank_hits,
)
from agentkit.backend.vectordb.concept_corpus.validator import (
    ERROR_CODES,
    WARNING_CODES,
    ExitCode,
    Finding,
    ValidationReport,
    validate_corpus,
)

__all__ = [
    "BuildArtifacts",
    "ConceptGraph",
    "ERROR_CODES",
    "ExitCode",
    "Finding",
    "Freshness",
    "RankedHit",
    "WARNING_CODES",
    "ValidationReport",
    "build_artifacts",
    "build_graph",
    "check_freshness",
    "rank_hits",
    "validate_corpus",
    "write_artifacts",
]
