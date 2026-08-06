"""Thin Git adapter for pre-merge concept document scoping."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class GitScopeError(ValueError):
    """Raised when the pre-merge Git range cannot be read."""




def changed_concept_docs(repo_root: Path, concept_root: Path, base: str) -> frozenset[str]:
    """Return every Markdown change pre-merge review must cover.

    Three sources, unioned. ``git diff base...HEAD`` and ``git diff HEAD``
    cover what git already knows: committed, staged and unstaged changes to
    tracked documents. Neither can report a document git has never seen --
    ``--diff-filter=A`` means "added in the index", not "new on disk" -- so
    a freshly written concept document would fall out of the pre-merge
    scope entirely. ``git ls-files --others --exclude-standard`` supplies
    that remainder; ``--exclude-standard`` keeps ignored files out, so the
    result stays the set of versionable working-tree Markdown.
    """
    try:
        concept_relative = concept_root.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise GitScopeError("concept root must be inside repo root") from exc
    prefix = concept_relative.rstrip("/") + "/"
    changed: set[str] = set()
    for range_args in ((f"{base}...HEAD",), ("HEAD",)):
        stdout = _git(
            repo_root,
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            "--diff-filter=ACDMR",
            *range_args,
            "--",
            concept_relative,
        )
        changed.update(_parse_changed_paths(stdout, prefix))
    # ``--full-name`` is not decoration: ``git ls-files`` reports relative to
    # the current directory while ``git diff`` reports relative to the
    # repository root, so without it the two halves of the union would be
    # expressed in different path bases whenever ``repo_root`` is a subdirectory.
    untracked = _git(
        repo_root, "ls-files", "--full-name", "--others", "--exclude-standard", "-z", "--", concept_relative
    )
    changed.update(path[len(prefix) :] for path in untracked.split("\0") if path.startswith(prefix) and path.endswith(".md"))
    return frozenset(changed)


def _git(repo_root: Path, *args: str) -> str:
    """Run one read-only git command and return its decoded stdout.

    One call, two contracts: the concept corpus is AK3-owned and must be
    UTF-8, so a path that is not decodable is a protocol violation and fails
    closed here -- carrying it on losslessly only moves the crash into the
    JSON transport, where it arrives without a cause. stderr is diagnosis;
    it is flattened so a bad byte cannot hide the real error.
    """
    completed = subprocess.run(["git", "-C", str(repo_root), *args], check=False, capture_output=True)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise GitScopeError(detail or f"git {args[0]} exited {completed.returncode}")
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitScopeError(f"concept path is not UTF-8: {exc}") from exc


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
