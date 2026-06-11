"""Story sizing logic.

``StorySize`` is, since AG3-021, re-exported from ``agentkit.core_types``
and uses the DK-10-normative vocabulary XS/S/M/L/XL (no more
small/medium/large/epic).
"""

from __future__ import annotations

import re

from agentkit.core_types import StorySize

_LABEL_PREFIX = "size:"
_VALID_SIZES: dict[str, StorySize] = {size.value.lower(): size for size in StorySize}
_LARGE_KEYWORDS: frozenset[str] = frozenset(
    {"refactor", "redesign", "migration", "overhaul", "rewrite", "rearchitect"}
)
_MEDIUM_KEYWORDS: frozenset[str] = frozenset(
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
    """Estimate the ``StorySize`` from label and title heuristics.

    The ``size:`` label prefix beats the title heuristic. Accepted
    label values are case-insensitive variants of the ``StorySize`` members
    (XS, S, M, L, XL). A title with larger-refactor keywords -> L;
    a title with integration/framework keywords -> M; otherwise -> S.

    Args:
        labels: Labels from the story-creation path.
        title: Story title.

    Returns:
        The estimated ``StorySize``.
    """

    for label in labels:
        normalized = label.strip().lower()
        if normalized.startswith(_LABEL_PREFIX):
            size_value = normalized[len(_LABEL_PREFIX) :]
            if size_value in _VALID_SIZES:
                return _VALID_SIZES[size_value]

    words = set(re.findall(r"[a-z]+", title.lower()))
    if words & _LARGE_KEYWORDS:
        return StorySize.L
    if words & _MEDIUM_KEYWORDS:
        return StorySize.M
    return StorySize.S


__all__ = [
    "StorySize",
    "estimate_size",
]
