"""Section-aware packing for Layer-2 review bundles (FK-37 §37.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

BUNDLE_TOKEN_LIMIT: int = 32_000
TRUNCATION_MARKER: str = "[...PACKED by section-aware bundle packing (FK-37 §37.3)...]"


class PackingKind(StrEnum):
    """Packing strategy applied to a bundle field.

    There is exactly ONE truncation mechanism (section-aware packing, FK-37
    §37.3 / DK-11 "sufficiency checks are only as good as the packing"): the
    legacy begin/end byte ``FALLBACK`` path was removed (AG3-067 AC9 — no second
    truncation path). ``MARKDOWN`` packs whole sections; ``CODE`` packs whole
    hunks/blocks. Even the degenerate overflow case stays section-aware
    (whole-placeholder-line boundary), never a mid-content byte cut.
    """

    MARKDOWN = "markdown"
    CODE = "code"


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
        packed = _section_aware_cap(packed, limit)
        protocol.append(
            "section placeholders exceeded limit; dropped trailing whole sections "
            "(section-aware, no mid-content cut)"
        )
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
        packed = _section_aware_cap(packed, limit)
        protocol.append(
            "code placeholders exceeded limit; dropped trailing whole blocks "
            "(section-aware, no mid-content cut)"
        )
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
    """Dispatch a bundle field to the SINGLE section-aware packing mechanism.

    FK-37 §37.3 keeps ``truncate_bundle()`` as the back-compatible dispatcher
    entry point, but AG3-067 AC9 removes the second (begin/end byte) truncation
    path: this dispatcher ALWAYS delegates to section-aware :func:`pack_markdown`
    (DK-11 "when content is bluntly truncated, the builder judges the quality of
    an already distorted bundle"). ``priority_headings`` is optional — ``None`` is
    normalised to an empty tuple (still section-aware, just unprioritised). There
    is no mid-content excerpt fallback anymore.
    """
    _validate_limit(limit)
    return pack_markdown(
        content,
        limit=limit,
        priority_headings=priority_headings or (),
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


def _section_aware_cap(content: str, limit: int) -> str:
    """Cap an over-limit packed body at a whole-section boundary (no byte cut).

    Reached only in the degenerate case where even the section placeholders join
    longer than ``limit`` (e.g. thousands of tiny sections). Keeps the SINGLE
    section-aware mechanism (AG3-067 AC9): whole ``\\n\\n``-delimited sections are
    retained from the front until the budget (including a trailing marker) is
    exhausted, then a single marker is appended. It NEVER slices mid-content
    (no begin/end byte excerpt), so a section is either fully present or fully
    dropped — keeping the bundle undistorted for the sufficiency check (DK-11).
    """
    marker = f"\n{TRUNCATION_MARKER}"
    if limit <= len(marker):
        return marker[:limit]
    budget = limit - len(marker)
    sections = content.split("\n\n")
    kept: list[str] = []
    used = 0
    for section in sections:
        section_cost = len(section) + (2 if kept else 0)
        if used + section_cost > budget:
            break
        kept.append(section)
        used += section_cost
    body = "\n\n".join(kept).rstrip()
    return (body + marker) if body else marker.lstrip("\n")


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
