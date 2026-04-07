"""Story sizing logic.

Estimates story size from labels and title metadata. Used by the
setup phase to determine resource allocation and timeout thresholds.
"""

from __future__ import annotations

import re
from enum import StrEnum


class StorySize(StrEnum):
    """Story size classification.

    Attributes:
        SMALL: Less than 2 hours estimated effort.
        MEDIUM: 2-8 hours estimated effort.
        LARGE: 8-24 hours estimated effort.
        EPIC: More than 24 hours -- should be split into smaller stories.
    """

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    EPIC = "epic"


_LABEL_PREFIX = "size:"
"""Prefix for size labels (e.g. ``size:small``, ``size:medium``)."""

_VALID_SIZES: dict[str, StorySize] = {
    size.value: size for size in StorySize
}

_EPIC_KEYWORDS: frozenset[str] = frozenset({
    "refactor",
    "redesign",
    "migration",
    "overhaul",
    "rewrite",
    "rearchitect",
})
"""Title keywords that hint at epic-scale effort."""

_LARGE_KEYWORDS: frozenset[str] = frozenset({
    "implement",
    "integration",
    "pipeline",
    "framework",
    "infrastructure",
    "architecture",
})
"""Title keywords that hint at large-scale effort."""


def estimate_size(labels: list[str], title: str) -> StorySize:
    """Estimate story size from labels and title.

    Labels take precedence: if a label matching ``size:<value>`` is
    present, that value is used directly. Otherwise the title is
    analyzed for keywords that hint at story complexity.

    Args:
        labels: GitHub labels attached to the issue.
        title: The issue title.

    Returns:
        The estimated ``StorySize``.
    """
    # Labels take precedence
    for label in labels:
        normalized = label.strip().lower()
        if normalized.startswith(_LABEL_PREFIX):
            size_value = normalized[len(_LABEL_PREFIX) :]
            if size_value in _VALID_SIZES:
                return _VALID_SIZES[size_value]

    # Fall back to title-based heuristic
    title_lower = title.lower()
    # Extract individual words for keyword matching
    words = set(re.findall(r"[a-z]+", title_lower))

    if words & _EPIC_KEYWORDS:
        return StorySize.LARGE  # Heuristic is conservative: suggest large, not epic

    if words & _LARGE_KEYWORDS:
        return StorySize.MEDIUM  # Conservative: one step below the keyword signal

    return StorySize.SMALL
