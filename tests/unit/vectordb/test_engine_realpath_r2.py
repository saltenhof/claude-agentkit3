"""REAL-PATH proofs for the engine cluster (Codex reviews r2 + r3).

Every test exercises the REAL production code (``WeaviateCorpusStore``,
``WeaviateRetrievalPort``, ``SyncService``, ``McpToolService``, the ingest
adapter, the CLI composition) with a double ONLY at the Weaviate CLIENT boundary
that RECORDS what production actually did (exact query, source_type, filters,
counts, property profile) and is held to the same strictness as the real
transport. Nothing is monkeypatched to a normalised exception; real faults
trigger real behaviour.
"""

from __future__ import annotations

import threading
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
from tests.unit.vectordb.corpus_doubles import (
    RecordingWeaviateClient,
    chunk_object,
    concept_hit,
    corpus_store,
    story_hit,
)

from agentkit.backend.vectordb.contracts import ToolArgumentError
from agentkit.backend.vectordb.engine import (
    RECEIPT_COLLECTION,
    WeaviateRetrievalPort,
    receipt_from_props,
)
from agentkit.backend.vectordb.mcp_server import McpToolService, handle_tool_call
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
from agentkit.backend.vectordb.schema import STORY_CONTEXT_COLLECTION
from agentkit.backend.vectordb.sync import ConcurrentSyncRejectedError, PartialWriteError, SyncService
from agentkit.concepts.parser import discover_concept_files
from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

_ENV = {
    "PROJECT_ID": "acme",
    "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.acme.local:8080",
    "WEAVIATE_GRPC_ENDPOINT": "weaviate.acme.local:50051",
}

_CONCEPT_DOC = dedent(
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
)

_APPENDIX_DOC = dedent(
    """\
    ---
    concept_id: FK-13-A
    title: Retrieval interfaces
    module: vectordb
    status: active
    doc_kind: appendix
    parent_concept_id: FK-13
    ---

    # Retrieval interfaces

    ## Signatures

    Tool signatures.
    """
)

_STORY_DOC = dedent(
    """\
    ---
    story_id: AG3-1
    title: A real story title
    status: Done
    story_type: implementation
    ---

    # A real story title

    ## Problem

    Something needs doing.
    """
)


def _binding(cwd: str = ".") -> RuntimeBinding:
    return RuntimeBinding.from_env(_ENV, command="python", args=(), cwd=cwd)


def _corpus(tmp_path: Path, *, with_appendix: bool = False) -> Path:
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True, exist_ok=True)
    (root / "13_retrieval.md").write_text(_CONCEPT_DOC, encoding="utf-8")
    if with_appendix:
        (root / "13a_interfaces.md").write_text(_APPENDIX_DOC, encoding="utf-8")
    return tmp_path / "concept"


def _service(
    tmp_path: Path,
    client: RecordingWeaviateClient | None = None,
    *,
    with_appendix: bool = False,
) -> tuple[McpToolService, RecordingWeaviateClient]:
    client = client or RecordingWeaviateClient()
    binding = _binding(str(tmp_path))
    store = corpus_store(client)
    service = McpToolService(
        binding=binding,
        retrieval=WeaviateRetrievalPort(client=client, store=store, binding=binding),  # type: ignore[arg-type]
        sync=SyncService(store=store),
        concepts_dir=_corpus(tmp_path, with_appendix=with_appendix),
        stories_dir=tmp_path,
    )
    return service, client


# --------------------------------------------------------------------------- #
# R02/N01/R05: concept_search issues a REAL scoped query with the full profile
# --------------------------------------------------------------------------- #


def test_r02_concept_search_issues_real_scoped_query(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    client.search_results = [concept_hit("u1", "FK-13", 0.9)]
    handle_tool_call(service, "concept_search", {"query": "retrieval"})
    assert len(client.search_calls) == 1
    call = client.search_calls[0]
    assert call["collection"] == STORY_CONTEXT_COLLECTION
    assert call["source_type"] == "concept"
    assert call["filters"]["concept_status"] == "active"  # default active (AC7)
    assert call["search_mode"] == "hybrid"
    assert call["project_id"] == "acme"
    # The requested property profile carries the concept extension (N11/§13.9.3).
    requested = {name for name, _dt, _ne in call["property_spec"]}  # type: ignore[union-attr]
    assert {"concept_id", "is_appendix", "defers_to", "concept_status"} <= requested


def test_r02_full_properties_returned(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    client.search_results = [concept_hit("u1", "FK-13", 0.8)]
    result = handle_tool_call(service, "concept_search", {"query": "r"})
    assert result["results"][0]["concept_id"] == "FK-13"
    assert result["results"][0]["module"] == "vectordb"  # full props preserved (N01)


def test_r05_story_search_covers_both_owned_types(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    handle_tool_call(service, "story_search", {"query": "x", "status": "Done"})
    source_types = sorted(str(c["source_type"]) for c in client.search_calls)
    assert source_types == ["research", "story"]
    for call in client.search_calls:
        assert call["filters"]["status"] == "Done"
        assert call["project_id"] == "acme"


# --------------------------------------------------------------------------- #
# N09: story_search honours the limit AND ranks globally by score
# --------------------------------------------------------------------------- #


def test_n09_story_search_merges_globally_and_truncates_to_limit(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    # Research scores INTERLEAVE with story scores; the top-3 by score are
    # research(0.95), story(0.9), research(0.8).
    client.search_results = [
        story_hit("s1", "AG3-1", 0.90),
        story_hit("s2", "AG3-2", 0.50),
        story_hit("s3", "AG3-3", 0.10),
        story_hit(
            "r1", "AG3-9", 0.95, source_type="research",
            source_file="stories/AG3-9/research/a.md",
        ),
        story_hit(
            "r2", "AG3-9", 0.80, source_type="research",
            source_file="stories/AG3-9/research/b.md",
        ),
        story_hit(
            "r3", "AG3-9", 0.05, source_type="research",
            source_file="stories/AG3-9/research/c.md",
        ),
    ]
    result = handle_tool_call(service, "story_search", {"query": "x", "limit": 3})
    results = result["results"]
    assert len(results) == 3, "the limit is a GLOBAL cap, not per source type (N09)"
    scores = [float(str(r["score"])) for r in results]
    assert scores == sorted(scores, reverse=True)
    assert scores == [0.95, 0.90, 0.80]
    # Global order means research CAN outrank story (no source-type grouping).
    assert results[0]["source_type"] == "research"
    # Each source type was queried with the bounded candidate limit.
    assert [c["limit"] for c in client.search_calls] == [3, 3]


# --------------------------------------------------------------------------- #
# N10: several section hits of the SAME concept survive ranking
# --------------------------------------------------------------------------- #


def test_n10_multiple_section_hits_of_one_concept_are_all_returned(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    client.search_results = [
        concept_hit("u1", "FK-13", 0.9, section_heading="Purpose", section_number="1"),
        concept_hit("u2", "FK-13", 0.8, section_heading="Data model", section_number="2"),
        concept_hit("u3", "FK-13", 0.7, section_heading="Tools", section_number="3"),
    ]
    result = handle_tool_call(service, "concept_search", {"query": "retrieval"})
    headings = [r["section_heading"] for r in result["results"]]
    assert len(result["results"]) == 3, "no hit may collapse onto its concept_id (N10)"
    assert sorted(headings) == ["Data model", "Purpose", "Tools"]
    assert all("authority_score" in r for r in result["results"])


# --------------------------------------------------------------------------- #
# R10: rule 3 is REACHABLE through concept_search (query detail is derived)
# --------------------------------------------------------------------------- #


def test_r10_rule3_appendix_boost_is_reachable_via_concept_search(tmp_path: Path) -> None:
    service, client = _service(tmp_path, with_appendix=True)
    client.search_results = [
        concept_hit("u1", "FK-13", 0.5),
        concept_hit("u2", "FK-13-A", 0.5, is_appendix=True, source_file="technical-design/13a_interfaces.md"),
    ]
    detail = handle_tool_call(service, "concept_search", {"query": "tool interface signatures"})
    appendix = next(r for r in detail["results"] if r["concept_id"] == "FK-13-A")
    assert "appendix-interface" in appendix["rank_reasons"], (
        "a query asking for interface detail must reach rule 3 (R10)"
    )
    assert appendix["authority_score"] > 0.5

    plain = handle_tool_call(service, "concept_search", {"query": "how does retrieval work"})
    appendix_plain = next(r for r in plain["results"] if r["concept_id"] == "FK-13-A")
    assert "appendix-interface" not in appendix_plain["rank_reasons"]


# --------------------------------------------------------------------------- #
# N04: the story revision is NOT the concept digest; latest = last completion
# --------------------------------------------------------------------------- #


def test_n04_story_revision_is_distinct_from_the_concept_corpus_digest(tmp_path: Path) -> None:
    story_md = tmp_path / "stories" / "AG3-1" / "story.md"
    story_md.parent.mkdir(parents=True)
    story_md.write_text(_STORY_DOC, encoding="utf-8")
    service, _client = _service(tmp_path)
    concept_revision = discover_concept_files(service.concepts_dir).corpus_revision

    first = handle_tool_call(service, "story_sync", {"full_reindex": True})
    assert first["corpus_revision"] != concept_revision, (
        "the story corpus revision must not be the concept-corpus digest (N04/D1)"
    )
    assert first["written"] >= 1

    # Editing a STORY changes the story revision (the concept corpus is untouched).
    story_md.write_text(_STORY_DOC.replace("Something needs doing.", "Changed."), encoding="utf-8")
    second = handle_tool_call(service, "story_sync", {"full_reindex": True})
    assert second["corpus_revision"] != first["corpus_revision"]
    assert discover_concept_files(service.concepts_dir).corpus_revision == concept_revision


def test_n04_last_revision_is_the_last_completion_not_the_lexicographic_max(
    tmp_path: Path,
) -> None:
    service, client = _service(tmp_path)
    store = service.sync.store
    # Complete 'zzz' FIRST, then 'aaa': the LAST completion is 'aaa', which is
    # the lexicographically SMALLER value.
    service.sync.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "a1")], corpus_revision="zzz-first",
    )
    service.sync.sync_source(
        project_id="acme", source_file="concept/b.md", source_type="concept",
        objects=[chunk_object("acme", "concept/b.md", "b1")], corpus_revision="aaa-last",
    )
    result = handle_tool_call(service, "story_list_sources", {})
    concept_row = next(s for s in result["sources"] if s["source_type"] == "concept")
    assert concept_row["last_revision"] == "aaa-last"
    assert concept_row["chunk_count"] == 2
    assert concept_row["source_count"] == 2
    assert concept_row["producer"] == "concept_sync"
    # The completion sequence is what carries the order.
    a = store.get_receipt(project_id="acme", source_file="concept/a.md")
    b = store.get_receipt(project_id="acme", source_file="concept/b.md")
    assert a is not None and b is not None and b.sequence > a.sequence


# --------------------------------------------------------------------------- #
# N08: a malformed / tampered receipt must never advance the freshness
# --------------------------------------------------------------------------- #


def _tamper_receipt(client: RecordingWeaviateClient, **overrides: object) -> None:
    uid, doc = next(iter(client.receipts.items()))
    client.receipts[uid] = {**doc, **overrides}


def test_n08_tampered_receipt_digest_is_fail_closed(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    service.sync.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "a1")], corpus_revision="rev-1",
    )
    # A receipt claiming a NEWER revision than its digest binds must not be trusted.
    _tamper_receipt(client, corpus_revision="rev-999")
    with pytest.raises(VectorDbUnavailableError, match="digest"):
        service.sync.store.get_receipt(project_id="acme", source_file="concept/a.md")
    envelope = handle_tool_call(service, "story_list_sources", {})
    assert envelope["error"] == "vectordb_unavailable"
    assert "last_revision" not in envelope


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"corpus_revision": ""}, "corpus_revision"),
        ({"source_type": 7}, "source_type"),
        ({"completed_at": None}, "completed_at"),
        ({"sequence": "not-a-number"}, "sequence"),
        ({"sequence": "0"}, "sequence"),
    ],
)
def test_n08_malformed_receipt_fields_are_fail_closed(
    tmp_path: Path, overrides: dict[str, object], match: str
) -> None:
    service, client = _service(tmp_path)
    service.sync.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "a1")], corpus_revision="rev-1",
    )
    _tamper_receipt(client, **overrides)
    with pytest.raises(VectorDbUnavailableError, match=match):
        service.sync.store.get_receipt(project_id="acme", source_file="concept/a.md")


def test_n08_receipt_from_props_rejects_a_foreign_identity() -> None:
    from agentkit.concepts.hashing import sync_receipt_digest

    props = {
        "project_id": "other",
        "source_file": "concept/a.md",
        "source_type": "concept",
        "corpus_revision": "rev",
        "digest": sync_receipt_digest("other", "concept/a.md", "rev"),
        "state": "completed",
        "completed_at": "2026-07-25T00:00:00Z",
        "sequence": "1",
    }
    with pytest.raises(VectorDbUnavailableError, match="identity mismatch"):
        receipt_from_props("acme", "concept/a.md", props)


def test_n08_receipt_collection_write_uses_one_stable_record(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    for revision in ("rev-1", "rev-2", "rev-3"):
        service.sync.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "a1")], corpus_revision=revision,
        )
    assert len(client.receipts) == 1
    doc = next(iter(client.receipts.values()))
    assert doc["corpus_revision"] == "rev-3"
    assert doc["sequence"] == "3"


# --------------------------------------------------------------------------- #
# N03: a GENUINE two-writer race -- exactly one wins, no manual pre-claim
# --------------------------------------------------------------------------- #


def test_n03_two_racing_writers_of_one_source_exactly_one_wins() -> None:
    client = RecordingWeaviateClient()
    # Both writers contend for the claim at the SAME instant; a read-then-write
    # claim would let both observe "no claim" and both win.
    client.insert_barrier = threading.Barrier(2, timeout=10)
    client.fetch_barrier = threading.Barrier(2, timeout=10)
    store = corpus_store(client)
    outcomes: list[str] = []
    lock = threading.Lock()

    def _writer(chunk: str) -> None:
        service = SyncService(store=store)
        try:
            service.sync_source(
                project_id="acme", source_file="concept/a.md", source_type="concept",
                objects=[chunk_object("acme", "concept/a.md", chunk)],
                corpus_revision="rev",
            )
            outcome = "won"
        except ConcurrentSyncRejectedError:
            outcome = "rejected"
        with lock:
            outcomes.append(outcome)

    threads = [
        threading.Thread(target=_writer, args=("c1",)),
        threading.Thread(target=_writer, args=("c2",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(outcomes) == ["rejected", "won"], (
        "exactly one racing writer may win the store-level claim (N03/D3)"
    )
    # Only the winner's single generation is in the store.
    assert len(client.objects) == 1
    assert len(client.receipts) == 1


# --------------------------------------------------------------------------- #
# R12: partial delete in the incremental reconcile -> no receipt, no success
# --------------------------------------------------------------------------- #


def test_r12_reconcile_partial_delete_rejected_no_receipt(tmp_path: Path) -> None:
    client = RecordingWeaviateClient()
    stale_a = chunk_object("acme", "gone.md", "a1")
    stale_b = chunk_object("acme", "gone.md", "b1")
    for obj in (stale_a, stale_b):
        client.objects[obj.uuid] = {**obj.properties, "uuid": obj.uuid}
    client.delete_confirmed_override = 1  # only 1 of 2 confirmed
    store = corpus_store(client)
    service = SyncService(store=store)
    with pytest.raises(PartialWriteError, match="partial delete"):
        service.reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source={}, corpus_revision="rev",
        )
    assert store.get_receipt(project_id="acme", source_file="gone.md") is None
    assert RECEIPT_COLLECTION not in {c["collection"] for c in client.ensure_calls}


# --------------------------------------------------------------------------- #
# R13: an explicit null/empty is a NAMED error for EVERY optional argument
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "tool,args,match",
    [
        ("story_search", {"query": "x", "project_id": None}, "project_id"),
        ("story_search", {"query": "x", "project_id": ""}, "project_id"),
        ("story_search", {"query": "x", "project_id": 123}, "project_id"),
        ("story_search", {"query": "x", "limit": None}, "limit"),
        ("story_search", {"query": "x", "search_mode": None}, "search_mode"),
        ("story_search", {"query": "x", "search_mode": ""}, "search_mode"),
        ("story_search", {"query": "x", "status": None}, "status"),
        ("story_search", {"query": "x", "status": ""}, "status"),
        ("story_search", {"query": "x", "story_type": None}, "story_type"),
        ("story_sync", {"full_reindex": None}, "full_reindex"),
        ("story_list_sources", {"project_id": None}, "project_id"),
        ("concept_search", {"query": "x", "concept_status": None}, "concept_status"),
        ("concept_search", {"query": "x", "concept_id": None}, "concept_id"),
        ("concept_search", {"query": "x", "module": None}, "module"),
        ("concept_search", {"query": "x", "is_appendix": None}, "is_appendix"),
        ("concept_search", {"query": "x", "limit": None}, "limit"),
        ("concept_sync", {"full_reindex": None}, "full_reindex"),
        ("concept_sync", {"concept_path": None}, "concept_path"),
    ],
)
def test_r13_explicit_null_or_empty_optional_is_a_named_error(
    tmp_path: Path, tool: str, args: dict[str, object], match: str
) -> None:
    service, client = _service(tmp_path)
    with pytest.raises(ToolArgumentError, match=match):
        handle_tool_call(service, tool, args)
    assert client.search_calls == []
    assert client.objects == {}


def test_r13_absent_optional_falls_back_to_the_documented_default(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    client.search_results = [concept_hit("u1", "FK-13", 0.5)]
    handle_tool_call(service, "concept_search", {"query": "x"})
    call = client.search_calls[0]
    assert call["limit"] == 10  # DEFAULT_LIMIT
    assert call["search_mode"] == "hybrid"
    assert call["project_id"] == "acme"
    assert call["filters"] == {"concept_status": "active"}


# --------------------------------------------------------------------------- #
# N05: a story source without frontmatter blocks the sync (zero writes)
# --------------------------------------------------------------------------- #


def test_n05_story_without_frontmatter_blocks_the_whole_sync(tmp_path: Path) -> None:
    good = tmp_path / "stories" / "AG3-1" / "story.md"
    good.parent.mkdir(parents=True)
    good.write_text(_STORY_DOC, encoding="utf-8")
    bad = tmp_path / "stories" / "AG3-2" / "story.md"
    bad.parent.mkdir(parents=True)
    bad.write_text("# No frontmatter here\n\n## S\n\ntext\n", encoding="utf-8")
    service, client = _service(tmp_path)
    result = handle_tool_call(service, "story_sync", {"full_reindex": True})
    assert result["error"] == "story_source_invalid"
    assert result["written"] == 0
    assert client.objects == {}, "not even the parsable subset may be indexed (AC10)"
    assert client.receipts == {}


def test_n05_story_metadata_is_not_coerced(tmp_path: Path) -> None:
    story = tmp_path / "stories" / "AG3-1" / "story.md"
    story.parent.mkdir(parents=True)
    story.write_text(
        "---\nstory_id: AG3-1\nstatus: 42\n---\n\n# T\n\n## S\n\ntext\n", encoding="utf-8"
    )
    service, client = _service(tmp_path)
    result = handle_tool_call(service, "story_sync", {"full_reindex": True})
    assert result["error"] == "story_source_invalid"
    assert "status" in result["detail"]
    assert client.objects == {}


# --------------------------------------------------------------------------- #
# concept_path (FK-13 §13.9.5) is honoured, not ignored
# --------------------------------------------------------------------------- #


def test_concept_path_syncs_only_the_selected_document(tmp_path: Path) -> None:
    service, client = _service(tmp_path, with_appendix=True)
    result = handle_tool_call(
        service, "concept_sync", {"concept_path": "technical-design/13a_interfaces.md"}
    )
    assert result["synced_sources"] == 1
    assert result["written"] >= 1
    indexed = {str(doc["source_file"]) for doc in client.objects.values()}
    assert indexed == {"technical-design/13a_interfaces.md"}


def test_concept_path_unknown_document_is_a_named_zero_write_error(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    result = handle_tool_call(service, "concept_sync", {"concept_path": "nope/absent.md"})
    assert result["error"] == "concept_path_unknown"
    assert result["written"] == 0
    assert client.objects == {}


def test_concept_path_with_full_reindex_is_rejected(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    result = handle_tool_call(
        service,
        "concept_sync",
        {"concept_path": "technical-design/13_retrieval.md", "full_reindex": True},
    )
    assert result["error"] == "concept_path_with_full_reindex"
    assert client.objects == {}


# --------------------------------------------------------------------------- #
# N07: incremental concept_sync deletes vanished concept chunks
# --------------------------------------------------------------------------- #


def test_n07_incremental_concept_sync_deletes_vanished(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    stale = chunk_object("acme", "technical-design/99_gone.md", "g1")
    client.objects[stale.uuid] = {**stale.properties, "uuid": stale.uuid}
    result = handle_tool_call(service, "concept_sync", {"full_reindex": False})
    assert result["deleted"] >= 1
    assert stale.uuid not in client.objects


# --------------------------------------------------------------------------- #
# R07: CLI sync exercises the REAL _default_service_factory / real engine
# --------------------------------------------------------------------------- #


def test_r07_cli_sync_runs_real_factory_and_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recording = RecordingWeaviateClient()
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
    assert len(recording.objects) > 0
    ensured = {c["collection"]: c["vectorizer"] for c in recording.ensure_calls}
    assert ensured[STORY_CONTEXT_COLLECTION] == "text2vec_transformers"  # FK-13 §13.2
    assert ensured[RECEIPT_COLLECTION] == "self_provided"


# --------------------------------------------------------------------------- #
# R08: validate --staged maps a REAL fault (no git repo) to exit 3
# --------------------------------------------------------------------------- #


def test_r08_validate_staged_real_git_fault_exit_3(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.cli import main as cli_main

    no_git = tmp_path / "nogit" / "concept"
    no_git.mkdir(parents=True)
    code = cli_main(["--concepts-dir", str(no_git), "validate", "--staged"])
    assert code == 3  # INTERNAL_FAILURE (R08)
