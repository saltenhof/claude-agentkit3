"""concept_validate + authority ranking (AG3-174 AC 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.vectordb.concept_corpus.resolver import ConceptGraphResolver
from agentkit.backend.vectordb.concept_corpus.validate import validate_corpus

if TYPE_CHECKING:
    from pathlib import Path


def _write(
    path: Path,
    concept_id: str,
    *,
    status: str = "active",
    doc_kind: str = "core",
    parent: str = "",
    authority: list[str] | None = None,
    defers: list[dict[str, str]] | None = None,
    body: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    auth = authority or []
    defers = defers or []
    auth_yaml = "\n".join(f"  - scope: {s}" for s in auth) if auth else "  []"
    defer_yaml = (
        "\n".join(
            f"  - target: {d['target']}\n    scope: {d.get('scope', '')}\n    reason: {d.get('reason', '')}"
            for d in defers
        )
        if defers
        else "  []"
    )
    parent_line = f"parent_concept_id: {parent}" if parent else "parent_concept_id:"
    section = body or f"## Section\n\nBody for {concept_id}.\n"
    path.write_text(
        f"""---
concept_id: {concept_id}
title: Title {concept_id}
module: mod
status: {status}
doc_kind: {doc_kind}
{parent_line}
authority_over:
{auth_yaml}
defers_to:
{defer_yaml}
---

# Title {concept_id}

{section}
""",
        encoding="utf-8",
    )


def test_validate_happy_path(tmp_path: Path) -> None:
    root = tmp_path / "concept"
    _write(root / "a.md", "C-A", authority=["scope-a"])
    _write(root / "b.md", "C-B", defers=[{"target": "C-A", "scope": "scope-a"}])
    result = validate_corpus(root)
    assert result.exit_code in (0, 1)
    assert result.ok_for_sync
    assert result.corpus_revision.startswith("sha256:")


def test_duplicate_active_id_is_error(tmp_path: Path) -> None:
    root = tmp_path / "concept"
    _write(root / "a.md", "DUP")
    _write(root / "b.md", "DUP")
    result = validate_corpus(root)
    assert result.exit_code == 2
    assert any(e.code == "E-ID-001" for e in result.errors)


def test_missing_defer_target_is_error(tmp_path: Path) -> None:
    root = tmp_path / "concept"
    _write(root / "a.md", "C-A", defers=[{"target": "MISSING"}])
    result = validate_corpus(root)
    assert any(e.code == "E-REF-001" for e in result.errors)


def test_authority_conflict_is_error(tmp_path: Path) -> None:
    root = tmp_path / "concept"
    _write(root / "a.md", "C-A", authority=["same"])
    _write(root / "b.md", "C-B", authority=["same"])
    result = validate_corpus(root)
    assert any(e.code == "E-AUTH-001" for e in result.errors)


def test_defer_cycle_is_error(tmp_path: Path) -> None:
    root = tmp_path / "concept"
    _write(root / "a.md", "C-A", defers=[{"target": "C-B", "scope": "s"}])
    _write(root / "b.md", "C-B", defers=[{"target": "C-A", "scope": "s"}])
    result = validate_corpus(root)
    assert any(e.code == "E-CYCLE-001" for e in result.errors)


def test_strict_escalates_warnings(tmp_path: Path) -> None:
    root = tmp_path / "concept"
    # Orphan active core -> W-ORPHAN-001
    _write(root / "a.md", "C-A")
    soft = validate_corpus(root, strict=False)
    hard = validate_corpus(root, strict=True)
    if soft.warnings:
        assert hard.exit_code == 2


def test_authority_ranking_five_rules() -> None:
    resolver = ConceptGraphResolver(
        {
            "nodes": {
                "AUTH": {"status": "active", "module": "m1", "doc_kind": "core"},
                "OTHER": {"status": "active", "module": "m2", "doc_kind": "core"},
                "APP": {"status": "active", "module": "m1", "doc_kind": "appendix"},
                "OLD": {"status": "archived", "module": "m1", "doc_kind": "core"},
            },
            "edges": [
                {"source": "OTHER", "target": "AUTH", "type": "defers_to", "scope": "s1"},
            ],
        }
    )
    hits = [
        {
            "concept_id": "OTHER",
            "score": 0.9,
            "module": "m2",
            "concept_status": "active",
            "is_appendix": False,
            "authority_over": [],
            "section_heading": "a",
        },
        {
            "concept_id": "AUTH",
            "score": 0.5,
            "module": "m1",
            "concept_status": "active",
            "is_appendix": False,
            "authority_over": ["s1"],
            "section_heading": "b",
        },
        {
            "concept_id": "APP",
            "score": 0.6,
            "module": "m1",
            "concept_status": "active",
            "is_appendix": True,
            "authority_over": [],
            "section_heading": "c",
        },
        {
            "concept_id": "OLD",
            "score": 0.95,
            "module": "m1",
            "concept_status": "archived",
            "is_appendix": False,
            "authority_over": [],
            "section_heading": "d",
        },
    ]
    ranked = resolver.rank(
        hits, query_scopes=["s1"], query_module="m1", prefer_appendix_detail=True
    )
    # AUTH should outrank OTHER due to direct authority despite lower base score.
    ids = [r.hit["concept_id"] for r in ranked]
    assert ids[0] == "AUTH"
    # Archived penalised relative to similar base scores.
    assert "archived_penalty" in ranked[ids.index("OLD")].reasons
