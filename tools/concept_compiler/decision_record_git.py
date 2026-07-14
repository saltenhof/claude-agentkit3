"""Thin git adapter for the concept decision-record compliance core."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .decision_record_diff import changed_body_lines
from .decision_record_git_changes import GitEntry, parse_changed_entries
from .decision_record_git_validation import validate_record_blob
from .decision_record_models import ConceptDiff, ConceptFileChange
from .decision_record_records import DECISIONS_ROOT

if TYPE_CHECKING:
    from pathlib import Path


class GitAdapterError(RuntimeError):
    """Raised when the requested git range cannot be acquired."""


def load_concept_diff(repo_root: Path, base: str, head: str) -> ConceptDiff:
    """Build an injected diff value object from a git commit range."""
    changes: list[ConceptFileChange] = []
    for entry in _changed_entries(repo_root, base, head):
        path = _representative_path(entry)
        old_text = _blob(repo_root, base, entry.old_path) if entry.old_path else ""
        new_text = _blob(repo_root, head, entry.new_path) if entry.new_path else ""
        old_normative = _is_normative_path(entry.old_path)
        new_normative = _is_normative_path(entry.new_path)
        if old_normative != new_normative:
            added, removed = changed_body_lines(old_text if old_normative else "", new_text if new_normative else "")
        else:
            added, removed = changed_body_lines(old_text, new_text)
        changes.append(
            ConceptFileChange(
                path=path,
                change_kind=entry.kind,
                post_path=entry.new_path,
                added_body_lines=added,
                removed_body_lines=removed,
            )
        )
    record_output = _git(repo_root, "ls-tree", "-r", "--name-only", head, "--", DECISIONS_ROOT)
    records = frozenset(line for line in record_output.splitlines() if line)
    conform = frozenset(path for path in records if validate_record_blob(path, _blob(repo_root, head, path)))
    return ConceptDiff(changed_files=tuple(changes), record_files=records, schema_conform_record_files=conform)


def load_commit_messages(repo_root: Path, base: str, head: str) -> tuple[str, ...]:
    """Return all commit messages reachable in ``base..head``."""
    output = _git(repo_root, "log", "--format=%B%x00", f"{base}..{head}")
    return tuple(message for message in output.split("\x00") if message.strip())


def _changed_entries(repo_root: Path, base: str, head: str) -> tuple[GitEntry, ...]:
    output = _git(repo_root, "diff", "--name-status", "--find-renames", "-z", base, head, "--", "concept")
    return parse_changed_entries(output)


def _representative_path(entry: GitEntry) -> str:
    candidates = (entry.new_path, entry.old_path)
    normative = next((path for path in candidates if _is_normative_path(path)), None)
    if normative:
        return normative
    return next((path for path in candidates if path and path.startswith("concept/")), next(path for path in candidates if path))


def _is_normative_path(path: str | None) -> bool:
    return bool(path and path.startswith("concept/") and not path.startswith(DECISIONS_ROOT))


def _blob(repo_root: Path, revision: str, path: str) -> str:
    return _git(repo_root, "show", f"{revision}:{path}")


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GitAdapterError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout
