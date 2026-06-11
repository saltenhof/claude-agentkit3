"""Unit tests for the deterministic story.md export (AG3-068 / FK-21 §21.11).

The story-attribute read surface and the Weaviate index are the injected
boundaries (the index is the Weaviate boundary => mocks exception). The
rendering, validation and fail-closed indexing policy run for real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.integrations.vectordb import VectorDbWriteError
from agentkit.story_context_manager.story_model import (
    Story,
    StorySpecification,
    WireStoryType,
)
from agentkit.story_creation.story_md_export import (
    StoryMdExportResult,
    export_story_md,
)

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

    def index_story(self, *, story_id: str, objects: object) -> int:
        del objects
        self.calls.append(story_id)
        return 1


class _FailIndex:
    def index_story(self, *, story_id: str, objects: object) -> int:
        del story_id, objects
        raise VectorDbWriteError("weaviate write rejected")


def test_export_success_writes_frontmatter_and_indexes(tmp_path: Path) -> None:
    index = _OkIndex()
    result = export_story_md(
        "AK3-042",
        tmp_path,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=index,
    )
    assert isinstance(result, StoryMdExportResult)
    assert result.success is True
    assert result.error == ""
    md = (tmp_path / "story.md").read_text(encoding="utf-8")
    assert md.startswith("---\n")
    assert "story_id: AK3-042" in md
    assert "exported_at:" in md
    assert "# Implement broker adapter" in md
    assert result.file_size_bytes > 500
    assert index.calls == ["AK3-042"]


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
        tmp_path,
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
        tmp_path,
        story_attributes=_FakeAttrs((short, None)),
        index=index,
    )
    assert result.success is False
    assert "bytes" in result.error
    assert index.calls == []


def test_unknown_story_fails_closed(tmp_path: Path) -> None:
    """NEGATIVE: an unknown story fails closed (no fabricated master data)."""
    result = export_story_md(
        "AK3-999",
        tmp_path,
        story_attributes=_FakeAttrs(None),
        index=_OkIndex(),
    )
    assert result.success is False
    assert "not in the AK3 story backend" in result.error
    assert not (tmp_path / "story.md").exists()


def test_export_renders_all_optional_sections(tmp_path: Path) -> None:
    """Spec-driven sections (problem/solution/AC/refs/DoD) are all rendered."""
    result = export_story_md(
        "AK3-042",
        tmp_path,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=_OkIndex(),
    )
    assert result.success is True
    md = (tmp_path / "story.md").read_text(encoding="utf-8")
    assert "## Problemstellung" in md
    assert "## Loesungsansatz" in md
    assert "## Akzeptanzkriterien" in md
    assert "## Konzept-Referenzen" in md
    assert "## Definition of Done" in md
    assert "vectordb_conflict_resolved: false" in md


def test_export_write_failure_is_fail_closed(tmp_path: Path) -> None:
    """NEGATIVE: an OSError on write yields success=False with the cause."""
    # A pre-existing *file* at the story-dir path makes the parent mkdir fail.
    blocking = tmp_path / "blocked"
    blocking.write_text("not a dir", encoding="utf-8")
    result = export_story_md(
        "AK3-042",
        blocking,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=_OkIndex(),
    )
    assert result.success is False
    assert result.error != ""


def test_export_is_deterministic_modulo_timestamp(tmp_path: Path) -> None:
    """The body (minus the exported_at line) is byte-stable across runs."""
    out1 = tmp_path / "a"
    out2 = tmp_path / "b"
    out1.mkdir()
    out2.mkdir()
    export_story_md("AK3-042", out1, story_attributes=_FakeAttrs((_story(), _spec())), index=_OkIndex())
    export_story_md("AK3-042", out2, story_attributes=_FakeAttrs((_story(), _spec())), index=_OkIndex())

    def _strip_ts(text: str) -> list[str]:
        return [line for line in text.splitlines() if not line.startswith("exported_at:")]

    assert _strip_ts((out1 / "story.md").read_text(encoding="utf-8")) == _strip_ts(
        (out2 / "story.md").read_text(encoding="utf-8")
    )
