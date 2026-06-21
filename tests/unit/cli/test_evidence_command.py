"""Tests for the ``agentkit evidence`` CLI command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from agentkit.backend.cli.main import main


def test_evidence_assemble_command_writes_manifest_and_prints_merge_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI command runs the assembler and writes ``bundle_manifest.json``."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    (story_dir / "story.md").write_text("# Story\n", encoding="utf-8")
    config_path = tmp_path / "evidence.json"
    config_path.write_text(
        json.dumps(
            {
                "repositories": [
                    {
                        "repo_id": "app",
                        "repo_path": str(repo),
                        "git_base_branch": "main",
                        "role": "app",
                        "affected": True,
                    }
                ],
                "change_evidence": {
                    "app": {"changed_files": ["src/app.py"]},
                },
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    exit_code = main([
        "evidence",
        "assemble",
        "--story-id",
        "AG3-061",
        "--story-dir",
        str(story_dir),
        "--output-dir",
        str(output_dir),
        "--config",
        str(config_path),
    ])

    assert exit_code == 0
    manifest_path = output_dir / "bundle_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_hash"]
    captured = capsys.readouterr()
    assert "merge_paths" in captured.out
    assert "src/app.py" in captured.out


def test_evidence_assemble_command_fails_closed_without_required_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI returns non-zero when mandatory evidence input is absent."""
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    (story_dir / "story.md").write_text("# Story\n", encoding="utf-8")

    exit_code = main([
        "evidence",
        "assemble",
        "--story-id",
        "AG3-061",
        "--story-dir",
        str(story_dir),
        "--output-dir",
        str(tmp_path / "out"),
    ])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Evidence assembly failed" in captured.err
