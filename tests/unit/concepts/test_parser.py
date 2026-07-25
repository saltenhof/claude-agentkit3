"""Parser SSOT discovery tests (FK-13 §13.9.13, AC5 discovery equality, AC9)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.concepts.parser import discover_concept_files

if TYPE_CHECKING:
    from pathlib import Path

_GOOD = """\
---
concept_id: FK-13
title: Retrieval
module: vectordb
status: active
doc_kind: core
authority_over:
  - scope: vectordb
defers_to:
  - target: FK-11
    scope: llm-evaluator
    reason: base
tags: [vektordb]
---

# 13 Retrieval

## 13.1 Purpose

Purpose text.

## 13.2 Stack

Stack text.
"""

_APPENDIX = """\
---
concept_id: FK-13-A
title: Retrieval Appendix
module: vectordb
status: active
doc_kind: appendix
parent_concept_id: FK-13
---

# Appendix

## Detail

Detail text.
"""


def _write_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "concept"
    (root / "technical-design").mkdir(parents=True)
    (root / "technical-design" / "13_retrieval.md").write_text(_GOOD, encoding="utf-8")
    (root / "technical-design" / "13a_appendix.md").write_text(_APPENDIX, encoding="utf-8")
    return root


def test_discovery_parses_documents_and_chunks(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    res = discover_concept_files(root)
    assert len(res.documents) == 2
    assert len(res.errors) == 0
    assert {d.concept_id for d in res.documents} == {"FK-13", "FK-13-A"}
    appendix = next(d for d in res.documents if d.concept_id == "FK-13-A")
    assert appendix.is_appendix is True
    assert appendix.parent_concept_id == "FK-13"


def test_discovery_propagates_authority_and_defers(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    res = discover_concept_files(root)
    core = next(c for c in res.chunks if c.concept_id == "FK-13" and c.section_number == "1")
    assert core.authority_over == ("vectordb",)
    assert core.defers_to == ("FK-11",)
    assert core.concept_status == "active"
    assert core.section_number == "1"
    assert core.layer == "technical"


def test_discovery_archive_path_marks_archived(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    arch = root / "archiv"
    arch.mkdir(parents=True)
    (arch / "old.md").write_text(_GOOD.replace("FK-13", "FK-OLD"), encoding="utf-8")
    res = discover_concept_files(root)
    archived = next(d for d in res.documents if d.concept_id == "FK-OLD")
    assert archived.is_archived is True
    assert archived.effective_status == "archived"
    assert all(c.concept_status == "archived" for c in res.chunks if c.concept_id == "FK-OLD")


def test_discovery_records_parse_error_fail_closed(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    (root / "technical-design" / "broken.md").write_text(
        "no frontmatter at all", encoding="utf-8"
    )
    res = discover_concept_files(root)
    assert res.has_errors
    err = next(e for e in res.errors if e.path.endswith("broken.md"))
    assert err.code == "E-SCHEMA-001"


def test_conceptignore_excludes_files(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    (root / "research").mkdir()
    (root / "research" / "notes.md").write_text(_GOOD, encoding="utf-8")
    (root / ".conceptignore").write_text("research/**\n", encoding="utf-8")
    res = discover_concept_files(root)
    assert all("research/" not in d.rel_path for d in res.documents)
    assert "research/notes.md" in res.ignored_files


def test_discovery_is_deterministic_same_revision(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    r1 = discover_concept_files(root)
    r2 = discover_concept_files(root)
    assert r1.corpus_revision == r2.corpus_revision
    assert [c.chunk_id for c in r1.chunks] == [c.chunk_id for c in r2.chunks]


def test_discovery_revision_changes_on_edit(tmp_path: Path) -> None:
    root = _write_corpus(tmp_path)
    r1 = discover_concept_files(root)
    target = root / "technical-design" / "13_retrieval.md"
    target.write_text(_GOOD.replace("Purpose text.", "Changed purpose."), encoding="utf-8")
    r2 = discover_concept_files(root)
    assert r1.corpus_revision != r2.corpus_revision


def test_discover_requires_existing_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_concept_files(tmp_path / "nope")
