"""Corpus freshness indicator (FK-13 §13.9.9).

The freshness indicator is ``corpus_revision`` (NOT mtime -- filesystem
timestamps are unreliable under git operations). The freshness gate compares the
persisted artifact revision against the current discovery revision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class Freshness:
    """Result of a freshness comparison."""

    fresh: bool
    expected_revision: str
    actual_revision: str


def read_persisted_revision(graph_artifact_path: Path) -> str | None:
    """Read the ``corpus_revision`` from a persisted ``concept_graph.json``."""
    if not graph_artifact_path.is_file():
        return None
    try:
        data = json.loads(graph_artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    revision = data.get("corpus_revision")
    return str(revision) if isinstance(revision, str) and revision else None


def check_freshness(expected_revision: str, graph_artifact_path: Path) -> Freshness:
    """Compare the expected revision against the persisted artifact.

    Hard-stop semantics (FK-13 §13.9.12): a stale/missing artifact is NOT fresh.
    """
    actual = read_persisted_revision(graph_artifact_path)
    if actual is None:
        return Freshness(fresh=False, expected_revision=expected_revision, actual_revision="")
    return Freshness(
        fresh=actual == expected_revision,
        expected_revision=expected_revision,
        actual_revision=actual,
    )


__all__ = ["Freshness", "check_freshness", "read_persisted_revision"]
