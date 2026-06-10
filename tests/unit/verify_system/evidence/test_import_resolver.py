"""Tests for FK-46 import resolution and Stage-2 evidence integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.verify_system.evidence import (
    AuthorityClass,
    BundleEntry,
    ConfidenceLabel,
    EvidenceAssembler,
    ImportResolver,
    RepoContext,
)
from agentkit.verify_system.evidence.import_resolver import CONFIDENCE_PRIORITY
from agentkit.verify_system.structural.system_evidence import ChangeEvidence


class StaticChangeEvidencePort:
    """Small unit-test read port keyed by repo path."""

    def __init__(self, repo: RepoContext, changed_files: tuple[str, ...]) -> None:
        self._repo = repo
        self._changed_files = changed_files

    def collect(self, repo_path: Path) -> ChangeEvidence:
        if repo_path.resolve() == self._repo.repo_path.resolve():
            return ChangeEvidence(available=True, changed_files=self._changed_files)
        return ChangeEvidence(available=False)


def _repo(tmp_path: Path, repo_id: str = "app") -> RepoContext:
    repo_path = tmp_path / repo_id
    repo_path.mkdir()
    return RepoContext(repo_id=repo_id, repo_path=repo_path, affected=True)


def _story(tmp_path: Path) -> Path:
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    (story_dir / "story.md").write_text("# Story\n", encoding="utf-8")
    return story_dir


def test_confidence_labels_and_priority_are_exact() -> None:
    assert [label.value for label in ConfidenceLabel] == [
        "RESOLVED_IMPORT",
        "RESOLVED_ALIAS",
        "BARREL_CONTEXT",
        "SAME_PACKAGE_HEURISTIC",
        "SPRING_SCAN_HEURISTIC",
        "UNRESOLVED_DYNAMIC",
    ]
    assert CONFIDENCE_PRIORITY == {
        ConfidenceLabel.RESOLVED_IMPORT: 5,
        ConfidenceLabel.RESOLVED_ALIAS: 4,
        ConfidenceLabel.BARREL_CONTEXT: 3,
        ConfidenceLabel.SAME_PACKAGE_HEURISTIC: 2,
        ConfidenceLabel.SPRING_SCAN_HEURISTIC: 1,
        ConfidenceLabel.UNRESOLVED_DYNAMIC: 0,
    }


def test_python_import_resolves_module_and_ambiguous_cross_repo_is_dynamic(tmp_path: Path) -> None:
    app = _repo(tmp_path, "app")
    lib = _repo(tmp_path, "lib")
    (app.repo_path / "pkg").mkdir()
    (lib.repo_path / "pkg").mkdir()
    (app.repo_path / "pkg" / "util.py").write_text("VALUE = 1\n", encoding="utf-8")
    (lib.repo_path / "pkg" / "util.py").write_text("VALUE = 2\n", encoding="utf-8")
    source = app.repo_path / "main.py"
    source.write_text("import pkg.util\n", encoding="utf-8")

    results = ImportResolver.from_repo_contexts({"app": app, "lib": lib}).resolve(source)

    assert results == [
        results[0],
    ]
    assert results[0].confidence is ConfidenceLabel.UNRESOLVED_DYNAMIC
    assert results[0].target_file is None


def test_typescript_alias_and_barrel_resolution(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo.repo_path / "src" / "components").mkdir(parents=True)
    (repo.repo_path / "src" / "components" / "button.ts").write_text("export const Button = 1;\n", encoding="utf-8")
    (repo.repo_path / "src" / "components" / "index.ts").write_text(
        "export { Button } from './button';\n",
        encoding="utf-8",
    )
    (repo.repo_path / "tsconfig.json").write_text(
        '{"compilerOptions":{"baseUrl":".","paths":{"@app/*":["src/*"]}}}',
        encoding="utf-8",
    )
    source = repo.repo_path / "src" / "main.ts"
    source.write_text("import { Button } from '@app/components';\n", encoding="utf-8")

    results = ImportResolver.from_repo_contexts({"app": repo}).resolve(source)

    assert [(result.target_file.name if result.target_file else None, result.confidence) for result in results] == [
        ("button.ts", ConfidenceLabel.BARREL_CONTEXT)
    ]


@pytest.mark.parametrize(
    ("suffix", "statement"),
    [
        (".js", "const helper = require('./helper');\n"),
        (".jsx", "import Helper from './helper';\n"),
        (".tsx", "export * from './helper';\n"),
    ],
)
def test_js_jsx_tsx_resolve_static_import_forms(tmp_path: Path, suffix: str, statement: str) -> None:
    repo = _repo(tmp_path)
    (repo.repo_path / "helper.ts").write_text("export const helper = 1;\n", encoding="utf-8")
    source = repo.repo_path / f"main{suffix}"
    source.write_text(statement, encoding="utf-8")

    results = ImportResolver.from_repo_contexts({"app": repo}).resolve(source)

    assert len(results) == 1
    assert results[0].target_file == repo.repo_path / "helper.ts"
    assert results[0].confidence is ConfidenceLabel.RESOLVED_IMPORT


def test_typescript_dynamic_import_is_unresolved_dynamic(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    source = repo.repo_path / "main.ts"
    source.write_text("await import('./runtime');\n", encoding="utf-8")

    results = ImportResolver.from_repo_contexts({"app": repo}).resolve(source)

    assert len(results) == 1
    assert results[0].confidence is ConfidenceLabel.UNRESOLVED_DYNAMIC
    assert results[0].target_file is None


def test_java_import_same_package_and_spring_heuristic(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    src = repo.repo_path / "src" / "main" / "java" / "com" / "acme"
    src.mkdir(parents=True)
    (src / "Imported.java").write_text("package com.acme;\nclass Imported {}\n", encoding="utf-8")
    (src / "BaseService.java").write_text("package com.acme;\nclass BaseService {}\n", encoding="utf-8")
    (src / "Scanned.java").write_text("package com.acme;\nclass Scanned {}\n", encoding="utf-8")
    source = src / "App.java"
    source.write_text(
        "package com.acme;\nimport com.acme.Imported;\n@SpringBootApplication\nclass App extends BaseService {}\n",
        encoding="utf-8",
    )

    results = ImportResolver.from_repo_contexts({"app": repo}).resolve(source)
    labels_by_target = {
        result.target_file.name: result.confidence
        for result in results
        if result.target_file is not None
    }

    assert labels_by_target["Imported.java"] is ConfidenceLabel.RESOLVED_IMPORT
    assert labels_by_target["BaseService.java"] is ConfidenceLabel.SAME_PACKAGE_HEURISTIC
    assert ConfidenceLabel.SPRING_SCAN_HEURISTIC in labels_by_target.values()


def test_stage2_provider_feeds_secondary_context_bundle_entries(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo.repo_path / "src").mkdir()
    (repo.repo_path / "lib").mkdir()
    (repo.repo_path / "lib" / "imported.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo.repo_path / "src" / "main.py").write_text("from lib.imported import VALUE\n", encoding="utf-8")
    assembler = EvidenceAssembler(
        {"app": repo},
        change_evidence_port=StaticChangeEvidencePort(repo, ("src/main.py",)),
        import_evidence_provider=ImportResolver.from_repo_contexts({"app": repo}),
    )

    result = assembler.assemble(story_dir=_story(tmp_path))

    imported_entries: list[BundleEntry] = [
        entry for entry in result.manifest.entries if entry.path == Path("lib/imported.py")
    ]
    assert len(imported_entries) == 1
    assert imported_entries[0].authority is AuthorityClass.SECONDARY_CONTEXT
    assert imported_entries[0].confidence == ConfidenceLabel.RESOLVED_IMPORT.value
