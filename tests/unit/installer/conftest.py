"""Shared fixtures for installer unit tests (AG3-176).

VectorDB is mandatory: full ``install_agentkit`` flows hit CP10 dual-harness
and CP10a first-index. Unit tests stay offline by stubbing the external
Weaviate/MCP ports at the CP10 module boundary.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _stub_vectordb_installer_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub endpoint preflight, MCP probe, and first-index for offline unit installs."""
    import agentkit.backend.installer.bootstrap_checkpoints.cp10_mcp as cp10_mcp
    import agentkit.backend.installer.bootstrap_checkpoints.cp10a_first_index as cp10a
    from agentkit.backend.installer.mcp_conformance.types import McpConformanceResult
    from agentkit.backend.vectordb.first_index import FirstIndexResult
    from agentkit.backend.vectordb.indexing_receipt import (
        IndexingReceipt,
        IndexingStatus,
    )

    monkeypatch.setattr(
        cp10_mcp,
        "_PREFLIGHT_META_FETCHER",
        lambda host, port, timeout: {"version": "1.24.0", "hostname": str(host)},
    )
    monkeypatch.setattr(
        cp10_mcp,
        "_PREFLIGHT_READY_PROBE",
        lambda host, port: True,
    )
    monkeypatch.setattr(
        cp10_mcp,
        "check_mcp_conformance",
        lambda cmd, **kwargs: McpConformanceResult(
            ok=True,
            reason=None,
            detail="stubbed ok for unit tests",
            tool_names=("story_search", "concept_search"),
        ),
    )

    def _fake_first_index(context: object) -> FirstIndexResult:
        from pathlib import Path

        root = getattr(context, "project_root", Path("."))
        receipt = IndexingReceipt(
            project_id="unit",
            producer_tool="story_sync",
            owned_source_types=("story", "research"),
            discovered=0,
            unchanged=0,
            upserted=0,
            deleted=0,
            failed=0,
            empty_corpus=True,
            start_revision="",
            end_revision="rev0",
            status=IndexingStatus.EMPTY_CORPUS,
            generation_id="gen0",
            published_at="2026-07-21T00:00:00Z",
            digest="0" * 64,
        )
        concept = IndexingReceipt(
            project_id="unit",
            producer_tool="concept_sync",
            owned_source_types=("concept",),
            discovered=0,
            unchanged=0,
            upserted=0,
            deleted=0,
            failed=0,
            empty_corpus=True,
            start_revision="",
            end_revision="rev0",
            status=IndexingStatus.EMPTY_CORPUS,
            generation_id="gen0",
            published_at="2026-07-21T00:00:00Z",
            digest="0" * 64,
        )
        return FirstIndexResult(
            story_receipt=receipt,
            concept_receipt=concept,
            story_receipt_path=Path(root)
            / ".agentkit"
            / "vectordb"
            / "receipts"
            / "s.json",
            concept_receipt_path=Path(root)
            / ".agentkit"
            / "vectordb"
            / "receipts"
            / "c.json",
        )

    monkeypatch.setattr(cp10a, "_execute_first_index", _fake_first_index)
