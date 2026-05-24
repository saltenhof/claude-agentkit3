"""Lock-deactivation data models for the governance BC.

Defines ``LockRecordId`` and ``DeactivationResult`` as the canonical typed
surface for ``Governance.deactivate_locks``.

Sources:
- FK-30 §30.6.0 — ``Governance.deactivate_locks`` top-surface
- FK-22 §22.7   — Lock-Record + Edge-Bundle paths
"""

from __future__ import annotations

from pathlib import Path
from typing import NewType

from pydantic import BaseModel, ConfigDict

LockRecordId = NewType("LockRecordId", str)
"""Opaque identifier for a single story-execution lock record."""


class DeactivationResult(BaseModel):
    """Result of a ``deactivate_locks`` call.

    Attributes:
        deactivated_locks: IDs of lock records removed from the backend.
        removed_edge_bundles: Filesystem paths of edge-bundle files deleted.
        errors: Non-fatal IO errors encountered during deactivation.
            Critical DB errors are raised, not stored here.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    deactivated_locks: list[LockRecordId] = []
    removed_edge_bundles: list[Path] = []
    errors: list[str] = []


__all__ = [
    "DeactivationResult",
    "LockRecordId",
]
