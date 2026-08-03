"""Thin Git adapter for pre-merge concept document scoping."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class GitScopeError(ValueError):
    """Raised when the pre-merge Git range cannot be read."""




def changed_concept_docs(repo_root: Path, concept_root: Path, base: str) -> frozenset[str]:
    """Return committed and working-tree Markdown changes for pre-merge review."""
    try:
        concept_relative = concept_root.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise GitScopeError("concept root must be inside repo root") from exc
    prefix = concept_relative.rstrip("/") + "/"
    changed: set[str] = set()
    for range_args in ((f"{base}...HEAD",), ("HEAD",)):
        command = [
            "git",
            "-C",
            str(repo_root),
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            "--diff-filter=ACDMR",
            *range_args,
            "--",
            concept_relative,
        ]
        # One call, two contracts: the concept corpus is AK3-owned and must be
        # UTF-8, so a path that is not decodable is a protocol violation and
        # fails closed here -- carrying it on losslessly only moves the crash
        # into the JSON transport, where it arrives without a cause. stderr is
        # diagnosis; it is flattened so a bad byte cannot hide the real error.
        completed = subprocess.run(command, check=False, capture_output=True)
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise GitScopeError(detail or f"git diff exited {completed.returncode}")
        try:
            stdout = completed.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitScopeError(f"concept path is not UTF-8: {exc}") from exc
        changed.update(_parse_changed_paths(stdout, prefix))
    return frozenset(changed)


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
