"""Unit tests for formal/prose drift auditing."""

from __future__ import annotations

from pathlib import Path

import pytest

from concept_compiler.compiler import compile_formal_specs
from concept_compiler.drift import FormalDriftError, audit_formal_prose_links

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
