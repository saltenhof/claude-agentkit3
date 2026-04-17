"""Story sizing logic."""

from __future__ import annotations

import re
from enum import StrEnum


class StorySize(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    EPIC = "epic"


_LABEL_PREFIX = "size:"
_VALID_SIZES: dict[str, StorySize] = {size.value: size for size in StorySize}
_EPIC_KEYWORDS: frozenset[str] = frozenset(
    {"refactor", "redesign", "migration", "overhaul", "rewrite", "rearchitect"}
)
_LARGE_KEYWORDS: frozenset[str] = frozenset(
    {
        "implement",
        "integration",
        "pipeline",
        "framework",
        "infrastructure",
        "architecture",
    }
)


def estimate_size(labels: list[str], title: str) -> StorySize:
    for label in labels:
        normalized = label.strip().lower()
        if normalized.startswith(_LABEL_PREFIX):
            size_value = normalized[len(_LABEL_PREFIX) :]
            if size_value in _VALID_SIZES:
                return _VALID_SIZES[size_value]

    words = set(re.findall(r"[a-z]+", title.lower()))
    if words & _EPIC_KEYWORDS:
        return StorySize.LARGE
    if words & _LARGE_KEYWORDS:
        return StorySize.MEDIUM
    return StorySize.SMALL


__all__ = [
    "StorySize",
    "estimate_size",
]
