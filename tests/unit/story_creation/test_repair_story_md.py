"""Unit tests for the batch story.md repair (AG3-068 / FK-21 §21.11.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.story_context_manager.story_model import (
    Story,
    StorySpecification,
    WireStoryType,
)
from agentkit.backend.story_creation.repair_story_md import repair_story_md

if TYPE_CHECKING:
    from pathlib import Path


def _story() -> Story:
    return Story(
        project_key="ak3",
        story_number=1,
        story_display_id="AK3-001",
        title="Implement broker adapter reconciliation",
        story_type=WireStoryType.IMPLEMENTATION,
        module="backend",
        participating_repos=["backend"],
        labels=["story"],
    )


def _spec() -> StorySpecification:
    return StorySpecification(
        need="A long enough problem statement to push the export above 500 bytes "
        "so the validation threshold is comfortably satisfied for the repair run.",
        solution="A long enough solution narrative to keep the rendered story.md "
        "well above the 500-byte minimum required by FK-21 §21.11.5 validation.",
        acceptance=["AC one", "AC two", "AC three"],
        concept_refs=["FK-21"],
    )


class _Attrs:
    def get_story_detail(self, story_display_id: str) -> object:
        del story_display_id
        return (_story(), _spec())


class _Index:
    def index_story(self, *, story_id: str, objects: object) -> int:
        del story_id, objects
        return 1


class _FailIndex:
    def index_story(self, *, story_id: str, objects: object) -> int:
        from agentkit.integration_clients.vectordb import VectorDbWriteError

        del story_id, objects
        raise VectorDbWriteError("rejected")


def test_repair_reports_n_m_k(tmp_path: Path) -> None:
    stories_root = tmp_path / "stories"
    # Valid dir name, missing story.md -> needs repair.
    (stories_root / "AK3-001_broker").mkdir(parents=True)
    # A non-story dir -> not counted.
    (stories_root / "_meta").mkdir()
    report = repair_story_md(
        stories_root,
        story_attributes=_Attrs(),
        index=_Index(),
    )
    assert report.checked == 1
    assert report.repaired == 1
    assert report.errors == 0
    assert (stories_root / "AK3-001_broker" / "story.md").is_file()


def test_repair_skips_valid_files(tmp_path: Path) -> None:
    stories_root = tmp_path / "stories"
    story_dir = stories_root / "AK3-001"
    story_dir.mkdir(parents=True)
    # Pre-write a valid story.md (> 500 bytes, frontmatter present).
    frontmatter = '---\nstory_id: AK3-001\nexported_at: "2026-01-01T00:00:00+00:00"\n---\n'
    body = "# Title\n\n" + ("padding line\n" * 60)
    (story_dir / "story.md").write_text(frontmatter + body, encoding="utf-8")

    report = repair_story_md(stories_root, story_attributes=_Attrs(), index=_Index())
    assert report.checked == 1
    assert report.repaired == 0
    assert report.errors == 0


def test_repair_counts_export_errors(tmp_path: Path) -> None:
    """A failing re-export (indexing blocked) is counted in K with detail."""
    stories_root = tmp_path / "stories"
    (stories_root / "AK3-001_broker").mkdir(parents=True)
    report = repair_story_md(
        stories_root,
        story_attributes=_Attrs(),
        index=_FailIndex(),
    )
    assert report.checked == 1
    assert report.repaired == 0
    assert report.errors == 1
    assert "AK3-001" in report.error_details


def test_repair_detects_too_short_existing_file(tmp_path: Path) -> None:
    """An existing but too-short story.md is detected as needing repair."""
    stories_root = tmp_path / "stories"
    story_dir = stories_root / "AK3-001"
    story_dir.mkdir(parents=True)
    (story_dir / "story.md").write_text("too short", encoding="utf-8")
    report = repair_story_md(stories_root, story_attributes=_Attrs(), index=_Index())
    assert report.checked == 1
    assert report.repaired == 1
