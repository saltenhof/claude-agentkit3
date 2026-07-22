"""Ingest domain models for StoryContext chunks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SourceType(StrEnum):
    """Allowed source_type values (FK-13 §13.3.2)."""

    STORY = "story"
    RESEARCH = "research"
    CONCEPT = "concept"


@dataclass(frozen=True)
class ChunkRecord:
    """One fully populated StoryContext object ready for upsert."""

    chunk_uuid: str
    content: str
    content_hash: str
    project_id: str
    source_type: SourceType
    source_file: str
    producer_tool: str
    section_heading: str
    title: str
    story_id: str = ""
    status: str = ""
    story_type: str = ""
    module: str = ""
    epic: str = ""
    concept_id: str = ""
    is_appendix: bool = False
    parent_concept_id: str = ""
    defers_to: tuple[str, ...] = ()
    authority_over: tuple[str, ...] = ()
    section_number: str = ""
    normative_rules: str = ""
    concept_status: str = ""
    generation_id: str = ""
    corpus_revision: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_properties(self) -> dict[str, object]:
        """Serialize to Weaviate property map (English keys, ARCH-55)."""
        props: dict[str, object] = {
            "content": self.content,
            "story_id": self.story_id,
            "title": self.title,
            "status": self.status,
            "story_type": self.story_type,
            "module": self.module,
            "epic": self.epic,
            "source_type": self.source_type.value,
            "source_file": self.source_file,
            "section_heading": self.section_heading,
            "content_hash": self.content_hash,
            "project_id": self.project_id,
            "concept_id": self.concept_id,
            "is_appendix": self.is_appendix,
            "parent_concept_id": self.parent_concept_id,
            "defers_to": list(self.defers_to),
            "authority_over": list(self.authority_over),
            "section_number": self.section_number,
            "normative_rules": self.normative_rules,
            "concept_status": self.concept_status,
            "chunk_uuid": self.chunk_uuid,
            "producer_tool": self.producer_tool,
            "generation_id": self.generation_id,
            "corpus_revision": self.corpus_revision,
        }
        props.update(self.extra)
        return props


@dataclass(frozen=True)
class SyncCounters:
    """Sync result counters for envelopes."""

    discovered: int = 0
    written: int = 0
    deleted: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "discovered": self.discovered,
            "written": self.written,
            "deleted": self.deleted,
            "skipped": self.skipped,
        }


__all__ = [
    "ChunkRecord",
    "SourceType",
    "SyncCounters",
]
