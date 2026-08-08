"""Core-side knowledge of the project directory layout (AG3-239).

Both machines need to know where a story's working directory lives: the edge
materialises it, the core reads and writes artefacts under it. The layout is
therefore duplicated on purpose, exactly as FK-10 / AG3-209 prescribe for
developer-machine path helpers -- the edge copy is
``agentkit.backend.installer.paths``.

**Why duplication rather than a shared module.** A path helper is not ``/v1``
vocabulary, so it has no home in the contract package (which is I/O-free
request/response data). And a shared module would have to live on one side,
making the other side import across the distribution boundary for a string
constant -- paying a boundary crossing, and after the wheel split an impossible
import, to learn the word "stories".

Before AG3-239 the CORE setup-preflight gate called
``installer.paths.story_dir`` -- a core module reaching into an edge module for
a constant. That is the crossing this leaf removes.

The module is a ``domain_core_foundation`` leaf: no I/O, no AK3 imports, safe to
import from anywhere in the core.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: Directory holding one working directory per story, relative to the project
#: root. Kept byte-identical with ``installer.paths.STORIES_DIR``; the contract
#: test ``tests/contract/governance/test_distribution_boundary.py`` pins the two
#: against each other so the copies cannot drift apart silently.
STORIES_DIR: str = "stories"


def story_dir(project_root: Path, story_id: str) -> Path:
    """Return the working directory of one story.

    Args:
        project_root: Root of the project.
        story_id: Canonical story identifier.

    Returns:
        ``<project_root>/stories/<story_id>``.
    """
    return project_root / STORIES_DIR / story_id


__all__ = ["STORIES_DIR", "story_dir"]
