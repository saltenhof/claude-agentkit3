"""Drift audit between formal specs and prose concept documents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from concept_compiler.compiler import CompiledFormalSpec
from concept_compiler.loader import try_load_frontmatter
from agentkit.exceptions import AgentKitError


class FormalDriftError(AgentKitError):
    """Raised when formal specs and prose concepts drift apart."""


@dataclass(frozen=True)
class DriftLink:
    """Resolved link from a formal spec doc to a prose concept file."""

    formal_doc_id: str
    prose_path: Path


PROSE_ANCHOR_RE = re.compile(r"<!--\s*PROSE-FORMAL:\s*([^>]+?)\s*-->", re.IGNORECASE)


def audit_formal_prose_links(compiled: CompiledFormalSpec, repo_root: Path) -> tuple[DriftLink, ...]:
    """Audit reciprocal doc-level links between formal specs and prose concepts."""
    formal_doc_ids = {document.doc_id for document in compiled.documents}
    links: list[DriftLink] = []
    prose_cache: dict[Path, tuple[dict[str, Any], tuple[str, ...]]] = {}

    for document in compiled.documents:
        prose_refs = _load_prose_refs(document.frontmatter, document.path)
        if not prose_refs:
            raise FormalDriftError(
                f"Formal spec document {document.doc_id} has no prose_refs",
                detail={"formal_doc_id": document.doc_id, "path": str(document.path)},
            )

        for prose_ref in prose_refs:
            prose_path = (repo_root / prose_ref).resolve()
            if not prose_path.is_file():
                raise FormalDriftError(
                    f"Prose reference does not exist for {document.doc_id}: {prose_ref}",
                    detail={"formal_doc_id": document.doc_id, "prose_ref": prose_ref},
                )

            cached = prose_cache.get(prose_path)
            if cached is None:
                prose_frontmatter = try_load_frontmatter(prose_path)
                if prose_frontmatter is None:
                    raise FormalDriftError(
                        f"Prose reference has no parseable frontmatter: {prose_path}",
                        detail={"formal_doc_id": document.doc_id, "prose_path": str(prose_path)},
                    )
                prose_anchors = _load_prose_anchors(prose_path)
                prose_cache[prose_path] = (prose_frontmatter, prose_anchors)
            else:
                prose_frontmatter, prose_anchors = cached

            formal_refs = _load_formal_refs(prose_frontmatter, prose_path)
            if document.doc_id not in formal_refs:
                raise FormalDriftError(
                    f"Prose concept does not declare reciprocal formal_refs link for {document.doc_id}: {prose_path}",
                    detail={"formal_doc_id": document.doc_id, "prose_path": str(prose_path)},
                )

            unknown_refs = sorted(ref for ref in formal_refs if ref not in formal_doc_ids)
            if unknown_refs:
                raise FormalDriftError(
                    f"Prose concept declares unknown formal_refs in {prose_path}: {', '.join(unknown_refs)}",
                    detail={"prose_path": str(prose_path), "unknown_formal_refs": unknown_refs},
                )

            unknown_anchors = sorted(ref for ref in prose_anchors if ref not in formal_doc_ids)
            if unknown_anchors:
                raise FormalDriftError(
                    f"Prose concept declares unknown PROSE-FORMAL anchors in {prose_path}: {', '.join(unknown_anchors)}",
                    detail={"prose_path": str(prose_path), "unknown_prose_anchors": unknown_anchors},
                )

            if _anchor_policy_is_strict(prose_frontmatter):
                missing_anchors = sorted(ref for ref in formal_refs if ref not in prose_anchors)
                if missing_anchors:
                    raise FormalDriftError(
                        f"Prose concept is missing strict PROSE-FORMAL anchors in {prose_path}: {', '.join(missing_anchors)}",
                        detail={"prose_path": str(prose_path), "missing_prose_anchors": missing_anchors},
                    )

            links.append(DriftLink(formal_doc_id=document.doc_id, prose_path=prose_path))

    return tuple(links)


def audit_concept_doc_classification(repo_root: Path) -> None:
    """Ensure every concept document is either formally linked or explicitly prose-only."""
    concept_roots = (
        repo_root / "concept" / "domain-design",
        repo_root / "concept" / "technical-design",
    )
    concept_files = sorted(
        path
        for root in concept_roots
        if root.is_dir()
        for path in root.rglob("*.md")
    )

    for path in concept_files:
        frontmatter = try_load_frontmatter(path)
        if frontmatter is None:
            raise FormalDriftError(
                f"Concept document has no parseable frontmatter: {path}",
                detail={"path": str(path)},
            )

        concept_id = frontmatter.get("concept_id")
        if not isinstance(concept_id, str) or concept_id == "":
            continue

        formal_refs = frontmatter.get("formal_refs")
        formal_scope = frontmatter.get("formal_scope")

        has_formal_refs = isinstance(formal_refs, list) and len(formal_refs) > 0
        is_prose_only = formal_scope == "prose-only"

        if has_formal_refs and is_prose_only:
            raise FormalDriftError(
                f"Concept document mixes formal_refs and formal_scope=prose-only: {path}",
                detail={"path": str(path), "concept_id": concept_id},
            )

        if has_formal_refs:
            if not all(isinstance(item, str) and item != "" for item in formal_refs):
                raise FormalDriftError(
                    f"Concept document formal_refs must be a list of non-empty strings in {path}",
                    detail={"path": str(path), "formal_refs": formal_refs},
                )
            continue

        if is_prose_only:
            continue

        raise FormalDriftError(
            f"Concept document must declare formal_refs or formal_scope=prose-only: {path}",
            detail={"path": str(path), "concept_id": concept_id},
        )


def _load_prose_refs(frontmatter: dict[str, Any], path: Path) -> tuple[str, ...]:
    refs = frontmatter.get("prose_refs")
    if not isinstance(refs, list) or not refs:
        raise FormalDriftError(
            f"Formal spec frontmatter must declare non-empty prose_refs in {path}",
            detail={"path": str(path)},
        )
    if not all(isinstance(item, str) and item != "" for item in refs):
        raise FormalDriftError(
            f"Formal spec prose_refs must be a list of non-empty strings in {path}",
            detail={"path": str(path), "prose_refs": refs},
        )
    return tuple(refs)


def _load_formal_refs(frontmatter: dict[str, Any], path: Path) -> tuple[str, ...]:
    refs = frontmatter.get("formal_refs")
    if not isinstance(refs, list) or not refs:
        raise FormalDriftError(
            f"Prose concept must declare non-empty formal_refs in {path}",
            detail={"path": str(path)},
        )
    if not all(isinstance(item, str) and item != "" for item in refs):
        raise FormalDriftError(
            f"Prose concept formal_refs must be a list of non-empty strings in {path}",
            detail={"path": str(path), "formal_refs": refs},
        )
    return tuple(refs)


def _load_prose_anchors(path: Path) -> tuple[str, ...]:
    text = path.read_text(encoding="utf-8")
    anchors: list[str] = []
    for match in PROSE_ANCHOR_RE.finditer(text):
        payload = match.group(1)
        parts = [part.strip() for part in payload.split(",")]
        anchors.extend(part for part in parts if part)
    return tuple(anchors)


def _anchor_policy_is_strict(frontmatter: dict[str, Any]) -> bool:
    return frontmatter.get("prose_anchor_policy") == "strict"
