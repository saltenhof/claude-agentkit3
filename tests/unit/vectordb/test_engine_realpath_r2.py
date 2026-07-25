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
from agentkit.backend.vectordb.schema import (
    FK13_VECTOR_SOURCE_PROPERTIES,
    FK13_VECTORIZER_MODEL,
    STORY_CONTEXT_COLLECTION,
)
from agentkit.backend.vectordb.sync import (
    ConcurrentSyncRejectedError,
    PartialWriteError,
    SyncReceipt,
    SyncService,
)
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

#: A DRAFT document that owns the ``chunking`` scope. Rule 1 must not lift it over
#: an active document: rule 4 demotes by WHOLE tiers (§13.9.11).
_DRAFT_OWNER_DOC = dedent(
    """\
    ---
    concept_id: FK-90
    title: Chunking draft
    module: planning
    status: draft
    doc_kind: core
    authority_over:
      - scope: chunking
    ---

    # Chunking draft

    ## Sizes

    Draft chunk sizes.
    """
)

#: A document in ANOTHER module that DEFERS to FK-13 for the ``chunking`` scope.
#: FK-13 does not own that scope directly, so with ``authority_scope=chunking``
#: only rule 2 can lift it -- and the credit must accrue to the deferral TARGET.
_DEFERRING_DOC = dedent(
    """\
    ---
    concept_id: FK-11
    title: Evaluation
    module: evaluator
    status: active
    doc_kind: core
    defers_to:
      - target: FK-13
        scope: chunking
        reason: Chunking is owned by the retrieval concept
    ---

    # Evaluation

    ## Chunking

    Chunking rules live in the retrieval concept.
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


def _corpus(
    tmp_path: Path,
    *,
    with_appendix: bool = False,
    with_deferral: bool = False,
    with_draft_owner: bool = False,
) -> Path:
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True, exist_ok=True)
    (root / "13_retrieval.md").write_text(_CONCEPT_DOC, encoding="utf-8")
    if with_appendix:
        (root / "13a_interfaces.md").write_text(_APPENDIX_DOC, encoding="utf-8")
    if with_deferral:
        (root / "11_evaluation.md").write_text(_DEFERRING_DOC, encoding="utf-8")
    if with_draft_owner:
        (root / "90_chunking_draft.md").write_text(_DRAFT_OWNER_DOC, encoding="utf-8")
    return tmp_path / "concept"


def _service(
    tmp_path: Path,
    client: RecordingWeaviateClient | None = None,
    *,
    with_appendix: bool = False,
    with_deferral: bool = False,
    with_draft_owner: bool = False,
) -> tuple[McpToolService, RecordingWeaviateClient]:
    client = client or RecordingWeaviateClient()
    binding = _binding(str(tmp_path))
    store = corpus_store(client)
    service = McpToolService(
        binding=binding,
        retrieval=WeaviateRetrievalPort(client=client, store=store, binding=binding),  # type: ignore[arg-type]
        sync=SyncService(store=store),
        concepts_dir=_corpus(
            tmp_path,
            with_appendix=with_appendix,
            with_deferral=with_deferral,
            with_draft_owner=with_draft_owner,
        ),
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
    assert call["filters"]["concept_status"] == ("active",)  # default active (AC7/D8)
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
        # N16: an UNKNOWN receipt state is REJECTED, never silently skipped.
        ({"state": "half_done"}, "unknown state"),
        ({"state": "in_progress"}, "does not bind"),
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
        "digest": sync_receipt_digest(
            project_id="other",
            source_file="concept/a.md",
            source_type="concept",
            corpus_revision="rev",
            state="completed",
            completed_at="2026-07-25T00:00:00Z",
            sequence=1,
        ),
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
        # Distinct owner ids: two writers, whether in one process or two, must
        # conflict (the claim is not process-local, N15).
        service = SyncService(store=store, owner_id=f"writer-{chunk}")
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
    assert call["filters"] == {"concept_status": ("active",)}


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
    # The REAL composition declares WHAT is embedded, from the schema SSOT (N35).
    story_call = next(
        c for c in recording.ensure_calls if c["collection"] == STORY_CONTEXT_COLLECTION
    )
    assert story_call["vector_source_properties"] == FK13_VECTOR_SOURCE_PROPERTIES
    assert story_call["vectorizer_model"] == FK13_VECTORIZER_MODEL


# --------------------------------------------------------------------------- #
# R08: validate --staged maps a REAL fault (no git repo) to exit 3
# --------------------------------------------------------------------------- #


def test_r08_validate_staged_real_git_fault_exit_3(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.cli import main as cli_main

    no_git = tmp_path / "nogit" / "concept"
    no_git.mkdir(parents=True)
    code = cli_main(["--concepts-dir", str(no_git), "validate", "--staged"])
    assert code == 3  # INTERNAL_FAILURE (R08)


# --------------------------------------------------------------------------- #
# N19/N01/R05: the ADVERTISED response contract is requested AND returned
# --------------------------------------------------------------------------- #


def test_n19_story_search_returns_every_advertised_response_field(tmp_path: Path) -> None:
    """Every field ``story_search`` advertises must arrive through the real path."""
    from agentkit.backend.vectordb.contracts import contract_for

    service, client = _service(tmp_path)
    client.search_results = [story_hit("s1", "AG3-1", 0.9)]
    result = handle_tool_call(service, "story_search", {"query": "x"})
    row = result["results"][0]
    for advertised in contract_for("story_search").return_fields:
        assert advertised in row, advertised
    assert row["module"] == "backend"
    assert row["epic"] == "retrieval"
    # ...and the transport was ASKED for them (a profile that omits module/epic
    # cannot return them, N19).
    requested = {name for name, _dt, _ne in client.search_calls[0]["property_spec"]}  # type: ignore[union-attr]
    assert {"module", "epic"} <= requested


def test_n19_concept_search_returns_every_advertised_response_field(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.contracts import contract_for

    service, client = _service(tmp_path)
    client.search_results = [concept_hit("c1", "FK-13", 0.9)]
    result = handle_tool_call(service, "concept_search", {"query": "x"})
    row = result["results"][0]
    for advertised in contract_for("concept_search").return_fields:
        assert advertised in row, advertised
    requested = {name for name, _dt, _ne in client.search_calls[0]["property_spec"]}  # type: ignore[union-attr]
    assert {"defers_to", "authority_over", "normative_rules"} <= requested


def test_n19_research_hits_carry_the_story_profile(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    client.search_results = [
        story_hit(
            "r1", "AG3-9", 0.5, source_type="research",
            source_file="stories/AG3-9/research/a.md", story_type="research",
        )
    ]
    result = handle_tool_call(service, "story_search", {"query": "x"})
    assert result["results"][0]["story_type"] == "research"
    assert result["results"][0]["module"] == "backend"


# --------------------------------------------------------------------------- #
# N24: research notes are identified by their PATH, not by story frontmatter
# --------------------------------------------------------------------------- #


def test_n24_research_note_without_frontmatter_is_ingested(tmp_path: Path) -> None:
    """A plain research note must NOT break the sync (its producer is the path)."""
    story = tmp_path / "stories" / "AG3-1" / "story.md"
    story.parent.mkdir(parents=True)
    story.write_text(_STORY_DOC, encoding="utf-8")
    note = tmp_path / "stories" / "AG3-1" / "research" / "findings.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Weaviate options\n\n## Findings\n\nBM25 needs word tokens.\n", encoding="utf-8")

    service, client = _service(tmp_path)
    result = handle_tool_call(service, "story_sync", {"full_reindex": True})
    assert "error" not in result
    indexed = {
        str(doc["source_file"]): doc for doc in client.objects.values()
    }
    research = indexed["stories/AG3-1/research/findings.md"]
    assert research["source_type"] == "research"
    # The story identity comes from the canonical path, the title from the note's
    # own heading, and the type is 'research' (FK-13 §13.3.1 story_type vocabulary).
    assert research["story_id"] == "AG3-1"
    assert research["title"] == "Weaviate options"
    assert research["story_type"] == "research"
    assert research["status"] == ""


def test_n24_research_frontmatter_is_still_validated_strictly(tmp_path: Path) -> None:
    story = tmp_path / "stories" / "AG3-1" / "story.md"
    story.parent.mkdir(parents=True)
    story.write_text(_STORY_DOC, encoding="utf-8")
    note = tmp_path / "stories" / "AG3-1" / "research" / "findings.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\ntitle: 42\n---\n\n# R\n\n## F\n\nfound.\n", encoding="utf-8")
    service, client = _service(tmp_path)
    result = handle_tool_call(service, "story_sync", {"full_reindex": True})
    assert result["error"] == "story_source_invalid"
    assert "title" in result["detail"]
    assert client.objects == {}


def test_n24_research_story_id_contradicting_the_path_is_rejected(tmp_path: Path) -> None:
    story = tmp_path / "stories" / "AG3-1" / "story.md"
    story.parent.mkdir(parents=True)
    story.write_text(_STORY_DOC, encoding="utf-8")
    note = tmp_path / "stories" / "AG3-1" / "research" / "findings.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\nstory_id: AG3-999\n---\n\n# R\n\n## F\n\nfound.\n", encoding="utf-8")
    service, client = _service(tmp_path)
    result = handle_tool_call(service, "story_sync", {"full_reindex": True})
    assert result["error"] == "story_source_invalid"
    assert "canonical path" in result["detail"]
    assert client.objects == {}


def test_n24_story_md_still_requires_its_frontmatter(tmp_path: Path) -> None:
    """The exported story artefact keeps the STRICT profile (N05 stays closed)."""
    story = tmp_path / "stories" / "AG3-1" / "story.md"
    story.parent.mkdir(parents=True)
    story.write_text("# No frontmatter\n\n## P\n\ntext\n", encoding="utf-8")
    service, client = _service(tmp_path)
    result = handle_tool_call(service, "story_sync", {"full_reindex": True})
    assert result["error"] == "story_source_invalid"
    assert client.objects == {}


# --------------------------------------------------------------------------- #
# N23: the authority scope is EXPLICIT and never derived from the module filter
# --------------------------------------------------------------------------- #


def test_n23_module_filter_is_not_used_as_the_authority_scope(tmp_path: Path) -> None:
    """The module filter must not silently activate the authority rules (N23)."""
    service, client = _service(tmp_path)
    client.search_results = [concept_hit("c1", "FK-13", 0.5, module="vectordb")]
    result = handle_tool_call(
        service, "concept_search", {"query": "retrieval", "module": "vectordb"}
    )
    reasons = result["results"][0]["rank_reasons"]
    # FK-13 declares authority_over: vectordb in the corpus, but no SCOPE was
    # asked about -- so rule 1 must NOT fire off the module filter.
    assert "authority_over-direct" not in reasons
    # The module filter still reaches the transport as a hard filter.
    assert client.search_calls[0]["filters"]["module"] == "vectordb"


def test_n23_explicit_authority_scope_activates_the_precedence(tmp_path: Path) -> None:
    """With an EXPLICIT scope the precedence applies -- and it is a tier."""
    service, client = _service(tmp_path)
    client.search_results = [concept_hit("c1", "FK-13", 0.1, module="vectordb")]
    result = handle_tool_call(
        service, "concept_search", {"query": "retrieval", "authority_scope": "vectordb"}
    )
    assert "authority_over-direct" in result["results"][0]["rank_reasons"]


# --------------------------------------------------------------------------- #
# D7: authority_scope is a RATIFIED, explicit ranking input (FK-13 §13.9.5)
#
# Rules 1 and 2 of §13.9.11 rank against the scope the CALLER asks about. Each
# test below drives the REAL tool path (handle_tool_call -> McpToolService ->
# WeaviateRetrievalPort -> rank_hits over a REAL parsed corpus) and each carries
# its counterexample: the same hits with a different (or absent) scope must rank
# differently, which is what proves the scope -- and only the scope -- did it.
# --------------------------------------------------------------------------- #


def test_d7_rule1_direct_authority_beats_a_higher_scoring_adjacent_hit(
    tmp_path: Path,
) -> None:
    """Rule 1: the owner of the QUERIED scope outranks a better-scoring neighbour."""
    service, client = _service(tmp_path, with_deferral=True)
    # FK-11 scores far better; FK-13 owns authority_over: vectordb in the corpus.
    client.search_results = [
        concept_hit("c-adjacent", "FK-11", 9.5, module="evaluator"),
        concept_hit("c-owner", "FK-13", 0.05, module="vectordb"),
    ]
    ranked = handle_tool_call(
        service,
        "concept_search",
        {"query": "how do we chunk", "authority_scope": "vectordb"},
    )["results"]
    assert [r["concept_id"] for r in ranked] == ["FK-13", "FK-11"]
    assert "authority_over-direct" in ranked[0]["rank_reasons"]
    # COUNTEREXAMPLE: a scope nobody owns leaves rule 1 silent, so the raw
    # similarity order returns. Same corpus, same hits -- only the scope changed.
    counter = handle_tool_call(
        service,
        "concept_search",
        {"query": "how do we chunk", "authority_scope": "unowned-scope"},
    )["results"]
    assert [r["concept_id"] for r in counter] == ["FK-11", "FK-13"]
    assert all("authority_over-direct" not in r["rank_reasons"] for r in counter)


def test_d7_rule2_scoped_deferral_target_beats_the_deferring_document(
    tmp_path: Path,
) -> None:
    """Rule 2: the TARGET of a scoped deferral wins -- not the deferrer."""
    service, client = _service(tmp_path, with_deferral=True)
    # FK-11 defers_to FK-13 for `chunking`; nobody OWNS `chunking` directly, so
    # only rule 2 can move anything here.
    client.search_results = [
        concept_hit("c-deferrer", "FK-11", 8.0, module="evaluator"),
        concept_hit("c-target", "FK-13", 0.05, module="vectordb"),
    ]
    ranked = handle_tool_call(
        service, "concept_search", {"query": "chunk sizes", "authority_scope": "chunking"}
    )["results"]
    assert [r["concept_id"] for r in ranked] == ["FK-13", "FK-11"]
    assert "scoped-authority-target" in ranked[0]["rank_reasons"]
    # The credit must NOT accrue to the deferring source.
    assert "scoped-authority-target" not in ranked[1]["rank_reasons"]
    assert "authority_over-direct" not in ranked[0]["rank_reasons"]  # rule 2, not 1
    # COUNTEREXAMPLE: the deferral is QUALIFIED on `chunking`. Ask about another
    # scope and the edge must not count -- score order returns.
    counter = handle_tool_call(
        service, "concept_search", {"query": "chunk sizes", "authority_scope": "tokenizing"}
    )["results"]
    assert [r["concept_id"] for r in counter] == ["FK-11", "FK-13"]
    assert all("scoped-authority-target" not in r["rank_reasons"] for r in counter)


def test_d7_absent_scope_never_derives_one_and_leaves_rules_345_intact(
    tmp_path: Path,
) -> None:
    """No scope supplied -> rules 1/2 inert, NO derivation, 3/4/5 unchanged."""
    service, client = _service(tmp_path, with_appendix=True, with_deferral=True)
    client.search_results = [
        concept_hit("c-appendix", "FK-13-A", 0.2, module="vectordb", is_appendix=True),
        concept_hit("c-core", "FK-13", 0.3, module="vectordb"),
        concept_hit("c-other", "FK-11", 0.4, module="evaluator"),
    ]
    # Every plausible derivation source is present and must be ignored: the module
    # filter says `vectordb`, the query text says "vectordb", and the corpus has
    # both an authority_over: vectordb owner and a scoped deferral.
    results = handle_tool_call(
        service,
        "concept_search",
        {"query": "vectordb interface chunking", "module": "vectordb"},
    )["results"]
    reasons = {r["concept_id"]: r["rank_reasons"] for r in results}
    assert all("authority_over-direct" not in v for v in reasons.values())
    assert all("scoped-authority-target" not in v for v in reasons.values())
    # Rule 3 (appendix + interface detail) and rule 5 (module match) still fire.
    assert "appendix-interface" in reasons["FK-13-A"]
    assert "module-match" in reasons["FK-13-A"]
    assert "module-match" in reasons["FK-13"]
    # ... and the rule-3 boost still lifts the appendix over the higher-scoring core.
    assert [r["concept_id"] for r in results][0] == "FK-13-A"
    # The module filter is a REAL transport filter, so the foreign-module hit never
    # reaches the ranking at all (the double applies the filters like Weaviate).
    assert "FK-11" not in reasons
    # The scope was never forwarded to the transport as a filter either.
    assert "authority_scope" not in client.search_calls[0]["filters"]  # type: ignore[operator]


# --------------------------------------------------------------------------- #
# D8: mixed status result sets -- rule 4 proven on the REAL filter path (N36)
#
# Rule 4 was behaviourally inert while `concept_status` accepted exactly ONE value:
# a real result set was status-homogeneous, so a demotion could never reorder
# anything, and the old "proof" only worked because the double ignored the filter.
# The double now applies every filter like Weaviate, and D8 makes the filter a SET.
# --------------------------------------------------------------------------- #


def test_d8_a_mixed_status_query_returns_both_and_ranks_active_first(
    tmp_path: Path,
) -> None:
    """The filter really returns both statuses AND rule 4 puts the active one first."""
    service, client = _service(tmp_path, with_draft_owner=True)
    client.search_results = [
        # The DRAFT scores 90x better and is returned by the transport.
        concept_hit("c-draft", "FK-90", 9.0, module="planning", concept_status="draft"),
        concept_hit("c-active", "FK-13", 0.1, module="vectordb", concept_status="active"),
    ]
    result = handle_tool_call(
        service,
        "concept_search",
        {"query": "chunk sizes", "concept_status": ["active", "draft"]},
    )
    ranked = result["results"]
    # 1. The transport really produced a MIXED set (the premise rule 4 needs).
    assert {r["concept_id"] for r in ranked} == {"FK-13", "FK-90"}
    assert {r["concept_status"] for r in ranked} == {"active", "draft"}
    # 2. Rule 4 ordered the active document first despite the far worse score.
    assert [r["concept_id"] for r in ranked] == ["FK-13", "FK-90"]
    assert "status-penalty(draft)" in ranked[1]["rank_reasons"]
    assert ranked[1]["score"] > ranked[0]["score"]
    # 3. The filter reached the transport as a SET, not as a post-filter.
    assert client.search_calls[0]["filters"]["concept_status"] == ("active", "draft")  # type: ignore[index]


def test_d8_rule4_outranks_a_direct_authority_of_a_draft(tmp_path: Path) -> None:
    """A live rule 1 must not lift a non-active owner: rule 4 demotes whole tiers."""
    service, client = _service(tmp_path, with_draft_owner=True)
    client.search_results = [
        # FK-90 OWNS `chunking` but is draft in the corpus, and it scores far better.
        concept_hit("c-draft-owner", "FK-90", 9.0, module="planning", concept_status="draft"),
        concept_hit("c-active", "FK-13", 0.1, module="vectordb", concept_status="active"),
    ]
    ranked = handle_tool_call(
        service, "concept_search",
        {
            "query": "chunk sizes",
            "authority_scope": "chunking",
            "concept_status": ["active", "draft"],
        },
    )["results"]
    assert [r["concept_id"] for r in ranked] == ["FK-13", "FK-90"]
    # Rule 1 DID fire for the draft -- and rule 4's whole-tier demotion still wins.
    assert "authority_over-direct" in ranked[1]["rank_reasons"]
    assert "status-penalty(draft)" in ranked[1]["rank_reasons"]


def test_d8_the_default_still_returns_active_only(tmp_path: Path) -> None:
    """The default is unchanged: drafts appear ONLY when explicitly requested."""
    service, client = _service(tmp_path, with_draft_owner=True)
    hits = [
        concept_hit("c-draft", "FK-90", 9.0, module="planning", concept_status="draft"),
        concept_hit("c-active", "FK-13", 0.1, module="vectordb", concept_status="active"),
    ]
    client.search_results = list(hits)
    default = handle_tool_call(service, "concept_search", {"query": "chunk sizes"})
    assert [r["concept_id"] for r in default["results"]] == ["FK-13"]
    assert client.search_calls[0]["filters"]["concept_status"] == ("active",)  # type: ignore[index]
    # An explicit archived-only query excludes both of them (filter faithfulness).
    client.search_results = list(hits)
    archived = handle_tool_call(
        service, "concept_search", {"query": "chunk sizes", "concept_status": ["archived"]}
    )
    assert archived["results"] == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("draft", "bare string", id="bare-string"),
        pytest.param(None, "explicitly null", id="null"),
        pytest.param([], "empty list", id="empty-list"),
        pytest.param(["draft", "draft"], "twice", id="duplicate"),
        pytest.param(["published"], "must be one of", id="unknown-value"),
        pytest.param(["active", 7], "must be a string", id="wrong-element-type"),
        pytest.param({"active": True}, "must be a list", id="wrong-container"),
    ],
)
def test_d8_concept_status_set_is_strictly_validated(
    tmp_path: Path, value: object, expected: str
) -> None:
    """No coercion (D8): every malformed status set is a NAMED error."""
    service, client = _service(tmp_path)
    client.search_results = [concept_hit("c1", "FK-13", 0.5)]
    with pytest.raises(ToolArgumentError, match=expected):
        handle_tool_call(
            service, "concept_search", {"query": "retrieval", "concept_status": value}
        )
    assert client.search_calls == []  # rejected BEFORE the query is issued


def test_d7_a_huge_similarity_score_cannot_overturn_a_direct_authority(
    tmp_path: Path,
) -> None:
    """Tiered precedence holds with rules 1/2 live: BM25 cannot buy authority."""
    service, client = _service(tmp_path, with_appendix=True)
    client.search_results = [
        # The appendix is in the queried module and matches the interface detail,
        # so it collects BOTH within-tier boosts on top of a huge BM25 score.
        concept_hit("c-loud", "FK-13-A", 12.5, module="vectordb", is_appendix=True),
        concept_hit("c-owner", "FK-13", 0.001, module="vectordb"),
    ]
    ranked = handle_tool_call(
        service, "concept_search",
        {"query": "interface test", "authority_scope": "vectordb", "module": "vectordb"},
    )["results"]
    assert [r["concept_id"] for r in ranked] == ["FK-13", "FK-13-A"]
    # The loud hit collected the rule-3 AND rule-5 boosts and STILL lost -- both are
    # bounded WITHIN their tier and can never cross a precedence boundary.
    assert "appendix-interface" in ranked[1]["rank_reasons"]
    assert "module-match" in ranked[1]["rank_reasons"]
    assert ranked[1]["score"] > ranked[0]["score"]


def test_d7_authority_scope_is_a_ranking_input_not_a_filter(tmp_path: Path) -> None:
    """The scope must never reach the transport as a filter (it selects nothing)."""
    service, client = _service(tmp_path)
    client.search_results = [concept_hit("c1", "FK-13", 0.5, module="vectordb")]
    handle_tool_call(
        service,
        "concept_search",
        {"query": "retrieval", "authority_scope": "vectordb", "module": "vectordb"},
    )
    filters = client.search_calls[0]["filters"]
    assert filters == {"concept_status": ("active",), "module": "vectordb"}  # scope absent


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "explicitly null"),
        ("", "empty string"),
        ("   ", "empty string"),
        (7, "must be a string"),
        (["vectordb"], "must be a string"),
    ],
)
def test_d7_authority_scope_is_strictly_validated(
    tmp_path: Path, value: object, expected: str
) -> None:
    """Same strictness regime as every other optional (R13/AC10)."""
    service, client = _service(tmp_path)
    client.search_results = [concept_hit("c1", "FK-13", 0.5)]
    with pytest.raises(ToolArgumentError, match=expected):
        handle_tool_call(
            service, "concept_search", {"query": "retrieval", "authority_scope": value}
        )
    assert client.search_calls == []  # rejected BEFORE the query is issued


# --------------------------------------------------------------------------- #
# N28: completions are immutable, position-bound and replay-proof
# --------------------------------------------------------------------------- #


def test_n28_an_established_completion_position_is_never_overwritten(
    tmp_path: Path,
) -> None:
    """A persisted completion is IMMUTABLE: its position cannot be re-used (N28).

    This is the replay path: re-inserting a saved, still digest-valid completion
    over the CURRENT position must LOSE, so the established completion order can
    never be rewritten and the reported freshness cannot be pulled backwards.
    (Publishing an older corpus revision again is a legitimate NEW completion at a
    NEW position -- that is not a replay.)
    """
    service, client = _service(tmp_path)
    store = service.sync.store
    service.sync.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev-1",
    )
    saved_doc = dict(next(iter(client.receipts.values())))  # the rev-1 completion
    service.sync.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev-2",
    )
    latest_uuid, latest_doc = next(iter(client.receipts.items()))
    assert latest_doc["corpus_revision"] == "rev-2"

    # Replay the saved rev-1 completion OVER the current position: the conditional
    # create must lose and the record must stay byte-identical.
    assert (
        client.insert_object(
            collection=RECEIPT_COLLECTION, uuid=latest_uuid, properties=saved_doc
        )
        is False
    )
    assert client.receipts[latest_uuid] == latest_doc
    still_latest = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert still_latest is not None
    assert still_latest.corpus_revision == "rev-2", "freshness must not be rewritten"
    # Superseded positions are pruned, so the log stays bounded; the winning
    # completion is the only one that decides freshness.
    assert len(client.receipts) == 1


def test_n28_a_moved_completion_record_is_fail_closed(tmp_path: Path) -> None:
    """A completion stored at a position it does not bind to is rejected (N28)."""
    service, client = _service(tmp_path)
    service.sync.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev-1",
    )
    uid, doc = next(iter(client.receipts.items()))
    del client.receipts[uid]
    client.receipts["11111111-2222-4333-8444-555555555555"] = doc  # moved record
    with pytest.raises(VectorDbUnavailableError, match="immutable and position-bound"):
        service.sync.store.list_receipts(project_id="acme")


def test_n28_a_stalled_writer_cannot_publish_ahead_of_a_later_one(tmp_path: Path) -> None:
    """The position is established BY the publish, so order cannot be reversed."""
    service, client = _service(tmp_path)
    store = service.sync.store
    # B completes first...
    b = store.set_receipt(
        receipt=SyncReceipt.for_completion("acme", "concept/b.md", "concept", "rev-b")
    )
    # ...then A (which "stalled" before publishing) completes.
    a = store.set_receipt(
        receipt=SyncReceipt.for_completion("acme", "concept/a.md", "concept", "rev-a")
    )
    assert a.sequence > b.sequence, "the LAST completion holds the highest position"
    rows = handle_tool_call(service, "story_list_sources", {})
    concept_row = next(s for s in rows["sources"] if s["source_type"] == "concept")
    assert concept_row["last_revision"] == "rev-a"
