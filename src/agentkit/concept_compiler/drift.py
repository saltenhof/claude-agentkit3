"""Drift audit between formal specs and prose concept documents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentkit.concept_compiler.compiler import CompiledFormalSpec
from agentkit.concept_compiler.loader import try_load_frontmatter
from agentkit.exceptions import AgentKitError


class FormalDriftError(AgentKitError):
    """Raised when formal specs and prose concepts drift apart."""


@dataclass(frozen=True)
class DriftLink:
    """Resolved link from a formal spec doc to a prose concept file."""

    formal_doc_id: str
    prose_path: Path


def audit_formal_prose_links(compiled: CompiledFormalSpec, repo_root: Path) -> tuple[DriftLink, ...]:
    """Audit reciprocal doc-level links between formal specs and prose concepts."""
    formal_doc_ids = {document.doc_id for document in compiled.documents}
    links: list[DriftLink] = []

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

            prose_frontmatter = try_load_frontmatter(prose_path)
            if prose_frontmatter is None:
                raise FormalDriftError(
                    f"Prose reference has no parseable frontmatter: {prose_path}",
                    detail={"formal_doc_id": document.doc_id, "prose_path": str(prose_path)},
                )

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

            links.append(DriftLink(formal_doc_id=document.doc_id, prose_path=prose_path))

    return tuple(links)


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
