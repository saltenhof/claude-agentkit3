"""Ingest adapter package: maps the SSOT discovery core onto StoryContext objects.

This is an ADAPTER on :mod:`agentkit.concepts` (the transport-free SSOT) -- it
adds NO second discovery/parser path. It owns:

- the three ingest profiles (``fk13_concept`` / ``fk13_story`` / ``ak3_tool``);
- source-type / producer classification (FK-13 §13.3.2 corrected, §13.9.5);
- the projection from concept chunks and story documents to StoryContext objects.
"""

from __future__ import annotations

from agentkit.backend.vectordb.ingest.adapter import (
    concept_chunks_to_objects,
    story_file_to_objects,
)
from agentkit.backend.vectordb.ingest.classify import (
    PRODUCER_BY_SOURCE_TYPE,
    classify_source_file,
    producer_for,
)
from agentkit.backend.vectordb.ingest.profiles import (
    AK3_TOOL_PROFILE,
    FK13_CONCEPT_PROFILE,
    FK13_STORY_PROFILE,
    IngestProfile,
)

__all__ = [
    "AK3_TOOL_PROFILE",
    "FK13_CONCEPT_PROFILE",
    "FK13_STORY_PROFILE",
    "IngestProfile",
    "PRODUCER_BY_SOURCE_TYPE",
    "classify_source_file",
    "concept_chunks_to_objects",
    "producer_for",
    "story_file_to_objects",
]
