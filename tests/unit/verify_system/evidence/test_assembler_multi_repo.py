"""Tests covering assembler error branches and multi-repo worker-hint resolution.

Closes the two hostile-verifier test gaps from AG3-061:
1. Coverage gap in assembler.py error branches and hint-resolution paths.
2. AC4 worker-hint multi-repo behaviors (explicit repo_id:path form, ambiguous
   hint, not-found hint, additive/no-downgrade/no-duplicate/self-reference).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.core_types.verify_evidence import VerifyEvidenceFile
from agentkit.backend.verify_system.evidence import (
    AuthorityClass,
    BundleEntry,
    EvidenceAssembler,
    EvidenceAssemblyError,
    RepoContext,
)
from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from collections.abc import Mapping


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StaticChangeEvidencePort:
    """Small unit-test read port that matches by resolved repo_path."""

    evidence_by_repo: dict[str, ChangeEvidence]
    repo_paths: dict[str, Path]

    def collect(self, repo_path: Path) -> ChangeEvidence:
        for repo_id, rp in self.repo_paths.items():
            if rp.resolve() == repo_path.resolve():
                return self.evidence_by_repo.get(repo_id, ChangeEvidence(available=False))
        return ChangeEvidence(available=False)


def _make_repo(tmp_path: Path, repo_id: str = "app", affected: bool = True) -> RepoContext:
    """Create a minimal on-disk repository structure and return its context."""
    repo_path = tmp_path / repo_id
    (repo_path / "src").mkdir(parents=True)
    (repo_path / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")
    return RepoContext(
        repo_id=repo_id,
        repo_path=repo_path,
        git_base_branch="main",
        role="app",
        affected=affected,
    )


def _make_story(tmp_path: Path) -> Path:
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


# ---------------------------------------------------------------------------
# Constructor validation (lines 115-116, 118-119, 123-124)
# ---------------------------------------------------------------------------


def test_constructor_rejects_empty_repos() -> None:
    """At least one repo is required — empty mapping raises EvidenceAssemblyError."""
    with pytest.raises(EvidenceAssemblyError, match="at least one RepoContext"):
        EvidenceAssembler({})


def test_constructor_rejects_non_positive_bundle_size_limit(tmp_path: Path) -> None:
    """Non-positive bundle_size_limit raises EvidenceAssemblyError."""
    repo = _make_repo(tmp_path)
    with pytest.raises(EvidenceAssemblyError, match="bundle_size_limit must be positive"):
        EvidenceAssembler(
            {repo.repo_id: repo},
            bundle_size_limit=0,
        )


def test_constructor_rejects_repo_id_key_mismatch(tmp_path: Path) -> None:
    """Mapping key that differs from RepoContext.repo_id raises EvidenceAssemblyError."""
    repo = _make_repo(tmp_path, repo_id="app")
    with pytest.raises(EvidenceAssemblyError, match="does not match RepoContext.repo_id"):
        EvidenceAssembler({"wrong_key": repo})


# ---------------------------------------------------------------------------
# assemble() — story_dir validation (lines 152-153)
# ---------------------------------------------------------------------------


def test_assemble_rejects_nonexistent_story_dir(tmp_path: Path) -> None:
    """story_dir must be an existing directory."""
    repo = _make_repo(tmp_path)
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
    )
    with pytest.raises(EvidenceAssemblyError, match="story_dir does not exist"):
        assembler.assemble(story_dir=tmp_path / "no_such_dir")


# ---------------------------------------------------------------------------
# _affected_repos — no affected repos (lines 313-314)
# ---------------------------------------------------------------------------


def test_assemble_fails_closed_when_no_repo_is_affected(tmp_path: Path) -> None:
    """All repos with affected=False must raise EvidenceAssemblyError."""
    repo = _make_repo(tmp_path, affected=False)
    assembler = _assembler(
        [repo],
        {},
    )
    with pytest.raises(EvidenceAssemblyError, match="at least one affected repo"):
        assembler.assemble(story_dir=_make_story(tmp_path))


# ---------------------------------------------------------------------------
# _ensure_repo_path — repo_path not a directory (lines 319-320)
# ---------------------------------------------------------------------------


def test_assemble_never_reads_missing_repo_path(tmp_path: Path) -> None:
    """A physical repo path is irrelevant to backend snapshot assembly."""
    repo = RepoContext(
        repo_id="ghost",
        repo_path=tmp_path / "ghost_repo",
        git_base_branch="main",
        role="app",
        affected=True,
    )
    assembler = EvidenceAssembler(
        {"ghost": repo},
        change_evidence_port=StaticChangeEvidencePort(
            evidence_by_repo={"ghost": ChangeEvidence(available=True, changed_files=("f.py",))},
            repo_paths={"ghost": repo.repo_path},
        ),
    )
    result = assembler.assemble(story_dir=_make_story(tmp_path))
    assert any("missing changed file" in item for item in result.manifest.warnings)


# ---------------------------------------------------------------------------
# Stage-1 empty changed paths (lines 207-208)
# ---------------------------------------------------------------------------


def test_stage1_empty_changed_files_is_named(tmp_path: Path) -> None:
    """An empty inventory remains visible without blocking normative review."""
    repo = _make_repo(tmp_path)
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=())},
    )
    result = assembler.assemble(story_dir=_make_story(tmp_path))
    assert any("changed-file inventory empty" in item for item in result.manifest.warnings)


# ---------------------------------------------------------------------------
# _entry_from_file — file not found (lines 333-334)
# ---------------------------------------------------------------------------


def test_missing_changed_file_is_named(tmp_path: Path) -> None:
    """A changed path absent from the immutable snapshot is named and omitted."""
    repo = _make_repo(tmp_path)
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/missing_file.py",))},
    )
    result = assembler.assemble(story_dir=_make_story(tmp_path))
    assert any("missing changed file" in item for item in result.manifest.warnings)


# ---------------------------------------------------------------------------
# _validated_external_entry — size mismatch (lines 354-358)
# ---------------------------------------------------------------------------


def test_external_import_entry_fails_on_size_mismatch(tmp_path: Path) -> None:
    """Stage-2 entries whose declared size differs from actual byte size must raise."""
    repo = _make_repo(tmp_path)
    actual_content = "print('app')\n"
    wrong_size = len(actual_content.encode("utf-8")) + 99
    bad_import = BundleEntry(
        repo_id="app",
        path=Path("src/app.py"),
        authority=AuthorityClass.SECONDARY_CONTEXT,
        confidence="HIGH",
        reason="Import with wrong size",
        size=wrong_size,
        content=actual_content,
    )
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
        import_entries=[bad_import],
    )
    with pytest.raises(EvidenceAssemblyError, match="size mismatch"):
        assembler.assemble(story_dir=_make_story(tmp_path))


# ---------------------------------------------------------------------------
# _resolve_repo_relative_path — path traversal (lines 370-371)
# ---------------------------------------------------------------------------


def test_path_traversal_in_changed_files_raises(tmp_path: Path) -> None:
    """A changed file path containing '..' must raise EvidenceAssemblyError."""
    repo = _make_repo(tmp_path)
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/../../../etc/passwd",))},
    )
    with pytest.raises(EvidenceAssemblyError, match="traverses outside repo"):
        assembler.assemble(story_dir=_make_story(tmp_path))


# ---------------------------------------------------------------------------
# _normative_entries — missing story.md (lines 443-444)
# ---------------------------------------------------------------------------


def test_normative_entries_fail_closed_when_story_md_missing(tmp_path: Path) -> None:
    """If story.md is absent from story_dir, assembly must raise EvidenceAssemblyError."""
    repo = _make_repo(tmp_path)
    story_dir = tmp_path / "story_no_spec"
    story_dir.mkdir()
    # Intentionally no story.md
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
    )
    with pytest.raises(EvidenceAssemblyError, match="mandatory story spec is missing"):
        assembler.assemble(story_dir=story_dir)


# ---------------------------------------------------------------------------
# _normative_entries — optional status.yaml is included when present (line 457)
# ---------------------------------------------------------------------------


def test_normative_entries_includes_optional_status_yaml(tmp_path: Path) -> None:
    """status.yaml present in story_dir is included as PRIMARY_NORMATIVE."""
    repo = _make_repo(tmp_path)
    story_dir = _make_story(tmp_path)
    (story_dir / "status.yaml").write_text("status: done\n", encoding="utf-8")
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
    )

    result = assembler.assemble(story_dir=story_dir)

    paths = {(e.repo_id, e.path.as_posix()) for e in result.manifest.entries}
    assert ("_story", "status.yaml") in paths


# ---------------------------------------------------------------------------
# _worker_hint_paths — JSON decode error (lines 476-478)
# ---------------------------------------------------------------------------


def test_worker_hints_invalid_json_raises(tmp_path: Path) -> None:
    """Invalid JSON in a worker hint file must raise EvidenceAssemblyError."""
    repo = _make_repo(tmp_path)
    story_dir = _make_story(tmp_path)
    (story_dir / "handover.json").write_text("{not valid json", encoding="utf-8")
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
    )
    with pytest.raises(EvidenceAssemblyError, match="invalid worker hint JSON"):
        assembler.assemble(story_dir=story_dir)


# ---------------------------------------------------------------------------
# _resolve_hint_path — explicit repo_id:path multi-repo form (lines 484-488)
# ---------------------------------------------------------------------------


def test_resolve_hint_path_explicit_repo_id_form_happy_path(tmp_path: Path) -> None:
    """A hint in 'repo_id:path' form resolves to the correct repo without ambiguity."""
    app = _make_repo(tmp_path, "app")
    docs = _make_repo(tmp_path, "docs")
    (docs.repo_path / "src" / "context.py").write_text("CONTEXT = 1\n", encoding="utf-8")
    story_dir = _make_story(tmp_path)
    (story_dir / "handover.json").write_text(
        json.dumps({"file_paths": ["docs:src/context.py"]}),
        encoding="utf-8",
    )
    assembler = _assembler(
        [app, docs],
        {
            "app": ChangeEvidence(available=True, changed_files=("src/app.py",)),
            "docs": ChangeEvidence(available=True, changed_files=("src/app.py",)),
        },
    )

    result = assembler.assemble(story_dir=story_dir)

    paths = {(e.repo_id, e.path.as_posix()) for e in result.manifest.entries}
    assert ("docs", "src/context.py") in paths


def test_resolve_hint_path_explicit_form_unknown_repo_id_raises(tmp_path: Path) -> None:
    """A hint with an unknown repo_id must raise EvidenceAssemblyError."""
    repo = _make_repo(tmp_path)
    story_dir = _make_story(tmp_path)
    (story_dir / "handover.json").write_text(
        json.dumps({"file_paths": ["nonexistent_repo:src/app.py"]}),
        encoding="utf-8",
    )
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
    )
    with pytest.raises(EvidenceAssemblyError, match="unknown repo_id"):
        assembler.assemble(story_dir=story_dir)


# ---------------------------------------------------------------------------
# _resolve_hint_path — ambiguous bare path across multiple repos (lines 496-500)
# ---------------------------------------------------------------------------


def test_resolve_hint_path_ambiguous_across_repos_is_named(tmp_path: Path) -> None:
    """An ambiguous hint is visible and never heuristically selected."""
    app = _make_repo(tmp_path, "app")
    docs = _make_repo(tmp_path, "docs")
    # Both repos have 'src/app.py' (created by _make_repo)
    story_dir = _make_story(tmp_path)
    (story_dir / "handover.json").write_text(
        json.dumps({"file_paths": ["src/app.py"]}),
        encoding="utf-8",
    )
    assembler = _assembler(
        [app, docs],
        {
            "app": ChangeEvidence(available=True, changed_files=("src/app.py",)),
            "docs": ChangeEvidence(available=True, changed_files=("src/app.py",)),
        },
    )
    # src/app.py is in both repos — must fail closed as ambiguous
    result = assembler.assemble(story_dir=story_dir)
    assert any("worker hint unresolved" in item for item in result.manifest.warnings)


# ---------------------------------------------------------------------------
# _resolve_hint_path — not-found bare path (lines 496-500)
# ---------------------------------------------------------------------------


def test_resolve_hint_path_not_found_is_named(tmp_path: Path) -> None:
    """A missing hint is visible and never backend-read."""
    repo = _make_repo(tmp_path)
    story_dir = _make_story(tmp_path)
    (story_dir / "handover.json").write_text(
        json.dumps({"file_paths": ["src/ghost_file.py"]}),
        encoding="utf-8",
    )
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
    )
    result = assembler.assemble(story_dir=story_dir)
    assert any("worker hint unresolved" in item for item in result.manifest.warnings)


# ---------------------------------------------------------------------------
# AC4 behaviors via multi-repo explicit repo_id:path form
# ---------------------------------------------------------------------------


def test_ac4_worker_hint_explicit_form_is_additive(tmp_path: Path) -> None:
    """Explicit-form hint for a file not already in the bundle is added (additive)."""
    app = _make_repo(tmp_path, "app")
    docs = _make_repo(tmp_path, "docs")
    (docs.repo_path / "guide.md").write_text("# Guide\n", encoding="utf-8")
    story_dir = _make_story(tmp_path)
    (story_dir / "handover.json").write_text(
        json.dumps({"file_paths": ["docs:guide.md"]}),
        encoding="utf-8",
    )
    assembler = _assembler(
        [app, docs],
        {
            "app": ChangeEvidence(available=True, changed_files=("src/app.py",)),
            "docs": ChangeEvidence(available=True, changed_files=("src/app.py",)),
        },
    )

    result = assembler.assemble(story_dir=story_dir)

    paths = {(e.repo_id, e.path.as_posix()) for e in result.manifest.entries}
    assert ("docs", "guide.md") in paths


def test_ac4_worker_hint_explicit_form_does_not_downgrade_authority(tmp_path: Path) -> None:
    """Explicit-form hint for a Stage-1 file does not downgrade its authority."""
    app = _make_repo(tmp_path, "app")
    docs = _make_repo(tmp_path, "docs")
    story_dir = _make_story(tmp_path)
    # Hint points to docs:src/app.py which is also a Stage-1 changed file in docs
    (story_dir / "handover.json").write_text(
        json.dumps({"file_paths": ["docs:src/app.py"]}),
        encoding="utf-8",
    )
    assembler = _assembler(
        [app, docs],
        {
            "app": ChangeEvidence(available=True, changed_files=("src/app.py",)),
            "docs": ChangeEvidence(available=True, changed_files=("src/app.py",)),
        },
    )

    result = assembler.assemble(story_dir=story_dir)

    docs_app_entries = [
        e
        for e in result.manifest.entries
        if e.repo_id == "docs" and e.path.as_posix() == "src/app.py"
    ]
    assert len(docs_app_entries) == 1
    assert docs_app_entries[0].authority == AuthorityClass.PRIMARY_IMPLEMENTATION


def test_ac4_worker_hint_explicit_form_no_duplicate(tmp_path: Path) -> None:
    """The same explicit-form hint appearing twice produces exactly one entry."""
    app = _make_repo(tmp_path, "app")
    docs = _make_repo(tmp_path, "docs")
    (docs.repo_path / "guide.md").write_text("# Guide\n", encoding="utf-8")
    story_dir = _make_story(tmp_path)
    # Same path twice — no duplicate
    (story_dir / "handover.json").write_text(
        json.dumps({"file_paths": ["docs:guide.md", "docs:guide.md"]}),
        encoding="utf-8",
    )
    assembler = _assembler(
        [app, docs],
        {
            "app": ChangeEvidence(available=True, changed_files=("src/app.py",)),
            "docs": ChangeEvidence(available=True, changed_files=("src/app.py",)),
        },
    )

    result = assembler.assemble(story_dir=story_dir)

    guide_entries = [
        e
        for e in result.manifest.entries
        if e.repo_id == "docs" and e.path.as_posix() == "guide.md"
    ]
    assert len(guide_entries) == 1


def test_ac4_worker_hint_explicit_form_self_reference_warning(tmp_path: Path) -> None:
    """Explicit-form hint pointing to a changed file records a self-reference warning."""
    app = _make_repo(tmp_path, "app")
    docs = _make_repo(tmp_path, "docs")
    story_dir = _make_story(tmp_path)
    # Hint points to a changed file in docs using explicit form
    (story_dir / "handover.json").write_text(
        json.dumps({"file_paths": ["docs:src/app.py"]}),
        encoding="utf-8",
    )
    assembler = _assembler(
        [app, docs],
        {
            "app": ChangeEvidence(available=True, changed_files=("src/app.py",)),
            "docs": ChangeEvidence(available=True, changed_files=("src/app.py",)),
        },
    )

    result = assembler.assemble(story_dir=story_dir)

    assert any("Self-reference WARNING" in w for w in result.manifest.warnings)


# ---------------------------------------------------------------------------
# Stage-2 import_evidence_provider protocol (line 235)
# ---------------------------------------------------------------------------


def test_stage2_import_evidence_provider_is_called(tmp_path: Path) -> None:
    """An ImportEvidenceProvider.collect() is invoked and its entries are included."""
    app = _make_repo(tmp_path, "app")
    (app.repo_path / "src" / "extra.py").write_text("EXTRA = 1\n", encoding="utf-8")

    class _FakeProvider:
        called: bool = False

        def collect(
            self,
            repos: Mapping[str, RepoContext],
            changed_files_by_repo: Mapping[str, list[Path]],
        ) -> list[BundleEntry]:
            self._called = True
            extra_content = "EXTRA = 1\n"
            return [
                BundleEntry(
                    repo_id="app",
                    path=Path("src/extra.py"),
                    authority=AuthorityClass.SECONDARY_CONTEXT,
                    confidence="HIGH",
                    reason="Resolved import from provider",
                    size=len(extra_content.encode("utf-8")),
                    content=extra_content,
                )
            ]

    provider = _FakeProvider()
    assembler = EvidenceAssembler(
        {"app": app},
        collected_files=[
            VerifyEvidenceFile.from_content(
                repo_id="app",
                path=path.relative_to(app.repo_path).as_posix(),
                content=path.read_text(encoding="utf-8"),
            )
            for path in app.repo_path.rglob("*")
            if path.is_file()
        ],
        change_evidence_port=StaticChangeEvidencePort(
            evidence_by_repo={"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
            repo_paths={"app": app.repo_path},
        ),
        import_evidence_provider=provider,
    )
    story_dir = _make_story(tmp_path)

    result = assembler.assemble(story_dir=story_dir)

    paths = {(e.repo_id, e.path.as_posix()) for e in result.manifest.entries}
    assert ("app", "src/extra.py") in paths


# ---------------------------------------------------------------------------
# Stage-3 config-entry root-scan branch (assembler._config_entries line 417)
# ---------------------------------------------------------------------------


def test_config_entries_includes_root_level_config_files(tmp_path: Path) -> None:
    """config_entries scans the repo root for YAML/JSON files."""
    repo = _make_repo(tmp_path)
    (repo.repo_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n', encoding="utf-8"
    )
    story_dir = _make_story(tmp_path)
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=("src/app.py",))},
    )

    result = assembler.assemble(story_dir=story_dir)

    paths = {(e.repo_id, e.path.as_posix()) for e in result.manifest.entries}
    assert ("app", "pyproject.toml") in paths


# ---------------------------------------------------------------------------
# BundleEntry path validator — absolute path and traversal (authority.py lines 60-64)
# ---------------------------------------------------------------------------


def test_bundle_entry_rejects_absolute_path() -> None:
    """BundleEntry validator must reject absolute paths."""
    import platform

    # Use a platform-correct absolute path (C:/ on Windows, /absolute on POSIX)
    abs_path = (
        Path("C:/absolute/path.py") if platform.system() == "Windows" else Path("/absolute/path.py")
    )
    with pytest.raises(ValueError, match="must be relative"):
        BundleEntry(
            repo_id="app",
            path=abs_path,
            authority=AuthorityClass.SECONDARY_CONTEXT,
            confidence=None,
            reason="test",
            size=1,
            content="x",
        )


def test_bundle_entry_rejects_path_traversal() -> None:
    """BundleEntry validator must reject paths containing '..'."""
    with pytest.raises(ValueError, match="must not traverse"):
        BundleEntry(
            repo_id="app",
            path=Path("src/../../../etc/passwd"),
            authority=AuthorityClass.SECONDARY_CONTEXT,
            confidence=None,
            reason="test",
            size=1,
            content="x",
        )


# ---------------------------------------------------------------------------
# BundleManifest — timezone-naive epoch and duplicate entries (lines 20-21, 58-59)
# ---------------------------------------------------------------------------


def test_iso_epoch_rejects_timezone_naive_datetime() -> None:
    """A timezone-naive datetime passed as evidence_epoch must raise ValueError."""
    from datetime import datetime

    from agentkit.backend.verify_system.evidence import AuthorityClass, BundleEntry, BundleManifest

    entry = BundleEntry(
        repo_id="app",
        path=Path("src/a.py"),
        authority=AuthorityClass.PRIMARY_IMPLEMENTATION,
        confidence=None,
        reason="test",
        size=3,
        content="abc",
    )
    naive_dt = datetime(2026, 6, 8, 12, 0)  # no tzinfo
    with pytest.raises(ValueError, match="timezone-aware"):
        BundleManifest.from_entries(
            [entry],
            truncated=False,
            warnings=[],
            evidence_epoch=naive_dt,
        )


def test_bundle_manifest_rejects_duplicate_entries() -> None:
    """BundleManifest validator must reject duplicate repo/path entries."""
    from agentkit.backend.verify_system.evidence import AuthorityClass, BundleEntry, BundleManifest

    entry = BundleEntry(
        repo_id="app",
        path=Path("src/a.py"),
        authority=AuthorityClass.PRIMARY_IMPLEMENTATION,
        confidence=None,
        reason="test",
        size=3,
        content="abc",
    )
    with pytest.raises(ValueError, match="duplicate bundle entry"):
        BundleManifest(
            entries=(entry, entry),
            total_size=6,
            truncated=False,
            warnings=(),
            evidence_epoch="2026-06-08T12:00:00+00:00",
            manifest_hash="a" * 64,
        )


# ---------------------------------------------------------------------------
# Absolute path outside repo in _resolve_repo_relative_path (lines 364-368)
# ---------------------------------------------------------------------------


def test_changed_file_absolute_path_outside_repo_raises(tmp_path: Path) -> None:
    """An absolute changed-file path that lies outside the repo root must raise."""
    import platform

    repo = _make_repo(tmp_path)
    # Use a platform-appropriate absolute path that is guaranteed outside the repo
    outside_path = (
        str(Path("C:/Windows/System32/ntdll.dll"))
        if platform.system() == "Windows"
        else "/etc/passwd"
    )
    assembler = _assembler(
        [repo],
        {"app": ChangeEvidence(available=True, changed_files=(outside_path,))},
    )
    story_dir = _make_story(tmp_path)
    with pytest.raises(EvidenceAssemblyError, match="outside repo"):
        assembler.assemble(story_dir=story_dir)
