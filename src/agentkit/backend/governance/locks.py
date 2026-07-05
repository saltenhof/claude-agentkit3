"""Lock-deactivation data models for the governance BC.

Defines ``LockRecordId`` and ``DeactivationResult`` as the canonical typed
surface for ``Governance.deactivate_locks``.

Sources:
- FK-30 §30.6.0 — ``Governance.deactivate_locks`` top-surface
- FK-22 §22.7   — Lock-Record + Edge-Bundle paths
- FK-29 §29.5   — Closure-Pfad (ClosureSequence calls deactivate_locks)

AG3-031 Pass-3 FK-30-Korrektur 2026-05-24 (Fix E4):
  DeactivationResult extended with removed_lock_exports and
  restored_to_ai_augmented per FK-30 §30.6.0.
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
        deactivated_locks: IDs of lock records set to INACTIVE in the backend.
        removed_edge_bundles: Filesystem paths of edge-bundle files deleted
            (legacy / compat path; FK-30 §30.6.0 primary paths are in
            removed_lock_exports).
        removed_lock_exports: Filesystem paths of lock-export files deleted.
            Covers the backend-local ``_temp/governance/locks/{story_id}/
            qa-lock.json`` (FK-30 §30.6.0). AG3-145 Teilschritt D (FK-10
            §10.2.4a): the dev-local ``.agent-guard/lock.json`` worktree exports
            are NO LONGER removed by the backend -- the edge tombstone projection
            (``tombstone_worktree_roots``) carries that removal.
        restored_to_ai_augmented: True when the story's operating mode was
            successfully reverted to ``ai_augmented`` (FK-30 §30.6.0 Z.683).
        errors: Non-fatal IO errors encountered during deactivation (including
            LockRecordNotFoundError surfaced by the repository).
            Critical DB errors are raised, not stored here.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    deactivated_locks: list[LockRecordId] = []
    removed_edge_bundles: list[Path] = []
    removed_lock_exports: list[Path] = []
    restored_to_ai_augmented: bool = False
    errors: list[str] = []


__all__ = [
    "DeactivationResult",
    "LockRecordId",
]
