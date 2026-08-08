"""Tests for the ``agentkit evidence assemble`` CLI command (FK-28 §28.7.1).

Since AG3-241 the command is an adapter on ``POST
/v1/projects/{key}/verify-evidence-assemblies``, not a second implementation of
the assembly: it reads the edge-exported checkpoint, ships it, and writes what
the core returned. These tests therefore drive it with a fake ``client_factory``
-- the network boundary is the only thing that is not real. The checkpoint
parsing, the wire request, the manifest write and the fail-closed exit contract
all run for real.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.cli.evidence_commands import (
    _cmd_evidence_assemble,
    add_evidence_parsers,
)
from agentkit.backend.core_types.verify_evidence import VerifyEvidenceFile
from agentkit_wire.verify_system import (
    VerifyEvidenceAssemblyRequest,
    VerifyEvidenceAssemblyResponse,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

_MANIFEST_HASH = "a" * 64


class _FakeCore:
    """Network-boundary double for the ONE call the command makes."""

    def __init__(
        self,
        *,
        response: VerifyEvidenceAssemblyResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[tuple[str, VerifyEvidenceAssemblyRequest]] = []

    def assemble_verify_evidence(
        self, *, project_key: str, request: VerifyEvidenceAssemblyRequest
    ) -> VerifyEvidenceAssemblyResponse:
        self.calls.append((project_key, request))
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _parse(argv: list[str]) -> argparse.Namespace:
    """Parse through the REAL production parser (the CLI surface is not faked)."""
    import argparse as _argparse

    parser = _argparse.ArgumentParser()
    add_evidence_parsers(parser.add_subparsers(dest="command"))
    return parser.parse_args(argv)


def _checkpoint(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "repositories": [
                    {
                        "repo_id": "app",
                        "git_base_branch": "main",
                        "role": "app",
                        "affected": True,
                    }
                ],
                "change_evidence": {"app": {"changed_files": ["src/app.py"]}},
                "collected_files": [
                    VerifyEvidenceFile.from_content(
                        repo_id="app",
                        path="src/app.py",
                        content="print('app')\n",
                    ).model_dump(mode="json")
                ],
            }
        ),
        encoding="utf-8",
    )


def _argv(tmp_path: Path, *, config: Path | None) -> list[str]:
    argv = [
        "evidence",
        "assemble",
        "--story-id",
        "AG3-061",
        "--story-dir",
        str(tmp_path / "story"),
        "--output-dir",
        str(tmp_path / "out"),
        "--project-key",
        "ak3",
        "--project-root",
        str(tmp_path / "project"),
    ]
    if config is not None:
        argv += ["--config", str(config)]
    return argv


def _response() -> VerifyEvidenceAssemblyResponse:
    manifest = json.dumps({"manifest_hash": _MANIFEST_HASH, "entries": []}, indent=2)
    return VerifyEvidenceAssemblyResponse(
        manifest_hash=_MANIFEST_HASH,
        merge_paths=("src/app.py",),
        bundle_manifest_json=manifest + "\n",
    )


def test_evidence_assemble_ships_the_checkpoint_and_writes_the_cores_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The command ships the checkpoint and writes back exactly what the core sent."""
    config_path = tmp_path / "evidence.json"
    _checkpoint(config_path)
    core = _FakeCore(response=_response())

    exit_code = _cmd_evidence_assemble(
        _parse(_argv(tmp_path, config=config_path)),
        client_factory=lambda _root: core,  # type: ignore[arg-type,return-value]
    )

    assert exit_code == 0
    # What crossed the boundary is the edge-exported checkpoint, scoped to the
    # project -- never a physical worktree path.
    assert len(core.calls) == 1
    project_key, request = core.calls[0]
    assert project_key == "ak3"
    assert request.story_id == "AG3-061"
    assert [r.repo_id for r in request.repositories] == ["app"]
    assert request.repositories[0].changed_files == ("src/app.py",)
    assert [f.path for f in request.collected_files] == ["src/app.py"]
    # The manifest on disk is the core's document, byte for byte.
    manifest_path = tmp_path / "out" / "bundle_manifest.json"
    assert manifest_path.read_text(encoding="utf-8") == _response().bundle_manifest_json
    captured = capsys.readouterr()
    assert "merge_paths" in captured.out
    assert "src/app.py" in captured.out


def test_evidence_assemble_builds_its_client_from_the_project_root(
    tmp_path: Path,
) -> None:
    """The credential/base-URL anchor is the ``--project-root``, not a guess."""
    config_path = tmp_path / "evidence.json"
    _checkpoint(config_path)
    core = _FakeCore(response=_response())
    seen: list[Path] = []

    def _factory(project_root: Path) -> _FakeCore:
        seen.append(project_root)
        return core

    exit_code = _cmd_evidence_assemble(
        _parse(_argv(tmp_path, config=config_path)),
        client_factory=_factory,  # type: ignore[arg-type]
    )

    assert exit_code == 0
    assert seen == [tmp_path / "project"]


def test_evidence_assemble_fails_closed_without_required_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A missing checkpoint is a non-zero exit, and the core is never called."""
    core = _FakeCore(response=_response())

    exit_code = _cmd_evidence_assemble(
        _parse(_argv(tmp_path, config=None)),
        client_factory=lambda _root: core,  # type: ignore[arg-type,return-value]
    )

    assert exit_code == 1
    assert core.calls == []
    assert "Evidence assembly failed [AG3-061]" in capsys.readouterr().err
    assert not (tmp_path / "out" / "bundle_manifest.json").exists()


def test_evidence_assemble_rejects_a_physical_repo_path_in_the_checkpoint(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A developer-machine path has no meaning on the core host and is refused."""
    config_path = tmp_path / "evidence.json"
    config_path.write_text(
        json.dumps(
            {
                "repositories": [
                    {"repo_id": "app", "repo_path": str(tmp_path / "worktree")}
                ],
                "change_evidence": {"app": {"changed_files": []}},
                "collected_files": [],
            }
        ),
        encoding="utf-8",
    )
    core = _FakeCore(response=_response())

    exit_code = _cmd_evidence_assemble(
        _parse(_argv(tmp_path, config=config_path)),
        client_factory=lambda _root: core,  # type: ignore[arg-type,return-value]
    )

    assert exit_code == 1
    assert core.calls == []
    assert "repo_path" in capsys.readouterr().err


@pytest.mark.parametrize(
    "error",
    [
        OSError("connection refused"),
        RuntimeError("core answered 422 verify_evidence_assembly_rejected"),
        ValueError("response body is not an assembly response"),
    ],
    ids=["unreachable", "core-rejected", "unreadable-answer"],
)
def test_evidence_assemble_fails_closed_when_the_core_cannot_answer(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    """No manifest is invented when the core does not produce one."""
    config_path = tmp_path / "evidence.json"
    _checkpoint(config_path)

    exit_code = _cmd_evidence_assemble(
        _parse(_argv(tmp_path, config=config_path)),
        client_factory=lambda _root: _FakeCore(error=error),  # type: ignore[arg-type,return-value]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Evidence assembly failed [AG3-061]" in captured.err
    assert captured.out == ""
    assert not (tmp_path / "out" / "bundle_manifest.json").exists()
