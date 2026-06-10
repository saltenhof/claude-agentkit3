"""Section-aware packing for Layer-2 review bundles (FK-37 §37.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

BUNDLE_TOKEN_LIMIT: int = 32_000
TRUNCATION_MARKER: str = "[...PACKED by section-aware bundle packing (FK-37 §37.3)...]"


class PackingKind(StrEnum):
    """Packing strategy applied to a bundle field."""

    MARKDOWN = "markdown"
    CODE = "code"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class PackingResult:
    """Packed content plus deterministic truncation metadata."""

    content: str
    truncated: bool
    original_chars: int
    packed_chars: int
    kind: PackingKind
    protocol: tuple[str, ...] = ()


def pack_markdown(
    content: str,
    *,
    limit: int = BUNDLE_TOKEN_LIMIT,
    priority_headings: tuple[str, ...] = (),
) -> PackingResult:
    """Pack Markdown by retaining whole sections before falling back to excerpts."""
    _validate_limit(limit)
    if len(content) <= limit:
        return PackingResult(
            content=content,
            truncated=False,
            original_chars=len(content),
            packed_chars=len(content),
            kind=PackingKind.MARKDOWN,
        )

    sections = _split_markdown_sections(content)
    ranked = sorted(
        enumerate(sections),
        key=lambda item: (_section_priority(item[1], priority_headings), item[0]),
    )
    kept_indexes: set[int] = set()
    budget = limit - len(TRUNCATION_MARKER) - 2
    used = 0
    protocol: list[str] = []
    for index, section in ranked:
        section_cost = len(section) + 2
        if section_cost > budget:
            protocol.append(f"omitted section {_section_title(section)!r}: {len(section)} chars")
            continue
        if used + section_cost <= budget:
            kept_indexes.add(index)
            used += section_cost
        else:
            protocol.append(f"omitted section {_section_title(section)!r}: {len(section)} chars")

    packed_parts: list[str] = []
    for index, section in enumerate(sections):
        if index in kept_indexes:
            packed_parts.append(section)
        else:
            packed_parts.append(
                f'[Section "{_section_title(section)}" omitted - {len(section)} chars]'
            )
    packed = "\n\n".join(packed_parts)
    if len(packed) > limit:
        packed = _middle_fallback(packed, limit)
        protocol.append("section placeholders exceeded limit; applied fallback excerpt")
    return PackingResult(
        content=packed,
        truncated=True,
        original_chars=len(content),
        packed_chars=len(packed),
        kind=PackingKind.MARKDOWN,
        protocol=tuple(protocol),
    )


def pack_code(
    content: str,
    *,
    changed_symbols: tuple[str, ...] = (),
    limit: int = BUNDLE_TOKEN_LIMIT,
) -> PackingResult:
    """Pack code or diff text by preferring hunks mentioning changed symbols."""
    _validate_limit(limit)
    if len(content) <= limit:
        return PackingResult(
            content=content,
            truncated=False,
            original_chars=len(content),
            packed_chars=len(content),
            kind=PackingKind.CODE,
        )

    blocks = _split_code_blocks(content)
    ranked = sorted(
        enumerate(blocks),
        key=lambda item: (_block_priority(item[1], changed_symbols), item[0]),
    )
    budget = limit - len(TRUNCATION_MARKER) - 2
    kept_indexes: set[int] = set()
    used = 0
    protocol: list[str] = []
    for index, block in ranked:
        block_cost = len(block) + 2
        if block_cost > budget:
            protocol.append(f"omitted oversized code block {index}: {len(block)} chars")
            continue
        if used + block_cost <= budget:
            kept_indexes.add(index)
            used += block_cost
        else:
            protocol.append(f"omitted code block {index}: {len(block)} chars")
    packed_parts = [
        block if index in kept_indexes else f"[Code block {index} omitted - {len(block)} chars]"
        for index, block in enumerate(blocks)
    ]
    packed = "\n\n".join(packed_parts).rstrip()
    if len(packed) > limit:
        packed = _middle_fallback(packed, limit)
        protocol.append("code placeholders exceeded limit; applied fallback excerpt")
    return PackingResult(
        content=packed,
        truncated=True,
        original_chars=len(content),
        packed_chars=len(packed),
        kind=PackingKind.CODE,
        protocol=tuple(protocol),
    )


def truncate_bundle(
    content: str,
    *,
    limit: int = BUNDLE_TOKEN_LIMIT,
    priority_headings: tuple[str, ...] | None = None,
) -> PackingResult:
    """Dispatch to section-aware Markdown packing or deterministic fallback."""
    _validate_limit(limit)
    if priority_headings is not None:
        return pack_markdown(content, limit=limit, priority_headings=priority_headings)
    if len(content) <= limit:
        return PackingResult(
            content=content,
            truncated=False,
            original_chars=len(content),
            packed_chars=len(content),
            kind=PackingKind.FALLBACK,
        )
    packed = _middle_fallback(content, limit)
    return PackingResult(
        content=packed,
        truncated=True,
        original_chars=len(content),
        packed_chars=len(packed),
        kind=PackingKind.FALLBACK,
        protocol=("fallback beginning/end excerpt applied",),
    )


def _split_markdown_sections(content: str) -> list[str]:
    matches = list(re.finditer(r"(?m)^#{1,6}\s+.+$", content))
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


def _split_code_blocks(content: str) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n(?=diff --git |\@\@ |class |def )", content)]
    return [block for block in blocks if block]


def _section_priority(section: str, priority_headings: tuple[str, ...]) -> int:
    title = _section_title(section).lower()
    for index, heading in enumerate(priority_headings):
        if heading.lower() in title:
            return index
    return len(priority_headings) + 1


def _block_priority(block: str, changed_symbols: tuple[str, ...]) -> int:
    if any(symbol and symbol in block for symbol in changed_symbols):
        return 0
    if block.startswith(("diff --git", "@@")):
        return 1
    return 2


def _section_title(section: str) -> str:
    first = section.splitlines()[0].strip() if section.strip() else "preamble"
    return first.lstrip("#").strip() or "preamble"


def _middle_fallback(content: str, limit: int) -> str:
    marker = f"\n{TRUNCATION_MARKER}\n"
    if limit <= len(marker):
        return marker[:limit]
    half = (limit - len(marker)) // 2
    tail = limit - len(marker) - half
    return content[:half].rstrip() + marker + content[-tail:].lstrip()


def _validate_limit(limit: int) -> None:
    if limit <= 0:
        raise ValueError("bundle packing limit must be > 0")


__all__ = [
    "BUNDLE_TOKEN_LIMIT",
    "PackingKind",
    "PackingResult",
    "TRUNCATION_MARKER",
    "pack_code",
    "pack_markdown",
    "truncate_bundle",
]
