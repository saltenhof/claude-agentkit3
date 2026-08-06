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

#: ``concept_id`` grammar of a decision record (konzept-konsistenz-governance.md W4).
DECISION_RECORD_ID_RE = re.compile(r"META-DEC-\d{4}-\d{2}-\d{2}-[A-Z0-9]+(?:-[A-Z0-9]+)*")
#: Target grammar of a ``defers_to`` edge: an authority-holding corpus document —
#: a technical/domain concept or a META policy document. Decision records hold no
#: authority themselves (``authority_over: []``) and are therefore not targets.
AUTHORITY_TARGET_RE = re.compile(r"(?:FK|DK)-\d{2}|META-(?!DEC-)[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*")
#: Lifecycle states a decision record may carry; subset of the corpus enum of
#: FK-13 §13.9.6 (``active | draft | archived``). A record persists a decision
#: that has already been taken, so ``draft`` is not a record state.
RECORD_STATUS_VALUES = frozenset({"active", "archived"})


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
    return (
        required_fields.issubset(frontmatter)
        and _identity_matches(frontmatter, expected_id_prefix)
        and _tags_match(frontmatter.get("tags"))
        and frontmatter.get("authority_over") == []
        and _edges_match(frontmatter.get("defers_to"), AUTHORITY_TARGET_RE)
        and _edges_match(frontmatter.get("supersedes"), DECISION_RECORD_ID_RE)
        and _supersession_state_matches(frontmatter)
    )


def _identity_matches(frontmatter: dict[str, Any], expected_id_prefix: str) -> bool:
    """Check the frozen identity fields that make a file a decision record."""
    concept_id = frontmatter.get("concept_id")
    title = frontmatter.get("title")
    return (
        isinstance(concept_id, str)
        and concept_id.startswith(expected_id_prefix)
        and bool(DECISION_RECORD_ID_RE.fullmatch(concept_id))
        and isinstance(title, str)
        and bool(title.strip())
        and frontmatter.get("module") == "meta"
        and frontmatter.get("cross_cutting") is True
        and frontmatter.get("doc_kind") == "decision-record"
        and frontmatter.get("formal_scope") == "prose-only"
    )


def _tags_match(tags: Any) -> bool:
    return (
        isinstance(tags, list)
        and all(isinstance(tag, str) for tag in tags)
        and {"meta", "decision-record"}.issubset(tags)
    )


def _edges_match(edges: Any, target_pattern: re.Pattern[str]) -> bool:
    """Check a frontmatter edge list against the corpus edge form (FK-13 §13.9.6).

    An edge is either a bare document id or a mapping with a ``target`` plus the
    optional qualifiers ``scope`` and ``reason``. An empty list is valid; the
    edges are what binds a record's prose to foreign authority
    (konzept-konsistenz-governance.md §3 P2), so emptiness is never required.
    """
    return isinstance(edges, list) and all(_edge_matches(edge, target_pattern) for edge in edges)


def _edge_matches(edge: Any, target_pattern: re.Pattern[str]) -> bool:
    if isinstance(edge, str):
        return bool(target_pattern.fullmatch(edge))
    if not isinstance(edge, dict):
        return False
    target = edge.get("target")
    qualifiers = (edge.get("scope"), edge.get("reason"))
    return (
        isinstance(target, str)
        and bool(target_pattern.fullmatch(target))
        and all(value is None or (isinstance(value, str) and bool(value.strip())) for value in qualifiers)
    )


def _supersession_state_matches(frontmatter: dict[str, Any]) -> bool:
    """Check ``status``/``superseded_by`` coherence.

    A record that has been replaced is no longer in force, so a set
    ``superseded_by`` requires ``status: archived``; only another decision
    record can replace a decision record.
    """
    status = frontmatter.get("status")
    superseded_by = frontmatter.get("superseded_by")
    if status not in RECORD_STATUS_VALUES:
        return False
    if superseded_by is None or superseded_by == "":
        return True
    return (
        isinstance(superseded_by, str)
        and bool(DECISION_RECORD_ID_RE.fullmatch(superseded_by))
        and status == "archived"
    )
