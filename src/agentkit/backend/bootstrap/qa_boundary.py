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
