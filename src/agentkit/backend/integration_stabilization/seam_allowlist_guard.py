"""Seam-allowlist guard-overlay for integration-stabilization.

FK-05 §5.10/§5.12/§5.14.
Invariant: capability_overlay_is_manifest_scoped.

This guard is a PreToolUse guard overlay that blocks worker writes to paths
outside the declared ``seam_allowlist``. It is docked onto the existing
``governance/guards/`` chain (no new God-guard, no duplication).

The ``SeamAllowlistGuard`` implements the ``GovernanceGuard`` Protocol
(``agentkit.backend.governance.protocols``) so it can be registered in the guard
chain alongside ``ScopeGuard``, ``BranchGuard``, etc.

Materialization (FK-05 §5.14, concept-conform, FK-10): the seam allowlist is
materialized to ``<worktree_root>/.agent-guard/seam_allowlist.json`` (NOT
``_temp/`` as a source-of-truth) and the production guard READS it. The
materialized file is the authoritative allowlist consumed by the guard overlay.

Fail-CLOSED: a broken/unreadable seam allowlist file blocks every mutating
operation (a missing/broken IS guard must BLOCK, never silently skip).
"""

from __future__ import annotations

import json
import os
from pathlib import Path  # noqa: TC003 -- Path used in runtime path operations
from typing import TYPE_CHECKING

from agentkit.backend.governance.protocols import GuardVerdict, ViolationType

if TYPE_CHECKING:
    from agentkit.backend.integration_stabilization.models import IntegrationScopeManifest
    from agentkit.backend.telemetry.emitters import EventEmitter

__all__ = [
    "SEAM_ALLOWLIST_FILE",
    "FailClosedSeamGuard",
    "SeamAllowlistGuard",
    "materialize_seam_allowlist",
    "materialize_seam_allowlist_file",
    "read_seam_allowlist_file",
]

#: Concept-conform materialization path (relative to a worktree root, FK-05 §5.14).
SEAM_ALLOWLIST_FILE: str = ".agent-guard/seam_allowlist.json"


def materialize_seam_allowlist(
    manifest: IntegrationScopeManifest,
) -> tuple[str, ...]:
    """Materialize the seam allowlist from an approved manifest (in-memory).

    Returns the union of ``target_seams`` and ``allowed_repos_paths`` as
    a tuple of normpath'd entries. This is the canonical, manifest-derived
    allowlist used by the guard overlay (FK-05 §5.14).

    Args:
        manifest: The approved integration scope manifest.

    Returns:
        A tuple of normalized allowed path prefixes.
    """
    combined = (*manifest.target_seams, *manifest.allowed_repos_paths)
    return tuple(os.path.normpath(p) for p in combined)


def materialize_seam_allowlist_file(
    manifest: IntegrationScopeManifest,
    worktree_root: Path,
) -> Path:
    """Write the seam allowlist to ``<worktree_root>/.agent-guard/seam_allowlist.json``.

    Concept-conform materialization (FK-05 §5.14, FK-10): the materialized file is
    the authoritative allowlist the production guard reads. Returns the written
    path so callers can verify materialization.

    Args:
        manifest: The approved integration scope manifest.
        worktree_root: The bound worktree root that owns the ``.agent-guard`` dir.

    Returns:
        The path of the written allowlist file.
    """
    allowlist = materialize_seam_allowlist(manifest)
    target = worktree_root / SEAM_ALLOWLIST_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"seam_allowlist": list(allowlist)}, indent=2),
        encoding="utf-8",
    )
    return target


def read_seam_allowlist_file(worktree_root: Path) -> tuple[str, ...] | None:
    """Read the materialized seam allowlist from a worktree root.

    Args:
        worktree_root: The worktree root that owns the ``.agent-guard`` dir.

    Returns:
        The persisted allowlist tuple, or ``None`` when the file is absent or
        unreadable (the caller fail-closes on ``None``).
    """
    path = worktree_root / SEAM_ALLOWLIST_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = data.get("seam_allowlist") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return None
    return tuple(os.path.normpath(str(p)) for p in raw)


class SeamAllowlistGuard:
    """PreToolUse guard overlay that blocks writes outside the seam allowlist.

    Docked onto the existing ``governance/guards/`` chain
    (invariant: capability_overlay_is_manifest_scoped — any widened write
    capability is limited to the approved seam allowlist and never becomes
    a global guard relaxation).

    Only inspects ``file_write`` and ``file_edit`` operations; all other
    operations are allowed unconditionally.

    On a BLOCK the guard emits the ``undeclared_surface_detected`` telemetry
    event through the injected emitter (FK-05 §5.14, AC11) at the guard boundary.

    Args:
        seam_allowlist: Tuple of allowed path prefixes (normpath'd). Derived
            from an approved manifest via :func:`materialize_seam_allowlist` or
            read from the materialized file via :func:`read_seam_allowlist_file`.
        emitter: Optional telemetry emitter; the ``undeclared_surface_detected``
            event is emitted on a BLOCK (AC11). ``None`` => no emission.
        story_id: Story id for the emitted event (required when emitter is set).
        project_key: Project key for the emitted event.
        run_id: Run id for the emitted event.
    """

    def __init__(
        self,
        seam_allowlist: tuple[str, ...],
        *,
        emitter: EventEmitter | None = None,
        story_id: str = "",
        project_key: str = "",
        run_id: str = "",
    ) -> None:
        self._allowlist: tuple[str, ...] = seam_allowlist
        self._emitter = emitter
        self._story_id = story_id
        self._project_key = project_key
        self._run_id = run_id

    @property
    def name(self) -> str:
        """Short identifier for this guard."""
        return "seam_allowlist_guard"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        """Block writes outside the manifest-declared seam allowlist.

        Only inspects ``file_write`` and ``file_edit`` operations.
        All other operations are allowed unconditionally.

        Args:
            operation: The operation type being attempted.
            context: Must contain ``"file_path"`` for write/edit ops.

        Returns:
            ``ALLOW`` when the target is within the seam allowlist,
            ``BLOCK`` with ``SCOPE_VIOLATION`` otherwise.
        """
        if operation not in ("file_write", "file_edit"):
            return GuardVerdict.allow(self.name)

        file_path = os.path.normpath(str(context.get("file_path", "")))

        for allowed in self._allowlist:
            if file_path == allowed or file_path.startswith(allowed + os.sep):
                return GuardVerdict.allow(self.name)

        self._emit_undeclared_surface(file_path)
        return GuardVerdict.block(
            self.name,
            ViolationType.SCOPE_VIOLATION,
            f"Write outside seam allowlist: {file_path!r}. "
            "The path is not within any declared integration seam or "
            "allowed repo path (FK-05 §5.12, "
            "invariant: capability_overlay_is_manifest_scoped).",
            detail={
                "file_path": file_path,
                "seam_allowlist": list(self._allowlist),
            },
        )

    def _emit_undeclared_surface(self, file_path: str) -> None:
        """Emit ``undeclared_surface_detected`` at the guard boundary (AC11)."""
        if self._emitter is None or not self._story_id:
            return
        from agentkit.backend.integration_stabilization.events import (
            emit_undeclared_surface_detected,
        )

        self._emitter.emit(
            emit_undeclared_surface_detected(
                story_id=self._story_id,
                project_key=self._project_key,
                run_id=self._run_id,
                surface_path=file_path,
            )
        )


class FailClosedSeamGuard:
    """Fail-CLOSED stand-in guard for a broken/missing IS seam guard (ERROR D).

    A missing or broken integration-stabilization guard must BLOCK productive
    work, never silently skip (the AC7 fail-open bug). When the production
    ``SeamAllowlistGuard`` cannot be constructed for an IS story (manifest /
    approval absent or unreadable, allowlist file unreadable), this guard is
    installed in its place and blocks every mutating operation fail-closed.

    Args:
        reason: Human-readable reason the production guard could not be built.
    """

    def __init__(self, reason: str) -> None:
        self._reason = reason

    @property
    def name(self) -> str:
        """Short identifier for this guard."""
        return "seam_allowlist_guard_fail_closed"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        """Block every mutating operation fail-closed (FK-05 §5.12).

        Args:
            operation: The operation type being attempted.
            context: Operation context (unused).

        Returns:
            ``ALLOW`` for non-mutating ops; ``BLOCK`` for mutations.
        """
        del context
        if operation not in ("file_write", "file_edit", "bash_command"):
            return GuardVerdict.allow(self.name)
        return GuardVerdict.block(
            self.name,
            ViolationType.SCOPE_VIOLATION,
            "Integration-stabilization seam guard could not be constructed; "
            f"productive work is fail-closed blocked ({self._reason}). A missing "
            "or broken IS guard must BLOCK, never silently skip (FK-05 §5.12).",
            detail={"reason": self._reason},
        )
