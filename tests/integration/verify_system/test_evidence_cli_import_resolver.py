"""Integration tests for productive evidence CLI assembly wiring."""

from __future__ import annotations

import json
from pathlib import Path

from agentkit.backend.cli.main import main
from agentkit.backend.verify_system.evidence import AuthorityClass, ConfidenceLabel


def test_evidence_assemble_cli_wires_import_resolver_into_stage2(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    repo_path = project_root / "app"
    story_dir = project_root / "stories" / "AG3-062"
    output_dir = tmp_path / "out"
    (repo_path / "src").mkdir(parents=True)
    (repo_path / "lib").mkdir()
    story_dir.mkdir(parents=True)
    (repo_path / "src" / "main.py").write_text(
        "from lib.imported import VALUE\n",
        encoding="utf-8",
    )
    (repo_path / "lib" / "imported.py").write_text("VALUE = 1\n", encoding="utf-8")
    (story_dir / "story.md").write_text("# AG3-062\n", encoding="utf-8")
    config_path = tmp_path / "evidence-config.json"
    config_path.write_text(
        json.dumps({
            "repositories": [
                {
                    "repo_id": "app",
                    "repo_path": str(repo_path),
                    "git_base_branch": "main",
                    "role": "app",
                    "affected": True,
                }
            ],
            "change_evidence": {
                "app": {"changed_files": ["src/main.py"]},
            },
        }),
        encoding="utf-8",
    )

    exit_code = main([
        "evidence",
        "assemble",
        "--story-id",
        "AG3-062",
        "--story-dir",
        str(story_dir),
        "--output-dir",
        str(output_dir),
        "--config",
        str(config_path),
    ])

    assert exit_code == 0
    manifest = json.loads((output_dir / "bundle_manifest.json").read_text(encoding="utf-8"))
    imported_entries = [
        entry
        for entry in manifest["entries"]
        if Path(entry["path"]).as_posix() == "lib/imported.py"
    ]
    assert len(imported_entries) == 1
    assert imported_entries[0]["authority"] == AuthorityClass.SECONDARY_CONTEXT.value
    assert imported_entries[0]["confidence"] == ConfidenceLabel.RESOLVED_IMPORT.value
