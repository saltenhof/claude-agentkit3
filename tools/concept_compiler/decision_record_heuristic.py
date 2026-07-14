"""Fail-closed changed-line classification for concept documents."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from enum import StrEnum
from typing import TYPE_CHECKING

from .normativity import NORMATIVE_MODAL_RE

if TYPE_CHECKING:
    from .decision_record_models import ChangedBodyLine, ConceptFileChange

_MARKDOWN_TARGET_RE = re.compile(r"(?<=\]\()[^)]+(?=\))")
_BARE_URL_RE = re.compile(r"https?://[^\s)>]+")
_ANCHOR_RE = re.compile(
    r"\{#[A-Za-z0-9_.:-]+\}|<a\s+[^>]*id=[\"'][^\"']+[\"'][^>]*>\s*</a>|"
    r"<!--\s*PROSE-FORMAL:\s*[^>]+-->",
    re.IGNORECASE,
)


class LineClass(StrEnum):
    """Exhaustive changed-body-line classifications."""

    IGNORABLE = "IGNORABLE"
    NORMATIVE = "NORMATIVE"
    AMBIGUOUS = "AMBIGUOUS"


def first_record_requiring_line(
    change: ConceptFileChange, *, allow_ambiguous: bool
) -> ChangedBodyLine | None:
    """Return the first line requiring a record, or ``None`` when exempt."""
    link_only = _link_only_line_ids(change)
    classified = [
        (line, _classify(line, (side, index) in link_only))
        for side, lines in (("added", change.added_body_lines), ("removed", change.removed_body_lines))
        for index, line in enumerate(lines)
    ]
    normative = sorted((line for line, kind in classified if kind is LineClass.NORMATIVE), key=lambda item: item.line)
    if normative:
        return normative[0]
    ambiguous = sorted((line for line, kind in classified if kind is LineClass.AMBIGUOUS), key=lambda item: item.line)
    return None if allow_ambiguous or not ambiguous else ambiguous[0]


def _classify(line: ChangedBodyLine, link_only: bool) -> LineClass:
    if link_only or not line.text.strip() or _is_pure_punctuation(line.text):
        return LineClass.IGNORABLE
    if NORMATIVE_MODAL_RE.search(line.text):
        return LineClass.NORMATIVE
    return LineClass.AMBIGUOUS


def _is_pure_punctuation(text: str) -> bool:
    characters = (character for character in text if not character.isspace())
    return all(unicodedata.category(character).startswith("P") for character in characters)


def _link_only_line_ids(change: ConceptFileChange) -> frozenset[tuple[str, int]]:
    added = _normalized_candidates(change.added_body_lines)
    removed = _normalized_candidates(change.removed_body_lines)
    shared = Counter(key for key, _ in added) & Counter(key for key, _ in removed)
    matched: set[tuple[str, int]] = set()
    for key, count in shared.items():
        added_indexes = [index for candidate, index in added if candidate == key][:count]
        removed_indexes = [index for candidate, index in removed if candidate == key][:count]
        matched.update(("added", index) for index in added_indexes)
        matched.update(("removed", index) for index in removed_indexes)
    return frozenset(matched)


def _normalized_candidates(lines: tuple[ChangedBodyLine, ...]) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        normalized = _ANCHOR_RE.sub("", line.text)
        normalized = _MARKDOWN_TARGET_RE.sub("<TARGET>", normalized)
        normalized = _BARE_URL_RE.sub("<URL>", normalized)
        if normalized != line.text:
            candidates.append((normalized, index))
    return candidates
