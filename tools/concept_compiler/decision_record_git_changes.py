"""Parsing for null-delimited git name-status output."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GitEntry:
    """One normalized A/M/D/R git change entry."""

    kind: str
    old_path: str | None
    new_path: str | None


def parse_changed_entries(output: str) -> tuple[GitEntry, ...]:
    """Parse ``git diff --name-status -z`` output deterministically."""
    tokens = output.split("\x00")
    entries: list[GitEntry] = []
    index = 0
    while index < len(tokens) and tokens[index]:
        status = tokens[index]
        index += 1
        if status.startswith("R"):
            entries.append(GitEntry("R", tokens[index], tokens[index + 1]))
            index += 2
        else:
            path = tokens[index]
            index += 1
            entries.append(GitEntry(status[0], path if status[0] != "A" else None, path if status[0] != "D" else None))
    return tuple(entries)
