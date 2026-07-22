"""Discovery SSOT + .conceptignore glob semantics (AG3-174 AC 5/9)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.concept_catalog.corpus.conceptignore import load_conceptignore
from agentkit.backend.concept_catalog.corpus.discovery import discover_concept_files
from agentkit.backend.concept_catalog.corpus.domain_errors import ConceptParseError

if TYPE_CHECKING:
    from pathlib import Path


def _write_concept(path: Path, concept_id: str, *, status: str = "active") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
concept_id: {concept_id}
title: Title {concept_id}
module: m
status: {status}
doc_kind: core
authority_over: []
defers_to: []
---

# Title {concept_id}

## Section

Body of {concept_id}.
""",
        encoding="utf-8",
    )


def test_discover_concept_files_basic(tmp_path: Path) -> None:
    root = tmp_path / "concept"
    _write_concept(root / "a.md", "C-01")
    _write_concept(root / "b.md", "C-02")
    result = discover_concept_files(root)
    assert {d.concept_id for d in result.documents} == {"C-01", "C-02"}


def test_conceptignore_glob_boundary_cases(tmp_path: Path) -> None:
    root = tmp_path / "concept"
    root.mkdir(parents=True)
    (root / ".conceptignore").write_text(
        "\n".join(
            [
                "research/**",
                "research/**/*",
                "*.md",
                "drafts/*.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rules = load_conceptignore(root)
    # research/** matches everything under research/
    assert rules.matches("research/note.md")
    assert rules.matches("research/deep/note.md")
    # research/**/* matches only under subdirectories, not direct children
    # Our combined patterns: research/** already matches direct children.
    (root / ".conceptignore").write_text("research/**/*\n", encoding="utf-8")
    deep_only = load_conceptignore(root)
    assert not deep_only.matches("research/note.md")
    assert deep_only.matches("research/sub/note.md")

    (root / ".conceptignore").write_text("*.md\n", encoding="utf-8")
    star = load_conceptignore(root)
    assert star.matches("foo.md")
    assert not star.matches("sub/foo.md")

    (root / ".conceptignore").write_text("drafts/*.md\n", encoding="utf-8")
    drafts = load_conceptignore(root)
    assert drafts.matches("drafts/a.md")
    assert not drafts.matches("drafts/sub/a.md")


def test_excluded_files_not_in_discovery(tmp_path: Path) -> None:
    root = tmp_path / "concept"
    _write_concept(root / "keep.md", "K-01")
    _write_concept(root / "research" / "skip.md", "S-01")
    (root / ".conceptignore").write_text("research/**\n", encoding="utf-8")
    result = discover_concept_files(root)
    assert [d.concept_id for d in result.documents] == ["K-01"]
    assert "research/skip.md" in result.excluded


def test_invalid_frontmatter_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "concept"
    root.mkdir()
    (root / "bad.md").write_text("no frontmatter\n", encoding="utf-8")
    with pytest.raises(ConceptParseError):
        discover_concept_files(root, strict=True)
