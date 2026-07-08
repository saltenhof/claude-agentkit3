"""HTTP header lookup helpers for control-plane request handling."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def lookup_header_ci(headers: Mapping[str, str] | None, name: str) -> str | None:
    """Look a request header up case-insensitively."""
    if headers is None:
        return None
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None
