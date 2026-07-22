"""SSOT chunk identity (AG3-174 R02) — single owner for all profiles."""

from __future__ import annotations

import uuid
from typing import Final

_CHUNK_NAMESPACE: Final[uuid.UUID] = uuid.UUID("6b1c2e8a-4d5f-4a7b-9c0d-1e2f3a4b5c6d")


def deterministic_chunk_uuid(
    *,
    project_id: str,
    source_file: str,
    section_heading: str,
    content_hash: str,
    ordering: int,
) -> str:
    """Return a stable UUID5 for a chunk identity tuple (all profiles)."""
    key = f"{project_id}|{source_file}|{section_heading}|{ordering}|{content_hash}"
    return str(uuid.uuid5(_CHUNK_NAMESPACE, key))


__all__ = ["deterministic_chunk_uuid"]
