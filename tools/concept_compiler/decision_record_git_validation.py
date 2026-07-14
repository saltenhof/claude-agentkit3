"""Post-tree decision-record validation for the thin git adapter."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from .decision_record_records import validate_decision_record_file


def validate_record_blob(path: str, content: str) -> bool:
    """Validate one git blob through the canonical frontmatter parser."""
    with TemporaryDirectory(prefix="concept-decision-record-") as directory:
        candidate = Path(directory) / PurePosixPath(path).name
        candidate.write_text(content, encoding="utf-8")
        return validate_decision_record_file(candidate)
