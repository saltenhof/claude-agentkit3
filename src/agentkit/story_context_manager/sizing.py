"""Story sizing logic.

``StorySize`` wird seit AG3-021 aus ``agentkit.core_types`` re-exportiert
und nutzt das DK-10-normative Vokabular XS/S/M/L/XL (keine
small/medium/large/epic mehr).
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
    """Schaetze die ``StorySize`` aus Label- und Titel-Heuristiken.

    Label-Prefix ``size:`` schlaegt die Titel-Heuristik. Akzeptierte
    Label-Werte sind case-insensitive Varianten der ``StorySize``-Member
    (XS, S, M, L, XL). Titel mit groesseren-Refactor-Keywords -> L;
    Titel mit Integrations-/Framework-Keywords -> M; ansonsten -> S.

    Args:
        labels: Labels aus dem Story-Erstellungspfad.
        title: Story-Titel.

    Returns:
        Die geschaetzte ``StorySize``.
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
