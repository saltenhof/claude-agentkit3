"""Tests for FK-37 section-aware packing."""

from __future__ import annotations

import re
import time

from agentkit.backend.verify_system.llm_evaluator.packing import (
    PackingKind,
    _split_markdown_sections,
    pack_code,
    pack_markdown,
    truncate_bundle,
)

# The exact behaviour the S5852-hardened ``_split_markdown_sections`` regex must
# preserve: the original (backtracking-prone) heading matcher. The non-vulnerable
# replacement must yield the IDENTICAL set of section boundaries.
_LEGACY_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+.+$")


def _legacy_split_markdown_sections(content: str) -> list[str]:
    """Reference implementation using the pre-S5852 backtracking regex."""
    matches = list(_LEGACY_HEADING_RE.finditer(content))
    if not matches:
        return [content]
    sections: list[str] = []
    if matches[0].start() > 0:
        sections.append(content[: matches[0].start()].strip())
    for pos, match in enumerate(matches):
        end = matches[pos + 1].start() if pos + 1 < len(matches) else len(content)
        section = content[match.start() : end].strip()
        if section:
            sections.append(section)
    return [section for section in sections if section]


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


def test_split_markdown_sections_matches_legacy_regex_behaviour() -> None:
    """S5852: the non-backtracking heading split is byte-identical to the old regex.

    Covers normal docs plus the cross-line / whitespace-only / no-trailing-text
    edge cases where ``\\s+.+$`` relied on a single backtrack step. The hardened
    matcher must produce the SAME section list for every one of them.
    """
    corpus = [
        "# Intro\nbody\n## Acceptance Criteria\nmore\n### Details\ntext",
        "preamble text\n## First\na\n## Second\nb",
        "no headings here at all\njust prose",
        "#No space after hash is not a heading",
        "####### too many hashes is not a heading",
        "# Title\n## Sub\n",
        "#\nnext line becomes the heading body via the old backtrack",
        "#   \nspaces then newline",
        "###",  # bare hashes, no whitespace -> no heading
        "### ",  # hashes + single space + EOS -> no match (old fails)
        "## heading with trailing spaces   \nbody",
        "text\n\n# H1\n\n## H2\n\ncontent",
    ]
    for content in corpus:
        assert _split_markdown_sections(content) == _legacy_split_markdown_sections(
            content
        ), f"section split diverged for {content!r}"


def test_split_markdown_sections_is_fast_on_pathological_input() -> None:
    """S5852: a pathological whitespace-heavy input must not blow up (<1s).

    The prior ``\\s+.+$`` adjacency is the polynomial-backtracking hotspot. Feed a
    large heading marker followed by a long whitespace-only run (the worst case
    that forces the engine to reconcile ``\\s+`` against ``.+`` at the line end),
    repeated across many lines, and assert it completes well under a second.
    """
    pathological = ("#" + " " * 4_000 + "\n") * 2_000
    start = time.perf_counter()
    sections = _split_markdown_sections(pathological)
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"section split too slow ({elapsed:.3f}s) -- ReDoS regression"
    # Whitespace-only lines are NOT headings (no ``.+`` text) -> the whole blob is
    # one section (matching the legacy regex semantics).
    assert sections == _legacy_split_markdown_sections(pathological)
