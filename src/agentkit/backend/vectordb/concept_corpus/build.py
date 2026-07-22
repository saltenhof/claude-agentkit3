"""Build INDEX.yaml and concept_graph.json (FK-13 §13.9.8)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from agentkit.backend.concept_catalog.corpus.chunking import chunk_markdown
from agentkit.backend.concept_catalog.corpus.parser import PARSER_VERSION
from agentkit.backend.concept_catalog.corpus.profiles import IngestProfileId, get_profile
from agentkit.backend.vectordb.concept_corpus.validate import ValidationResult, validate_corpus


@dataclass(frozen=True)
class BuildArtifacts:
    """Built corpus artifacts."""

    corpus_revision: str
    index: dict[str, Any]
    graph: dict[str, Any]
    index_path: Path | None
    graph_path: Path | None


def build_corpus_artifacts(
    concept_root: Path | str,
    *,
    output_dir: Path | str | None = None,
    validation: ValidationResult | None = None,
    persist: bool = True,
) -> BuildArtifacts:
    """Build INDEX.yaml + concept_graph.json from a validated corpus.

    Only a validated graph is persisted (FK-13 §13.9.8). When validation has
    errors, raises ``ValueError``.
    """
    root = Path(concept_root)
    result = validation if validation is not None else validate_corpus(root)
    if not result.ok_for_sync:
        raise ValueError(
            f"refusing to build artifacts from invalid corpus "
            f"(exit_code={result.exit_code}, errors={len(result.errors)})"
        )

    profile = get_profile(IngestProfileId.FK13_CONCEPT)
    concepts: list[dict[str, Any]] = []
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    for doc in result.documents:
        fm = doc.frontmatter
        chunks, _ = chunk_markdown(doc.body, profile=profile, title=fm.title)
        sections = [
            {"number": c.section_number, "heading": c.section_heading}
            for c in chunks
            if c.section_heading not in {"(intro)", "(document)"}
        ]
        appendices = [
            {
                "concept_id": other.concept_id,
                "file": other.rel_path,
            }
            for other in result.documents
            if other.frontmatter.parent_concept_id == doc.concept_id
        ]
        concepts.append(
            {
                "concept_id": doc.concept_id,
                "title": fm.title,
                "module": fm.module,
                "status": doc.effective_status,
                "doc_kind": fm.doc_kind,
                "file": doc.rel_path,
                "sections": sections,
                "appendices": appendices,
                "authority_over": [{"scope": a.scope} for a in fm.authority_over],
                "defers_to": [
                    {"target": d.target, "scope": d.scope, "reason": d.reason}
                    for d in fm.defers_to
                ],
            }
        )
        nodes[doc.concept_id] = {
            "status": doc.effective_status,
            "module": fm.module,
            "doc_kind": fm.doc_kind,
        }
        for d in fm.defers_to:
            edges.append(
                {
                    "source": doc.concept_id,
                    "target": d.target,
                    "type": "defers_to",
                    "scope": d.scope,
                }
            )
        if fm.parent_concept_id:
            edges.append(
                {
                    "source": fm.parent_concept_id,
                    "target": doc.concept_id,
                    "type": "parent_of_appendix",
                    "scope": "",
                }
            )

    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    index: dict[str, Any] = {
        "corpus_revision": result.corpus_revision,
        "generated_at": generated_at,
        "parser_version": PARSER_VERSION,
        "concepts": concepts,
    }
    graph: dict[str, Any] = {
        "corpus_revision": result.corpus_revision,
        "nodes": nodes,
        "edges": edges,
    }

    index_path: Path | None = None
    graph_path: Path | None = None
    if persist:
        out = Path(output_dir) if output_dir is not None else root
        out.mkdir(parents=True, exist_ok=True)
        index_path = out / "INDEX.yaml"
        graph_path = out / "concept_graph.json"
        index_path.write_text(
            yaml.safe_dump(index, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        graph_path.write_text(
            json.dumps(graph, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return BuildArtifacts(
        corpus_revision=result.corpus_revision,
        index=index,
        graph=graph,
        index_path=index_path,
        graph_path=graph_path,
    )


__all__ = [
    "BuildArtifacts",
    "build_corpus_artifacts",
]
