"""Deterministic source-unit partition (FK-78 section 78.7).

A Markdown source is partitioned into non-overlapping blocks: the preamble
before the first heading forms its own unit when non-empty; every ATX or
Setext heading of any level starts a new unit reaching up to the line
before the next heading; headings inside code fences do not count; equal
heading titles are disambiguated with a running anchor number (matching
the toolchain-wide slug numbering of :func:`docmodel.anchor_slugs`).
Non-Markdown sources are partitioned into paragraph blocks separated by
blank lines. The partition is complete and overlap-free; the checker
re-derives it, so thinning the unit register is impossible.

Unit digests are SHA-256 over the LF-normalized unit text.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .docmodel import github_slug, heading_outline

_MARKDOWN_SUFFIXES = (".md", ".markdown")


@dataclass(frozen=True)
class SourceUnit:
    """One derived coverage unit of a source document.

    Attributes:
        locator: ``<path>#<anchor>`` for heading units or
            ``<path>#L<a>-L<b>`` for preamble/paragraph units.
        start_line: 1-based first line of the unit.
        end_line: 1-based last line of the unit (inclusive).
        text: LF-normalized unit text without a trailing newline.
        digest: SHA-256 lowercase-hex digest of ``text``.
    """

    locator: str
    start_line: int
    end_line: int
    text: str
    digest: str


@dataclass(frozen=True)
class AnchoredHeading:
    """One heading with its resolved (de-duplicated) anchor slug."""

    line: int
    level: int
    anchor: str


def lf_normalize(text: str) -> str:
    """Normalize CRLF/CR line endings to LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def text_digest(text: str) -> str:
    """Return the SHA-256 lowercase-hex digest of the LF-normalized text."""
    return hashlib.sha256(lf_normalize(text).encode("utf-8")).hexdigest()


def is_markdown_path(rel_path: str) -> bool:
    """Return whether a source path is partitioned as Markdown."""
    return rel_path.lower().endswith(_MARKDOWN_SUFFIXES)


def anchored_outline(text: str) -> tuple[AnchoredHeading, ...]:
    """Return the heading outline with document-order de-duplicated anchors."""
    seen: dict[str, int] = {}
    anchored: list[AnchoredHeading] = []
    for heading in heading_outline(text):
        slug = github_slug(heading.title)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchor = slug if count == 0 else f"{slug}-{count}"
        anchored.append(AnchoredHeading(line=heading.line, level=heading.level, anchor=anchor))
    return tuple(anchored)


def derive_units(rel_path: str, text: str) -> tuple[SourceUnit, ...]:
    """Derive the deterministic unit partition of one source document.

    Args:
        rel_path: Project-relative ``/``-path of the source (locator prefix).
        text: Raw source text (any line-ending convention).

    Returns:
        The complete, overlap-free unit partition in document order.
    """
    lines = lf_normalize(text).split("\n")
    if not any(line.strip() for line in lines):
        return ()
    if is_markdown_path(rel_path):
        return _markdown_units(rel_path, lines, text)
    return _paragraph_units(rel_path, lines)


def section_index(rel_path: str, text: str) -> dict[str, SourceUnit]:
    """Map heading anchors to their section units for a Markdown document."""
    index: dict[str, SourceUnit] = {}
    for unit in derive_units(rel_path, text):
        anchor = unit.locator.split("#", 1)[1]
        if not anchor.startswith("L"):
            index[anchor] = unit
    return index


def _unit(rel_path: str, lines: list[str], start: int, end: int, anchor: str | None) -> SourceUnit:
    text = "\n".join(lines[start - 1 : end])
    fragment = anchor if anchor is not None else f"L{start}-L{end}"
    return SourceUnit(
        locator=f"{rel_path}#{fragment}",
        start_line=start,
        end_line=end,
        text=text,
        digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _markdown_units(rel_path: str, lines: list[str], text: str) -> tuple[SourceUnit, ...]:
    outline = anchored_outline(lf_normalize(text))
    units: list[SourceUnit] = []
    first_heading_line = outline[0].line if outline else len(lines) + 1
    if any(line.strip() for line in lines[: first_heading_line - 1]):
        units.append(_unit(rel_path, lines, 1, first_heading_line - 1, None))
    for index, heading in enumerate(outline):
        end = outline[index + 1].line - 1 if index + 1 < len(outline) else len(lines)
        units.append(_unit(rel_path, lines, heading.line, end, heading.anchor))
    return tuple(units)


def _paragraph_units(rel_path: str, lines: list[str]) -> tuple[SourceUnit, ...]:
    units: list[SourceUnit] = []
    start: int | None = None
    for number, line in enumerate(lines, start=1):
        if line.strip():
            if start is None:
                start = number
            continue
        if start is not None:
            units.append(_unit(rel_path, lines, start, number - 1, None))
            start = None
    if start is not None:
        units.append(_unit(rel_path, lines, start, len(lines), None))
    return tuple(units)
