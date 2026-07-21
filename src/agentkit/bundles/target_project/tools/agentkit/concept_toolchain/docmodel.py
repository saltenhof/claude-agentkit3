"""Concept-document scanner and Markdown helpers for the concept toolchain."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .smy import SmyError, parse_smy

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_ATX_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
_SETEXT_UNDERLINE_RE = re.compile(r"^(=+|-+)\s*$")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_EXPLICIT_ANCHOR_RE = re.compile(r"\{#(?P<anchor>[A-Za-z0-9_.:-]+)\}|<a\s+[^>]*id=[\"'](?P<html>[^\"']+)[\"']", re.IGNORECASE)


@dataclass(frozen=True)
class ConceptDocument:
    """One scanned Markdown document below a configured concept root."""

    layer: str
    path: Path
    rel_path: str
    text: str
    frontmatter: dict[str, object] | None
    frontmatter_error: str | None
    frontmatter_error_line: int
    frontmatter_end: int

    @property
    def concept_id(self) -> str:
        """Return the frontmatter ``concept_id`` when it is a string."""
        if self.frontmatter is None:
            return ""
        value = self.frontmatter.get("concept_id")
        return value if isinstance(value, str) else ""


def scan_documents(project_root: Path, concept_roots: Mapping[str, str]) -> tuple[ConceptDocument, ...]:
    """Scan all Markdown documents below the configured concept roots.

    Missing root directories are skipped here; checks that depend on a
    specific root verify its existence themselves (fail-closed).
    """
    documents: list[ConceptDocument] = []
    for layer, relative_root in sorted(concept_roots.items()):
        root = project_root / relative_root
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            documents.append(load_document(project_root, layer, path))
    return tuple(documents)


def load_document(project_root: Path, layer: str, path: Path) -> ConceptDocument:
    """Load one Markdown file and parse its frontmatter via SMY."""
    text = path.read_text(encoding="utf-8")
    payload, end_line = split_frontmatter(text)
    frontmatter: dict[str, object] | None = None
    error: str | None = None
    error_line = 0
    if payload is not None:
        try:
            frontmatter = parse_smy(payload)
        except SmyError as exc:
            error = exc.message
            error_line = exc.line + 1
    return ConceptDocument(
        layer=layer,
        path=path,
        rel_path=path.relative_to(project_root).as_posix(),
        text=text,
        frontmatter=frontmatter,
        frontmatter_error=error,
        frontmatter_error_line=error_line,
        frontmatter_end=end_line,
    )


def split_frontmatter(text: str) -> tuple[str | None, int]:
    """Split off the frontmatter payload.

    Returns:
        A tuple of the payload between the ``---`` markers (or ``None``)
        and the 1-based line number of the closing marker (0 if absent).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, 0
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return "\n".join(lines[1:index - 1]), index
    return None, 0


def body_lines(text: str) -> tuple[tuple[int, str], ...]:
    """Return body lines outside frontmatter and fenced code blocks."""
    lines = text.splitlines()
    _, frontmatter_end = split_frontmatter(text)
    output: list[tuple[int, str]] = []
    in_fence = False
    fence_marker = ""
    for number, line in enumerate(lines, start=1):
        if number <= frontmatter_end:
            continue
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)[0]
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence = False
            continue
        if in_fence:
            continue
        output.append((number, line))
    return tuple(output)


@dataclass(frozen=True)
class Heading:
    """One ATX or Setext heading with its 1-based line number and level."""

    line: int
    level: int
    title: str


def heading_outline(text: str) -> tuple[Heading, ...]:
    """Extract ATX and Setext headings with levels, skipping fences.

    Setext ``=`` underlines yield level 1, ``-`` underlines level 2. The
    title of a Setext heading is the raw text line above the underline.
    """
    headings: list[Heading] = []
    lines = body_lines(text)
    previous: tuple[int, str] | None = None
    for number, line in lines:
        atx = _ATX_HEADING_RE.match(line)
        if atx:
            headings.append(Heading(line=number, level=len(atx.group("hashes")), title=atx.group("title").strip()))
            previous = None
            continue
        underline = _SETEXT_UNDERLINE_RE.match(line)
        if (
            previous is not None
            and underline
            and previous[1].strip()
            and not previous[1].lstrip().startswith(("-", "*", "+", ">"))
        ):
            level = 1 if underline.group(1).startswith("=") else 2
            headings.append(Heading(line=previous[0], level=level, title=previous[1]))
            previous = None
            continue
        previous = (number, line)
    return tuple(headings)


def extract_headings(text: str) -> tuple[tuple[int, str], ...]:
    """Extract ATX and Setext headings as ``(line, title)``, skipping fences."""
    return tuple((heading.line, heading.title) for heading in heading_outline(text))


def github_slug(title: str) -> str:
    """Build a GitHub-style anchor slug for one heading title."""
    lowered = title.strip().lower()
    kept = [char for char in lowered if char.isalnum() or char in (" ", "-", "_")]
    return "".join(kept).replace(" ", "-")


def anchor_slugs(text: str) -> frozenset[str]:
    """Return all resolvable anchors of a document.

    Includes GitHub-style heading slugs (with ``-N`` de-duplication) and
    explicit ``{#anchor}`` / ``<a id="anchor">`` anchors.
    """
    slugs: set[str] = set()
    seen: dict[str, int] = {}
    for _, title in extract_headings(text):
        slug = github_slug(title)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        slugs.add(slug if count == 0 else f"{slug}-{count}")
    for _, line in body_lines(text):
        for match in _EXPLICIT_ANCHOR_RE.finditer(line):
            explicit = match.group("anchor") or match.group("html")
            if explicit:
                slugs.add(explicit)
    return frozenset(slugs)


def file_digest_sha256(path: Path) -> str:
    """Return the lowercase-hex SHA-256 digest of a file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
