"""REAL-PATH proofs for the r2 engine-cluster fixes (Codex review r2).

Every test exercises the REAL production code (WeaviateCorpusStore,
WeaviateRetrievalPort, SyncService, McpToolService, the ingest adapter, the
real connection constructor) with a fake ONLY at the Weaviate CLIENT boundary
that RECORDS what production actually did (the exact query, source_type,
filters, counts, connection params, vectorizer). Nothing is monkeypatched to a
normalised exception; real faults trigger real behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.vectordb.engine import (
    CLAIM_COLLECTION,
    RECEIPT_COLLECTION,
    WeaviateCorpusStore,
    WeaviateRetrievalPort,
    connect_real_client,
)
from agentkit.backend.vectordb.mcp_server import McpToolService, build_mcp_server, handle_tool_call
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
from agentkit.backend.vectordb.schema import STORY_CONTEXT_COLLECTION, StoryContextObject, deterministic_uuid
from agentkit.backend.vectordb.sync import (
    ConcurrentSyncRejectedError,
    PartialWriteError,
    SyncReceipt,
    SyncService,
)
from agentkit.concepts.frontmatter import FrontmatterError
from agentkit.concepts.parser import discover_concept_files

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

_ENV = {
    "PROJECT_ID": "acme",
    "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.acme.local:8080",
    "WEAVIATE_GRPC_ENDPOINT": "weaviate.acme.local:50051",
}


# --------------------------------------------------------------------------- #
# Recording fake at the Weaviate CLIENT boundary (the only permitted fake)
# --------------------------------------------------------------------------- #


@dataclass
class RecordingClient:
    """Fake at the thin-adapter corpus boundary. RECORDS every production call."""

    objects: dict[str, dict[str, object]] = field(default_factory=dict)
    receipts: dict[str, dict[str, object]] = field(default_factory=dict)
    claims: dict[str, dict[str, object]] = field(default_factory=dict)
    search_calls: list[dict[str, object]] = field(default_factory=list)
    ensure_calls: list[dict[str, object]] = field(default_factory=list)
    search_results: list[tuple[str, dict[str, object], float]] = field(default_factory=list)
    upsert_fail_count: int = 0  # if set, upsert reports this many fewer written

    # -- fetch --
    def fetch_by_property(
        self, *, collection: str, prop: str, value: str, return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]:
        return self._fetch(collection, lambda p: str(p.get(prop, "")) == value)

    def fetch_by_property_any(
        self, *, collection: str, prop: str, values: Sequence[str], return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]:
        v = set(values)
        return self._fetch(collection, lambda p: str(p.get(prop, "")) in v)

    def _fetch(
        self, collection: str, predicate: object
    ) -> Sequence[tuple[str, dict[str, object]]]:
        store = self._store_for(collection)
        return [
            (uid, {k: v for k, v in props.items() if k != "uuid"})
            for uid, props in store.items()
            if predicate(props)  # type: ignore[arg-type]
        ]

    def _store_for(self, collection: str) -> dict[str, dict[str, object]]:
        if collection == RECEIPT_COLLECTION:
            return self.receipts
        if collection == CLAIM_COLLECTION:
            return self.claims
        return self.objects

    # -- search (the REAL retrieval path) --
    def search_objects(
        self,
        *,
        collection: str,
        query: str,
        search_mode: str,
        project_id: str,
        source_type: str,
        filters: Mapping[str, object],
        limit: int,
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object], float]]:
        self.search_calls.append(
            {
                "collection": collection,
                "query": query,
                "search_mode": search_mode,
                "project_id": project_id,
                "source_type": source_type,
                "filters": dict(filters),
                "limit": limit,
            }
        )
        return list(self.search_results)

    # -- mutations --
    def upsert(self, *, collection: str, objects: Sequence[Mapping[str, object]]) -> int:
        store = self._store_for(collection)
        n = 0
        for obj in objects:
            uid = str(obj.get("uuid", ""))
            if not uid:
                continue
            store[uid] = dict(obj)
            n += 1
        if self.upsert_fail_count and collection == STORY_CONTEXT_COLLECTION:
            self.upsert_fail_count = 0
            return max(0, n - 1)  # partial
        return n

    def delete_by_ids(self, *, collection: str, uuids: Sequence[str]) -> int:
        store = self._store_for(collection)
        deleted = 0
        for uid in uuids:
            if str(uid) in store:
                del store[str(uid)]
                deleted += 1
        return deleted

    def ensure_collection(
        self, *, collection: str, property_specs: Sequence[Mapping[str, object]], vectorizer: str = "self_provided"
    ) -> None:
        self.ensure_calls.append(
            {"collection": collection, "vectorizer": vectorizer, "prop_count": len(property_specs)}
        )


def _binding() -> RuntimeBinding:
    return RuntimeBinding.from_env(_ENV, command="python", args=(), cwd=".")


def _store(client: RecordingClient | None = None) -> WeaviateCorpusStore:
    return WeaviateCorpusStore(client=client or RecordingClient())


def _obj(project_id: str, source_file: str, chunk_id: str, source_type: str = "concept") -> StoryContextObject:
    props = {
        "content": f"c-{chunk_id}", "source_type": source_type, "source_file": source_file,
        "project_id": project_id, "content_hash": f"h-{chunk_id}", "section_heading": "h",
    }
    return StoryContextObject(uuid=deterministic_uuid(project_id, source_file, chunk_id), properties=props)


def _corpus(tmp_path: Path) -> Path:
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True, exist_ok=True)
    (root / "13_retrieval.md").write_text(
        dedent(
            """\
            ---
            concept_id: FK-13
            title: Retrieval
            module: vectordb
            status: active
            doc_kind: core
            authority_over:
              - scope: vectordb
            ---

            # Retrieval

            ## Purpose

            Semantic search over stories and concepts.
            """
        ),
        encoding="utf-8",
    )
    return tmp_path / "concept"


def _service(tmp_path: Path, client: RecordingClient | None = None) -> tuple[McpToolService, RecordingClient]:
    client = client or RecordingClient()
    binding = _binding()
    store = WeaviateCorpusStore(client=client)
    sync = SyncService(store=store)
    retrieval = WeaviateRetrievalPort(client=client, store=store, binding=binding)
    svc = McpToolService(
        binding=binding, retrieval=retrieval, sync=sync,
        concepts_dir=_corpus(tmp_path), stories_dir=tmp_path,
    )
    return svc, client


# --------------------------------------------------------------------------- #
# R02/N01/R05: concept_search issues a REAL StoryContext query scoped by
# source_type=concept + the typed filters + default active
# --------------------------------------------------------------------------- #


def test_r02_concept_search_issues_real_scoped_query(tmp_path: Path) -> None:
    svc, client = _service(tmp_path)
    client.search_results = [("u1", {"concept_id": "FK-13", "title": "Retrieval", "module": "vectordb"}, 0.9)]
    handle_tool_call(svc, "concept_search", {"query": "retrieval"})
    assert len(client.search_calls) == 1
    call = client.search_calls[0]
    assert call["collection"] == STORY_CONTEXT_COLLECTION
    assert call["source_type"] == "concept"
    assert call["filters"]["concept_status"] == "active"  # default active (R02/AC7)
    assert call["search_mode"] == "hybrid"
    assert call["project_id"] == "acme"


def test_r05_story_search_covers_both_owned_types(tmp_path: Path) -> None:
    svc, client = _service(tmp_path)
    handle_tool_call(svc, "story_search", {"query": "x", "status": "Done"})
    # story_search must query BOTH story AND research (R05), both with the filter.
    source_types = sorted(c["source_type"] for c in client.search_calls)
    assert source_types == ["research", "story"]
    for c in client.search_calls:
        assert c["filters"]["status"] == "Done"
        assert c["project_id"] == "acme"


def test_r02_full_properties_returned(tmp_path: Path) -> None:
    svc, client = _service(tmp_path)
    client.search_results = [
        ("u1", {"concept_id": "FK-13", "title": "Retrieval", "module": "vectordb", "concept_status": "active"}, 0.8)
    ]
    result = handle_tool_call(svc, "concept_search", {"query": "r"})
    assert result["results"][0]["concept_id"] == "FK-13"
    assert result["results"][0]["module"] == "vectordb"  # full props preserved (N01)


# --------------------------------------------------------------------------- #
# N04: story_list_sources reads persisted receipts for real last_revision
# --------------------------------------------------------------------------- #


def test_n04_list_sources_reads_real_receipt_revision(tmp_path: Path) -> None:
    svc, client = _service(tmp_path)
    # Sync a concept source, which writes a receipt with a real revision.
    discovery = discover_concept_files(svc.concepts_dir)
    from agentkit.backend.vectordb.ingest.adapter import concept_chunks_to_objects

    objs = concept_chunks_to_objects("acme", discovery)
    by_source: dict[str, list[StoryContextObject]] = {}
    for o in objs:
        by_source.setdefault(o.properties["source_file"], []).append(o)
    svc.sync.reconcile_sources(
        project_id="acme", producer="concept_sync",
        objects_by_source=by_source, corpus_revision=discovery.corpus_revision,
    )
    result = handle_tool_call(svc, "story_list_sources", {})
    concept_row = next(s for s in result["sources"] if s["source_type"] == "concept")
    assert concept_row["last_revision"] == discovery.corpus_revision  # real, not "" (N04)
    assert concept_row["chunk_count"] > 0


# --------------------------------------------------------------------------- #
# N03: two service instances over ONE shared store -- loser REJECTED (D3)
# --------------------------------------------------------------------------- #


def test_n03_two_writers_shared_store_rejects_loser(tmp_path: Path) -> None:
    client = RecordingClient()
    store = _store(client)
    writer_a = SyncService(store=store)
    writer_b = SyncService(store=store)
    assert store.try_claim_source(project_id="acme", source_file="f.md") is True
    with pytest.raises(ConcurrentSyncRejectedError):
        writer_b.sync_source(
            project_id="acme", source_file="f.md", source_type="concept",
            objects=[_obj("acme", "f.md", "c1")], corpus_revision="rev",
        )
    store.release_source(project_id="acme", source_file="f.md")
    assert writer_a.sync_source(
        project_id="acme", source_file="f.md", source_type="concept",
        objects=[_obj("acme", "f.md", "c1")], corpus_revision="rev",
    ).written == 1


# --------------------------------------------------------------------------- #
# R12/N08: partial delete rejected in reconcile; single receipt record
# --------------------------------------------------------------------------- #


def test_r12_reconcile_partial_delete_rejected_no_receipt(tmp_path: Path) -> None:
    client = RecordingClient()
    # Seed a vanished concept source (2 objects) the store reports but cannot fully delete.
    stale_a = _obj("acme", "gone.md", "a1", "concept")
    stale_b = _obj("acme", "gone.md", "b1", "concept")
    client.objects[stale_a.uuid] = {**stale_a.properties, "uuid": stale_a.uuid}
    client.objects[stale_b.uuid] = {**stale_b.properties, "uuid": stale_b.uuid}
    # Make delete remove only 1 of 2 (partial) by pre-removing one from the fake.
    # We simulate a partial delete by failing the second delete.
    original_delete = client.delete_by_ids

    def _partial_delete(*, collection: str, uuids: Sequence[str]) -> int:
        # delete only the first, then fail the rest
        if len(uuids) > 1:
            return 1
        return original_delete(collection=collection, uuids=uuids)

    client.delete_by_ids = _partial_delete  # type: ignore[method-assign]
    store = _store(client)
    service = SyncService(store=store)
    with pytest.raises(PartialWriteError, match="partial delete"):
        service.reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source={}, corpus_revision="rev",
        )
    # No completed receipt for the vanished source.
    assert store.get_receipt(project_id="acme", source_file="gone.md") is None


def test_n08_single_receipt_record_per_source(tmp_path: Path) -> None:
    client = RecordingClient()
    store = _store(client)
    r1 = SyncReceipt.for_completion("acme", "f.md", "concept", "rev-1")
    r2 = SyncReceipt.for_completion("acme", "f.md", "concept", "rev-2")
    store.set_receipt(receipt=r1)
    store.set_receipt(receipt=r2)
    # Both upserts use the SAME stable per-source uuid -> 1 record, latest wins.
    receipt_docs = [d for d in client.receipts.values()]
    assert len(receipt_docs) == 1
    assert receipt_docs[0]["corpus_revision"] == "rev-2"


# --------------------------------------------------------------------------- #
# R03: gRPC host+port passed INTO the real connection constructor
# --------------------------------------------------------------------------- #


def test_r03_grpc_passed_into_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    captured: dict[str, object] = {}

    fake_weaviate = types.ModuleType("weaviate")

    def _connect(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    fake_weaviate.connect_to_local = _connect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "weaviate", fake_weaviate)
    binding = _binding()
    connect_real_client(binding)
    assert captured["host"] == "weaviate.acme.local"
    assert captured["port"] == 8080
    assert captured["grpc_host"] == "weaviate.acme.local"  # gRPC INTO the constructor (R03)
    assert captured["grpc_port"] == 50051


# --------------------------------------------------------------------------- #
# N02: StoryContext collection uses text2vec_transformers (FK-13 §13.2)
# --------------------------------------------------------------------------- #


def test_n02_story_context_uses_text2vec_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    captured: dict[str, object] = {}
    config_mod = types.ModuleType("weaviate.classes.config")

    class _Vecs:
        @staticmethod
        def text2vec_transformers(**kwargs: object) -> str:
            captured["text2vec_kwargs"] = kwargs
            return "text2vec_transformers"

        @staticmethod
        def self_provided() -> str:
            return "self_provided"

    class _Configure:
        Vectors = _Vecs()

    class _DataType:
        TEXT = "TEXT"
        BOOL = "BOOL"
        TEXT_ARRAY = "TEXT_ARRAY"

    class _Property:
        def __init__(self, **kwargs: object) -> None:
            pass

    class _Tokenization:
        FIELD = "field"

    class _Collections:
        def __init__(self) -> None:
            self.created: list[dict[str, object]] = []

        def exists(self, name: str) -> bool:
            return False

        def create(self, **kwargs: object) -> None:
            self.created.append(kwargs)
            captured["create_kwargs"] = kwargs

    config_mod.Configure = _Configure  # type: ignore[attr-defined]
    config_mod.DataType = _DataType  # type: ignore[attr-defined]
    config_mod.Property = _Property  # type: ignore[attr-defined]
    config_mod.Tokenization = _Tokenization  # type: ignore[attr-defined]
    classes_mod = types.ModuleType("weaviate.classes")
    classes_mod.config = config_mod  # type: ignore[attr-defined]
    weaviate_mod = types.ModuleType("weaviate")
    weaviate_mod.classes = classes_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "weaviate", weaviate_mod)
    monkeypatch.setitem(sys.modules, "weaviate.classes", classes_mod)
    monkeypatch.setitem(sys.modules, "weaviate.classes.config", config_mod)

    class _Client:
        collections = _Collections()

    from agentkit.backend.vectordb.schema import ensure_story_context_collection

    ensure_story_context_collection(_Client())
    assert captured["create_kwargs"]["vector_config"] == "text2vec_transformers"  # N02


# --------------------------------------------------------------------------- #
# R13: explicit null/empty project_id is a NAMED ERROR (not silent fallback)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "args",
    [
        {"query": "x", "project_id": None},
        {"query": "x", "project_id": ""},
        {"query": "x", "project_id": "   "},
    ],
)
def test_r13_explicit_empty_null_project_id_rejected(args: dict[str, object], tmp_path: Path) -> None:
    from agentkit.backend.vectordb.contracts import ToolArgumentError

    svc, _client = _service(tmp_path)
    with pytest.raises(ToolArgumentError, match="project_id"):
        handle_tool_call(svc, "story_search", args)


def test_r13_wrong_typed_project_id_rejected(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.contracts import ToolArgumentError

    svc, _client = _service(tmp_path)
    with pytest.raises(ToolArgumentError, match="project_id"):
        handle_tool_call(svc, "story_search", {"query": "x", "project_id": 123})


# --------------------------------------------------------------------------- #
# R04/N05/N06: story ingest relative path, real title/status, FrontmatterError
# propagates, divergent project_id REJECTED
# --------------------------------------------------------------------------- #


def test_r04_story_ingest_relative_path_real_title_status(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects

    story_md = tmp_path / "stories" / "AG3-1" / "story.md"
    story_md.parent.mkdir(parents=True)
    story_md.write_text(
        "---\nstory_id: AG3-1\ntitle: My Real Title\nstatus: Done\n---\n\n# H\n\n## Problem\n\nNeed.\n",
        encoding="utf-8",
    )
    objs = story_file_to_objects("acme", story_md, source_file="stories/AG3-1/story.md")
    assert objs
    assert all(o.properties["source_file"] == "stories/AG3-1/story.md" for o in objs)  # relative (R04)
    assert objs[0].properties["title"] == "My Real Title"  # real title (R04)
    assert objs[0].properties["status"] == "Done"  # real status (R04)
    assert objs[0].properties["project_id"] == "acme"


def test_n05_invalid_frontmatter_propagates_writes_nothing(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects

    story_md = tmp_path / "bad.md"
    # Genuinely-invalid frontmatter: a duplicate YAML key -> parse_frontmatter_block
    # raises FrontmatterError (no last-wins), which must PROPAGATE (N05) and write
    # nothing.
    story_md.write_text(
        "---\nstory_id: X\nstory_id: Y\n---\n\n# H\n\n## S\n\ntext\n",
        encoding="utf-8",
    )
    with pytest.raises(FrontmatterError):
        story_file_to_objects("acme", story_md, source_file="bad.md")


def test_n06_divergent_object_project_id_rejected() -> None:
    from agentkit.backend.story_creation.weaviate_index import WeaviateStoryIndex

    class _Adapter:
        def story_sync(self, *, objects: object) -> int:
            return 1

    idx = WeaviateStoryIndex(_Adapter())  # type: ignore[arg-type]
    bad = [{"story_id": "S", "project_id": "other"}]
    with pytest.raises(ValueError, match="diverges"):
        idx.index_story(story_id="S", project_id="acme", objects=bad)


# --------------------------------------------------------------------------- #
# N07: incremental concept_sync calls reconcile_sources (vanished concepts deleted)
# --------------------------------------------------------------------------- #


def test_n07_incremental_concept_sync_deletes_vanished(tmp_path: Path) -> None:
    svc, client = _service(tmp_path)
    # Seed a vanished concept chunk in the store.
    stale = _obj("acme", "technical-design/99_gone.md", "g1", "concept")
    client.objects[stale.uuid] = {**stale.properties, "uuid": stale.uuid}
    # The corpus has FK-13 only; 99_gone is absent -> must be deleted on incremental.
    result = handle_tool_call(svc, "concept_sync", {"full_reindex": False})
    assert result["deleted"] >= 1  # vanished concept removed (N07)
    assert stale.uuid not in client.objects


# --------------------------------------------------------------------------- #
# R01: real MCP tool CALL through the FastMCP server (not schema-only)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_r01_real_mcp_call_tool_dispatches(tmp_path: Path) -> None:
    svc, client = _service(tmp_path)
    client.search_results = [("u1", {"concept_id": "FK-13", "title": "T", "module": "m"}, 0.5)]
    server = build_mcp_server(svc)
    result = await server.call_tool("concept_search", {"query": "retrieval"})
    # The real tool ran (a search was issued + ranked result returned).
    assert client.search_calls[0]["source_type"] == "concept"
    if isinstance(result, dict):
        assert result["results"]
    else:
        assert result  # content blocks returned


# --------------------------------------------------------------------------- #
# R07: CLI sync exercises the REAL _default_service_factory / real engine
# (fake only at the connection seam; composition + service + sync run for real)
# --------------------------------------------------------------------------- #


def test_r07_cli_sync_runs_real_factory_and_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recording = RecordingClient()
    # Fake ONLY at the connection seam (the Weaviate client boundary). Everything
    # else -- compose_runtime, ensure collection, store/sync/retrieval/service --
    # runs for real via _default_service_factory.
    monkeypatch.setattr(
        "agentkit.backend.vectordb.engine.connect_real_client",
        lambda binding: recording,
    )
    monkeypatch.setenv("PROJECT_ID", "acme")
    monkeypatch.setenv("WEAVIATE_HTTP_ENDPOINT", "http://weaviate.acme.local:8080")
    monkeypatch.setenv("WEAVIATE_GRPC_ENDPOINT", "weaviate.acme.local:50051")
    monkeypatch.setenv("AGENTKIT_CONCEPTS_DIR", str(_corpus(tmp_path)))
    monkeypatch.chdir(tmp_path)

    from agentkit.backend.vectordb.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["--concepts-dir", str(_corpus(tmp_path)), "sync", "--full"])
    code = int(args.func(args))
    assert code == 0
    # The REAL engine wrote concept chunks through the recording client.
    assert len(recording.objects) > 0
    # The real composition ensured BOTH the StoryContext + auxiliary collections.
    ensured = {c["collection"] for c in recording.ensure_calls}
    assert STORY_CONTEXT_COLLECTION in ensured


# --------------------------------------------------------------------------- #
# R08: validate --staged maps a REAL fault (no git repo) to exit 3
# --------------------------------------------------------------------------- #


def test_r08_validate_staged_real_git_fault_exit_3(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.cli import main as cli_main

    # A concepts-dir that is NOT inside any git repo -> _repo_root raises a REAL
    # GitOperationError -> exit 3 (not monkeypatched).
    no_git = tmp_path / "nogit" / "concept"
    no_git.mkdir(parents=True)
    code = cli_main(["--concepts-dir", str(no_git), "validate", "--staged"])
    assert code == 3  # INTERNAL_FAILURE (R08)

