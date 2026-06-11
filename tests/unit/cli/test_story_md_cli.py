"""Unit tests for the ``export-story-md`` / ``repair-story-md`` CLI handlers.

Covers the AG3-068 CLI export/repair branches (FK-21 §21.11 / §21.11.6):

* fail-closed when the Weaviate index cannot be built (VectorDbError -> exit 1);
* a successful export prints the four-field result and returns exit 0;
* an export blocker (failed indexing / missing story) returns exit 1;
* the repair report N/M/K is printed and the exit code follows the error count.

The Weaviate index and the story-attribute read surface are the injected
boundaries (Weaviate / story-backend boundary => mocks exception). The argument
parsing, dispatch, result rendering and exit-code mapping run for real.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.cli import main as cli_main
from agentkit.integrations.vectordb import VectorDbWriteError
from agentkit.story_context_manager.story_model import (
    Story,
    StorySpecification,
    WireStoryType,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _story() -> Story:
    return Story(
        project_key="ak3",
        story_number=42,
        story_display_id="AK3-042",
        title="Implement broker adapter",
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
    def index_story(self, *, story_id: str, objects: object) -> int:
        del story_id, objects
        return 1


class _FailIndex:
    def index_story(self, *, story_id: str, objects: object) -> int:
        del story_id, objects
        raise VectorDbWriteError("weaviate write rejected")


# ---------------------------------------------------------------------------
# export-story-md
# ---------------------------------------------------------------------------


def test_export_story_md_fail_closed_when_weaviate_absent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """NEGATIVE: weaviate-client / Weaviate absent => VectorDbError, exit 1.

    Uses the REAL ``_build_weaviate_index`` (weaviate-client is not installed in
    the test env), so this exercises the genuine fail-closed connect branch.
    """
    rc = cli_main.main(
        ["export-story-md", "--story-id", "AK3-042", "--story-dir", "/tmp/x"]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "export-story-md failed [VectorDbUnavailable]" in err


def test_export_story_md_success_prints_result_and_exit_0(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: _OkIndex())
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    rc = cli_main.main(
        ["export-story-md", "--story-id", "AK3-042", "--story-dir", str(tmp_path)]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["error"] == ""
    assert payload["file_size_bytes"] > 500
    assert set(payload) == {"success", "story_md_path", "file_size_bytes", "error"}
    assert (tmp_path / "story.md").is_file()


def test_export_story_md_indexing_failure_exit_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEGATIVE: a Weaviate indexing failure blocks the export (exit 1)."""
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: _FailIndex())
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    rc = cli_main.main(
        ["export-story-md", "--story-id", "AK3-042", "--story-dir", str(tmp_path)]
    )
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert "Weaviate indexing failed" in payload["error"]


def test_export_story_md_unknown_story_exit_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEGATIVE: an unknown story (no master data) is a fail-closed blocker."""
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: _OkIndex())
    monkeypatch.setattr(cli_main, "_build_story_attributes", lambda: _FakeAttrs(None))
    rc = cli_main.main(
        ["export-story-md", "--story-id", "AK3-999", "--story-dir", str(tmp_path)]
    )
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert "not in the AK3 story backend" in payload["error"]


# ---------------------------------------------------------------------------
# repair-story-md
# ---------------------------------------------------------------------------


def test_repair_story_md_fail_closed_when_weaviate_absent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """NEGATIVE: weaviate absent => VectorDbError, exit 1 (real connect branch)."""
    rc = cli_main.main(["repair-story-md", "--stories-root", str(tmp_path)])
    assert rc == 1
    assert "repair-story-md failed [VectorDbUnavailable]" in capsys.readouterr().err


def test_repair_story_md_reports_n_m_k_and_exit_0(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing story.md is (re)exported; the N/M/K report is printed."""
    (tmp_path / "AK3-042").mkdir()
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: _OkIndex())
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    rc = cli_main.main(["repair-story-md", "--stories-root", str(tmp_path)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["checked"] == 1
    assert payload["repaired"] == 1
    assert payload["errors"] == 0
    assert payload["error_details"] == {}
    assert (tmp_path / "AK3-042" / "story.md").is_file()


def test_repair_story_md_export_failure_exit_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEGATIVE: a per-story export failure surfaces as K>0 and exit 1."""
    (tmp_path / "AK3-042").mkdir()
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: _FailIndex())
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    rc = cli_main.main(["repair-story-md", "--stories-root", str(tmp_path)])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["checked"] == 1
    assert payload["repaired"] == 0
    assert payload["errors"] == 1
    assert "AK3-042" in payload["error_details"]
