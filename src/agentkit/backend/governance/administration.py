"""Core-side administration of governance state (AG3-239 M2).

This module owns the governance operation that is neither hook-process work nor
edge orchestration:

* ``deactivate_locks`` -- deactivate a story's lock records and clean up the
  lock exports (FK-30 section 30.6.0). Driven by ClosureSequence (FK-29
  section 29.5), story-exit, story-split and story-reset.

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

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.governance.errors import LockRecordNotFoundError
from agentkit.backend.governance.locks import DeactivationResult, LockRecordId

if TYPE_CHECKING:
    from agentkit.backend.state_backend.store.lock_record_repository import (
        LockRecordRepository,
    )


class Governance:
    """Core-side lock deactivation for a finished story (FK-30 §30.6.0).

    ``deactivate_locks`` deactivates a story's lock records and cleans up the
    lock exports. It is called by ClosureSequence (FK-29 §29.5) and by the
    story-exit, story-split and story-reset services.

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

    AG3-145 sub-step D (FK-10 §10.2.4a): the ``worktree_repo`` dependency was
    removed. ``deactivate_locks`` no longer writes physically into worktrees; the
    dev-local ``.agent-guard`` projection (lock-export removal + mode marker) runs
    entirely over the edge bundle-publication + ``tombstone_worktree_roots``
    mechanism (``harness_client.projectedge.client``). The backend keeps no
    worktree path authority.
    """

    def __init__(self, *, lock_repo: LockRecordRepository) -> None:
        self._lock_repo = lock_repo

    # ------------------------------------------------------------------
    # deactivate_locks (FK-30 §30.6.0)
    # ------------------------------------------------------------------

    def deactivate_locks(self, story_id: str) -> DeactivationResult:
        """Deactivate all lock records for a story and remove lock exports.

        Called by ClosureSequence (FK-29 §29.5) after successful postflight.
        After this call, guards that depend on an active lock record
        (branch_guard, orchestrator_guard, qa_agent_guard) become inactive.

        Idempotent for already-deactivated stories (all locks INACTIVE):
        returns empty deactivated_locks without errors (but the story_id
        must be known — completely unknown story_ids raise LockRecordNotFoundError,
        surfaced in errors[]).

        Fail-closed (Fix E6, AG3-031 Pass-3):
        - Unknown story_id (no lock records at all) → LockRecordNotFoundError
          surfaced in errors[0].
        - IO errors on lock-export deletion → collected in ``errors[]``.
        - DB failures → raised immediately (not silently swallowed).

        Args:
            story_id: Canonical story identifier.

        Returns:
            ``DeactivationResult`` with ``deactivated_locks``,
            ``removed_edge_bundles``, ``removed_lock_exports``,
            ``restored_to_ai_augmented``, ``errors``.

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

        # Fix E4: purge the correct lock-export paths (FK-30 §30.6.0 + FK-29 §29.5)
        removed_bundles, bundle_errors = self._purge_edge_bundles(story_id)
        errors.extend(bundle_errors)

        removed_exports, export_errors = self._purge_qa_lock_export(story_id)
        errors.extend(export_errors)

        # AG3-145 sub-step D (FK-10 §10.2.4a): the mode restoration no longer
        # touches worktrees (see ``_restore_ai_augmented_mode``). The dev-local
        # ``.agent-guard/lock.json`` removal is carried by the edge tombstone
        # projection, not the backend.
        restored, restore_errors = self._restore_ai_augmented_mode(story_id)
        errors.extend(restore_errors)

        return DeactivationResult(
            deactivated_locks=deactivated,
            removed_edge_bundles=removed_bundles,
            removed_lock_exports=removed_exports,
            restored_to_ai_augmented=restored,
            errors=errors,
        )

    def _purge_edge_bundles(
        self, story_id: str
    ) -> tuple[list[Path], list[str]]:
        """Remove legacy edge-bundle file for ``story_id``.

        Compatibility path: ``_temp/governance/{story_id}/edge-bundle.json``.
        Missing files are silently skipped (idempotent). IO errors collected.

        Args:
            story_id: Canonical story identifier.

        Returns:
            Tuple of (removed_paths, error_messages).
        """
        removed: list[Path] = []
        errors: list[str] = []

        candidate = Path("_temp") / "governance" / story_id / "edge-bundle.json"
        if candidate.exists():
            try:
                candidate.unlink()
                removed.append(candidate)
            except OSError as exc:
                errors.append(
                    f"Failed to remove edge bundle {candidate}: {exc}"
                )

        return removed, errors

    def _purge_qa_lock_export(
        self, story_id: str
    ) -> tuple[list[Path], list[str]]:
        """Remove QA-lock export file for ``story_id`` (FK-30 §30.6.0 + FK-29 §29.5).

        Removes ``_temp/governance/locks/{story_id}/qa-lock.json``.
        Missing files are silently skipped (idempotent). IO errors collected.

        Args:
            story_id: Canonical story identifier.

        Returns:
            Tuple of (removed_paths, error_messages).
        """
        removed: list[Path] = []
        errors: list[str] = []

        qa_lock_path = (
            Path("_temp") / "governance" / "locks" / story_id / "qa-lock.json"
        )
        if qa_lock_path.exists():
            try:
                qa_lock_path.unlink()
                removed.append(qa_lock_path)
            except OSError as exc:
                errors.append(
                    f"Failed to remove qa-lock export {qa_lock_path}: {exc}"
                )

        return removed, errors

    def _restore_ai_augmented_mode(
        self, story_id: str
    ) -> tuple[bool, list[str]]:
        """Write the ``ai_augmented`` mode tombstone for the story (FK-30 §30.6.0 Z.683).

        AG3-145 sub-step D (FK-10 §10.2.4a): the governance deactivation no
        longer writes PHYSICALLY into worktrees. The former per-worktree
        ``.agent-guard/lock.json`` removal and ``.agent-guard/mode.json`` write
        are gone from the backend -- the dev-local ``.agent-guard`` projection
        runs entirely over the edge bundle-publication + serverside
        ``tombstone_worktree_roots`` mechanism
        (``harness_client.projectedge.client``): on lock deactivation the
        control-plane emits an edge bundle whose ``tombstone_worktree_roots``
        drive the edge to delete each worktree's ``.agent-guard/lock.json``.

        Only the backend-local legacy ``_temp/governance/locks/{story_id}/
        mode.json`` tombstone (existing non-worktree consumers) is written here;
        it is NOT a worktree write. Idempotent: skipped when the dir is absent.

        Args:
            story_id: Canonical story identifier.

        Returns:
            Tuple of (restored, errors) where ``restored`` is True when the
            legacy mode marker was written, and ``errors`` is a list of non-fatal
            IO error messages.
        """
        import json

        mode_payload = json.dumps(
            {"operating_mode": "ai_augmented", "story_id": story_id}
        )
        any_written = False
        errors: list[str] = []

        # Legacy backend-local tombstone (non-worktree consumers, backward compat).
        mode_dir = Path("_temp") / "governance" / "locks" / story_id
        if mode_dir.exists():
            legacy_file = mode_dir / "mode.json"
            try:
                legacy_file.write_text(mode_payload, encoding="utf-8")
                any_written = True
            except OSError as exc:
                errors.append(
                    f"failed to write legacy mode.json at {legacy_file}: {exc}"
                )

        return any_written, errors
