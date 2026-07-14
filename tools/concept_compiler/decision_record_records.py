"""Decision-record filename, trailer, and frontmatter validation."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from .loader import try_load_frontmatter

DECISIONS_ROOT = "concept/_meta/decisions/"
DECISION_RECORD_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
DECISION_TRAILER_RE = re.compile(r"^Concept-Decision:[ \t]*(.*?)[ \t]*\r?$", re.MULTILINE)
FORMAT_ONLY_TRAILER_RE = re.compile(r"^Concept-Format-Only:[ \t]*(.*?)[ \t]*\r?$", re.MULTILINE)


def decision_trailers(messages: tuple[str, ...]) -> tuple[str, ...]:
    """Return all case-sensitive Concept-Decision trailer values."""
    return tuple(match.group(1) for message in messages for match in DECISION_TRAILER_RE.finditer(message))


def format_only_reasons(messages: tuple[str, ...]) -> tuple[str, ...]:
    """Return all case-sensitive Concept-Format-Only reason values."""
    return tuple(match.group(1) for message in messages for match in FORMAT_ONLY_TRAILER_RE.finditer(message))


def record_path_for_trailer(value: str) -> str:
    """Resolve a trailer value to its canonical repository-relative path."""
    filename = value if value.endswith(".md") else f"{value}.md"
    return f"{DECISIONS_ROOT}{filename}"


def is_record_path_name_valid(path: str) -> bool:
    """Return whether a path is directly under decisions and follows its schema."""
    pure = PurePosixPath(path)
    return str(pure.parent) == DECISIONS_ROOT.rstrip("/") and bool(DECISION_RECORD_NAME_RE.fullmatch(pure.name))


def validate_decision_record_file(path: Path) -> bool:
    """Validate the frozen decision-record filename and frontmatter schema."""
    frontmatter = try_load_frontmatter(path)
    if frontmatter is None or not DECISION_RECORD_NAME_RE.fullmatch(path.name):
        return False
    expected_id_prefix = f"META-DEC-{path.name[:10]}-"
    return _frontmatter_matches(frontmatter, expected_id_prefix)


def _frontmatter_matches(frontmatter: dict[str, Any], expected_id_prefix: str) -> bool:
    required_fields = {
        "concept_id", "title", "module", "cross_cutting", "status", "doc_kind",
        "authority_over", "defers_to", "supersedes", "superseded_by", "tags", "formal_scope",
    }
    required_empty_lists = ("authority_over", "defers_to", "supersedes")
    concept_id = frontmatter.get("concept_id")
    title = frontmatter.get("title")
    tags = frontmatter.get("tags")
    return (
        required_fields.issubset(frontmatter)
        and isinstance(concept_id, str)
        and concept_id.startswith(expected_id_prefix)
        and bool(re.fullmatch(r"META-DEC-\d{4}-\d{2}-\d{2}-[A-Z0-9]+(?:-[A-Z0-9]+)*", concept_id))
        and isinstance(title, str)
        and bool(title.strip())
        and frontmatter.get("module") == "meta"
        and frontmatter.get("cross_cutting") is True
        and frontmatter.get("status") == "active"
        and frontmatter.get("doc_kind") == "decision-record"
        and all(frontmatter.get(field) == [] for field in required_empty_lists)
        and frontmatter.get("superseded_by") is None
        and isinstance(tags, list)
        and all(isinstance(tag, str) for tag in tags)
        and {"meta", "decision-record"}.issubset(tags)
        and frontmatter.get("formal_scope") == "prose-only"
    )
