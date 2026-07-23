"""Concept corpus build artifacts (FK-13 §13.9.8).

Produces the deterministic ``INDEX.yaml`` and ``concept_graph.json`` from the
SSOT discovery result, both carrying the SAME ``corpus_revision``. Only a
validated corpus (no errors) is persisted (the caller enforces the gate).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from agentkit.backend.vectordb.concept_corpus.graph import build_graph
from agentkit.concepts.hashing import PARSER_VERSION

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.concepts.parser import DiscoveryResult


@dataclass(frozen=True)
class BuildArtifacts:
    """The two deterministic corpus build artifacts + their shared revision."""

    index_yaml: str
    concept_graph_json: str
    corpus_revision: str


def build_artifacts(discovery: DiscoveryResult) -> BuildArtifacts:
    """Render ``INDEX.yaml`` and ``concept_graph.json`` from discovery."""
    graph = build_graph(discovery)
    revision = discovery.corpus_revision

    index: dict[str, Any] = {
        "corpus_revision": revision,
        "parser_version": PARSER_VERSION,
        "concepts": [
            {
                "concept_id": doc.concept_id,
                "title": doc.title,
                "module": doc.module,
                "status": doc.effective_status,
                "doc_kind": doc.doc_kind,
                "file": doc.rel_path,
                "authority_over": [{"scope": s} for s in doc.authority_scopes],
                "defers_to": [
                    {"target": t, "scope": s, "reason": r} for (t, s, r) in doc.defers_to_full
                ],
            }
            for doc in sorted(discovery.documents, key=lambda d: d.concept_id)
        ],
    }
    index_yaml = yaml.safe_dump(index, sort_keys=True, allow_unicode=True, default_flow_style=False)

    graph_doc: dict[str, Any] = {
        "corpus_revision": revision,
        "nodes": {
            cid: {
                "status": node.status,
                "module": node.module,
                "doc_kind": node.doc_kind,
            }
            for cid, node in sorted(graph.nodes.items())
        },
        "edges": [
            {"source": e.source, "target": e.target, "type": e.type, "scope": e.scope}
            for e in graph.edges
        ],
    }
    concept_graph_json = json.dumps(graph_doc, sort_keys=True, ensure_ascii=False, indent=2)
    return BuildArtifacts(
        index_yaml=index_yaml,
        concept_graph_json=concept_graph_json,
        corpus_revision=revision,
    )


def write_artifacts(artifacts: BuildArtifacts, out_dir: Path) -> tuple[Path, Path]:
    """Write the build artifacts to ``out_dir``; return ``(index, graph)`` paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "INDEX.yaml"
    graph_path = out_dir / "concept_graph.json"
    index_path.write_text(artifacts.index_yaml, encoding="utf-8")
    graph_path.write_text(artifacts.concept_graph_json, encoding="utf-8")
    return index_path, graph_path


__all__ = ["BuildArtifacts", "build_artifacts", "write_artifacts"]
