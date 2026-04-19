"""Unit tests for formal/prose drift auditing."""

from __future__ import annotations

from pathlib import Path

import pytest

from concept_compiler.compiler import compile_formal_specs
from concept_compiler.drift import FormalDriftError, audit_concept_doc_classification, audit_formal_prose_links

FIXTURES = Path("tests/fixtures/concept_compiler")


def test_audit_formal_prose_links_accepts_reciprocal_mapping() -> None:
    compiled = compile_formal_specs(FIXTURES / "drift_ok")

    links = audit_formal_prose_links(compiled, Path("."))

    assert len(links) == 1
    assert links[0].formal_doc_id == "formal.example.drift"


def test_audit_formal_prose_links_rejects_missing_backref() -> None:
    compiled = compile_formal_specs(FIXTURES / "drift_missing_backref")

    with pytest.raises(FormalDriftError, match="reciprocal formal_refs link"):
        audit_formal_prose_links(compiled, Path("."))


def test_audit_formal_prose_links_accepts_strict_prose_anchors() -> None:
    compiled = compile_formal_specs(FIXTURES / "drift_anchor_ok")

    links = audit_formal_prose_links(compiled, Path("."))

    assert len(links) == 1
    assert links[0].formal_doc_id == "formal.example.anchor"


def test_audit_formal_prose_links_rejects_missing_strict_prose_anchor() -> None:
    compiled = compile_formal_specs(FIXTURES / "drift_anchor_missing")

    with pytest.raises(FormalDriftError, match="missing strict PROSE-FORMAL anchors"):
        audit_formal_prose_links(compiled, Path("."))


def test_audit_concept_doc_classification_accepts_prose_only_concepts() -> None:
    audit_concept_doc_classification(FIXTURES / "concept_classification_ok")


def test_audit_concept_doc_classification_rejects_unclassified_concepts() -> None:
    with pytest.raises(FormalDriftError, match="must declare formal_refs or formal_scope=prose-only"):
        audit_concept_doc_classification(FIXTURES / "concept_classification_missing")
