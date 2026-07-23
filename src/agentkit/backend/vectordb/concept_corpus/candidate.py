"""Candidate-corpus builder for ``validate --staged`` (FK-13 §13.9.9 Ring 2).

Builds a candidate corpus = staged files (NEW state) + unchanged files (current
working state) so validation always runs against the TOTAL post-commit state,
never file-by-file against the old rest-corpus. Pure + transport-free so the
cross-file blocking behaviour is directly testable without git.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def build_candidate_corpus(
    concepts_dir: Path,
    overlays: Mapping[str, str],
    *,
    dest: Path,
) -> Path:
    """Materialise a candidate corpus into ``dest``.

    Copies the current corpus, then OVERLAYS the staged file contents (relative
    POSIX paths -> text). Staged files that are deletions (empty overlay) are
    removed from the candidate. The result is a complete post-commit corpus.

    Args:
        concepts_dir: Current working corpus root.
        overlays: Staged file contents keyed by POSIX-relative path.
        dest: Destination directory (created if absent).

    Returns:
        The ``dest`` path holding the candidate corpus.
    """
    concepts_dir = concepts_dir.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    if concepts_dir.is_dir():
        for path in concepts_dir.rglob("*"):
            if path.is_dir():
                continue
            rel = path.relative_to(concepts_dir)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    # Apply overlays (staged new state).
    for rel_posix, content in overlays.items():
        target = dest / rel_posix
        if content == "":
            # Staged deletion: remove from candidate.
            if target.is_file():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return dest


__all__ = ["build_candidate_corpus"]
