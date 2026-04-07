"""Sentinel markers for prompt compliance tracking.

Sentinels are markers embedded in prompts that agents echo in their
output to signal they used the approved template.  Format::

    [SENTINEL:{template-name}-v{version}:{story_id}]
"""

from __future__ import annotations

import re

SENTINEL_PATTERN: re.Pattern[str] = re.compile(
    r"\[SENTINEL:"
    r"(?P<template>[a-z0-9-]+)"
    r"-v(?P<version>\d+)"
    r":(?P<story_id>[A-Za-z0-9_-]+)\]"
)
"""Compiled regex for extracting sentinel components from text."""


def make_sentinel(
    template_name: str,
    story_id: str,
    version: int = 1,
) -> str:
    """Create a sentinel marker string.

    Args:
        template_name: Name of the template
            (e.g. ``"worker-implementation"``).
        story_id: Unique story identifier (e.g. ``"AG3-001"``).
        version: Template version number.  Defaults to ``1``.

    Returns:
        Formatted sentinel string, e.g.
        ``"[SENTINEL:worker-implementation-v1:AG3-001]"``.
    """
    return f"[SENTINEL:{template_name}-v{version}:{story_id}]"


def extract_sentinel(text: str) -> dict[str, str] | None:
    """Extract sentinel data from text.

    Searches *text* for the first occurrence of a sentinel marker and
    returns its components.

    Args:
        text: Text that may contain a sentinel marker.

    Returns:
        Dictionary with keys ``"template"``, ``"version"``, and
        ``"story_id"`` if a sentinel is found, otherwise ``None``.
    """
    match = SENTINEL_PATTERN.search(text)
    if match is None:
        return None
    return {
        "template": match.group("template"),
        "version": match.group("version"),
        "story_id": match.group("story_id"),
    }


def validate_sentinel(
    text: str,
    expected_template: str,
    expected_story_id: str,
) -> bool:
    """Check if text contains the expected sentinel.

    Args:
        text: Text to search for the sentinel.
        expected_template: Expected template name component.
        expected_story_id: Expected story identifier component.

    Returns:
        ``True`` if a matching sentinel is found, ``False`` otherwise.
    """
    data = extract_sentinel(text)
    if data is None:
        return False
    return (
        data["template"] == expected_template
        and data["story_id"] == expected_story_id
    )
