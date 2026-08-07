"""Core-side administration of governance state (AG3-239 M2).

This module owns the governance operation that is neither hook-process work nor
edge orchestration:

* ``deactivate_locks`` -- deactivate a story's lock records (FK-30 section
  30.6.0). Driven by ClosureSequence (FK-29 section 29.5), story-exit,
  story-split and story-reset.

It holds a canonical repository (``LockRecordRepository``) and therefore belongs
to the core (FK-01 section 1.1a).

Why this module exists: until AG3-239 the class lived in ``governance.runner``
next to ``GuardRunner`` and the hook dispatch, which run inside the short-lived
hook process on the developer machine. One module therefore carried symbols of
both distributions, and because ``runner`` is classified ``edge``, ten import
edges crossed the distribution boundary for no reason -- among them three of the
four governance-owned ``state_backend`` bindings. Splitting the symbols removed
all ten without a single endpoint (measured 64 -> 59 crossings for the bounded
context); see
``architecture-conformance.symbol_boundary.governance_runner``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.governance.errors import LockRecordNotFoundError
from agentkit.backend.governance.locks import DeactivationResult, LockRecordId

if TYPE_CHECKING:
    from agentkit.backend.state_backend.store.lock_record_repository import (
        LockRecordRepository,
    )


class Governance:
    """Core-side lock deactivation for a finished story (FK-30 §30.6.0).

    ``deactivate_locks`` deactivates a story's lock records. It is called by
    ClosureSequence (FK-29 §29.5) and by the story-exit, story-split and
    story-reset services.

    Two surfaces are deliberately NOT here:

    * **Hook dispatch** runs in the hook process on the developer machine and is
      reached through ``governance.runner.run_hook``.
    * **Hook registration** persists through a ``HookRegistrationRepository`` and
      then materialises ``.claude/settings.json`` / ``.codex/hooks.json`` on the
      developer machine. The second half is edge work the core cannot do, so the
      whole operation is edge orchestration and lives in
      ``installer.writer_client.InstallerHookGovernance``.

    Args:
        lock_repo: Repository for story-execution lock deactivation.

    AG3-239: until this story the class carried ``register_hooks`` as well, and
    every construction site had to supply a dummy for the half it did not need --
    the installer faked a lock repository, and the three composition-root sites
    faked a hook repository by binding a direct-DB
    ``StateBackendHookRegistrationRepository`` they never called. Four dummies at
    four of four call sites is the measurement that the class was two things.

    AG3-145 sub-step D (FK-10 §10.2.4a) and AG3-239: the operation touches no
    filesystem at all. The dev-local ``.agent-guard`` projection runs entirely
    over the edge bundle-publication + ``tombstone_worktree_roots`` mechanism
    (``harness_client.projectedge.client``). The backend keeps no path
    authority, on a worktree or anywhere else.
    """

    def __init__(self, *, lock_repo: LockRecordRepository) -> None:
        self._lock_repo = lock_repo

    # ------------------------------------------------------------------
    # deactivate_locks (FK-30 §30.6.0)
    # ------------------------------------------------------------------

    def deactivate_locks(self, story_id: str) -> DeactivationResult:
        """Deactivate all lock records for a story (FK-30 §30.6.0).

        Called by ClosureSequence (FK-29 §29.5) after successful postflight, and
        by the story-exit, story-split and story-reset services. After this call
        the canonical lock state says the story holds no active lock, and the
        guards that depend on one (branch guard, orchestrator guard, QA
        protection) stop applying.

        Idempotent for already-deactivated stories (all locks INACTIVE):
        returns empty ``deactivated_locks`` without errors, and
        ``guards_deactivated`` is still True -- the guards ARE off, which is what
        the caller asked about.

        Fail-closed (Fix E6, AG3-031 Pass-3):
        - Unknown story_id (no lock records at all) → LockRecordNotFoundError
          surfaced in ``errors[0]`` and ``guards_deactivated`` False. Nothing was
          proven about that story's guards, so the caller must not proceed.
        - DB failures → raised immediately (not silently swallowed).

        AG3-239: this operation no longer touches the filesystem. It used to
        delete and write under ``_temp/governance/**`` relative to the process
        CWD -- the EDGE's projection directory -- and derived
        ``restored_to_ai_augmented`` from whether one of those legacy
        directories happened to exist. Story exit gated on that flag, so on a
        core host every exit would have been rejected. The edge-side mode
        restoration is carried by the tombstone projection (AG3-145 sub-step D,
        FK-10 §10.2.4a).

        Args:
            story_id: Canonical story identifier.

        Returns:
            ``DeactivationResult`` with ``deactivated_locks``,
            ``guards_deactivated`` and ``errors``.

        Raises:
            Exception: On unrecoverable DB failures.
        """
        # Fix E6: fail-closed for unknown story_id.
        # LockRecordNotFoundError is surfaced in errors[]; critical DB errors
        # (any other exception) are re-raised immediately.
        errors: list[str] = []
        deactivated: list[LockRecordId] = []
        try:
            deactivated = self._lock_repo.deactivate_locks_for_story(story_id)
        except LockRecordNotFoundError as exc:
            errors.append(str(exc))

        return DeactivationResult(
            deactivated_locks=deactivated,
            guards_deactivated=not errors,
            errors=errors,
        )
