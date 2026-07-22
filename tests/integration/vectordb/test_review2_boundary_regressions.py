"""Real-boundary regression tests for review-2/3 open findings.

Fakes only at the external Weaviate client port. R06 uses a real stdio
subprocess (mcp StdioServerParameters + stdio_client + ClientSession).
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from tests.support.vectordb.memory_store import MemoryWeaviateClient
from tests.support.vectordb.project_fixtures import (
    make_fk13_project,
    write_fk13_concept,
)

from agentkit.backend.vectordb.concept_corpus.sync import (
    ConceptSyncBlockedError,
    concept_sync_bounded_window,
)
from agentkit.backend.vectordb.concept_corpus.validate import validate_corpus
from agentkit.backend.vectordb.ingest.engine import IngestEngine, IngestError
from agentkit.backend.vectordb.mcp.tools import KnowledgeTools, ToolExecutionError
from agentkit.backend.vectordb.mcp.wire_models import parse_tool_args
from agentkit.backend.vectordb.mcp_server import dispatch_tool, list_tools
from agentkit.backend.vectordb.project_binding import bind_project
from agentkit.backend.vectordb.runtime_binding import load_runtime_binding_from_env
from agentkit.backend.vectordb.schema import (
    STORY_COLLECTION,
    STORY_CONTEXT_PROPERTIES,
    SchemaDriftError,
    ensure_story_context_schema,
)
from agentkit.integration_clients.vectordb.errors import (
    VectorDbUnavailableError,
    VectorDbWriteError,
)
from agentkit.integration_clients.vectordb.weaviate_adapter import WeaviateStoryAdapter

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


def _env_for(root: Path, project_id: str = "P1") -> dict[str, str]:
    return {
        "PROJECT_ID": project_id,
        "WEAVIATE_HOST": "weaviate.example.test",
        "WEAVIATE_HTTP_PORT": "9903",
        "WEAVIATE_GRPC_PORT": "50051",
    }


def _tools(
    tmp_path: Path, project_id: str = "P1"
) -> tuple[KnowledgeTools, MemoryWeaviateClient, Path]:
    root = make_fk13_project(tmp_path, project_id)
    binding = load_runtime_binding_from_env(_env_for(root, project_id), cwd=root)
    client = MemoryWeaviateClient()
    adapter = WeaviateStoryAdapter(client)  # type: ignore[arg-type]
    engine = IngestEngine(adapter, lock_dir=root / ".locks")
    engine.story_sync(binding.project, full_reindex=True)
    concept_sync_bounded_window(binding.project, engine, full_reindex=True)
    tools = KnowledgeTools(binding, engine, search_port=adapter)
    return tools, client, root


# ---------------------------------------------------------------------------
# R04
# ---------------------------------------------------------------------------


class _LiarStore:
    """Reports written==expected without writing; fetch returns old rows."""

    def __init__(self, inner: MemoryWeaviateClient) -> None:
        self._inner = inner
        self.delete_calls = 0

    def upsert(self, **kwargs: object) -> int:
        objects = kwargs.get("objects") or []
        return len(objects)  # type: ignore[arg-type]

    def delete_by_filter(self, **kwargs: object) -> int:
        self.delete_calls += 1
        raise AssertionError("delete must not run after liar write (R04)")

    def delete_by_ids(self, **kwargs: object) -> dict[str, int]:
        self.delete_calls += 1
        raise AssertionError("delete must not run after liar write (R04)")

    def fetch(self, **kwargs: object) -> Sequence[Mapping[str, object]]:
        return self._inner.fetch(**kwargs)


def test_r04_liar_store_no_delete_no_new_receipt(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    result = concept_sync_bounded_window(binding, engine, full_reindex=True)
    receipt_before = result.receipt_path.read_text(encoding="utf-8")
    before = list(client.fetch(collection=STORY_COLLECTION, project_id="P1"))
    assert before

    liar = _LiarStore(client)
    bad = IngestEngine(liar, lock_dir=root / ".locks-liar")  # type: ignore[arg-type]
    with pytest.raises(IngestError, match="generation_id|mismatch|incomplete"):
        concept_sync_bounded_window(binding, bad, full_reindex=True)
    assert liar.delete_calls == 0
    after = list(client.fetch(collection=STORY_COLLECTION, project_id="P1"))
    assert len(after) == len(before)
    assert result.receipt_path.read_text(encoding="utf-8") == receipt_before


def test_r04_partial_write_zero_no_delete(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    concept_sync_bounded_window(binding, engine, full_reindex=True)
    before = list(client.fetch(collection=STORY_COLLECTION, project_id="P1"))
    receipt_path = root / ".agentkit" / "vectordb" / "concept_sync_receipt_P1.json"
    receipt_before = receipt_path.read_text(encoding="utf-8")

    class _Partial:
        def upsert(self, **kwargs: object) -> int:
            return 0

        def delete_by_filter(self, **kwargs: object) -> int:
            raise AssertionError("delete must not run")

        def delete_by_ids(self, **kwargs: object) -> dict[str, int]:
            raise AssertionError("delete must not run")

        def fetch(self, **kwargs: object):  # type: ignore[no-untyped-def]
            return client.fetch(**kwargs)

    with pytest.raises(IngestError, match="partial write"):
        IngestEngine(_Partial(), lock_dir=root / ".locks-b").concept_sync(  # type: ignore[arg-type]
            binding, full_reindex=True
        )
    assert len(client.fetch(collection=STORY_COLLECTION, project_id="P1")) == len(before)
    assert receipt_path.read_text(encoding="utf-8") == receipt_before


# ---------------------------------------------------------------------------
# R06 — flat schemas + REAL stdio subprocess
# ---------------------------------------------------------------------------


def test_r06_tools_list_flat_schemas() -> None:
    tools = list_tools()
    assert [t["name"] for t in tools] == [
        "story_search",
        "story_list_sources",
        "story_sync",
        "concept_search",
        "concept_sync",
    ]
    for t in tools:
        schema = t["inputSchema"]
        assert isinstance(schema, dict)
        props = schema.get("properties") or {}
        assert "arguments" not in props
        assert schema.get("additionalProperties") is False


def test_r06_flat_calls_type_and_extra_rejection(tmp_path: Path) -> None:
    tools, _, _ = _tools(tmp_path)
    with pytest.raises(ValidationError):
        parse_tool_args("story_sync", {"full_reindex": 1})
    assert dispatch_tool(tools, "story_sync", {"full_reindex": 1})["ok"] is False
    assert dispatch_tool(tools, "story_search", {"query": "x", "limit": True})["ok"] is False
    assert dispatch_tool(tools, "story_search", {"query": "x", "extra_field": "nope"})[
        "ok"
    ] is False
    assert dispatch_tool(tools, "story_search", {})["ok"] is False
    out = dispatch_tool(tools, "story_list_sources", {})
    assert out["ok"] is True and out["project_id"] == "P1"
    assert dispatch_tool(tools, "story_list_sources", {"project_id": "OTHER"})[
        "ok"
    ] is False
    out = dispatch_tool(tools, "story_sync", {"full_reindex": True})
    assert out["ok"] is True and out.get("full_reindex") is True


def test_r06_real_stdio_client_wire_matrix(tmp_path: Path) -> None:
    """R06/R19: real stdio subprocess + ClientSession wire matrix (Codex path)."""
    root = make_fk13_project(tmp_path, "P1")
    env = {
        **dict(__import__("os").environ),
        **_env_for(root, "P1"),
        "PYTHONPATH": str(
            __import__("pathlib").Path(__file__).resolve().parents[3]
            / "src"
        )
        + __import__("os").pathsep
        + str(__import__("pathlib").Path(__file__).resolve().parents[3]),
    }
    # cwd must be project root so bind_project finds config when PROJECT_ID set
    # via load_runtime_binding_from_env cwd default.
    runner = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "support"
        / "vectordb"
        / "mcp_stdio_runner.py"
    )

    async def _drive() -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=[str(runner)],
            env=env,
            cwd=str(root),
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            listed = await session.list_tools()
            names = [t.name for t in listed.tools]
            assert names == [
                "story_search",
                "story_list_sources",
                "story_sync",
                "concept_search",
                "concept_sync",
            ]
            for t in listed.tools:
                schema = t.inputSchema
                assert "arguments" not in (schema.get("properties") or {})
                assert schema.get("additionalProperties") is False

            # flat full_reindex=true accepted
            ok = await session.call_tool(
                "story_sync", arguments={"full_reindex": True}
            )
            text = ok.content[0].text  # type: ignore[union-attr]
            payload = json.loads(text)
            assert payload["ok"] is True
            assert payload.get("full_reindex") is True

            # 1 → bool rejected (MCP/tool validation)
            bad = await session.call_tool(
                "story_sync", arguments={"full_reindex": 1}
            )
            bad_text = bad.content[0].text  # type: ignore[union-attr]
            if getattr(bad, "isError", False):
                assert True
            else:
                bad_payload = json.loads(bad_text)
                assert bad_payload.get("ok") is False

            # extras rejected
            extra = await session.call_tool(
                "story_search",
                arguments={"query": "x", "extra_field": "nope"},
            )
            if not getattr(extra, "isError", False):
                assert json.loads(extra.content[0].text).get("ok") is False  # type: ignore[union-attr]

            # missing required
            miss = await session.call_tool("story_search", arguments={})
            if not getattr(miss, "isError", False):
                assert json.loads(miss.content[0].text).get("ok") is False  # type: ignore[union-attr]

            # omit project_id → bound
            src = await session.call_tool("story_list_sources", arguments={})
            src_payload = json.loads(src.content[0].text)  # type: ignore[union-attr]
            assert src_payload["ok"] is True
            assert src_payload["project_id"] == "P1"

            # foreign project rejected
            foreign = await session.call_tool(
                "story_list_sources", arguments={"project_id": "OTHER"}
            )
            foreign_payload = json.loads(foreign.content[0].text)  # type: ignore[union-attr]
            assert foreign_payload.get("ok") is False

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# R07 — project hits + strict delete counters
# ---------------------------------------------------------------------------


def test_r07_foreign_project_hit_rejected() -> None:
    class _Foreign:
        def search(self, **kwargs: object):  # type: ignore[no-untyped-def]
            return [
                {
                    "story_id": "S1",
                    "title": "T",
                    "score": 0.9,
                    "snippet": "hi",
                    "source_type": "story",
                    "section_heading": "H",
                    "project_id": "OTHER",
                    "content": "hi",
                }
            ]

        def is_ready(self) -> bool:
            return True

        def close(self) -> None:
            return None

        def upsert(self, **kwargs: object) -> int:
            return 0

        def delete_by_filter(self, **kwargs: object) -> int:
            return 0

        def delete_by_ids(self, **kwargs: object) -> dict[str, int]:
            return {"matches": 0, "successful": 0, "failed": 0}

        def fetch(self, **kwargs: object):  # type: ignore[no-untyped-def]
            return []

    adapter = WeaviateStoryAdapter(_Foreign())  # type: ignore[arg-type]
    with pytest.raises(VectorDbUnavailableError, match="project_id"):
        adapter.search(
            collection=STORY_COLLECTION,
            query="q",
            search_mode="hybrid",
            project_id="P1",
            limit=5,
            source_types=["story"],
        )


def test_r07_missing_failed_counter_no_success_receipt(tmp_path: Path) -> None:
    """R07 Codex killer: missing ``failed`` must not become success."""
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    concept_sync_bounded_window(binding, engine, full_reindex=True)
    write_fk13_concept(
        root / "concepts",
        concept_id="FK-TEST",
        body="## Purpose\n\nChanged body for delete path.\n",
    )
    receipt_path = root / ".agentkit" / "vectordb" / "concept_sync_receipt_P1.json"
    before_receipt = receipt_path.read_text(encoding="utf-8")
    before_rows = list(
        client.fetch(collection=STORY_COLLECTION, project_id="P1", source_types=["concept"])
    )

    class _MissingFailed:
        def __init__(self, inner: MemoryWeaviateClient) -> None:
            self._inner = inner
            self.delete_calls = 0

        def upsert(self, **kwargs: object) -> int:
            return self._inner.upsert(**kwargs)  # type: ignore[arg-type]

        def fetch(self, **kwargs: object):  # type: ignore[no-untyped-def]
            return self._inner.fetch(**kwargs)

        def delete_by_ids(self, **kwargs: object) -> dict[str, object]:
            self.delete_calls += 1
            # Lie: claim full delete success without failed key and without deleting.
            uuids = kwargs.get("uuids") or []
            n = len(uuids)  # type: ignore[arg-type]
            return {"matches": n, "successful": n}  # missing failed

        def delete_by_filter(self, **kwargs: object) -> int:
            return 0

    port = _MissingFailed(client)
    adapter = WeaviateStoryAdapter(port)  # type: ignore[arg-type]
    bad = IngestEngine(adapter, lock_dir=root / ".locks-mf")
    with pytest.raises((IngestError, VectorDbWriteError), match="failed|counters|R07"):
        concept_sync_bounded_window(binding, bad, full_reindex=True)
    assert receipt_path.read_text(encoding="utf-8") == before_receipt
    after_rows = list(
        client.fetch(collection=STORY_COLLECTION, project_id="P1", source_types=["concept"])
    )
    # Store was not deleted by the liar; rows still present.
    assert len(after_rows) >= len(before_rows) - 0


def test_r07_bare_int_and_bool_counters_rejected() -> None:
    from agentkit.integration_clients.vectordb.strict_counters import (
        parse_delete_counters,
    )

    with pytest.raises(VectorDbWriteError, match="bare integer|R07"):
        parse_delete_counters(3)
    with pytest.raises(VectorDbWriteError, match="failed|R07"):
        parse_delete_counters({"matches": 1, "successful": 1})
    with pytest.raises(VectorDbWriteError, match="non-bool|R07"):
        parse_delete_counters({"matches": True, "successful": True, "failed": False})
    assert parse_delete_counters({"matches": 2, "successful": 2, "failed": 0}) == {
        "matches": 2,
        "successful": 2,
        "failed": 0,
    }


def test_r07_adapter_upsert_and_filter_delete_reject_coerced_counts() -> None:
    """R07: bool/float/str write & filter-delete counts rejected at adapter (not int())."""

    class _CoerceClient:
        def __init__(self, upsert_val: object, filter_val: object) -> None:
            self._upsert_val = upsert_val
            self._filter_val = filter_val

        def is_ready(self) -> bool:
            return True

        def close(self) -> None:
            return None

        def search(self, **kwargs: object):  # type: ignore[no-untyped-def]
            return []

        def upsert(self, **kwargs: object) -> object:
            return self._upsert_val

        def delete_by_filter(self, **kwargs: object) -> object:
            return self._filter_val

        def delete_by_ids(self, **kwargs: object) -> dict[str, int]:
            return {"matches": 0, "successful": 0, "failed": 0}

        def fetch(self, **kwargs: object):  # type: ignore[no-untyped-def]
            return []

    # bool (Codex: adapter_upsert_bool ACCEPTED 1 / adapter_filter_delete_bool)
    for bad in (True, 1.5, "2"):
        adapter = WeaviateStoryAdapter(_CoerceClient(bad, 0))  # type: ignore[arg-type]
        with pytest.raises(VectorDbWriteError, match="non-bool int|R07"):
            adapter.story_sync(objects=[{"story_id": "S"}])
        with pytest.raises(VectorDbWriteError, match="non-bool int|R07"):
            adapter.upsert(
                collection=STORY_COLLECTION, objects=[{"story_id": "S"}]
            )
        adapter_f = WeaviateStoryAdapter(_CoerceClient(0, bad))  # type: ignore[arg-type]
        with pytest.raises(VectorDbWriteError, match="non-bool int|R07"):
            adapter_f.delete_by_filter(
                collection=STORY_COLLECTION, project_id="P1"
            )

    # Legitimate non-bool int still accepted.
    ok = WeaviateStoryAdapter(_CoerceClient(1, 3))  # type: ignore[arg-type]
    assert ok.story_sync(objects=[{"story_id": "S"}]) == 1
    assert ok.upsert(collection=STORY_COLLECTION, objects=[{"story_id": "S"}]) == 1
    assert ok.delete_by_filter(collection=STORY_COLLECTION, project_id="P1") == 3


def test_r07_zero_delete_no_success_receipt(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    concept_sync_bounded_window(binding, engine, full_reindex=True)
    write_fk13_concept(
        root / "concepts",
        concept_id="FK-TEST",
        body="## Purpose\n\nChanged body content for delete path.\n",
    )
    receipt_path = root / ".agentkit" / "vectordb" / "concept_sync_receipt_P1.json"
    before_receipt = receipt_path.read_text(encoding="utf-8")

    class _ZeroDelete:
        def __init__(self, inner: MemoryWeaviateClient) -> None:
            self._inner = inner

        def upsert(self, **kwargs: object) -> int:
            return self._inner.upsert(**kwargs)  # type: ignore[arg-type]

        def fetch(self, **kwargs: object):  # type: ignore[no-untyped-def]
            return self._inner.fetch(**kwargs)

        def delete_by_ids(self, **kwargs: object) -> dict[str, int]:
            return {"matches": 0, "successful": 0, "failed": 0}

        def delete_by_filter(self, **kwargs: object) -> int:
            return 0

    bad = IngestEngine(_ZeroDelete(client), lock_dir=root / ".locks-z")  # type: ignore[arg-type]
    with pytest.raises(IngestError, match="partial delete|expected"):
        concept_sync_bounded_window(binding, bad, full_reindex=True)
    assert receipt_path.read_text(encoding="utf-8") == before_receipt


# ---------------------------------------------------------------------------
# R09 / R10
# ---------------------------------------------------------------------------


def test_r09_missing_graph_fail_closed(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = load_runtime_binding_from_env(_env_for(root), cwd=root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    engine.story_sync(binding.project, full_reindex=True)
    with pytest.raises(ToolExecutionError, match="concept_graph|graph_unavailable|R09"):
        KnowledgeTools(binding, engine, search_port=client)


def test_r09_malformed_graph_fail_closed(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    (root / "concepts" / "concept_graph.json").write_text("{not json", encoding="utf-8")
    binding = load_runtime_binding_from_env(_env_for(root), cwd=root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    with pytest.raises(ToolExecutionError, match="malform|graph_unavailable|R09"):
        KnowledgeTools(binding, engine, search_port=client)


def test_r09_stale_graph_fail_closed(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = load_runtime_binding_from_env(_env_for(root), cwd=root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    concept_sync_bounded_window(binding.project, engine, full_reindex=True)
    graph_path = root / "concepts" / "concept_graph.json"
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    data["corpus_revision"] = "sha256:stale"
    graph_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ToolExecutionError, match="stale|graph_stale|R09"):
        KnowledgeTools(binding, engine, search_port=client)


def test_r10_concept_path_matrix(tmp_path: Path) -> None:
    tools, client, root = _tools(tmp_path)
    assert tools.handle_raw("concept_sync", {"concept_path": "fk_test.md"})["ok"] is True
    assert tools.handle_raw("concept_sync", {"concept_path": "concepts/fk_test.md"})[
        "ok"
    ] is True
    abs_path = str((root / "concepts" / "fk_test.md").resolve())
    assert tools.handle_raw("concept_sync", {"concept_path": abs_path})["ok"] is True
    with pytest.raises(ToolExecutionError):
        tools.handle_raw("concept_sync", {"concept_path": str(tmp_path / "outside.md")})
    with pytest.raises(ToolExecutionError):
        tools.handle_raw("concept_sync", {"concept_path": "no_such.md"})
    assert "fk_test.md" in str(client.fetch(collection=STORY_COLLECTION, project_id="P1"))


# ---------------------------------------------------------------------------
# R12
# ---------------------------------------------------------------------------


def test_r12_adapter_incremental_change_and_delete(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    mem = MemoryWeaviateClient()
    adapter = WeaviateStoryAdapter(mem)  # type: ignore[arg-type]
    assert hasattr(adapter, "delete_by_ids")
    engine = IngestEngine(adapter, lock_dir=root / ".locks")
    concept_sync_bounded_window(binding, engine, full_reindex=True)
    write_fk13_concept(
        root / "concepts",
        concept_id="FK-TEST",
        body="## Purpose\n\nUpdated content for incremental replace.\n",
    )
    concept_sync_bounded_window(binding, engine, full_reindex=False)
    rows2 = list(
        adapter.fetch(
            collection=STORY_COLLECTION, project_id="P1", source_types=["concept"]
        )
    )
    contents = " ".join(str(r.get("content")) for r in rows2)
    assert "Updated content" in contents
    (root / "concepts" / "fk_test.md").unlink()
    write_fk13_concept(root / "concepts", concept_id="FK-OTHER", filename="fk_other.md")
    concept_sync_bounded_window(binding, engine, full_reindex=False)
    rows3 = list(
        adapter.fetch(
            collection=STORY_COLLECTION, project_id="P1", source_types=["concept"]
        )
    )
    files = {str(r.get("source_file")) for r in rows3}
    assert not any("fk_test.md" in f for f in files)
    assert any("fk_other" in f for f in files)


# ---------------------------------------------------------------------------
# R14
# ---------------------------------------------------------------------------


def test_r14_no_introspection_fail_closed() -> None:
    class _Coll:
        def exists(self, name: str) -> bool:
            return True

        def create(self, **kwargs: object) -> None:
            raise AssertionError("must not create")

    class _Client:
        collections = _Coll()

    with pytest.raises(SchemaDriftError, match="introspect|fail-closed|R14"):
        ensure_story_context_schema(_Client())


def test_r14_missing_vector_metadata_rejected() -> None:
    """R14 Codex killer: names+types alone without vectorize proof → reject."""

    class _Prop:
        def __init__(self, name: str, data_type: str) -> None:
            self.name = name
            self.data_type = data_type
            # deliberately omit skip_vectorization and tokenization

    props = [_Prop(p.name, p.data_type) for p in STORY_CONTEXT_PROPERTIES]

    class _Cfg:
        properties = props
        # no vectorizer either

    class _CollObj:
        config = type("CfgAPI", (), {"get": staticmethod(lambda: _Cfg())})()

    class _Coll:
        def exists(self, name: str) -> bool:
            return True

        def get(self, name: str) -> _CollObj:
            return _CollObj()

    with pytest.raises(SchemaDriftError):
        ensure_story_context_schema(type("C", (), {"collections": _Coll()})())


# ---------------------------------------------------------------------------
# R16 — desired-set freshness, not generation uniformity
# ---------------------------------------------------------------------------


def test_r16_incremental_success_is_ok_with_mixed_generations(tmp_path: Path) -> None:
    """R16 Codex killer: successful incremental must yield freshness=ok."""
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    concept_sync_bounded_window(binding, engine, full_reindex=True)
    # Change one concept so incremental writes new gen for one chunk, skips rest.
    write_fk13_concept(
        root / "concepts",
        concept_id="FK-TEST",
        body="## Purpose\n\nIncremental body change for mixed gens.\n",
    )
    # Add a second doc so skip path is non-trivial after first full.
    write_fk13_concept(
        root / "concepts",
        concept_id="FK-STABLE",
        filename="fk_stable.md",
        authority=["vectordb-stable"],
        body="## Purpose\n\nStable document body stays unchanged.\n",
    )
    concept_sync_bounded_window(binding, engine, full_reindex=True)
    # Second incremental: only FK-TEST changes
    write_fk13_concept(
        root / "concepts",
        concept_id="FK-TEST",
        body="## Purpose\n\nSecond incremental change only on FK-TEST.\n",
    )
    concept_sync_bounded_window(binding, engine, full_reindex=False)
    rows = list(
        client.fetch(collection=STORY_COLLECTION, project_id="P1", source_types=["concept"])
    )
    gens = {str(r.get("generation_id")) for r in rows}
    # Mixed generations are expected on incremental success.
    assert len(gens) >= 1
    sources = engine.list_sources(binding)
    concept_src = next(s for s in sources if s["source_type"] == "concept")
    assert concept_src["freshness_status"] == "ok", (
        f"R16_INCREMENTAL_FRESHNESS {concept_src['freshness_status']} "
        f"R16_OBSERVED_GENS {sorted(gens)}"
    )


def test_r16_abort_before_receipt_keeps_last_success(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    engine.story_sync(binding, full_reindex=True)
    concept_sync_bounded_window(binding, engine, full_reindex=True)
    sources_ok = engine.list_sources(binding)
    concept_src = next(s for s in sources_ok if s["source_type"] == "concept")
    assert concept_src["freshness_status"] == "ok"
    last_gen = concept_src["last_generation_id"]
    assert last_gen

    liar = _LiarStore(client)
    with pytest.raises(IngestError):
        concept_sync_bounded_window(
            binding,
            IngestEngine(liar, lock_dir=root / ".locks-l"),  # type: ignore[arg-type]
            full_reindex=True,
        )
    sources_after = engine.list_sources(binding)
    concept_after = next(s for s in sources_after if s["source_type"] == "concept")
    assert concept_after["last_generation_id"] == last_gen
    assert concept_after["freshness_status"] == "ok"


def test_r16_extra_row_is_partial(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    concept_sync_bounded_window(binding, engine, full_reindex=True)
    rows = list(
        client.fetch(collection=STORY_COLLECTION, project_id="P1", source_types=["concept"])
    )
    assert rows
    rogue = dict(rows[0])
    rogue["chunk_uuid"] = "00000000-0000-4000-8000-000000000099"
    rogue["content_hash"] = "not-the-desired-hash"
    rogue["generation_id"] = "foreign-gen"
    client.upsert(
        collection=STORY_COLLECTION,
        objects=[rogue],
        uuids=[str(rogue["chunk_uuid"])],
    )
    sources = engine.list_sources(binding)
    concept_src = next(s for s in sources if s["source_type"] == "concept")
    assert concept_src["freshness_status"] in {"partial", "stale"}


# ---------------------------------------------------------------------------
# R11 — malform fundamental_scopes blocks sync; absence is inert
# ---------------------------------------------------------------------------


def test_r11_malformed_fundamental_scopes_blocks_sync(tmp_path: Path) -> None:
    """R11: present malform scopes file → E-INTERNAL-001 in errors, sync blocked."""
    root = make_fk13_project(tmp_path, "P1")
    meta = root / "concepts" / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "fundamental_scopes.yaml").write_text(
        "scopes: not-a-list\n",
        encoding="utf-8",
    )
    result = validate_corpus(root / "concepts")
    assert any(e.code == "E-INTERNAL-001" for e in result.errors)
    assert result.ok_for_sync is False
    assert result.exit_code in (2, 3)

    binding = bind_project(root)
    engine = IngestEngine(MemoryWeaviateClient(), lock_dir=root / ".locks")
    with pytest.raises(ConceptSyncBlockedError):
        concept_sync_bounded_window(binding, engine, full_reindex=True)


def test_r11_absent_fundamental_scopes_allows_sync(tmp_path: Path) -> None:
    """R11: absence of fundamental_scopes.yaml remains inert for sync."""
    root = make_fk13_project(tmp_path, "P1")
    assert not (root / "concepts" / "_meta" / "fundamental_scopes.yaml").is_file()
    result = validate_corpus(root / "concepts")
    assert not any(e.code == "E-INTERNAL-001" for e in result.errors)
    assert result.ok_for_sync is True

    binding = bind_project(root)
    engine = IngestEngine(MemoryWeaviateClient(), lock_dir=root / ".locks")
    out = concept_sync_bounded_window(binding, engine, full_reindex=True)
    assert out.ingest.counters.written >= 1
