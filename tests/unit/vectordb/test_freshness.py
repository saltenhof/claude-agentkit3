"""Freshness indicator tests (FK-13 §13.9.9 / §13.9.12)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.vectordb.concept_corpus.freshness import (
    check_freshness,
    read_persisted_revision,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_read_persisted_revision_present(tmp_path: Path) -> None:
    g = tmp_path / "concept_graph.json"
    g.write_text(json.dumps({"corpus_revision": "abc123"}), encoding="utf-8")
    assert read_persisted_revision(g) == "abc123"


def test_read_persisted_revision_missing(tmp_path: Path) -> None:
    assert read_persisted_revision(tmp_path / "nope.json") is None


def test_read_persisted_revision_malformed(tmp_path: Path) -> None:
    g = tmp_path / "concept_graph.json"
    g.write_text("not json", encoding="utf-8")
    assert read_persisted_revision(g) is None


def test_check_freshness_fresh(tmp_path: Path) -> None:
    g = tmp_path / "concept_graph.json"
    g.write_text(json.dumps({"corpus_revision": "rev-1"}), encoding="utf-8")
    result = check_freshness("rev-1", g)
    assert result.fresh is True


def test_check_freshness_stale(tmp_path: Path) -> None:
    g = tmp_path / "concept_graph.json"
    g.write_text(json.dumps({"corpus_revision": "old"}), encoding="utf-8")
    result = check_freshness("new", g)
    assert result.fresh is False
    assert result.actual_revision == "old"


def test_check_freshness_missing_artifact_not_fresh(tmp_path: Path) -> None:
    result = check_freshness("rev-1", tmp_path / "absent.json")
    assert result.fresh is False
    assert result.actual_revision == ""
