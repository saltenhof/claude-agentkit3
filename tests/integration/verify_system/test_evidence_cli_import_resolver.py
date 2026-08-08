"""The evidence assembly wires ``ImportResolver`` into Stage 2 (FK-28 §28.7.1).

Since AG3-241 the assembly runs in the core behind
``POST /v1/projects/{key}/verify-evidence-assemblies``; the CLI is an adapter on
it. The property under test is unchanged and still load-bearing: an imported file
that no changed-file inventory mentions must reach the reviewer as
``SECONDARY_CONTEXT`` / ``RESOLVED_IMPORT``, which only happens if Stage 2 gets a
real ``ImportResolver.from_collected_files``.

The path exercised here is the whole one -- the real CLI parses the real
checkpoint, the real wire request crosses a fake that stands ONLY for the
network, and the real :func:`assemble_evidence_bundle` produces the manifest the
CLI writes. Nothing about the assembly is simulated.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentkit.backend.cli.evidence_commands import (
    _cmd_evidence_assemble,
    add_evidence_parsers,
)
from agentkit.backend.core_types.verify_evidence import VerifyEvidenceFile
from agentkit.backend.verify_system.evidence import AuthorityClass, ConfidenceLabel
from agentkit.backend.verify_system.evidence.assembly_service import (
    assemble_evidence_bundle,
)
from agentkit_wire.verify_system import (
    VerifyEvidenceAssemblyRequest,
    VerifyEvidenceAssemblyResponse,
)


class _CoreOverTheWire:
    """Stands for the network ONLY: it runs the real core service in-process.

    The core resolves the story working directory from canonical level-1 state;
    the test supplies that same anchor here, because a project registry read is
    the one thing an in-process double cannot borrow.
    """

    def __init__(self, *, story_dir: Path) -> None:
        self._story_dir = story_dir
        self.calls: list[str] = []

    def assemble_verify_evidence(
        self, *, project_key: str, request: VerifyEvidenceAssemblyRequest
    ) -> VerifyEvidenceAssemblyResponse:
        self.calls.append(project_key)
        return assemble_evidence_bundle(request, story_dir=self._story_dir)


def _parse(argv: list[str]) -> object:
    import argparse

    parser = argparse.ArgumentParser()
    add_evidence_parsers(parser.add_subparsers(dest="command"))
    return parser.parse_args(argv)


def test_evidence_assemble_wires_import_resolver_into_stage2(tmp_path: Path) -> None:
    """An import-only file arrives as SECONDARY_CONTEXT / RESOLVED_IMPORT."""
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
    core = _CoreOverTheWire(story_dir=story_dir)

    exit_code = _cmd_evidence_assemble(
        _parse([  # type: ignore[arg-type]
            "evidence",
            "assemble",
            "--story-id",
            "AG3-062",
            "--story-dir",
            str(story_dir),
            "--output-dir",
            str(output_dir),
            "--project-key",
            "ak3",
            "--project-root",
            str(project_root),
            "--config",
            str(config_path),
        ]),
        client_factory=lambda _root: core,  # type: ignore[arg-type,return-value]
    )

    assert exit_code == 0
    assert core.calls == ["ak3"]
    manifest = json.loads(
        (output_dir / "bundle_manifest.json").read_text(encoding="utf-8")
    )
    imported_entries = [
        entry
        for entry in manifest["entries"]
        if Path(entry["path"]).as_posix() == "lib/imported.py"
    ]
    assert len(imported_entries) == 1
    assert imported_entries[0]["authority"] == AuthorityClass.SECONDARY_CONTEXT.value
    assert imported_entries[0]["confidence"] == ConfidenceLabel.RESOLVED_IMPORT.value


def test_import_resolution_is_the_services_own_wiring(tmp_path: Path) -> None:
    """The core service wires the resolver itself -- no caller may skip it.

    Calling :func:`assemble_evidence_bundle` directly (the route's own call)
    yields the same import-derived entry, which is what makes the CLI a genuine
    adapter rather than the place the behaviour lives.
    """
    story_dir = tmp_path / "stories" / "AG3-062"
    story_dir.mkdir(parents=True)
    (story_dir / "story.md").write_text("# AG3-062\n", encoding="utf-8")
    changed = VerifyEvidenceFile.from_content(
        repo_id="app", path="src/main.py", content="from lib.imported import VALUE\n"
    )
    imported = VerifyEvidenceFile.from_content(
        repo_id="app", path="lib/imported.py", content="VALUE = 1\n"
    )
    request = VerifyEvidenceAssemblyRequest.model_validate({
        "story_id": "AG3-062",
        "repositories": [{"repo_id": "app", "changed_files": ["src/main.py"]}],
        "collected_files": [
            changed.model_dump(mode="json"),
            imported.model_dump(mode="json"),
        ],
    })

    response = assemble_evidence_bundle(request, story_dir=story_dir)

    manifest = json.loads(response.bundle_manifest_json)
    resolved = [
        entry
        for entry in manifest["entries"]
        if entry["confidence"] == ConfidenceLabel.RESOLVED_IMPORT.value
    ]
    assert [Path(entry["path"]).as_posix() for entry in resolved] == ["lib/imported.py"]
    assert response.manifest_hash == manifest["manifest_hash"]
