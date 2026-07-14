"""Thin Git adapter for pre-merge concept document scoping."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class GitScopeError(ValueError):
    """Raised when the pre-merge Git range cannot be read."""


def changed_concept_docs(repo_root: Path, concept_root: Path, base: str) -> frozenset[str]:
    """Return changed Markdown paths relative to the configured concept root."""
    try:
        concept_relative = concept_root.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise GitScopeError("concept root must be inside repo root") from exc
    command = [
        "git", "-C", str(repo_root), "diff", "--name-status", "-z", "--find-renames",
        "--diff-filter=ACDMR", f"{base}...HEAD", "--", concept_relative,
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise GitScopeError(completed.stderr.strip() or f"git diff exited {completed.returncode}")
    return _parse_changed_paths(completed.stdout, concept_relative.rstrip("/") + "/")


def _parse_changed_paths(raw: str, prefix: str) -> frozenset[str]:
    tokens = iter(raw.split("\0"))
    paths: set[str] = set()
    for status in tokens:
        if not status:
            break
        count = 2 if status.startswith(("R", "C")) else 1
        for _ in range(count):
            path = next(tokens, "")
            if path.startswith(prefix) and path.endswith(".md"):
                paths.add(path[len(prefix) :])
    return frozenset(paths)
