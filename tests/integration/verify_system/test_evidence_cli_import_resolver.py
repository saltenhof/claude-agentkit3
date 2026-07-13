"""Integration tests for productive evidence CLI assembly wiring."""

from __future__ import annotations

import json
from pathlib import Path

from agentkit.backend.cli.main import main
from agentkit.backend.core_types.verify_evidence import VerifyEvidenceFile
from agentkit.backend.verify_system.evidence import AuthorityClass, ConfidenceLabel


def test_evidence_assemble_cli_wires_import_resolver_into_stage2(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    story_dir = project_root / "stories" / "AG3-062"
    output_dir = tmp_path / "out"
    story_dir.mkdir(parents=True)
    (story_dir / "story.md").write_text("# AG3-062\n", encoding="utf-8")
    config_path = tmp_path / "evidence-config.json"
    config_path.write_text(
        json.dumps({
            "repositories": [
                {
                    "repo_id": "app",
                    "git_base_branch": "main",
                    "role": "app",
                    "affected": True,
                }
            ],
            "change_evidence": {
                "app": {"changed_files": ["src/main.py"]},
            },
            "collected_files": [
                VerifyEvidenceFile.from_content(
                    repo_id="app",
                    path="src/main.py",
                    content="from lib.imported import VALUE\n",
                ).model_dump(mode="json"),
                VerifyEvidenceFile.from_content(
                    repo_id="app",
                    path="lib/imported.py",
                    content="VALUE = 1\n",
                ).model_dump(mode="json"),
            ],
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
