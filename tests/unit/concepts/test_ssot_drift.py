"""SSOT drift: both real entry points share discovery/identity (R02/R19).

FK-13 side is formed via build_concept_chunks() (productive builder), not by
re-deriving chunks from shared kernel helpers alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.support.vectordb.project_fixtures import write_fk13_concept, write_project_config

from agentkit.backend.concept_catalog.corpus.chunking import chunk_markdown
from agentkit.backend.concept_catalog.corpus.discovery import discover_concept_files
from agentkit.backend.concept_catalog.corpus.domain_errors import ConceptParseError
from agentkit.backend.concept_catalog.corpus.identity import deterministic_chunk_uuid
from agentkit.backend.concept_catalog.corpus.profiles import IngestProfileId, get_profile
from agentkit.backend.vectordb.ingest.builders import build_concept_chunks
from agentkit.backend.vectordb.project_binding import bind_project

if TYPE_CHECKING:
    from pathlib import Path


def test_discover_concept_files_is_ssot_owner() -> None:
    from agentkit.backend.concept_catalog.corpus import parser as parser_mod

    assert hasattr(parser_mod, "discover_concept_files")
    assert parser_mod.discover_concept_files is discover_concept_files


def test_both_entry_points_exact_file_chunk_identity_equality(tmp_path: Path) -> None:
    """R02/R19: productive FK-13 builder vs tools.concept_ingester on same corpus."""
    root = tmp_path / "proj"
    root.mkdir()
    write_project_config(root, project_key="P1")
    concepts = root / "concepts"
    (concepts / "domain-design").mkdir(parents=True)
    write_fk13_concept(
        concepts / "domain-design",
        concept_id="FK-AA",
        filename="fk_aa.md",
        authority=["scope-a"],
    )
    write_fk13_concept(
        concepts / "domain-design",
        concept_id="FK-BB",
        filename="fk_bb.md",
        authority=["scope-b"],
    )
    (concepts / ".conceptignore").write_text("skip.md\n", encoding="utf-8")
    (concepts / "skip.md").write_text("# skip\n", encoding="utf-8")

    binding = bind_project(root)
    # Productive FK-13 entry: build_concept_chunks (not bare kernel re-chunk).
    fk13_records = build_concept_chunks(binding)
    fk13_paths = {r.source_file for r in fk13_records}
    assert not any("skip.md" in p for p in fk13_paths)
    assert fk13_records

    # Every FK-13 UUID must equal the SSOT identity function with builder inputs.
    docs = discover_concept_files(concepts, strict=True).documents
    profile = get_profile(IngestProfileId.FK13_CONCEPT)
    rebuilt: set[str] = set()
    for doc in docs:
        chunks, _ = chunk_markdown(
            doc.body, profile=profile, title=doc.frontmatter.title
        )
        rel = binding.relative_posix(doc.path)
        for tc in chunks:
            rebuilt.add(
                deterministic_chunk_uuid(
                    project_id=binding.project_id,
                    source_file=rel,
                    section_heading=tc.section_heading,
                    content_hash=tc.content_hash,
                    ordering=tc.ordering,
                )
            )
    assert {r.chunk_uuid for r in fk13_records} == rebuilt

    from tools.concept_ingester.discovery import discover as tool_discover

    tool = tool_discover(concepts, max_chars=12000)
    ssot_inv = discover_concept_files(
        concepts, strict=True, frontmatter_mode="inventory"
    )
    ssot_paths = {d.rel_path for d in ssot_inv.documents}
    tool_paths = {c.rel_path for c in tool.chunks}
    # Exact path equality between tool consumer and inventory discovery.
    assert tool_paths == ssot_paths
    assert "skip.md" not in ssot_paths

    # Tool identities use the same SSOT function (inventory project_id="").
    tool_ids = {c.chunk_id for c in tool.chunks}
    expected_tool_ids: set[str] = set()
    for c in tool.chunks:
        expected_tool_ids.add(
            deterministic_chunk_uuid(
                project_id="",
                source_file=c.rel_path,
                section_heading=c.heading,
                content_hash=c.content_hash,
                ordering=c.ordering,
            )
        )
    assert tool_ids == expected_tool_ids


def test_inventory_mode_hard_rejects_duplicate_yaml_key(tmp_path: Path) -> None:
    """R02: inventory profile never repairs parse errors into fake frontmatter."""
    root = tmp_path / "concepts" / "domain-design"
    root.mkdir(parents=True)
    bad = root / "bad.md"
    bad.write_text(
        """---
concept_id: GOOD
concept_id: DUP
title: Bad
status: active
doc_kind: core
---

# Bad
""",
        encoding="utf-8",
    )
    with pytest.raises(ConceptParseError, match="duplicate|YAML|E-SCHEMA"):
        discover_concept_files(
            root.parent, strict=True, frontmatter_mode="inventory"
        )
    from tools.concept_ingester.discovery import discover as tool_discover

    with pytest.raises(ConceptParseError):
        tool_discover(root.parent, max_chars=12000)


def test_shared_negative_matrix_both_entry_points(tmp_path: Path) -> None:
    """R02: shared negative matrix at both entry points."""
    cases = {
        "missing_fm": "# no frontmatter\n",
        "bad_utf8": None,
        "dup_key": (
            "---\nconcept_id: A\nconcept_id: B\ntitle: T\nstatus: active\n"
            "doc_kind: core\n---\n\n# T\n"
        ),
    }
    from tools.concept_ingester.discovery import discover as tool_discover

    for name, body in cases.items():
        root = tmp_path / name / "domain-design"
        root.mkdir(parents=True)
        path = root / "bad.md"
        if name == "bad_utf8":
            path.write_bytes(
                b"---\nconcept_id: X\ntitle: T\nstatus: active\n"
                b"doc_kind: core\n---\n\n# \xff\xfe\n"
            )
        else:
            assert body is not None
            path.write_text(body, encoding="utf-8")
        with pytest.raises(ConceptParseError):
            discover_concept_files(
                root.parent, strict=True, frontmatter_mode="inventory"
            )
        with pytest.raises(ConceptParseError):
            tool_discover(root.parent, max_chars=12000)
