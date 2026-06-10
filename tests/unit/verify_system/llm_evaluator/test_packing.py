"""Tests for FK-37 section-aware packing."""

from __future__ import annotations

from agentkit.verify_system.llm_evaluator.packing import (
    PackingKind,
    pack_code,
    pack_markdown,
    truncate_bundle,
)


def test_pack_markdown_keeps_priority_sections() -> None:
    content = "\n\n".join(
        [
            "# Intro\n" + "a" * 500,
            "## Acceptance Criteria\n" + "b" * 500,
            "## Background\n" + "c" * 500,
        ]
    )

    result = pack_markdown(
        content,
        limit=900,
        priority_headings=("Acceptance",),
    )

    assert result.truncated is True
    assert "Acceptance Criteria" in result.content
    assert "omitted" in result.content


def test_pack_code_keeps_changed_symbol_block() -> None:
    content = "\n\n".join(
        [
            "def unchanged():\n    pass\n" + "x" * 500,
            "def changed():\n    return 1\n" + "y" * 500,
            "def neighbor():\n    pass\n" + "z" * 500,
        ]
    )

    result = pack_code(content, changed_symbols=("def changed",), limit=750)

    assert result.truncated is True
    assert "def changed" in result.content
    assert "omitted" in result.content


def test_truncate_bundle_dispatches_to_markdown() -> None:
    result = truncate_bundle(
        "# Important\n" + "x" * 1_000,
        limit=300,
        priority_headings=("Important",),
    )

    assert result.kind is PackingKind.MARKDOWN
    assert result.truncated is True


def test_truncate_bundle_without_priorities_is_still_section_aware() -> None:
    """AC9: no second begin/end truncation path -- always section-aware MARKDOWN."""
    content = "\n\n".join(
        [
            "## Section A\n" + "a" * 500,
            "## Section B\n" + "b" * 500,
            "## Section C\n" + "c" * 500,
        ]
    )

    result = truncate_bundle(content, limit=700)

    # The dispatcher delegates to section-aware packing even with no priorities;
    # there is no longer a FALLBACK begin/end byte excerpt.
    assert result.kind is PackingKind.MARKDOWN
    assert result.truncated is True
    # Whole sections are dropped as placeholders -- never a mid-content cut.
    assert "omitted" in result.content
    assert not hasattr(PackingKind, "FALLBACK")


def test_truncate_bundle_below_limit_passes_through() -> None:
    """A small field is returned verbatim (untruncated), not excerpted."""
    result = truncate_bundle("# Tiny\nshort body", limit=10_000)

    assert result.kind is PackingKind.MARKDOWN
    assert result.truncated is False
    assert result.content == "# Tiny\nshort body"


def test_pack_markdown_placeholder_overflow_caps_section_aware() -> None:
    """Degenerate overflow (many tiny sections) stays section-aware, no byte cut."""
    # Hundreds of tiny sections whose omission placeholders alone exceed a small
    # limit -- exercises the _section_aware_cap branch.
    content = "\n\n".join(f"## Heading number {i}\nbody{i}" for i in range(400))

    result = pack_markdown(content, limit=200)

    assert result.truncated is True
    assert len(result.content) <= 200
    # The cap keeps whole placeholder lines + a single marker; it never slices a
    # placeholder mid-line (every retained '[Section ... omitted' line is whole).
    for line in result.content.splitlines():
        if line.startswith("[Section"):
            assert line.endswith("]")
