"""Remediation proofs for the r1 cluster: R02 endpoints, R05 closure, R10, R11.

Fakes live ONLY at the Weaviate CLIENT boundary (:mod:`corpus_doubles`); the
discovery, chunk identity, resolver rules and the story/research source closure
all run productively. The R10 rule tests are independent counterexamples: each
asserts that the rule's boost ACTUALLY happens in the positive case and is absent
in the negative case, so deleting the boost turns the test red.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
from tests.unit.vectordb.corpus_doubles import (
    RecordingWeaviateClient,
    chunk_object,
    corpus_store,
    seed_object,
)

from agentkit.backend.vectordb.concept_corpus.graph import build_graph
from agentkit.backend.vectordb.concept_corpus.resolver import (
    APPENDIX_DETAIL_BOOST,
    MODULE_MATCH_BOOST,
    TIER_DIRECT_AUTHORITY,
    derive_query_detail,
    rank_hits,
)
from agentkit.backend.vectordb.contracts import allowed_keys_for
from agentkit.backend.vectordb.engine import (
    WeaviateRetrievalPort,
    _split_endpoint,
    _split_grpc,
)
from agentkit.backend.vectordb.mcp_server import McpToolService, handle_tool_call
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
from agentkit.backend.vectordb.schema import deterministic_uuid
from agentkit.backend.vectordb.sync import SyncReceipt, SyncService
from agentkit.concepts.parser import discover_concept_files

if TYPE_CHECKING:
    from agentkit.backend.vectordb.concept_corpus.graph import ConceptGraph

_ENV = {
    "PROJECT_ID": "acme",
    "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.acme.local:8080",
    "WEAVIATE_GRPC_ENDPOINT": "weaviate.acme.local:50051",
}


# --------------------------------------------------------------------------- #
# R02: endpoint parsing is fail-closed and carries the TLS flag
# --------------------------------------------------------------------------- #


def test_r02_split_endpoint_fail_closed() -> None:
    assert _split_endpoint("http://weaviate.acme.local:8080") == (
        "weaviate.acme.local", 8080, False
    )
    assert _split_endpoint("https://weaviate.acme.local:443") == (
        "weaviate.acme.local", 443, True
    )
    with pytest.raises(Exception, match="host:port"):
        _split_endpoint("http://weaviate.acme.local")  # no port
    with pytest.raises(Exception, match="http"):
        _split_endpoint("weaviate.acme.local:8080")  # no scheme


def test_r02_split_grpc_fail_closed() -> None:
    assert _split_grpc("weaviate.acme.local:50051") == ("weaviate.acme.local", 50051, False)
    assert _split_grpc("grpcs://weaviate.acme.local:50051") == (
        "weaviate.acme.local", 50051, True
    )
    with pytest.raises(Exception, match="host:port"):
        _split_grpc("weaviate.acme.local")
    with pytest.raises(Exception, match="non-integer port"):
        _split_grpc("weaviate.acme.local:notaport")


def test_r02_corpus_store_delegates_to_client_exact_counts() -> None:
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    objs = [chunk_object("acme", "stories/x/story.md", "c1", "story")]
    assert store.upsert_objects(objects=objs, owning_claim="1|writer-a") == 1
    store.set_receipt(
        receipt=SyncReceipt.for_completion("acme", "stories/x/story.md", "story", "rev")
    )
    receipt = store.get_receipt(project_id="acme", source_file="stories/x/story.md")
    assert receipt is not None and receipt.corpus_revision == "rev"


def test_r01_allowed_keys_match_contract() -> None:
    assert allowed_keys_for("story_search") == frozenset(
        {"query", "search_mode", "project_id", "status", "story_type", "limit"}
    )
    assert allowed_keys_for("concept_sync") == frozenset(
        {"project_id", "full_reindex", "concept_path"}
    )


# --------------------------------------------------------------------------- #
# R05: story + research ingestion via the classifier, project-relative paths
# --------------------------------------------------------------------------- #


_STORY_FM = "---\nstory_id: AG3-1\ntitle: T\nstatus: Backlog\n---\n"


def _project(tmp_path: Path) -> Path:
    (tmp_path / "stories" / "AG3-1" / "research").mkdir(parents=True)
    (tmp_path / "stories" / "AG3-1" / "story.md").write_text(
        f"{_STORY_FM}\n# T\n\n## P\n\nneed.\n", encoding="utf-8"
    )
    (tmp_path / "stories" / "AG3-1" / "research" / "findings.md").write_text(
        f"{_STORY_FM}\n# R\n\n## Findings\n\nfound.\n", encoding="utf-8"
    )
    # Negative research cases: neither may be ingested.
    (tmp_path / "stories" / "AG3-1" / "review-codex.md").write_text(
        f"{_STORY_FM}\n# review\n", encoding="utf-8"
    )
    (tmp_path / "stories" / "AG3-1" / "handover.md").write_text(
        f"{_STORY_FM}\n# handover\n", encoding="utf-8"
    )
    cdir = tmp_path / "concept" / "technical-design"
    cdir.mkdir(parents=True)
    (cdir / "13.md").write_text(
        "---\nconcept_id: FK-13\ntitle: T\nmodule: m\nstatus: active\ndoc_kind: core\n"
        "---\n\n# T\n\n## S\n\ns.\n",
        encoding="utf-8",
    )
    return tmp_path / "concept"


def _service(tmp_path: Path) -> tuple[McpToolService, RecordingWeaviateClient]:
    concepts_dir = _project(tmp_path)
    client = RecordingWeaviateClient()
    binding = RuntimeBinding.from_env(_ENV, command="python", args=(), cwd=str(tmp_path))
    store = corpus_store(client)
    service = McpToolService(
        binding=binding,
        retrieval=WeaviateRetrievalPort(client=client, store=store, binding=binding),  # type: ignore[arg-type]
        sync=SyncService(store=store),
        concepts_dir=concepts_dir,
        stories_dir=tmp_path / "stories",
    )
    return service, client


def test_r05_story_sync_ingests_story_and_research_relative(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    result = handle_tool_call(service, "story_sync", {"full_reindex": True})
    indexed = {str(doc["source_file"]): str(doc["source_type"]) for doc in client.objects.values()}
    assert indexed["stories/AG3-1/story.md"] == "story"
    assert indexed["stories/AG3-1/research/findings.md"] == "research"
    assert not any("review" in rel for rel in indexed)
    assert not any("handover" in rel for rel in indexed)
    assert all(not Path(rel).is_absolute() for rel in indexed)
    assert result["written"] == len(client.objects)
    # The stored identity is derived from the PROJECT-RELATIVE path (R04).
    for uid, doc in client.objects.items():
        assert uid != deterministic_uuid("acme", str(tmp_path / doc["source_file"]), "x")


def test_r05_incremental_deletes_vanished_source(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    handle_tool_call(service, "story_sync", {"full_reindex": True})
    # Seed a STALE story source, then vanish the real one.
    stale = chunk_object("acme", "stories/AG3-GONE/story.md", "g1", "story")
    seed_object(client, stale)  # as a previous claim generation wrote it (D9)
    (tmp_path / "stories" / "AG3-1" / "story.md").unlink()
    result = handle_tool_call(service, "story_sync", {"full_reindex": False})
    assert result["deleted"] >= 2  # the stale source AND the vanished story.md
    assert stale.uuid not in client.objects
    remaining = {str(doc["source_file"]) for doc in client.objects.values()}
    assert remaining == {"stories/AG3-1/research/findings.md"}


def test_r05_story_sync_does_not_touch_concept_chunks(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    handle_tool_call(service, "concept_sync", {"full_reindex": True})
    concept_uuids = set(client.objects)
    handle_tool_call(service, "story_sync", {"full_reindex": True})
    assert concept_uuids <= set(client.objects)


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
    before = next(
        c for c in discover_concept_files(tmp_path / "concept").chunks if "original" in c.content
    )
    (root / "13.md").write_text(doc.replace("original content", "edited content"), encoding="utf-8")
    after = next(
        c for c in discover_concept_files(tmp_path / "concept").chunks if "edited" in c.content
    )
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
    assert obj.uuid == deterministic_uuid("acme", "concept/x.md", "shadow-1")
    assert obj.uuid != deterministic_uuid("acme", "concept/x.md", "logical-1")
    assert obj.chunk_id == "shadow-1"  # the identity input is carried (N13)


# --------------------------------------------------------------------------- #
# R10: one independent counterexample per authority rule
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


def _graph(tmp_path: Path) -> ConceptGraph:
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "13.md").write_text(_CORE, encoding="utf-8")
    (root / "14.md").write_text(_CORE_DEFER, encoding="utf-8")
    return build_graph(discover_concept_files(tmp_path / "concept"))


def test_r10_rule1_authority_over_for_query_scope_outranks(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    hits = [{"concept_id": "FK-14", "score": 0.9}, {"concept_id": "FK-13", "score": 0.5}]
    ranked = rank_hits(graph, hits, query_authority_scope="vectordb")
    assert ranked[0].concept_id == "FK-13"  # owns the queried scope despite lower base
    assert "authority_over-direct" in ranked[0].reasons
    # N23: the precedence is a TIER -- no similarity score can reverse it.
    assert ranked[0].tier == TIER_DIRECT_AUTHORITY
    assert ranked[0].tier < ranked[1].tier
    # Counterexample: for an UNRELATED scope the base score decides again.
    other = rank_hits(graph, hits, query_authority_scope="unrelated")
    assert other[0].concept_id == "FK-14"


def test_r10_rule2_scoped_authority_target_boosted(tmp_path: Path) -> None:
    """Rule 2 in ISOLATION: the deferral TARGET (which owns no scope itself) beats
    the deferring source. Rule 1 must not be able to explain the outcome, so the
    target deliberately declares NO authority_over."""
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "15.md").write_text(
        dedent(
            """            ---
            concept_id: FK-15
            title: Target
            module: other
            status: active
            doc_kind: core
            ---

            # Target

            ## P

            p.
            """
        ),
        encoding="utf-8",
    )
    (root / "16.md").write_text(
        dedent(
            """            ---
            concept_id: FK-16
            title: Deferrer
            module: other
            status: active
            doc_kind: core
            defers_to:
              - target: FK-15
                scope: vectordb
            ---

            # Deferrer

            ## P

            p.
            """
        ),
        encoding="utf-8",
    )
    graph = build_graph(discover_concept_files(tmp_path / "concept"))
    hits = [{"concept_id": "FK-15", "score": 0.5}, {"concept_id": "FK-16", "score": 0.9}]
    ranked = rank_hits(graph, hits, query_authority_scope="vectordb")
    target = next(r for r in ranked if r.concept_id == "FK-15")
    deferrer = next(r for r in ranked if r.concept_id == "FK-16")
    assert "scoped-authority-target" in target.reasons
    assert "scoped-authority-target" not in deferrer.reasons
    # A TIER decides, so the deferrer's higher similarity score cannot reverse it.
    assert target.tier < deferrer.tier
    assert ranked[0].concept_id == "FK-15"
    # Counterexample: for a DIFFERENT scope there is no scoped deferral at all.
    other = rank_hits(graph, hits, query_authority_scope="unrelated")
    assert all("scoped-authority-target" not in r.reasons for r in other)
    assert other[0].concept_id == "FK-16"


def test_r10_rule3_appendix_boost_only_for_detail(tmp_path: Path) -> None:
    appendix = dedent(
        """\
        ---
        concept_id: FK-13-A
        title: App
        module: vectordb
        status: active
        doc_kind: appendix
        parent_concept_id: FK-13
        ---

        # App

        ## S

        s.
        """
    )
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "13.md").write_text(_CORE, encoding="utf-8")
    (root / "13a.md").write_text(appendix, encoding="utf-8")
    graph = build_graph(discover_concept_files(tmp_path / "concept"))
    hits = [{"concept_id": "FK-13", "score": 0.5}, {"concept_id": "FK-13-A", "score": 0.5}]

    normalised = 0.5 / 1.5  # score/(1+score), N23
    ranked_empty = rank_hits(graph, hits)
    empty_app = next(r for r in ranked_empty if r.concept_id == "FK-13-A")
    assert "appendix-interface" not in empty_app.reasons
    assert empty_app.authority_score == pytest.approx(normalised)

    ranked_detail = rank_hits(graph, hits, query_detail="interface")
    detail_app = next(r for r in ranked_detail if r.concept_id == "FK-13-A")
    assert "appendix-interface" in detail_app.reasons
    # The boost is real, and it lifts the appendix ABOVE the core doc.
    assert detail_app.authority_score == pytest.approx(normalised + APPENDIX_DETAIL_BOOST)
    assert ranked_detail[0].concept_id == "FK-13-A"


def test_r10_query_detail_is_derived_from_the_query_text() -> None:
    assert derive_query_detail("what is the tool interface?") == "interface"
    assert derive_query_detail("show the CONTRACT tests") == "contract"
    assert derive_query_detail("how does retrieval work") == ""
    assert derive_query_detail("interfacing with weaviate") == ""


def test_r10_rule4_archived_penalty(tmp_path: Path) -> None:
    doc = dedent(
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
    (tdir / "13.md").write_text(doc, encoding="utf-8")
    (root / "archiv").mkdir()
    (root / "archiv" / "13_old.md").write_text(doc.replace("FK-13", "FK-OLD"), encoding="utf-8")
    graph = build_graph(discover_concept_files(root))
    hits = [{"concept_id": "FK-13", "score": 0.5}, {"concept_id": "FK-OLD", "score": 0.5}]
    ranked = rank_hits(graph, hits)
    assert ranked[0].concept_id == "FK-13"
    archived = next(r for r in ranked if r.concept_id == "FK-OLD")
    assert archived.authority_score < archived.score
    assert any(r.startswith("status-penalty") for r in archived.reasons)


def test_r10_rule5_module_match_boost_exists_and_is_guarded(tmp_path: Path) -> None:
    """The boost must ACTUALLY happen without a cross-module authority (R10).

    Positive: a query from module ``other`` for a scope NOBODY owns -> the
    module-local FK-14 gets the module-match boost.
    Negative: the same query for the scope FK-13 owns in ANOTHER module -> the
    stronger cross-module authority suppresses the boost.
    """
    graph = _graph(tmp_path)  # FK-13 owns 'vectordb' in module 'vectordb'
    hits = [{"concept_id": "FK-14", "score": 0.5}]

    normalised = 0.5 / 1.5  # score/(1+score), N23
    boosted = rank_hits(graph, hits, query_authority_scope="unowned-scope", query_module="other")[0]
    assert "module-match" in boosted.reasons
    assert boosted.authority_score == pytest.approx(normalised + MODULE_MATCH_BOOST)

    guarded = rank_hits(graph, hits, query_authority_scope="vectordb", query_module="other")[0]
    assert "module-match" not in guarded.reasons
    assert guarded.authority_score == pytest.approx(normalised)
