"""Tests for the evidence assembler core."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentkit.backend.core_types.verify_evidence import VerifyEvidenceFile
from agentkit.backend.verify_system.evidence import (
    AuthorityClass,
    BundleEntry,
    EvidenceAssembler,
    RepoContext,
)
from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence


@dataclass(frozen=True)
class StaticChangeEvidencePort:
    """Small unit-test read port with real ``ChangeEvidence`` value objects."""

    evidence_by_repo: dict[str, ChangeEvidence]
    repo_paths: dict[str, Path]

    def collect(self, story_dir: Path) -> ChangeEvidence:
        for repo_id, repo_path in self.repo_paths.items():
            if repo_path.resolve() == story_dir.resolve():
                return self.evidence_by_repo.get(repo_id, ChangeEvidence(available=False))
        return ChangeEvidence(available=False)


def _repo(tmp_path: Path, repo_id: str = "app") -> RepoContext:
    repo_path = tmp_path / repo_id
    (repo_path / "src").mkdir(parents=True)
    (repo_path / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")
    return RepoContext(
        repo_id=repo_id,
        repo_path=repo_path,
        git_base_branch="main",
        role="app",
        affected=True,
    )


def _story(tmp_path: Path) -> Path:
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    (story_dir / "story.md").write_text("# Story\n", encoding="utf-8")
    return story_dir


def _assembler(
    repos: list[RepoContext],
    evidence_by_repo: dict[str, ChangeEvidence],
    *,
    import_entries: list[BundleEntry] | None = None,
    bundle_size_limit: int = 350 * 1024,
) -> EvidenceAssembler:
    collected = [
        VerifyEvidenceFile.from_content(
            repo_id=repo.repo_id,
            path=path.relative_to(repo.repo_path).as_posix(),
            content=path.read_text(encoding="utf-8"),
        )
        for repo in repos
        for path in repo.repo_path.rglob("*")
        if path.is_file()
    ]
    return EvidenceAssembler(
        {repo.repo_id: repo for repo in repos},
        collected_files=collected,
        change_evidence_port=StaticChangeEvidencePort(
            evidence_by_repo=evidence_by_repo,
            repo_paths={repo.repo_id: repo.repo_path for repo in repos},
        ),
        import_entries=import_entries or [],
        bundle_size_limit=bundle_size_limit,
    )


def test_assembler_builds_three_stage_bundle_with_deterministic_merge_paths(
    tmp_path: Path,
) -> None:
    """Stage 1, Stage 2 and Stage 3 entries are assembled deterministically."""
    repo = _repo(tmp_path)
    (repo.repo_path / "src" / "neighbor.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo.repo_path / "src" / "imported.py").write_text("IMPORTED = 1\n", encoding="utf-8")
    (repo.repo_path / "docs.md").write_text("worker context\n", encoding="utf-8")
    story_dir = _story(tmp_path)
    (story_dir / "handover.json").write_text(
        '{"file_paths": ["docs.md"]}',
        encoding="utf-8",
    )
    imported = BundleEntry(
        repo_id="app",
        path=Path("src/imported.py"),
        authority=AuthorityClass.SECONDARY_CONTEXT,
        confidence="HIGH",
        reason="Resolved import",
        size=len(b"IMPORTED = 1\n"),
        content="IMPORTED = 1\n",
    )
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
        import_entries=[imported],
    )

    first = assembler.assemble(
        story_dir=story_dir,
        evidence_epoch="2026-06-08T12:00:00+00:00",
    )
    second = assembler.assemble(
        story_dir=story_dir,
        evidence_epoch="2026-06-08T12:00:00+00:00",
    )

    authorities = {
        (entry.repo_id, entry.path.as_posix()): entry.authority
        for entry in first.manifest.entries
    }
    assert authorities[("app", "src/app.py")] == AuthorityClass.PRIMARY_IMPLEMENTATION
    assert authorities[("app", "src/imported.py")] == AuthorityClass.SECONDARY_CONTEXT
    assert authorities[("app", "docs.md")] == AuthorityClass.WORKER_ASSERTION
    assert first.merge_paths == second.merge_paths
    assert first.manifest.model_dump_json() == second.manifest.model_dump_json()


def test_worker_hint_is_additive_and_does_not_downgrade_duplicate(
    tmp_path: Path,
) -> None:
    """A worker hint for a Stage-1 file creates no duplicate or downgrade."""
    repo = _repo(tmp_path)
    story_dir = _story(tmp_path)
    (story_dir / "worker-manifest.json").write_text(
        '{"files": ["src/app.py"]}',
        encoding="utf-8",
    )
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
    )

    result = assembler.assemble(story_dir=story_dir)
    app_entries = [
        entry for entry in result.manifest.entries if entry.path.as_posix() == "src/app.py"
    ]

    assert len(app_entries) == 1
    assert app_entries[0].authority == AuthorityClass.PRIMARY_IMPLEMENTATION


def test_worker_hint_on_changed_file_records_self_reference_warning(
    tmp_path: Path,
) -> None:
    """Hints pointing at changed files are recorded as warnings."""
    repo = _repo(tmp_path)
    story_dir = _story(tmp_path)
    (story_dir / "handover.json").write_text(
        '{"merge_paths": ["src/app.py"]}',
        encoding="utf-8",
    )
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
    )

    result = assembler.assemble(story_dir=story_dir)

    assert any("Self-reference WARNING" in warning for warning in result.manifest.warnings)


def test_size_limit_excludes_low_authority_entries_with_warning(tmp_path: Path) -> None:
    """Oversized bundles are reduced by authority without content truncation."""
    repo = _repo(tmp_path)
    (repo.repo_path / "worker.md").write_text("w" * 200, encoding="utf-8")
    story_dir = _story(tmp_path)
    (story_dir / "handover.json").write_text(
        '{"file_paths": ["worker.md"]}',
        encoding="utf-8",
    )
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
        bundle_size_limit=80,
    )

    result = assembler.assemble(story_dir=story_dir)

    assert result.manifest.truncated is True
    assert "worker.md" not in result.merge_paths
    assert any("Bundle truncated WARNING" in warning for warning in result.manifest.warnings)


def test_multi_repo_entries_retain_repo_id(tmp_path: Path) -> None:
    """Entries from multiple repos stay repo-scoped in the manifest."""
    app = _repo(tmp_path, "app")
    docs = _repo(tmp_path, "docs")
    story_dir = _story(tmp_path)
    assembler = _assembler(
        [app, docs],
        {
            "app": ChangeEvidence(available=True, changed_files=("src/app.py",)),
            "docs": ChangeEvidence(available=True, changed_files=("src/app.py",)),
        },
    )

    result = assembler.assemble(story_dir=story_dir)

    assert ("app", "src/app.py") in {
        (entry.repo_id, entry.path.as_posix()) for entry in result.manifest.entries
    }
    assert ("docs", "src/app.py") in {
        (entry.repo_id, entry.path.as_posix()) for entry in result.manifest.entries
    }


def test_missing_change_evidence_is_named_and_review_continues(tmp_path: Path) -> None:
    """Unavailable collection stays visible while normative review continues."""
    repo = _repo(tmp_path)
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=False)},
    )

    result = assembler.assemble(story_dir=_story(tmp_path))
    assert any("EDGE_EVIDENCE_UNAVAILABLE" in item for item in result.manifest.warnings)


def test_nonexistent_import_entry_is_named_and_omitted(tmp_path: Path) -> None:
    """Stage-2 entries absent from the edge snapshot are never fabricated."""
    repo = _repo(tmp_path)
    missing_entry = BundleEntry(
        repo_id="app",
        path=Path("src/missing.py"),
        authority=AuthorityClass.SECONDARY_CONTEXT,
        confidence="HIGH",
        reason="Resolved import",
        size=1,
        content="x",
    )
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
        import_entries=[missing_entry],
    )

    result = assembler.assemble(story_dir=_story(tmp_path))
    assert any("missing import file" in item for item in result.manifest.warnings)
