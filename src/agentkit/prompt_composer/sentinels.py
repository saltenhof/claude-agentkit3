"""Sentinel markers for prompt compliance tracking."""

from __future__ import annotations

import re

SENTINEL_PATTERN: re.Pattern[str] = re.compile(
    r"\[SENTINEL:"
    r"(?P<template>[a-z0-9-]+)"
    r"-v(?P<version>\d+)"
    r":(?P<story_id>[A-Za-z0-9_-]+)\]"
)


def make_sentinel(
    template_name: str,
    story_id: str,
    version: int = 1,
) -> str:
    return f"[SENTINEL:{template_name}-v{version}:{story_id}]"


def extract_sentinel(text: str) -> dict[str, str] | None:
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
    data = extract_sentinel(text)
    if data is None:
        return False
    return (
        data["template"] == expected_template
        and data["story_id"] == expected_story_id
    )

__all__ = [
    "SENTINEL_PATTERN",
    "extract_sentinel",
    "make_sentinel",
    "validate_sentinel",
]
