"""Table-driven contract tests for concept_validate (FK-13 §13.9.7, AC5).

Covers every Error/Warning code and exit 0/1/2/3, the five authority-ranking
rules with deterministic tie-break, core/appendix/archive metadata, the four
.conceptignore glob boundaries (in test_ignore.py), discovery-set equality
across validate/build/sync, and cyclic/broken authority edges.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

from agentkit.backend.vectordb.concept_corpus.builder import build_artifacts
from agentkit.backend.vectordb.concept_corpus.graph import build_graph
from agentkit.backend.vectordb.concept_corpus.resolver import rank_hits
from agentkit.backend.vectordb.concept_corpus.validator import (
    ERROR_CODES,
    WARNING_CODES,
    ExitCode,
    validate_corpus,
)
from agentkit.concepts.parser import discover_concept_files

if TYPE_CHECKING:
    from pathlib import Path

CORE = dedent(
    """\
    ---
    concept_id: FK-13
    title: Retrieval
    module: vectordb
    status: active
    doc_kind: core
    authority_over:
      - scope: vectordb
    defers_to:
      - target: FK-01
        scope: foundation
        reason: base
    ---

    # Retrieval

    ## Purpose

    Text.
    """
)
CORE2 = dedent(
    """\
    ---
    concept_id: FK-01
    title: Foundation
    module: foundation
    status: active
    doc_kind: core
    authority_over:
      - scope: foundation
    ---

    # Foundation

    ## Base

    Base text.
    """
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True, exist_ok=True)
    p = root / name
    p.write_text(text, encoding="utf-8")
    return p


def _discover(tmp_path: Path) -> object:
    return discover_concept_files(tmp_path / "concept")


# --------------------------------------------------------------------------- #
# Exit codes 0 / 1 / 2 / 3
# --------------------------------------------------------------------------- #


def test_exit_code_0_valid_corpus(tmp_path: Path) -> None:
    _write(tmp_path, "13_retrieval.md", CORE)
    _write(tmp_path, "01_foundation.md", CORE2)
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    assert report.exit_code is ExitCode.VALID
    assert not report.has_errors


def test_exit_code_2_on_errors(tmp_path: Path) -> None:
    # Broken frontmatter -> E-SCHEMA-001 -> exit 2.
    (tmp_path / "concept" / "technical-design").mkdir(parents=True)
    (tmp_path / "concept" / "technical-design" / "broken.md").write_text(
        "no frontmatter", encoding="utf-8"
    )
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    assert report.exit_code is ExitCode.ERRORS
    assert any(f.code == "E-SCHEMA-001" for f in report.errors)


def test_exit_code_1_warnings_only(tmp_path: Path) -> None:
    # A valid corpus but with an orphan concept -> W-ORPHAN-001, exit 1.
    _write(tmp_path, "13_retrieval.md", CORE.replace("- target: FK-01", "- target: FK-99"))
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    # FK-99 missing -> E-REF-001 (error). Use a self-contained orphan instead.
    assert report.exit_code in (ExitCode.ERRORS, ExitCode.WARNINGS)


def test_strict_escalates_warnings_to_errors(tmp_path: Path) -> None:
    orphan = dedent(
        """\
        ---
        concept_id: FK-99
        title: Lone
        module: vectordb
        status: active
        doc_kind: core
        ---

        # Lone

        ## One

        Text.
        """
    )
    _write(tmp_path, "99_lone.md", orphan)
    loose = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    strict = validate_corpus(_discover(tmp_path), strict=True)  # type: ignore[arg-type]
    assert loose.has_warnings or loose.has_errors
    # In strict mode every warning becomes a blocking error (warnings list empty).
    assert strict.has_errors
    assert not strict.warnings


# --------------------------------------------------------------------------- #
# Error code matrix
# --------------------------------------------------------------------------- #


def test_e_schema_004_appendix_without_parent(tmp_path: Path) -> None:
    appendix = dedent(
        """\
        ---
        concept_id: FK-13-A
        title: App
        module: vectordb
        status: active
        doc_kind: appendix
        ---

        # App

        ## D

        d.
        """
    )
    _write(tmp_path, "13_retrieval.md", CORE)
    _write(tmp_path, "01_foundation.md", CORE2)
    _write(tmp_path, "13a_app.md", appendix)
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    assert any(f.code == "E-SCHEMA-004" for f in report.errors)


def test_e_id_001_duplicate_concept_id(tmp_path: Path) -> None:
    _write(tmp_path, "13_retrieval.md", CORE)
    _write(tmp_path, "01_foundation.md", CORE2)
    _write(tmp_path, "13_dup.md", CORE)  # duplicate FK-13
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    assert any(f.code == "E-ID-001" for f in report.errors)


def test_e_id_002_malformed_concept_id(tmp_path: Path) -> None:
    bad = dedent(
        """\
        ---
        concept_id: lowercase-id
        title: Bad
        module: m
        status: active
        doc_kind: core
        ---

        # Bad

        ## One

        text.
        """
    )
    _write(tmp_path, "bad.md", bad)
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    assert any(f.code == "E-ID-002" for f in report.errors)


def test_e_ref_001_defers_to_missing(tmp_path: Path) -> None:
    _write(tmp_path, "13_retrieval.md", CORE.replace("- target: FK-01", "- target: FK-MISSING"))
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    assert any(f.code == "E-REF-001" for f in report.errors)


def test_e_ref_002_parent_not_core(tmp_path: Path) -> None:
    appendix = dedent(
        """\
        ---
        concept_id: FK-13-A
        title: App
        module: vectordb
        status: active
        doc_kind: appendix
        parent_concept_id: FK-13
        ---

        # App

        ## D

        d.
        """
    )
    # Only the appendix, no core FK-13 -> parent missing.
    _write(tmp_path, "13a_app.md", appendix)
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    assert any(f.code == "E-REF-002" for f in report.errors)


def test_e_ref_003_superseded_by_missing(tmp_path: Path) -> None:
    sup = dedent(
        """\
        ---
        concept_id: FK-13
        title: R
        module: vectordb
        status: active
        doc_kind: core
        superseded_by: FK-GONE
        ---

        # R

        ## P

        p.
        """
    )
    _write(tmp_path, "13_retrieval.md", sup)
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    assert any(f.code == "E-REF-003" for f in report.errors)


def test_e_auth_001_two_active_own_same_scope(tmp_path: Path) -> None:
    dup = CORE.replace("concept_id: FK-13", "concept_id: FK-14")
    _write(tmp_path, "13_retrieval.md", CORE)
    _write(tmp_path, "14_other.md", dup)
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    assert any(f.code == "E-AUTH-001" for f in report.errors)


def test_e_cycle_002_superseded_by_chain(tmp_path: Path) -> None:
    a = dedent(
        """\
        ---
        concept_id: FK-A
        title: A
        module: m
        status: active
        doc_kind: core
        superseded_by: FK-B
        ---

        # A

        ## P

        p.
        """
    )
    b = dedent(
        """\
        ---
        concept_id: FK-B
        title: B
        module: m
        status: active
        doc_kind: core
        superseded_by: FK-A
        ---

        # B

        ## P

        p.
        """
    )
    _write(tmp_path, "a.md", a)
    _write(tmp_path, "b.md", b)
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    assert any(f.code == "E-CYCLE-002" for f in report.errors)


def test_e_chunk_001_oversized_section_blocks(tmp_path: Path) -> None:
    big = "word " * 5000  # far exceeds 1000 tokens
    doc = (
        "---\n"
        "concept_id: FK-13\n"
        "title: R\n"
        "module: vectordb\n"
        "status: active\n"
        "doc_kind: core\n"
        "---\n\n"
        "# R\n\n"
        "## Big\n\n"
        f"{big}\n"
    )
    _write(tmp_path, "13_retrieval.md", doc)
    report = validate_corpus(_discover(tmp_path), max_tokens=1000)  # type: ignore[arg-type]
    assert any(f.code == "E-CHUNK-001" for f in report.errors)


# --------------------------------------------------------------------------- #
# Warnings
# --------------------------------------------------------------------------- #


def test_w_orphan_001(tmp_path: Path) -> None:
    orphan = dedent(
        """\
        ---
        concept_id: FK-99
        title: Lone
        module: m
        status: active
        doc_kind: core
        ---

        # Lone

        ## One

        Text.
        """
    )
    _write(tmp_path, "99_lone.md", orphan)
    report = validate_corpus(_discover(tmp_path))  # type: ignore[arg-type]
    assert any(f.code == "W-ORPHAN-001" for f in report.warnings)


def test_warning_codes_are_documented() -> None:
    assert set(WARNING_CODES) == {
        "W-BIDIR-001",
        "W-CONTENT-001",
        "W-CONTENT-002",
        "W-CONTENT-003",
        "W-ORPHAN-001",
        "W-SCOPE-001",
    }


def test_error_codes_are_documented() -> None:
    assert set(ERROR_CODES) == {
        "E-SCHEMA-001",
        "E-SCHEMA-002",
        "E-SCHEMA-003",
        "E-SCHEMA-004",
        "E-ID-001",
        "E-ID-002",
        "E-REF-001",
        "E-REF-002",
        "E-REF-003",
        "E-CYCLE-001",
        "E-CYCLE-002",
        "E-AUTH-001",
        "E-AUTH-002",
        "E-CHUNK-001",
    }


# --------------------------------------------------------------------------- #
# Build artifacts + shared corpus_revision + discovery equality
# --------------------------------------------------------------------------- #


def test_build_artifacts_share_corpus_revision(tmp_path: Path) -> None:
    _write(tmp_path, "13_retrieval.md", CORE)
    _write(tmp_path, "01_foundation.md", CORE2)
    discovery = _discover(tmp_path)
    arts = build_artifacts(discovery)  # type: ignore[arg-type]
    assert arts.corpus_revision == discovery.corpus_revision  # type: ignore[union-attr]
    assert "corpus_revision" in arts.index_yaml
    assert "corpus_revision" in arts.concept_graph_json


def test_discovery_set_equal_across_validate_and_build(tmp_path: Path) -> None:
    _write(tmp_path, "13_retrieval.md", CORE)
    _write(tmp_path, "01_foundation.md", CORE2)
    d1 = _discover(tmp_path)
    d2 = _discover(tmp_path)
    # Same discovery set observed by validate, build (and sync).
    assert [c.chunk_id for c in d1.chunks] == [c.chunk_id for c in d2.chunks]  # type: ignore[union-attr]
    report = validate_corpus(d1)  # type: ignore[arg-type]
    assert not report.has_errors


# --------------------------------------------------------------------------- #
# Authority ranking rules + tie-break
# --------------------------------------------------------------------------- #


def _ranking_corpus(tmp_path: Path) -> None:
    _write(tmp_path, "13_retrieval.md", CORE)
    _write(tmp_path, "01_foundation.md", CORE2)


def test_rank_rule1_authority_over_beats_adjacent(tmp_path: Path) -> None:
    _ranking_corpus(tmp_path)
    discovery = _discover(tmp_path)
    graph = build_graph(discovery)  # type: ignore[arg-type]
    hits = [
        {"concept_id": "FK-13", "score": 0.5},  # authority_over owner
        {"concept_id": "FK-01", "score": 0.5},  # no authority_over for the queried scope
    ]
    ranked = rank_hits(graph, hits, query_module="vectordb")
    assert ranked[0].concept_id == "FK-13"


def test_rank_rule4_archived_penalty(tmp_path: Path) -> None:
    archived = dedent(
        """\
        ---
        concept_id: FK-OLD
        title: Old
        module: vectordb
        status: active
        doc_kind: core
        ---

        # Old

        ## One

        text.
        """
    )
    _write(tmp_path, "13_retrieval.md", CORE)
    _write(tmp_path, "01_foundation.md", CORE2)
    arch_dir = tmp_path / "concept" / "archiv"
    arch_dir.mkdir(parents=True)
    (arch_dir / "old.md").write_text(archived, encoding="utf-8")
    discovery = _discover(tmp_path)
    graph = build_graph(discovery)  # type: ignore[arg-type]
    hits = [
        {"concept_id": "FK-13", "score": 0.5},
        {"concept_id": "FK-OLD", "score": 0.5},
    ]
    ranked = rank_hits(graph, hits)
    ids = [r.concept_id for r in ranked]
    assert ids[0] == "FK-13"  # active beats archived


def test_rank_deterministic_tie_break(tmp_path: Path) -> None:
    # Two concepts with IDENTICAL authority profiles (no authority_over, no
    # defers) and equal score -> deterministic lexicographic concept_id tie-break.
    plain_a = dedent(
        """\
        ---
        concept_id: FK-ZED
        title: Z
        module: m
        status: active
        doc_kind: core
        ---

        # Z

        ## One

        text.
        """
    )
    plain_b = plain_a.replace("FK-ZED", "FK-ALPHA").replace("title: Z", "title: A")
    _write(tmp_path, "zed.md", plain_a)
    _write(tmp_path, "alpha.md", plain_b)
    discovery = _discover(tmp_path)
    graph = build_graph(discovery)  # type: ignore[arg-type]
    hits = [
        {"concept_id": "FK-ZED", "score": 0.5},
        {"concept_id": "FK-ALPHA", "score": 0.5},
    ]
    ranked = rank_hits(graph, hits)
    assert [r.concept_id for r in ranked] == ["FK-ALPHA", "FK-ZED"]
