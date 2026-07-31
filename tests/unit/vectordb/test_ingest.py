"""Ingest adapter + profiles + source/producer closure tests (AC3, AC5, AC9)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.vectordb.ingest import (
    FK13_CONCEPT_PROFILE,
    FK13_STORY_PROFILE,
    classify_source_file,
    concept_chunks_to_objects,
    producer_for,
)
from agentkit.backend.vectordb.ingest.classify import (
    PRODUCER_BY_SOURCE_TYPE,
    source_types_for_producer,
)
from agentkit.concepts.parser import discover_concept_files

if TYPE_CHECKING:
    from pathlib import Path

# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #


def test_concept_profile_binds_concept_sync() -> None:
    assert FK13_CONCEPT_PROFILE.producer == "concept_sync"
    assert FK13_CONCEPT_PROFILE.source_types == ("concept",)


def test_story_profile_binds_story_sync() -> None:
    assert FK13_STORY_PROFILE.producer == "story_sync"
    assert set(FK13_STORY_PROFILE.source_types) == {"story", "research"}


def test_producer_closure_is_exclusive() -> None:
    # story/research -> ONLY story_sync; concept -> ONLY concept_sync.
    assert PRODUCER_BY_SOURCE_TYPE["story"] == "story_sync"
    assert PRODUCER_BY_SOURCE_TYPE["research"] == "story_sync"
    assert PRODUCER_BY_SOURCE_TYPE["concept"] == "concept_sync"
    assert set(source_types_for_producer("story_sync")) == {"story", "research"}
    assert set(source_types_for_producer("concept_sync")) == {"concept"}


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path,expected",
    [
        ("stories/AG3-174/story.md", "story"),
        ("stories/AG3-174/research/findings.md", "research"),
        ("stories/AG3-174/research/sub/deep.md", "research"),
        ("concept/technical-design/13_retrieval.md", "concept"),
        ("concept/_meta/decisions/x.md", "concept"),
        ("stories/AG3-174/review-codex.md", None),
        ("review-arch.md", None),
        ("stories/AG3-174/closure/audit.md", None),
        ("stories/AG3-174/handover.md", None),
        ("random/readme.md", None),
    ],
)
def test_classify_source_file(path: str, expected: str | None) -> None:
    assert classify_source_file(path) == expected


def test_review_md_is_negative_research_case() -> None:
    # AC3: review*.md must NOT land as research.
    assert classify_source_file("stories/AG3-174/review-11-codex.md") is None


def test_producer_for_none_is_none() -> None:
    assert producer_for(None) is None
    assert producer_for("bogus") is None


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #


_DOC = """\
---
concept_id: FK-13
title: Retrieval
module: vectordb
status: active
doc_kind: core
authority_over:
  - scope: vectordb
---

# 13 Retrieval

## 13.1 Purpose

Purpose text.
"""


def _write_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "concept"
    (root / "technical-design").mkdir(parents=True)
    (root / "technical-design" / "13.md").write_text(_DOC, encoding="utf-8")
    return root


def test_concept_chunks_to_objects_carries_full_fields(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    discovery = discover_concept_files(root)
    objects = concept_chunks_to_objects("acme", discovery)
    assert objects
    obj = objects[0]
    assert obj.properties["source_type"] == "concept"
    assert obj.properties["project_id"] == "acme"
    assert obj.properties["concept_id"] == "FK-13"
    assert obj.properties["authority_over"] == ["vectordb"]
    assert obj.properties["content"]
    assert obj.properties["section_number"]
    # deterministic UUID stable across calls
    again = concept_chunks_to_objects("acme", discovery)
    assert [o.uuid for o in objects] == [o.uuid for o in again]


def test_concept_objects_uuid_is_project_scoped(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    discovery = discover_concept_files(root)
    acme = concept_chunks_to_objects("acme", discovery)
    other = concept_chunks_to_objects("other", discovery)
    assert {o.uuid for o in acme}.isdisjoint({o.uuid for o in other})


def test_story_file_to_objects(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects
    from agentkit.backend.vectordb.schema import deterministic_uuid

    story_md = tmp_path / "stories" / "AG3-1" / "story.md"
    story_md.parent.mkdir(parents=True)
    story_md.write_text(
        "---\nstory_id: AG3-1\ntitle: Real title\nstatus: Backlog\n---\n"
        "\n# Title\n\n## Problem\n\nNeed.\n",
        encoding="utf-8",
    )
    rel = "stories/AG3-1/story.md"
    objs = story_file_to_objects("acme", story_md, source_file=rel)
    assert objs
    assert all(o.properties["source_type"] == "story" for o in objs)
    assert all(o.properties["project_id"] == "acme" for o in objs)
    assert all(o.properties["source_file"] == rel for o in objs)
    assert objs[0].properties["story_id"] == "AG3-1"
    assert objs[0].properties["title"] == "Real title"
    assert objs[0].properties["status"] == "Backlog"
    # The identity is derived from the PROJECT-RELATIVE path and is verifiable.
    assert objs[0].uuid == deterministic_uuid("acme", rel, objs[0].chunk_id)


def test_story_file_to_objects_requires_a_relative_source_file(tmp_path: Path) -> None:
    """R04: an absolute path must never become the corpus identity."""
    from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects

    story_md = tmp_path / "stories" / "AG3-1" / "story.md"
    story_md.parent.mkdir(parents=True)
    story_md.write_text("---\nstory_id: AG3-1\n---\n\n# T\n\n## P\n\nn.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="PROJECT-RELATIVE"):
        story_file_to_objects("acme", story_md, source_file=story_md.as_posix())


def test_story_file_without_frontmatter_is_rejected(tmp_path: Path) -> None:
    """N05: ABSENT frontmatter is a named error, not an accepted partial quality."""
    from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects
    from agentkit.concepts.frontmatter import FrontmatterError

    story_md = tmp_path / "s.md"
    story_md.write_text("# No frontmatter\n\n## P\n\nn.\n", encoding="utf-8")
    with pytest.raises(FrontmatterError, match="no frontmatter block"):
        story_file_to_objects("acme", story_md, source_file="stories/x/story.md")


@pytest.mark.parametrize(
    "frontmatter,match",
    [
        ("story_id: AG3-1\nstatus: 42\n", "status"),
        ("story_id: AG3-1\ntitle: true\n", "title"),
        ("story_id: 7\n", "story_id"),
        ("story_id: AG3-1\nstory_type: [a]\n", "story_type"),
        ("title: T\n", "story_id"),
    ],
)
def test_story_metadata_is_never_coerced(
    tmp_path: Path, frontmatter: str, match: str
) -> None:
    """N05: numeric/boolean/list metadata is a named error -- no ``str()`` coercion."""
    from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects
    from agentkit.concepts.frontmatter import FrontmatterError

    story_md = tmp_path / "s.md"
    story_md.write_text(f"---\n{frontmatter}---\n\n# T\n\n## P\n\nn.\n", encoding="utf-8")
    with pytest.raises(FrontmatterError, match=match):
        story_file_to_objects("acme", story_md, source_file="stories/x/story.md")


def test_research_source_type_is_carried(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects

    doc = tmp_path / "findings.md"
    doc.write_text("---\nstory_id: AG3-1\n---\n\n# R\n\n## F\n\nfound.\n", encoding="utf-8")
    objs = story_file_to_objects(
        "acme", doc, source_file="stories/AG3-1/research/findings.md", source_type="research"
    )
    assert all(o.properties["source_type"] == "research" for o in objs)


def test_classify_story_corpus_files(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.ingest.adapter import classify_story_corpus_files
    from agentkit.backend.vectordb.project_binding import ProjectBinding

    (tmp_path / "concept" / "technical-design").mkdir(parents=True)
    (tmp_path / "concept" / "technical-design" / "13.md").write_text("# c\n", encoding="utf-8")
    (tmp_path / "stories" / "AG3-1").mkdir(parents=True)
    (tmp_path / "stories" / "AG3-1" / "story.md").write_text("# s\n", encoding="utf-8")
    binding = ProjectBinding(
        project_id="acme",
        project_root=tmp_path,
        concepts_dir=tmp_path / "concept",
        stories_dir=tmp_path / "stories",
        weaviate_http_endpoint="http://weaviate.acme.local:8080",
        weaviate_grpc_endpoint="weaviate.acme.local:50051",
    )
    classified = classify_story_corpus_files(binding)
    assert any("story.md" in p for p in classified)
    assert all(v in ("story", "research", "concept") for v in classified.values())


# --------------------------------------------------------------------------- #
# N32: a SLUGGED story directory yields the story id, not the directory name
# --------------------------------------------------------------------------- #


_SLUGGED = "stories/AG3-174-vectordb-retrieval-engine/research/note.md"


def test_n32_slugged_research_directory_yields_the_story_id() -> None:
    from agentkit.backend.vectordb.ingest.adapter import research_story_id

    assert research_story_id(_SLUGGED) == "AG3-174"
    assert research_story_id("stories/AG3-174/research/note.md") == "AG3-174"
    assert research_story_id("stories/AK3-042_broker/research/deep/note.md") == "AK3-042"


def test_n32_slugged_research_note_without_frontmatter_is_ingested(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects

    note = tmp_path / "note.md"
    note.write_text("# Options\n\n## Findings\n\nfound.\n", encoding="utf-8")
    objs = story_file_to_objects(
        "acme", note, source_file=_SLUGGED, source_type="research"
    )
    assert objs
    assert objs[0].properties["story_id"] == "AG3-174"
    assert objs[0].properties["story_type"] == "research"
    assert objs[0].properties["title"] == "Options"


def test_n32_slugged_research_note_accepts_the_matching_story_id(tmp_path: Path) -> None:
    """A CORRECT frontmatter story_id must not be rejected as contradictory."""
    from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects

    note = tmp_path / "note.md"
    note.write_text("---\nstory_id: AG3-174\n---\n\n# R\n\n## F\n\nfound.\n", encoding="utf-8")
    objs = story_file_to_objects(
        "acme", note, source_file=_SLUGGED, source_type="research"
    )
    assert objs[0].properties["story_id"] == "AG3-174"


def test_n32_slugged_research_note_rejects_a_contradicting_story_id(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects
    from agentkit.concepts.frontmatter import FrontmatterError

    note = tmp_path / "note.md"
    note.write_text("---\nstory_id: AG3-999\n---\n\n# R\n\n## F\n\nfound.\n", encoding="utf-8")
    with pytest.raises(FrontmatterError, match="canonical path"):
        story_file_to_objects("acme", note, source_file=_SLUGGED, source_type="research")


def test_n32_research_directory_that_is_no_story_is_rejected() -> None:
    from agentkit.backend.vectordb.ingest.adapter import research_story_id

    with pytest.raises(ValueError, match="does not identify a story"):
        research_story_id("stories/scratchpad/research/note.md")


def test_n32_story_dir_parser_is_shared_with_the_export() -> None:
    """ONE definition of the directory <-> story-id relation (N32)."""
    from agentkit.backend.story_creation.story_md_export import story_dir_story_id
    from agentkit.backend.vectordb.ingest.classify import story_id_from_story_dir_name

    for name in ("AG3-174", "AG3-174-vectordb-retrieval-engine", "AK3-042_broker", "nope"):
        assert story_dir_story_id(name) == story_id_from_story_dir_name(name)
