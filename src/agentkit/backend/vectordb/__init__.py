"""VectorDB app-layer package (FK-13): schema, binding, ingest, corpus, MCP."""

from __future__ import annotations

from agentkit.backend.vectordb.project_binding import ProjectBinding, bind_project
from agentkit.backend.vectordb.schema import STORY_COLLECTION, ensure_story_context_schema

__all__ = [
    "STORY_COLLECTION",
    "ProjectBinding",
    "bind_project",
    "ensure_story_context_schema",
]
