"""Unit tests for the ``export-story-md`` / ``repair-story-md`` CLI handlers.

Covers the AG3-068 CLI export/repair branches (FK-21 §21.11 / §21.11.6) and the
AG3-174 N06 authority rule: the project id comes from the project configuration
(``project_prefix``) or the ``PROJECT_ID`` binding -- a caller-supplied
``--project-id`` is only a cross-check, a divergent one is REJECTED and a missing
authority is a hard error (D2).

The Weaviate index and the story-attribute read surface are the injected
boundaries (Weaviate / story-backend boundary => mocks exception). The argument
parsing, project-id resolution, dispatch, result rendering and exit-code mapping
run for real.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.cli import main as cli_main
from agentkit.backend.story_context_manager.story_model import (
    Story,
    StorySpecification,
    WireStoryType,
)
from agentkit.integration_clients.vectordb import VectorDbWriteError

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
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.objects: list[dict[str, object]] = []

    def index_story(self, *, story_id: str, project_id: str, objects: object) -> int:
        self.calls.append((story_id, project_id))
        self.objects = list(objects)  # type: ignore[arg-type]
        return len(self.objects)


def _story_dir(tmp_path: Path, story_id: str = "AK3-042") -> Path:
    """The CANONICAL ``<root>/stories/<story-id>/`` layout the export verifies."""
    directory = tmp_path / "stories" / story_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_project_config(root: Path, prefix: str) -> None:
    """Write a minimal valid project.yaml carrying the authoritative prefix."""
    config_dir = root / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.yaml").write_text(
        "project_key: acme\n"
        "project_name: Acme\n"
        f"project_prefix: {prefix}\n"
        "repositories:\n  - name: app\n    path: .\n"
        "pipeline:\n"
        "  config_version: '3.0'\n"
        "  features:\n    multi_llm: false\n"
        "  sonarqube:\n    available: false\n    enabled: false\n"
        "  ci:\n    available: false\n    enabled: false\n",
        encoding="utf-8",
    )


class _FailIndex:
    def index_story(self, *, story_id: str, project_id: str, objects: object) -> int:
        del story_id, project_id, objects
        raise VectorDbWriteError("weaviate write rejected")


# ---------------------------------------------------------------------------
# export-story-md
# ---------------------------------------------------------------------------


def test_export_story_md_fail_closed_when_weaviate_absent(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEGATIVE: weaviate-client / Weaviate absent => VectorDbError, exit 1.

    Uses the REAL ``_build_weaviate_index`` (weaviate-client is not installed in
    the test env), so this exercises the genuine fail-closed connect branch.
    """
    monkeypatch.setenv("PROJECT_ID", "AK3")
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
    index = _OkIndex()
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: index)
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.setenv("PROJECT_ID", "AK3")
    story_dir = _story_dir(tmp_path)
    rc = cli_main.main(
        ["export-story-md", "--story-id", "AK3-042", "--story-dir", str(story_dir), "--project-id", "AK3"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    # R04: the indexed objects carry the PROJECT-RELATIVE canonical source path
    # and the authoritative project id -- never an absolute path.
    assert index.calls == [("AK3-042", "AK3")]
    assert {str(o.properties["source_file"]) for o in index.objects} == {
        "stories/AK3-042/story.md"
    }
    assert all(o.properties["project_id"] == "AK3" for o in index.objects)
    assert payload["error"] == ""
    assert payload["file_size_bytes"] > 500
    assert set(payload) == {"success", "story_md_path", "file_size_bytes", "error"}
    assert (story_dir / "story.md").is_file()


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
    monkeypatch.setenv("PROJECT_ID", "AK3")
    rc = cli_main.main(
        [
            "export-story-md", "--story-id", "AK3-042",
            "--story-dir", str(_story_dir(tmp_path)), "--project-id", "AK3",
        ]
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
    monkeypatch.setenv("PROJECT_ID", "AK3")
    rc = cli_main.main(
        ["export-story-md", "--story-id", "AK3-999", "--story-dir", str(_story_dir(tmp_path, "AK3-999"))]
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEGATIVE: weaviate absent => VectorDbError, exit 1 (real connect branch)."""
    monkeypatch.setenv("PROJECT_ID", "AK3")
    rc = cli_main.main(["repair-story-md", "--stories-root", str(tmp_path), "--project-id", "AK3"])
    assert rc == 1
    assert "repair-story-md failed [VectorDbUnavailable]" in capsys.readouterr().err


def test_repair_story_md_reports_n_m_k_and_exit_0(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing story.md is (re)exported; the N/M/K report is printed."""
    stories_root = tmp_path / "stories"
    (stories_root / "AK3-042").mkdir(parents=True)
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: _OkIndex())
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.setenv("PROJECT_ID", "AK3")
    rc = cli_main.main(["repair-story-md", "--stories-root", str(stories_root), "--project-id", "AK3"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["checked"] == 1
    assert payload["repaired"] == 1
    assert payload["errors"] == 0
    assert payload["error_details"] == {}
    assert (stories_root / "AK3-042" / "story.md").is_file()


def test_repair_story_md_export_failure_exit_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEGATIVE: a per-story export failure surfaces as K>0 and exit 1."""
    stories_root = tmp_path / "stories"
    (stories_root / "AK3-042").mkdir(parents=True)
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: _FailIndex())
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.setenv("PROJECT_ID", "AK3")
    rc = cli_main.main(["repair-story-md", "--stories-root", str(stories_root), "--project-id", "AK3"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["checked"] == 1
    assert payload["repaired"] == 0
    assert payload["errors"] == 1
    assert "AK3-042" in payload["error_details"]


# ---------------------------------------------------------------------------
# N06 / D2: the project id is AUTHORITATIVE, not a caller argument
# ---------------------------------------------------------------------------


def test_n06_divergent_project_id_is_rejected_without_indexing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A --project-id diverging from the configured prefix must be REJECTED."""
    index = _OkIndex()
    project_root = tmp_path / "project"
    _write_project_config(project_root, "ACME")
    story_dir = project_root / "stories" / "AK3-042"
    story_dir.mkdir(parents=True)
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: index)
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.delenv("PROJECT_ID", raising=False)
    rc = cli_main.main(
        [
            "export-story-md",
            "--story-id", "AK3-042",
            "--story-dir", str(story_dir),
            "--project-root", str(project_root),
            "--project-id", "FOREIGN",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "export-story-md failed [ProjectBinding]" in err
    assert "FOREIGN" in err
    assert index.calls == [], "no cross-project indexing may happen"
    assert not (story_dir / "story.md").exists(), "no artefact may be written"


def test_n06_matching_project_id_uses_the_configured_prefix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = _OkIndex()
    project_root = tmp_path / "project"
    _write_project_config(project_root, "ACME")
    story_dir = project_root / "stories" / "AK3-042"
    story_dir.mkdir(parents=True)
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: index)
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.delenv("PROJECT_ID", raising=False)
    rc = cli_main.main(
        [
            "export-story-md",
            "--story-id", "AK3-042",
            "--story-dir", str(story_dir),
            "--project-root", str(project_root),
            "--project-id", "ACME",
        ]
    )
    assert rc == 0
    capsys.readouterr()
    assert index.calls == [("AK3-042", "ACME")]


def test_n06_omitted_project_id_derives_the_configured_prefix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = _OkIndex()
    project_root = tmp_path / "project"
    _write_project_config(project_root, "ACME")
    story_dir = project_root / "stories" / "AK3-042"
    story_dir.mkdir(parents=True)
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: index)
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.delenv("PROJECT_ID", raising=False)
    rc = cli_main.main(
        [
            "export-story-md",
            "--story-id", "AK3-042",
            "--story-dir", str(story_dir),
            "--project-root", str(project_root),
        ]
    )
    assert rc == 0
    capsys.readouterr()
    assert index.calls == [("AK3-042", "ACME")]


def test_n06_env_diverging_from_the_config_is_rejected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = _OkIndex()
    project_root = tmp_path / "project"
    _write_project_config(project_root, "ACME")
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: index)
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.setenv("PROJECT_ID", "OTHER")
    rc = cli_main.main(
        [
            "export-story-md",
            "--story-id", "AK3-042",
            "--story-dir", str(project_root / "stories" / "AK3-042"),
            "--project-root", str(project_root),
        ]
    )
    assert rc == 1
    assert "diverges" in capsys.readouterr().err
    assert index.calls == []


def test_n06_missing_authority_is_a_hard_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No config prefix and no PROJECT_ID: the export must NOT fall back to ''."""
    index = _OkIndex()
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: index)
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.delenv("PROJECT_ID", raising=False)
    monkeypatch.delenv("AGENTKIT_PROJECT_ID", raising=False)
    rc = cli_main.main(
        [
            "export-story-md",
            "--story-id", "AK3-042",
            "--story-dir", str(_story_dir(tmp_path)),
            "--project-root", str(tmp_path),
            "--project-id", "ANY",
        ]
    )
    assert rc == 1
    assert "no authoritative project id" in capsys.readouterr().err
    assert index.calls == []


def test_n06_repair_rejects_a_divergent_project_id(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = _OkIndex()
    stories_root = tmp_path / "stories"
    (stories_root / "AK3-042").mkdir(parents=True)
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: index)
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.setenv("PROJECT_ID", "AK3")
    rc = cli_main.main(
        ["repair-story-md", "--stories-root", str(stories_root), "--project-id", "FOREIGN"]
    )
    assert rc == 1
    assert "repair-story-md failed [ProjectBinding]" in capsys.readouterr().err
    assert index.calls == []
    assert not (stories_root / "AK3-042" / "story.md").exists()


def test_n22_invalid_project_config_is_not_treated_as_absent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N22/D2: a malformed EXISTING config must not fall back to PROJECT_ID."""
    index = _OkIndex()
    project_root = tmp_path / "project"
    config_dir = project_root / ".agentkit" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "project.yaml").write_text("project_key: acme\n", encoding="utf-8")
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: index)
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.setenv("PROJECT_ID", "AK3")
    rc = cli_main.main(
        [
            "export-story-md",
            "--story-id", "AK3-042",
            "--story-dir", str(project_root / "stories" / "AK3-042"),
            "--project-root", str(project_root),
            "--project-id", "AK3",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "exists but is invalid" in err
    assert index.calls == [], "an invalid config must never bind to the env value"


def test_n22_unreadable_project_config_is_a_hard_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A config that exists but cannot be parsed as YAML is fail-closed."""
    index = _OkIndex()
    project_root = tmp_path / "project"
    config_dir = project_root / ".agentkit" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "project.yaml").write_text("project_key: [unclosed\n", encoding="utf-8")
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: index)
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.setenv("PROJECT_ID", "AK3")
    rc = cli_main.main(
        [
            "repair-story-md",
            "--stories-root", str(project_root / "stories"),
            "--project-root", str(project_root),
        ]
    )
    assert rc == 1
    assert "[ProjectBinding]" in capsys.readouterr().err
    assert index.calls == []


def test_n22_genuinely_absent_config_still_uses_the_env_binding(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absence is NOT invalidity: with no project.yaml the env is the authority."""
    index = _OkIndex()
    project_root = tmp_path / "project"
    (project_root / "stories" / "AK3-042").mkdir(parents=True)
    monkeypatch.setattr(cli_main, "_build_weaviate_index", lambda _root: index)
    monkeypatch.setattr(
        cli_main, "_build_story_attributes", lambda: _FakeAttrs((_story(), _spec()))
    )
    monkeypatch.setenv("PROJECT_ID", "AK3")
    rc = cli_main.main(
        [
            "export-story-md",
            "--story-id", "AK3-042",
            "--story-dir", str(project_root / "stories" / "AK3-042"),
            "--project-root", str(project_root),
        ]
    )
    assert rc == 0
    capsys.readouterr()
    assert index.calls == [("AK3-042", "AK3")]
