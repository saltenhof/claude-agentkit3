"""Heading-based chunking for the concept/story corpus (FK-13 §13.3.3 / §13.9.4).

Chunking is deterministic and transport-free. Documents are split at ``##`` and
``###`` headings; each chunk keeps its section heading. Oversized sections are
split BELOW the heading level (deterministic paragraph-based overflow), sized by
tokens of the bound embedding-model tokenizer (FK-13 §13.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from agentkit.concepts.tokenizer import chunk_token_count

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Default max tokens per chunk (FK-13 §13.3.3 "~1000 Tokens").
DEFAULT_MAX_TOKENS: Final[int] = 1000

@dataclass(frozen=True)
class Section:
    """One heading-delimited section of a document body.

    Attributes:
        heading: Section heading text (or a synthetic label for the intro).
        level: Heading level (2 or 3); 0 for the synthetic intro.
        section_number: Deterministic section number like ``"3"`` / ``"3.2"``.
        body: The section body text (heading line included).
    """

    heading: str
    level: int
    section_number: str
    body: str


@dataclass(frozen=True)
class _HeadingBoundary:
    start: int
    level: int
    heading: str


def split_into_sections(body: str) -> list[Section]:
    """Split a document body into heading-delimited sections.

    A leading intro (text before the first heading) becomes a synthetic
    ``(intro)`` section. Empty sections are dropped.
    """
    body = body.strip("\n")
    if not body:
        return []
    matches = _find_heading_boundaries(body)
    sections: list[Section] = []
    if not matches:
        stripped = body.strip()
        if stripped:
            sections.append(Section("(document)", 0, "0", stripped))
        return sections
    return _sections_from_matches(body, matches, sections)


def _sections_from_matches(
    body: str,
    matches: list[_HeadingBoundary],
    sections: list[Section],
) -> list[Section]:
    """Append intro and heading-delimited sections for known heading matches."""
    intro = body[: matches[0].start].strip()
    if intro:
        sections.append(Section("(intro)", 0, "0", intro))
    counters: list[int] = []  # per-level running counters; index 0 -> level 2
    for i, match in enumerate(matches):
        level = match.level
        heading = match.heading
        idx = level - 2
        # Reset deeper counters when a shallower heading appears.
        if idx < len(counters):
            counters[idx] += 1
            del counters[idx + 1:]
        else:
            # idx == len(counters): advance one level at a time.
            while len(counters) <= idx:
                counters.append(1)
        section_number = _join_number(counters)
        end = matches[i + 1].start if i + 1 < len(matches) else len(body)
        section_body = body[match.start:end].strip()
        if section_body:
            sections.append(Section(heading, level, section_number, section_body))
    return sections


def _find_heading_boundaries(body: str) -> list[_HeadingBoundary]:
    boundaries: list[_HeadingBoundary] = []
    offset = 0
    for raw_line in body.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        level = len(line) - len(line.lstrip("#"))
        if level in (2, 3) and len(line) > level and line[level].isspace():
            heading = line[level:].strip()
            if heading:
                boundaries.append(
                    _HeadingBoundary(start=offset, level=level, heading=heading)
                )
        offset += len(raw_line)
    return boundaries


def _join_number(counters: list[int]) -> str:
    return ".".join(str(n) for n in counters)


def overflow_split(text: str, max_tokens: int) -> list[str]:
    """Deterministically split ``text`` below the heading level when oversized.

    Splits on paragraph boundaries first (``\\n\\n``), then on line boundaries if
    a single paragraph still exceeds ``max_tokens``. Never returns an empty list
    for non-empty input; a single over-long line is emitted as-is with its token
    count recorded by the caller (so E-CHUNK-001 stays blockable, FK-13 §13.9.7).
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if not text.strip():
        return []
    if chunk_token_count(text) <= max_tokens:
        return [text]
    parts: list[str] = []
    paragraphs = text.split("\n\n")
    buf: list[str] = []
    size = 0
    for para in paragraphs:
        para_tokens = chunk_token_count(para)
        buf, size = _append_paragraph(
            para,
            para_tokens=para_tokens,
            max_tokens=max_tokens,
            parts=parts,
            buf=buf,
            size=size,
        )
    if buf:
        parts.append("\n\n".join(buf))
    return [p for p in parts if p.strip()]


def _append_paragraph(
    para: str,
    *,
    para_tokens: int,
    max_tokens: int,
    parts: list[str],
    buf: list[str],
    size: int,
) -> tuple[list[str], int]:
    """Update overflow buffers for one paragraph without changing split semantics."""
    if buf and size + para_tokens > max_tokens:
        parts.append("\n\n".join(buf))
        next_buf = [para] if para_tokens <= max_tokens else _split_long_para(para, max_tokens)
        next_size = chunk_token_count(next_buf[0]) if len(next_buf) == 1 else max_tokens
        return next_buf, next_size
    if para_tokens > max_tokens:
        if buf:
            parts.append("\n\n".join(buf))
        parts.extend(_split_long_para(para, max_tokens))
        return [], 0
    buf.append(para)
    return buf, size + para_tokens


def _split_long_para(para: str, max_tokens: int) -> list[str]:
    """Split a too-long paragraph on line boundaries."""
    lines = para.split("\n")
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for line in lines:
        lt = chunk_token_count(line)
        if buf and size + lt > max_tokens:
            parts.append("\n".join(buf))
            buf = [line]
            size = lt
        else:
            buf.append(line)
            size += lt
    if buf:
        parts.append("\n".join(buf))
    return parts


def chunk_document(body: str, *, max_tokens: int = DEFAULT_MAX_TOKENS) -> list[tuple[Section, str]]:
    """Chunk a document body into ``(section, chunk_text)`` pairs.

    Each oversized section is split via :func:`overflow_split`; every emitted
    chunk carries its source :class:`Section` so metadata (heading, section
    number) propagates.
    """
    out: list[tuple[Section, str]] = []
    for section in split_into_sections(body):
        for piece in overflow_split(section.body, max_tokens) or [section.body]:
            out.append((section, piece))
    return out


def iter_chunks(body: str, *, max_tokens: int = DEFAULT_MAX_TOKENS) -> Iterator[tuple[Section, str]]:
    """Iterate ``(section, chunk_text)`` lazily."""
    yield from chunk_document(body, max_tokens=max_tokens)


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "Section",
    "chunk_document",
    "iter_chunks",
    "overflow_split",
    "split_into_sections",
]
