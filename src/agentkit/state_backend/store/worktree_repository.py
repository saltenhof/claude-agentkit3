"""StateBackendWorktreeRepository — WorktreeRepository implementation.

Implements ``agentkit.governance.repository.WorktreeRepository`` by loading
the ``StoryContext`` from the state backend and extracting the
``worktree_map`` field.  This keeps
``agentkit.governance.runner.Governance`` decoupled from the state backend
(Architecture Conformance Fix E4, AG3-031 Pass-4).

Source: FK-30 §30.6.0 + FK-22 §22.7 — worktree paths come from the
canonical StoryContext stored in the state backend.
"""

from __future__ import annotations

from pathlib import Path

from agentkit.installer.paths import story_dir as resolve_story_dir
from agentkit.state_backend.store import facade


class StateBackendWorktreeRepository:
    """Derive worktree paths from StoryContext stored in the state backend.

    Reads ``StoryContext.worktree_map`` to obtain all worktree root paths
    for a given story.  The context is loaded from the story-scoped
    state-backend record (SQLite / Postgres, depending on active backend).

    This class intentionally does not inherit from the Protocol class — it
    satisfies the structural (duck-typed) Protocol without formal inheritance,
    which avoids an import of ``agentkit.governance.repository`` from this
    module (direction: state_backend -> governance would be a layering
    violation).

    Args:
        project_root: Root directory used to resolve the story directory via
            ``agentkit.installer.paths.story_dir``.  When ``None``, falls
            back to ``Path.cwd()``.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root or Path.cwd()

    def list_worktree_paths(self, story_id: str) -> list[Path]:
        """Return all worktree root paths for ``story_id``.

        Loads the ``StoryContext`` from the state backend and extracts the
        ``worktree_map`` values.  Returns an empty list when the context is
        absent or has no worktrees.

        Args:
            story_id: Canonical story identifier.

        Returns:
            List of worktree root ``Path`` objects (values of
            ``StoryContext.worktree_map``).  Empty list when no worktrees
            are registered.
        """
        s_dir = resolve_story_dir(self._project_root, story_id)
        ctx = facade.load_story_context(s_dir)
        if ctx is None:
            return []
        return list(ctx.worktree_map.values())


__all__ = ["StateBackendWorktreeRepository"]
