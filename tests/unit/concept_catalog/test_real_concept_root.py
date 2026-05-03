from __future__ import annotations

from pathlib import Path

from agentkit.concept_catalog.index import ConceptIndex


def test_real_concept_root_loads() -> None:
    root = Path(__file__).resolve().parents[3] / "concept"
    index = ConceptIndex(root)

    index.load()

    assert len(index.list()) > 50
    assert index.get("DK-00") is not None
