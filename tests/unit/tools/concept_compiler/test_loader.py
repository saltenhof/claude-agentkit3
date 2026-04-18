"""Unit tests for formal spec loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from concept_compiler.loader import (
    FORMAL_SPEC_BEGIN,
    FORMAL_SPEC_END,
    FormalSpecError,
    discover_formal_spec_files,
    load_formal_spec,
)

FIXTURES = Path("tests/fixtures/concept_compiler")


def test_discover_formal_spec_files_returns_only_spec_docs() -> None:
    root = FIXTURES / "valid_minimal"
    spec = root / "commands.md"

    assert discover_formal_spec_files(root) == (spec,)


def test_discover_formal_spec_files_rejects_unbalanced_markers() -> None:
    with pytest.raises(FormalSpecError, match="unbalanced"):
        discover_formal_spec_files(FIXTURES / "broken_markers")


def test_load_formal_spec_parses_frontmatter_and_yaml() -> None:
    loaded = load_formal_spec(FIXTURES / "valid_minimal" / "commands.md")

    assert loaded.doc_id == "formal.example.commands"
    assert loaded.context == "example"
    assert loaded.spec_kind == "command-set"
    assert loaded.spec["commands"][0]["id"] == "example.command.run"


def test_load_formal_spec_rejects_id_mismatch() -> None:
    with pytest.raises(FormalSpecError, match="Frontmatter id and FORMAL-SPEC object differ"):
        load_formal_spec(FIXTURES / "id_mismatch" / "events.md")
