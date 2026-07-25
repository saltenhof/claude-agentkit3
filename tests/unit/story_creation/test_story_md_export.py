"""Unit tests for the deterministic story.md export (AG3-068 / FK-21 §21.11).

The story-attribute read surface and the Weaviate index are the injected
boundaries (the index is the Weaviate boundary => mocks exception). The
rendering, validation and fail-closed indexing policy run for real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.story_context_manager.story_model import (
    Story,
    StorySpecification,
    WireStoryType,
)
from agentkit.backend.story_creation.story_md_export import (
    StoryMdExportResult,
    canonical_story_source_file,
    export_story_md,
)
from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects
from agentkit.backend.vectordb.schema import deterministic_uuid
from agentkit.integration_clients.vectordb import VectorDbWriteError

if TYPE_CHECKING:
    from pathlib import Path


def _story(title: str = "Implement broker adapter") -> Story:
    return Story(
        project_key="ak3",
        story_number=42,
        story_display_id="AK3-042",
        title=title,
        story_type=WireStoryType.IMPLEMENTATION,
        module="backend/app",
        epic="payments",
        participating_repos=["backend"],
        labels=["story", "backend"],
    )


def _spec() -> StorySpecification:
    return StorySpecification(
        need="The broker adapter mishandles partial fills.",
        solution="Introduce an idempotent reconciliation step in the adapter.",
        acceptance=["Partial fills reconcile", "No duplicate orders"],
        concept_refs=["FK-13", "FK-21"],
        definition_of_done=["Tests green", "Reviewed"],
    )


class _FakeAttrs:
    def __init__(self, detail: object) -> None:
        self._detail = detail

    def get_story_detail(self, story_display_id: str) -> object:
        del story_display_id
        return self._detail


class _OkIndex:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.last_objects: list[dict[str, object]] = []

    def index_story(self, *, story_id: str, project_id: str, objects: object) -> int:
        self.calls.append(story_id)
        self.last_objects = list(objects) if isinstance(objects, list) else []  # type: ignore[arg-type]
        return len(self.last_objects)


def _story_dir(tmp_path: Path, story_id: str = "AK3-042") -> Path:
    """Create the CANONICAL story directory ``<root>/stories/<story-id>/`` (N21).

    The export verifies containment under a ``stories/`` root and agreement with
    the story id, because the indexed ``source_file`` must be the path
    ``story_sync`` also discovers.
    """
    directory = tmp_path / "stories" / story_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class _FailIndex:
    def index_story(self, *, story_id: str, project_id: str, objects: object) -> int:
        del story_id, project_id, objects
        raise VectorDbWriteError("weaviate write rejected")


def test_export_success_writes_frontmatter_and_indexes(tmp_path: Path) -> None:
    index = _OkIndex()
    story_dir = _story_dir(tmp_path)
    result = export_story_md(
        "AK3-042",
        story_dir,
        project_id="acme",
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=index,
    )
    assert isinstance(result, StoryMdExportResult)
    assert result.success is True
    assert result.error == ""
    md = (story_dir / "story.md").read_text(encoding="utf-8")
    assert md.startswith("---\n")
    assert "story_id: AK3-042" in md
    assert "exported_at:" in md
    assert "# Implement broker adapter" in md
    assert result.file_size_bytes > 500
    assert index.calls == ["AK3-042"]
    # R04: exported objects carry the full StoryContext projection, not the old
    # minimal problem/solution shape.
    assert index.last_objects
    obj = index.last_objects[0]
    assert obj["project_id"] == "acme"
    assert obj["source_type"] == "story"
    assert "content" in obj and obj["content"]
    assert "content_hash" in obj and obj["content_hash"]
    assert "section_heading" in obj
    assert "uuid" in obj
    # R04: the REAL caller indexes the PROJECT-RELATIVE canonical corpus path and
    # the REAL title/status from the exported frontmatter -- not an absolute path
    # and not the story id as a stand-in title.
    rel = "stories/AK3-042/story.md"
    assert canonical_story_source_file(story_dir, "AK3-042") == rel
    assert {str(o["source_file"]) for o in index.last_objects} == {rel}
    assert obj["title"] == "Implement broker adapter"
    assert obj["status"] == "Backlog"
    assert obj["story_type"] == "implementation"
    assert obj["module"] == "backend/app"
    assert obj["epic"] == "payments"
    # The uuid is the deterministic identity of the RELATIVE path.
    # ...and the exported frontmatter itself carries the real metadata (R04).
    assert "title: Implement broker adapter" in md
    assert "status: Backlog" in md
    assert "story_type: implementation" in md


def test_r04_indexed_identity_is_derived_from_the_relative_path(tmp_path: Path) -> None:
    """R04: re-projecting the written file yields the SAME uuids as the export."""
    index = _OkIndex()
    story_dir = _story_dir(tmp_path)
    result = export_story_md(
        "AK3-042",
        story_dir,
        project_id="acme",
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=index,
    )
    assert result.success is True
    rel = canonical_story_source_file(story_dir, "AK3-042")
    reprojected = story_file_to_objects("acme", story_dir / "story.md", source_file=rel)
    assert {o.uuid for o in reprojected} == {str(o["uuid"]) for o in index.last_objects}
    for obj in reprojected:
        assert obj.uuid == deterministic_uuid("acme", rel, obj.chunk_id)


def test_n21_directory_outside_a_stories_root_is_rejected(tmp_path: Path) -> None:
    """N21: exporting into an arbitrary folder must NOT fabricate a corpus path."""
    import pytest

    stray = tmp_path / "tmp" / "AK3-042"
    stray.mkdir(parents=True)
    with pytest.raises(ValueError, match="not contained in a 'stories' root"):
        canonical_story_source_file(stray, "AK3-042")


def test_n21_directory_name_must_identify_the_story(tmp_path: Path) -> None:
    """N21: ``stories/foo/story.md`` must not be indexed as story ``AK3-042``."""
    import pytest

    foreign = tmp_path / "stories" / "foo"
    foreign.mkdir(parents=True)
    with pytest.raises(ValueError, match="does not identify story"):
        canonical_story_source_file(foreign, "AK3-042")
    other_story = tmp_path / "stories" / "AK3-999"
    other_story.mkdir(parents=True)
    with pytest.raises(ValueError, match="does not identify story"):
        canonical_story_source_file(other_story, "AK3-042")


def test_n21_slugged_story_directory_is_accepted(tmp_path: Path) -> None:
    """The corpus convention allows ``<STORY-ID>-<slug>`` (as in this repo)."""
    slugged = tmp_path / "stories" / "AK3-042-broker-adapter"
    slugged.mkdir(parents=True)
    assert (
        canonical_story_source_file(slugged, "AK3-042")
        == "stories/AK3-042-broker-adapter/story.md"
    )


def test_n21_export_rejects_a_non_canonical_directory(tmp_path: Path) -> None:
    """Through the REAL export: a stray directory neither writes nor indexes."""
    index = _OkIndex()
    stray = tmp_path / "scratch" / "AK3-042"
    stray.mkdir(parents=True)
    result = export_story_md(
        "AK3-042",
        stray,
        project_id="acme",
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=index,
    )
    assert result.success is False
    assert "not contained in a 'stories' root" in result.error
    assert index.calls == []


def test_export_result_has_exactly_four_fields() -> None:
    """AC8: StoryMdExportResult is frozen with EXACTLY the four FK fields."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(StoryMdExportResult)}
    assert fields == {"success", "story_md_path", "file_size_bytes", "error"}
    assert StoryMdExportResult.__dataclass_params__.frozen is True


def test_indexing_failure_blocks_export_fail_closed(tmp_path: Path) -> None:
    """NEGATIVE: an indexing failure blocks the export (no catch-up, §21.11.4)."""
    result = export_story_md(
        "AK3-042",
        _story_dir(tmp_path),
        project_id="acme",
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=_FailIndex(),
    )
    assert result.success is False
    assert "indexing failed" in result.error.lower()
    # The file was written (size carried) but the export is a hard FAIL.
    assert result.file_size_bytes > 0


def test_too_short_story_fails_validation(tmp_path: Path) -> None:
    """NEGATIVE: a < 500-byte render fails validation (no indexing attempted)."""
    index = _OkIndex()
    short = _story(title="x")
    result = export_story_md(
        "AK3-042",
        _story_dir(tmp_path),
        project_id="acme",
        story_attributes=_FakeAttrs((short, None)),
        index=index,
    )
    assert result.success is False
    assert "bytes" in result.error
    assert index.calls == []


def test_unknown_story_fails_closed(tmp_path: Path) -> None:
    """NEGATIVE: an unknown story fails closed (no fabricated master data)."""
    story_dir = _story_dir(tmp_path, "AK3-999")
    result = export_story_md(
        "AK3-999",
        story_dir,
        story_attributes=_FakeAttrs(None),
        project_id="acme", index=_OkIndex(),
    )
    assert result.success is False
    assert "not in the AK3 story backend" in result.error
    assert not (story_dir / "story.md").exists()


def test_export_renders_all_optional_sections(tmp_path: Path) -> None:
    """Spec-driven sections (problem/solution/AC/refs/DoD) are all rendered."""
    story_dir = _story_dir(tmp_path)
    result = export_story_md(
        "AK3-042",
        story_dir,
        story_attributes=_FakeAttrs((_story(), _spec())),
        project_id="acme", index=_OkIndex(),
    )
    assert result.success is True
    md = (story_dir / "story.md").read_text(encoding="utf-8")
    assert "## Problemstellung" in md
    assert "## Loesungsansatz" in md
    assert "## Akzeptanzkriterien" in md
    assert "## Konzept-Referenzen" in md
    assert "## Definition of Done" in md
    assert "vectordb_conflict_resolved: false" in md


def test_export_write_failure_is_fail_closed(tmp_path: Path) -> None:
    """NEGATIVE: an OSError on write yields success=False with the cause."""
    # A pre-existing *file* at the story-dir path makes the parent mkdir fail.
    (tmp_path / "stories").mkdir()
    blocking = tmp_path / "stories" / "AK3-042"
    blocking.write_text("not a dir", encoding="utf-8")
    result = export_story_md(
        "AK3-042",
        blocking,
        story_attributes=_FakeAttrs((_story(), _spec())),
        project_id="acme", index=_OkIndex(),
    )
    assert result.success is False
    assert result.error != ""


def test_export_is_deterministic_modulo_timestamp(tmp_path: Path) -> None:
    """The body (minus the exported_at line) is byte-stable across runs."""
    out1 = _story_dir(tmp_path / "a")
    out2 = _story_dir(tmp_path / "b")
    export_story_md("AK3-042", out1, story_attributes=_FakeAttrs((_story(), _spec())), project_id="acme", index=_OkIndex())
    export_story_md("AK3-042", out2, story_attributes=_FakeAttrs((_story(), _spec())), project_id="acme", index=_OkIndex())

    def _strip_ts(text: str) -> list[str]:
        return [line for line in text.splitlines() if not line.startswith("exported_at:")]

    assert _strip_ts((out1 / "story.md").read_text(encoding="utf-8")) == _strip_ts(
        (out2 / "story.md").read_text(encoding="utf-8")
    )
