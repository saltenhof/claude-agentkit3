"""Remediation proofs (Codex review r1): R01/R05/R11/R12/R13 + engine R02.

These STRENGTHEN behaviour (not names/shapes). Fakes live ONLY at the
CorpusStorePort / RetrievalPort / Weaviate boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.vectordb.concept_corpus.graph import build_graph
from agentkit.backend.vectordb.concept_corpus.resolver import rank_hits
from agentkit.backend.vectordb.contracts import (
    TOOL_NAMES,
    ToolArgumentError,
    allowed_keys_for,
)
from agentkit.backend.vectordb.engine import (
    RECEIPT_COLLECTION,
    WeaviateCorpusStore,
    _split_endpoint,
    _split_grpc,
)
from agentkit.backend.vectordb.mcp_server import McpToolService, build_mcp_server, handle_tool_call
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
from agentkit.backend.vectordb.schema import StoryContextObject, deterministic_uuid
from agentkit.backend.vectordb.sync import PartialWriteError, SyncReceipt, SyncService
from agentkit.concepts.parser import discover_concept_files

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_ENV = {
    "PROJECT_ID": "acme",
    "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.acme.local:8080",
    "WEAVIATE_GRPC_ENDPOINT": "weaviate.acme.local:50051",
}


# --------------------------------------------------------------------------- #
# R01: real inputSchema + required params + real MCP tool call for all 5
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_r01_each_tool_advertises_real_params_and_required() -> None:
    service = _minimal_service()
    server = build_mcp_server(service)
    tools = {t.name: t for t in await server.list_tools()}
    assert set(tools) == set(TOOL_NAMES)
    # required params are the real FK-13 ones, not a generic 'kwargs'.
    assert tools["story_search"].inputSchema["required"] == ["query"]
    assert tools["concept_search"].inputSchema["required"] == ["query"]
    assert "kwargs" not in tools["story_search"].inputSchema.get("properties", {})
    assert "query" in tools["story_search"].inputSchema["properties"]
    assert "search_mode" in tools["story_search"].inputSchema["properties"]
    assert "is_appendix" in tools["concept_search"].inputSchema["properties"]


def test_r01_allowed_keys_match_contract() -> None:
    assert allowed_keys_for("story_search") == frozenset(
        {"query", "search_mode", "project_id", "status", "story_type", "limit"}
    )
    assert allowed_keys_for("concept_sync") == frozenset(
        {"project_id", "full_reindex", "concept_path"}
    )


# --------------------------------------------------------------------------- #
# R02: engine composition + endpoint parsing (subprocess in test_engine_subprocess)
# --------------------------------------------------------------------------- #


def test_r02_split_endpoint_fail_closed() -> None:
    assert _split_endpoint("http://weaviate.acme.local:8080") == ("weaviate.acme.local", 8080)
    with pytest.raises(Exception, match="host:port"):
        _split_endpoint("http://weaviate.acme.local")  # no port


def test_r02_split_grpc_fail_closed() -> None:
    assert _split_grpc("weaviate.acme.local:50051") == ("weaviate.acme.local", 50051)
    with pytest.raises(Exception, match="host:port"):
        _split_grpc("weaviate.acme.local")
    with pytest.raises(Exception, match="non-integer port"):
        _split_grpc("weaviate.acme.local:notaport")


def test_r02_corpus_store_delegates_to_client_exact_counts() -> None:
    store = WeaviateCorpusStore(client=_FakeCorpusClient())
    objs = [_obj("acme", "stories/x/story.md", "c1", "story")]
    assert store.upsert_objects(objects=objs) == 1
    store.set_receipt(receipt=SyncReceipt.for_completion("acme", "stories/x/story.md", "story", "rev"))
    r = store.get_receipt(project_id="acme", source_file="stories/x/story.md")
    assert r is not None and r.corpus_revision == "rev"


# --------------------------------------------------------------------------- #
# R05: story + research ingestion via classifier, relative paths, delete-closure
# --------------------------------------------------------------------------- #


def test_r05_story_sync_ingests_story_and_research_relative(tmp_path: Path) -> None:
    (tmp_path / "stories" / "AG3-1").mkdir(parents=True)
    (tmp_path / "stories" / "AG3-1" / "story.md").write_text(
        "---\nstory_id: AG3-1\n---\n\n# T\n\n## P\n\nneed.\n", encoding="utf-8"
    )
    (tmp_path / "stories" / "AG3-1" / "research").mkdir()
    (tmp_path / "stories" / "AG3-1" / "research" / "findings.md").write_text(
        "---\nstory_id: AG3-1\n---\n\n# R\n\n## Findings\n\nfound.\n", encoding="utf-8"
    )
    # review*.md must NOT be ingested.
    (tmp_path / "stories" / "AG3-1" / "review-codex.md").write_text("# review\n", encoding="utf-8")
    (tmp_path / "concept" / "technical-design").mkdir(parents=True)
    (tmp_path / "concept" / "technical-design" / "13.md").write_text(
        "---\nconcept_id: FK-13\ntitle: T\nmodule: m\nstatus: active\ndoc_kind: core\n---\n\n# T\n\n## S\n\ns.\n",
        encoding="utf-8",
    )
    service = _service_with_cwd(tmp_path, tmp_path / "concept")
    result = handle_tool_call(service, "story_sync", {"full_reindex": True})
    sources = service._discover_story_corpus_objects("acme")  # noqa: SLF001
    rels = sorted(sources.keys())
    assert any(r.endswith("story.md") for r in rels)
    assert any("research/findings.md" in r for r in rels)
    assert not any("review" in r for r in rels)
    # paths are project-relative, not absolute
    assert all(not Path(r).is_absolute() for r in rels)
    # research objects carry source_type=research
    for rel, objs in sources.items():
        if "research" in rel:
            assert all(o.properties["source_type"] == "research" for o in objs)
    assert result["written"] >= 1


def test_r05_incremental_deletes_vanished_source(tmp_path: Path) -> None:
    (tmp_path / "stories" / "AG3-1").mkdir(parents=True)
    story_md = tmp_path / "stories" / "AG3-1" / "story.md"
    story_md.write_text("---\nstory_id: AG3-1\n---\n\n# T\n\n## P\n\nn.\n", encoding="utf-8")
    (tmp_path / "concept" / "technical-design").mkdir(parents=True)
    (tmp_path / "concept" / "technical-design" / "13.md").write_text(
        "---\nconcept_id: FK-13\ntitle: T\nmodule: m\nstatus: active\ndoc_kind: core\n---\n\n# T\n\n## S\n\ns.\n",
        encoding="utf-8",
    )
    service = _service_with_cwd(tmp_path, tmp_path / "concept")
    handle_tool_call(service, "story_sync", {"full_reindex": True})
    # Seed a STALE story source in the store, then vanish it (delete the file).
    store = service.sync.store
    stale = _obj("acme", "stories/AG3-GONE/story.md", "g1", "story")
    store.upsert_objects(objects=[stale])
    story_md.unlink()
    result = handle_tool_call(service, "story_sync", {"full_reindex": False})
    assert result["deleted"] >= 1


# --------------------------------------------------------------------------- #
# R11: shadow/generation identity (content edit -> new UUID, chunk_id stable)
# --------------------------------------------------------------------------- #


def test_r11_content_edit_changes_shadow_uuid_keeps_chunk_id(tmp_path: Path) -> None:
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    doc = dedent(
        """\
        ---
        concept_id: FK-13
        title: T
        module: m
        status: active
        doc_kind: core
        ---

        # T

        ## S

        original content
        """
    )
    (root / "13.md").write_text(doc, encoding="utf-8")
    before = next(c for c in discover_concept_files(tmp_path / "concept").chunks if "original" in c.content)
    (root / "13.md").write_text(doc.replace("original content", "edited content"), encoding="utf-8")
    after = next(c for c in discover_concept_files(tmp_path / "concept").chunks if "edited" in c.content)
    assert before.chunk_id == after.chunk_id  # stable logical identity
    assert before.shadow_id != after.shadow_id  # generation identity changed


def test_r11_object_uuid_is_shadow_bearing() -> None:
    from agentkit.backend.vectordb.ingest.adapter import _concept_chunk_to_object
    from agentkit.concepts.parser import ConceptChunk

    chunk = ConceptChunk(
        chunk_id="logical-1",
        shadow_id="shadow-1",
        source_file="concept/x.md",
        section_heading="h",
        section_number="1",
        content="c",
        content_hash="hash-1",
        concept_id="FK-1",
        title="T",
        module="m",
        concept_status="active",
        doc_kind="core",
        is_appendix=False,
        parent_concept_id="",
        defers_to=(),
        authority_over=(),
        normative_rules="",
        layer="technical",
        ordering=0,
    )
    obj = _concept_chunk_to_object("acme", chunk)
    # object UUID derived from shadow identity, not logical chunk_id
    assert obj.uuid == deterministic_uuid("acme", "concept/x.md", "shadow-1")
    assert obj.uuid != deterministic_uuid("acme", "concept/x.md", "logical-1")


# --------------------------------------------------------------------------- #
# R12: partial write/delete rejected, no receipt/success
# --------------------------------------------------------------------------- #


def test_r12_partial_upsert_rejected_no_receipt() -> None:
    store = _PartialStore(upsert_return=0)
    service = SyncService(store=store)
    with pytest.raises(PartialWriteError, match="partial write"):
        service.sync_source(
            project_id="acme", source_file="f", source_type="story",
            objects=[_obj("acme", "f", "c1", "story")], corpus_revision="rev",
        )
    # no receipt published
    assert store.get_receipt(project_id="acme", source_file="f") is None


def test_r12_should_set_not_persisted_rejected() -> None:
    store = _ShouldSetGapStore()
    service = SyncService(store=store)
    with pytest.raises(PartialWriteError, match="should-set not persisted"):
        service.sync_source(
            project_id="acme", source_file="f", source_type="story",
            objects=[_obj("acme", "f", "c1", "story")], corpus_revision="rev",
        )


def test_r12_partial_delete_rejected() -> None:
    store = _PartialStore(delete_return=0)
    service = SyncService(store=store)
    # seed an old object so there is something to delete
    old = _obj("acme", "f", "old", "story")
    store.objects[old.uuid] = {**old.properties, "uuid": old.uuid}
    with pytest.raises(PartialWriteError, match="partial delete"):
        service.sync_source(
            project_id="acme", source_file="f", source_type="story",
            objects=[_obj("acme", "f", "new", "story")], corpus_revision="rev",
        )


# --------------------------------------------------------------------------- #
# R13: unknown args + wrong-typed values rejected
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "tool,args,match",
    [
        ("story_search", {"query": "x", "bogus": 1}, "unknown argument"),
        ("story_search", {"query": "x", "project_id": 1}, "project_id"),
        ("story_search", {"query": "x", "status": False}, "status"),
        ("concept_search", {"query": "x", "concept_status": "published"}, "concept_status"),
        ("concept_search", {"query": "x", "limit": True}, "limit"),
        ("concept_search", {"query": "x", "module": 7}, "module"),
        ("story_sync", {"full_reindex": "yes"}, "full_reindex"),
    ],
)
def test_r13_wrong_typed_or_unknown_args_rejected(tool: str, args: dict[str, object], match: str) -> None:
    service = _minimal_service()
    with pytest.raises(ToolArgumentError, match=match):
        handle_tool_call(service, tool, args)


# --------------------------------------------------------------------------- #
# R10: resolver counterexamples per rule
# --------------------------------------------------------------------------- #


_CORE = dedent(
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

    ## P

    p.
    """
)
_CORE_DEFER = dedent(
    """\
    ---
    concept_id: FK-14
    title: Helper
    module: other
    status: active
    doc_kind: core
    defers_to:
      - target: FK-13
        scope: vectordb
    ---

    # Helper

    ## P

    p.
    """
)


def _graph(tmp_path: Path) -> object:
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "13.md").write_text(_CORE, encoding="utf-8")
    (root / "14.md").write_text(_CORE_DEFER, encoding="utf-8")
    return build_graph(discover_concept_files(tmp_path / "concept"))


def test_r10_rule1_authority_over_for_query_scope_outranks(tmp_path: Path) -> None:
    g = _graph(tmp_path)
    hits = [{"concept_id": "FK-14", "score": 0.9}, {"concept_id": "FK-13", "score": 0.5}]
    ranked = rank_hits(g, hits, query_scope="vectordb")
    assert ranked[0].concept_id == "FK-13"  # owns the queried scope despite lower base


def test_r10_rule2_scoped_authority_target_boosted(tmp_path: Path) -> None:
    # FK-14 defers_to FK-13 for scope "vectordb". Rule 2 boosts the TARGET
    # (FK-13), not the deferrer (FK-14) (R10 correction).
    g = _graph(tmp_path)
    hits = [{"concept_id": "FK-13", "score": 0.5}, {"concept_id": "FK-14", "score": 0.5}]
    ranked = rank_hits(g, hits, query_scope="vectordb")
    fk13 = next(r for r in ranked if r.concept_id == "FK-13")
    fk14 = next(r for r in ranked if r.concept_id == "FK-14")
    assert "scoped-authority-target" in fk13.reasons
    assert "scoped-authority-target" not in fk14.reasons
    assert fk13.authority_score > fk14.authority_score


def test_r10_rule4_archived_penalty(tmp_path: Path) -> None:
    arch = dedent(
        """\
        ---
        concept_id: FK-13
        title: T
        module: m
        status: active
        doc_kind: core
        authority_over:
          - scope: s
        ---

        # T

        ## P

        p.
        """
    )
    root = tmp_path / "concept"
    tdir = root / "technical-design"
    tdir.mkdir(parents=True)
    (tdir / "13.md").write_text(arch, encoding="utf-8")
    (root / "archiv").mkdir()
    (root / "archiv" / "13_old.md").write_text(arch.replace("FK-13", "FK-OLD"), encoding="utf-8")
    g = build_graph(discover_concept_files(root))
    hits = [{"concept_id": "FK-13", "score": 0.5}, {"concept_id": "FK-OLD", "score": 0.5}]
    ranked = rank_hits(g, hits)
    assert ranked[0].concept_id == "FK-13"


# --------------------------------------------------------------------------- #
# helpers / fakes
# --------------------------------------------------------------------------- #


def _obj(project_id: str, source_file: str, chunk_id: str, source_type: str) -> StoryContextObject:
    props = {
        "content": f"c-{chunk_id}", "source_type": source_type, "source_file": source_file,
        "project_id": project_id, "content_hash": f"h-{chunk_id}", "section_heading": "h",
    }
    return StoryContextObject(uuid=deterministic_uuid(project_id, source_file, chunk_id), properties=props)


@dataclass
class _FakeRetrieval:
    def search(self, **kwargs: object) -> Sequence[Mapping[str, object]]:
        return ()

    def list_sources(self, *, project_id: str) -> Sequence[Mapping[str, object]]:
        return ()


@dataclass
class _FakeStore:
    objects: dict[str, dict[str, object]] = field(default_factory=dict)
    receipts: dict[str, SyncReceipt] = field(default_factory=dict)
    _claims: set[tuple[str, str]] = field(default_factory=set)

    def list_objects_for_source(self, *, project_id: str, source_file: str) -> Sequence[Mapping[str, object]]:
        return [
            {"uuid": uid, "source_file": o["source_file"], "source_type": o["source_type"],
             "project_id": o["project_id"]}
            for uid, o in self.objects.items()
            if o["project_id"] == project_id and o["source_file"] == source_file
        ]

    def list_objects_for_source_types(self, *, project_id: str, source_types: Sequence[str]) -> Sequence[Mapping[str, object]]:
        types = set(source_types)
        return [
            {"uuid": uid, "source_file": o["source_file"], "source_type": o["source_type"],
             "project_id": o["project_id"]}
            for uid, o in self.objects.items()
            if o["project_id"] == project_id and o["source_type"] in types
        ]

    def upsert_objects(self, *, objects: Sequence[StoryContextObject]) -> int:
        for obj in objects:
            self.objects[obj.uuid] = {**obj.properties, "uuid": obj.uuid}
        return len(objects)

    def delete_objects(self, *, uuids: Sequence[str]) -> int:
        n = 0
        for uid in uuids:
            if uid in self.objects:
                del self.objects[uid]
                n += 1
        return n

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        return self.receipts.get(f"{project_id}|{source_file}")

    def set_receipt(self, *, receipt: SyncReceipt) -> None:
        self.receipts[f"{receipt.project_id}|{receipt.source_file}"] = receipt

    def try_claim_source(self, *, project_id: str, source_file: str) -> bool:
        key = (project_id, source_file)
        if key in self._claims:
            return False
        self._claims.add(key)
        return True

    def release_source(self, *, project_id: str, source_file: str) -> None:
        self._claims.discard((project_id, source_file))


@dataclass
class _PartialStore(_FakeStore):
    upsert_return: int | None = None
    delete_return: int | None = None

    def upsert_objects(self, *, objects: Sequence[StoryContextObject]) -> int:
        if self.upsert_return is not None:
            return self.upsert_return
        return super().upsert_objects(objects=objects)

    def delete_objects(self, *, uuids: Sequence[str]) -> int:
        if self.delete_return is not None:
            return self.delete_return
        return super().delete_objects(uuids=uuids)


@dataclass
class _ShouldSetGapStore(_FakeStore):
    """Upsert claims success but the should-set is NOT persisted (R12)."""

    def list_objects_for_source(self, *, project_id: str, source_file: str) -> Sequence[Mapping[str, object]]:
        return []  # nothing persisted -> should-set gap


@dataclass
class _FakeCorpusClient:
    """Fake at the thin-adapter corpus boundary (R02)."""

    receipt_docs: dict[str, dict[str, object]] = field(default_factory=dict)

    def fetch_by_property(
        self, *, collection: str, prop: str, value: str, return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]:
        if collection == RECEIPT_COLLECTION:
            for uid, doc in self.receipt_docs.items():
                if str(doc.get(prop)) == value:
                    return [(uid, {k: doc.get(k) for k in return_props})]
            return []
        return [(
            "u1",
            {"source_file": value, "source_type": "story", "project_id": "acme", "content_hash": "h"},
        )]

    def fetch_by_property_any(
        self, *, collection: str, prop: str, values: Sequence[str], return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]:
        return []

    def upsert(self, *, collection: str, objects: Sequence[Mapping[str, object]]) -> int:
        if collection == RECEIPT_COLLECTION:
            for obj in objects:
                self.receipt_docs[str(obj.get("uuid"))] = dict(obj)
        return len(objects)

    def delete_by_ids(self, *, collection: str, uuids: Sequence[str]) -> int:
        return len(uuids)

    def ensure_collection(self, *, collection: str, property_specs: Sequence[Mapping[str, object]]) -> None:
        return None


def _minimal_service() -> McpToolService:
    import tempfile

    d = Path(tempfile.mkdtemp())
    (d / "concept" / "technical-design").mkdir(parents=True)
    (d / "concept" / "technical-design" / "13.md").write_text(
        "---\nconcept_id: FK-13\ntitle: T\nmodule: m\nstatus: active\ndoc_kind: core\n---\n\n# T\n\n## S\n\ns.\n",
        encoding="utf-8",
    )
    binding = RuntimeBinding.from_env(_ENV, command="python", args=(), cwd=str(d))
    return McpToolService(
        binding=binding, retrieval=_FakeRetrieval(), sync=SyncService(store=_FakeStore()),
        concepts_dir=d / "concept", stories_dir=d,
    )


def _service_with_cwd(cwd: Path, concepts_dir: Path) -> McpToolService:
    binding = RuntimeBinding.from_env(_ENV, command="python", args=(), cwd=str(cwd))
    return McpToolService(
        binding=binding, retrieval=_FakeRetrieval(), sync=SyncService(store=_FakeStore()),
        concepts_dir=concepts_dir, stories_dir=cwd,
    )
