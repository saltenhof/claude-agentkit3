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
