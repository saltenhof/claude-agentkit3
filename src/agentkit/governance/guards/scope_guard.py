"""Scope guard -- prevents writes outside story scope during execution.

Only active during story execution.  Blocks ``file_write`` and
``file_edit`` operations whose target path falls outside the set of
allowed directories.
"""

from __future__ import annotations

import os

from agentkit.governance.protocols import GuardVerdict, ViolationType


class ScopeGuard:
    """Blocks file writes outside the story's worktree / story-dir.

    During story execution every write must target a path that is a
    descendant of one of the configured ``allowed_paths``.  When no
    paths are configured, every write is blocked.

    This guard is only meaningful during story execution; callers
    should register it with the appropriate allowed paths for the
    current story.
    """

    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        # Normalise once at construction time for fast comparisons.
        self._allowed: tuple[str, ...] = tuple(
            os.path.normpath(p) for p in (allowed_paths or [])
        )

    @property
    def name(self) -> str:
        """Short identifier for this guard."""
        return "scope_guard"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        """Block writes outside allowed scope.

        Only inspects ``file_write`` and ``file_edit`` operations; all
        others are allowed unconditionally.

        Args:
            operation: The operation type being attempted.
            context: Must contain ``"file_path"`` for write/edit ops.

        Returns:
            ``ALLOW`` when the target is inside an allowed path,
            ``BLOCK`` otherwise.
        """
        if operation not in ("file_write", "file_edit"):
            return GuardVerdict.allow(self.name)

        file_path = os.path.normpath(str(context.get("file_path", "")))

        for allowed in self._allowed:
            # Use os.path for reliable prefix comparison.
            if file_path == allowed or file_path.startswith(allowed + os.sep):
                return GuardVerdict.allow(self.name)

        return GuardVerdict.block(
            self.name,
            ViolationType.SCOPE_VIOLATION,
            f"Write outside allowed scope: {file_path!r}",
            detail={
                "file_path": file_path,
                "allowed_paths": list(self._allowed),
            },
        )
