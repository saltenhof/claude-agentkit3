"""Small QA-boundary value objects for the composition root."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QaBoundaryBinding:
    """Resolved QA boundary scope for sync-push commissioning."""

    scope: Any
    ctx: Any
    active: Any
    boundary_id: str


def boundary_id_from_sync_point(
    sync_point_id: str,
    *,
    expected_type: object,
) -> str | None:
    """Extract a boundary id from ``<type>:<id>[:epoch-n]`` correlations."""

    expected_value = getattr(expected_type, "value", str(expected_type))
    prefix = f"{expected_value}:"
    if not sync_point_id.startswith(prefix):
        return None
    body = sync_point_id[len(prefix) :]
    if not body:
        return None
    if ":epoch-" in body:
        body = body.rsplit(":epoch-", 1)[0]
    return body or None
