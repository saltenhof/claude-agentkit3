"""Heading-based chunking with model-bound token overflow (FK-13 §13.3.3).

Split at ``##`` / ``###`` (profile-controlled). No overlap. Overflow below the
heading level is a deterministic paragraph/character partition. Token unit is
the pinned MiniLM tokenizer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.concept_catalog.corpus.hashing import sha256_text
from agentkit.backend.vectordb.tokenizer import count_tokens

if TYPE_CHECKING:
    from agentkit.backend.concept_catalog.corpus.profiles import IngestProfile

_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class TextChunk:
    """One chunk produced by the shared kernel."""

    section_heading: str
    section_number: str
    content: str
    content_hash: str
    ordering: int
    token_count: int


@dataclass(frozen=True)
class ChunkOverflowFinding:
    """Token-limit overflow finding (may be blocking per profile)."""

    section_heading: str
    token_count: int
    max_tokens: int


def chunk_markdown(
    body: str,
    *,
    profile: IngestProfile,
    title: str = "",
) -> tuple[list[TextChunk], list[ChunkOverflowFinding]]:
    """Chunk a markdown body according to ``profile``.

    Returns:
        ``(chunks, overflow_findings)``. When
        ``profile.enforce_token_limit_as_error`` is True, findings for
        pre-split sections exceeding the limit are still reported so
        ``E-CHUNK-001`` stays blocking at validate time.
    """
    sections = _split_sections(body, heading_levels=profile.heading_levels, title=title)
    chunks: list[TextChunk] = []
    findings: list[ChunkOverflowFinding] = []
    ordering = 0
    for section_number, heading, content in sections:
        tokens = count_tokens(content)
        if tokens > profile.max_tokens:
            findings.append(
                ChunkOverflowFinding(
                    section_heading=heading,
                    token_count=tokens,
                    max_tokens=profile.max_tokens,
                )
            )
            # Still split for downstream consumers that need deterministic parts,
            # but validation keeps E-CHUNK-001 blocking.
            parts = _split_overflow(content, max_tokens=profile.max_tokens)
        else:
            parts = [content]
        for part_i, part in enumerate(parts):
            part_heading = heading if part_i == 0 else f"{heading} (part {part_i + 1})"
            part_tokens = count_tokens(part)
            chunks.append(
                TextChunk(
                    section_heading=part_heading,
                    section_number=section_number if part_i == 0 else f"{section_number}.{part_i}",
                    content=part,
                    content_hash=sha256_text(part),
                    ordering=ordering,
                    token_count=part_tokens,
                )
            )
            ordering += 1
    return chunks, findings


def _split_sections(
    body: str,
    *,
    heading_levels: tuple[int, ...],
    title: str,
) -> list[tuple[str, str, str]]:
    body = body.replace("\r\n", "\n")
    if not body.strip():
        return []
    allowed = set(heading_levels)
    matches = [
        m
        for m in _HEADING_RE.finditer(body)
        if len(m.group(1)) in allowed
    ]
    if not matches:
        heading = title or "(document)"
        return [("1", heading, body.strip())]

    sections: list[tuple[str, str, str]] = []
    intro = body[: matches[0].start()].strip()
    counters = {2: 0, 3: 0}
    if intro:
        sections.append(("0", "(intro)", intro))

    for i, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[match.end() : end].strip()
        if not content:
            continue
        if level == 2:
            counters[2] += 1
            counters[3] = 0
            number = str(counters[2])
        else:
            if counters[2] == 0:
                counters[2] = 1
            counters[3] += 1
            number = f"{counters[2]}.{counters[3]}"
        # Keep heading line in content for search quality.
        full = f"{'#' * level} {heading}\n\n{content}"
        sections.append((number, heading, full))
    return sections


def _split_overflow(text: str, *, max_tokens: int) -> list[str]:
    """Deterministic split below heading level (paragraphs, then hard cut)."""
    if count_tokens(text) <= max_tokens:
        return [text]
    paragraphs = text.split("\n\n")
    parts: list[str] = []
    buf: list[str] = []
    for para in paragraphs:
        candidate = "\n\n".join([*buf, para]) if buf else para
        if buf and count_tokens(candidate) > max_tokens:
            parts.append("\n\n".join(buf))
            buf = [para]
            if count_tokens(para) > max_tokens:
                parts.extend(_hard_split(para, max_tokens=max_tokens))
                buf = []
        else:
            if count_tokens(para) > max_tokens and not buf:
                parts.extend(_hard_split(para, max_tokens=max_tokens))
            else:
                buf.append(para)
    if buf:
        joined = "\n\n".join(buf)
        if count_tokens(joined) > max_tokens:
            parts.extend(_hard_split(joined, max_tokens=max_tokens))
        else:
            parts.append(joined)
    return parts or [text]


def _hard_split(text: str, *, max_tokens: int) -> list[str]:
    """Binary-search character windows so each part is <= max_tokens."""
    if count_tokens(text) <= max_tokens:
        return [text]
    parts: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        lo = start + 1
        hi = n
        best = start + 1
        while lo <= hi:
            mid = (lo + hi) // 2
            window = text[start:mid]
            if count_tokens(window) <= max_tokens:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best <= start:
            best = start + 1
        parts.append(text[start:best])
        start = best
    return parts


__all__ = [
    "ChunkOverflowFinding",
    "TextChunk",
    "chunk_markdown",
]
