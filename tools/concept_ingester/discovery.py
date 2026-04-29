"""Walks the concept corpus and turns it into typed, hashable chunks."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

LAYER_DOMAIN = "domain"
LAYER_FORMAL = "formal"
LAYER_TECHNICAL = "technical"

_LAYER_BY_DIR: dict[str, str] = {
    "domain-design": LAYER_DOMAIN,
    "formal-spec": LAYER_FORMAL,
    "technical-design": LAYER_TECHNICAL,
}

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_H2_RE = re.compile(r"^##\s+(?P<heading>.+?)\s*$", re.MULTILINE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")

_CHUNK_NAMESPACE = uuid.UUID("4f3a07f6-9b6c-5e9b-8c5c-2a1d2b3c4d5e")


@dataclass(frozen=True)
class ConceptChunk:
    """A single retrievable unit of concept knowledge."""

    chunk_id: str
    layer: str
    doc_id: str
    title: str
    module: str
    tags: tuple[str, ...]
    rel_path: str
    section_anchor: str
    heading: str
    ordering: int
    content: str
    content_hash: str
    file_mtime: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _DocumentFrame:
    path: Path
    rel_path: str
    layer: str
    frontmatter: dict[str, Any]
    body: str
    mtime: str


def discover_chunks(concept_root: Path, max_chars: int) -> list[ConceptChunk]:
    """Discover all concept chunks beneath ``concept_root``."""
    chunks: list[ConceptChunk] = []
    for frame in _iter_documents(concept_root):
        chunks.extend(_chunk_document(frame, max_chars=max_chars))
    return chunks


def _iter_documents(concept_root: Path) -> Iterator[_DocumentFrame]:
    if not concept_root.is_dir():
        raise FileNotFoundError(f"concept root does not exist: {concept_root}")
    for path in sorted(concept_root.rglob("*.md")):
        rel = path.relative_to(concept_root).as_posix()
        layer = _layer_for(rel)
        if layer is None:
            continue
        text = path.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(text)
        mtime = (
            datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        yield _DocumentFrame(
            path=path,
            rel_path=rel,
            layer=layer,
            frontmatter=frontmatter,
            body=body,
            mtime=mtime,
        )


def _layer_for(rel_path: str) -> str | None:
    head = rel_path.split("/", 1)[0]
    return _LAYER_BY_DIR.get(head)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}, text
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text[match.end() :]
    if not isinstance(loaded, dict):
        return {}, text[match.end() :]
    return loaded, text[match.end() :]


def _chunk_document(frame: _DocumentFrame, max_chars: int) -> list[ConceptChunk]:
    fm = frame.frontmatter
    doc_id = _doc_id(fm, frame.rel_path)
    title = _string(fm.get("title")) or _fallback_title(frame.rel_path)
    module = _string(fm.get("module")) or _string(fm.get("context")) or ""
    tags = _string_list(fm.get("tags"))
    extra = _extra_fields(fm)

    sections = _split_into_sections(frame.body)
    chunks: list[ConceptChunk] = []
    for ordering, (heading, content) in enumerate(sections):
        for sub_ordering, sub_text in enumerate(_subsplit(content, max_chars)):
            anchor = _section_anchor(heading, ordering, sub_ordering)
            content_hash = hashlib.sha256(sub_text.encode("utf-8")).hexdigest()
            chunk_id = str(uuid.uuid5(_CHUNK_NAMESPACE, f"{frame.rel_path}#{anchor}"))
            chunks.append(
                ConceptChunk(
                    chunk_id=chunk_id,
                    layer=frame.layer,
                    doc_id=doc_id,
                    title=title,
                    module=module,
                    tags=tags,
                    rel_path=frame.rel_path,
                    section_anchor=anchor,
                    heading=heading,
                    ordering=ordering * 1000 + sub_ordering,
                    content=sub_text,
                    content_hash=content_hash,
                    file_mtime=frame.mtime,
                    extra=extra,
                )
            )
    return chunks


def _split_into_sections(body: str) -> list[tuple[str, str]]:
    body = body.strip("\n")
    if not body:
        return []
    matches = list(_H2_RE.finditer(body))
    if not matches:
        return [("(document)", body.strip())]
    sections: list[tuple[str, str]] = []
    intro = body[: matches[0].start()].strip()
    if intro:
        sections.append(("(intro)", intro))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        heading = m.group("heading").strip()
        content = body[m.end() : end].strip()
        if not content:
            continue
        sections.append((heading, f"## {heading}\n\n{content}"))
    return sections


def _subsplit(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    paragraphs = text.split("\n\n")
    buf: list[str] = []
    size = 0
    for para in paragraphs:
        para_size = len(para) + 2
        if buf and size + para_size > max_chars:
            parts.append("\n\n".join(buf))
            buf = [para]
            size = para_size
        else:
            buf.append(para)
            size += para_size
    if buf:
        parts.append("\n\n".join(buf))
    return parts


def _section_anchor(heading: str, ordering: int, sub_ordering: int) -> str:
    base = _SLUG_RE.sub("-", heading.lower()).strip("-") or "section"
    suffix = f"-{ordering:03d}"
    if sub_ordering > 0:
        suffix += f"-{sub_ordering:02d}"
    return base + suffix


def _doc_id(frontmatter: dict[str, Any], rel_path: str) -> str:
    for key in ("concept_id", "id"):
        value = _string(frontmatter.get(key))
        if value:
            return value
    return rel_path


def _fallback_title(rel_path: str) -> str:
    name = rel_path.rsplit("/", 1)[-1]
    return name.removesuffix(".md").replace("_", " ").replace("-", " ").strip()


def _string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _string_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return ()


def _extra_fields(frontmatter: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "doc_kind",
        "status",
        "spec_kind",
        "context",
        "version",
        "parent_concept_id",
        "formal_scope",
    )
    extra: dict[str, Any] = {}
    for key in keys:
        if key in frontmatter and frontmatter[key] is not None:
            extra[key] = frontmatter[key]
    return extra
