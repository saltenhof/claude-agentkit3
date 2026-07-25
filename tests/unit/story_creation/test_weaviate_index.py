"""The story index routes through the ONE claim-aware corpus write path (N38).

Story export/split/repair used to index through the thin adapter's own
``story_sync``, which upserted directly: no claim, no generation stamp, no
completion. The double here therefore sits at the WEAVIATE CLIENT seam, so the REAL
``WeaviateCorpusStore`` and ``SyncService`` run underneath and the full chain
export -> resync -> vanished-delete is exercised productively.
"""

from __future__ import annotations

import pytest
from tests.unit.vectordb.corpus_doubles import RecordingWeaviateClient, corpus_store

from agentkit.backend.story_creation.weaviate_index import WeaviateStoryIndex
from agentkit.backend.vectordb.engine import WeaviateCorpusStore
from agentkit.backend.vectordb.schema import (
    OWNING_GENERATION_PROPERTY,
    deterministic_uuid,
)
from agentkit.backend.vectordb.sync import ConcurrentSyncRejectedError, SyncService
from agentkit.integration_clients.vectordb import VectorDbWriteError

_STORY_SOURCE = "stories/AK3-1/story.md"


class _FakeAdapter:
    """Stands in for the transport adapter's connection ownership only."""

    def __init__(self, client: object) -> None:
        self._client = client

    @property
    def corpus_client(self) -> object:
        return self._client


def _story_object(
    chunk: str, *, project_id: str = "acme", source_file: str = _STORY_SOURCE
) -> dict[str, object]:
    """A COMPLETE StoryContext object exactly as the export path builds it."""
    return {
        "uuid": deterministic_uuid(project_id, source_file, f"hash-{chunk}"),
        "content": f"body of {chunk}",
        "title": "A real story title",
        "story_id": "AK3-1",
        "status": "Done",
        "story_type": "implementation",
        "module": "",
        "epic": "",
        "source_type": "story",
        "source_file": source_file,
        "section_heading": chunk,
        "section_number": "1",
        "content_hash": f"hash-{chunk}",
        "project_id": project_id,
        "concept_id": "",
        "is_appendix": False,
        "parent_concept_id": "",
        "defers_to": [],
        "authority_over": [],
        "normative_rules": "",
        "concept_status": "",
    }


def _index(client: RecordingWeaviateClient) -> WeaviateStoryIndex:
    store = corpus_store(client)
    return WeaviateStoryIndex(
        _FakeAdapter(client),  # type: ignore[arg-type]
        sync=SyncService(store=store),
    )


def test_n38_an_exported_story_is_claimed_stamped_and_completed() -> None:
    """The export goes through the sync owner: generation stamp AND completion."""
    client = RecordingWeaviateClient()
    written = _index(client).index_story(
        story_id="AK3-1", project_id="acme", objects=[_story_object("a")]
    )
    assert written == 1
    stored = next(iter(client.objects.values()))
    assert stored[OWNING_GENERATION_PROPERTY] == 1, "an export must not be unstamped"
    # A completion was published, so the exported story has real freshness.
    receipt = corpus_store(client).get_receipt(
        project_id="acme", source_file=_STORY_SOURCE
    )
    assert receipt is not None
    assert receipt.source_type == "story"
    assert receipt.generation == 1


def test_n38_export_then_resync_then_vanished_delete_is_one_closed_chain() -> None:
    """The AC3 chain: an exported story can be re-synced AND deleted afterwards.

    Before this fix the export wrote unstamped objects, so a later sync or delete read
    no generation and had to fail closed -- an automatically exported story could
    never be updated or removed again.
    """
    client = RecordingWeaviateClient()
    index = _index(client)
    index.index_story(
        story_id="AK3-1", project_id="acme", objects=[_story_object("a")]
    )
    first = dict(client.objects)

    # 1. RESYNC through the MCP-side sync owner: the exported generation is replaced.
    store = corpus_store(client)
    service = SyncService(store=store)
    resync = service.reconcile_sources(
        project_id="acme",
        producer="story_sync",
        objects_by_source={
            _STORY_SOURCE: [
                obj
                for obj in _corpus_objects([_story_object("b")])
            ]
        },
        corpus_revision="rev-2",
    )
    assert sum(r.written for r in resync) == 1
    assert sum(r.deleted for r in resync) == 1, "the exported chunk was superseded"
    assert set(client.objects) != set(first)
    assert all(
        props[OWNING_GENERATION_PROPERTY] == 2 for props in client.objects.values()
    )

    # 2. VANISHED DELETE: the story disappears from the corpus and is removed.
    vanished = service.reconcile_sources(
        project_id="acme",
        producer="story_sync",
        objects_by_source={},
        corpus_revision="rev-3",
    )
    assert sum(r.deleted for r in vanished) == 1
    assert client.objects == {}, "an exported story participates in the delete closure"


def _corpus_objects(raw: list[dict[str, object]]) -> list[object]:
    """Map export dicts onto the typed corpus objects the sync owner takes."""
    from agentkit.backend.vectordb.schema import StoryContextObject

    return [
        StoryContextObject(
            uuid=str(obj["uuid"]),
            chunk_id=str(obj["content_hash"]),
            properties={k: v for k, v in obj.items() if k != "uuid"},
        )
        for obj in raw
    ]


def test_n38_a_concurrent_export_of_the_same_story_is_rejected() -> None:
    """The export now takes the source claim, so D3 applies to it too."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    held = store.try_claim_source(
        project_id="acme", source_file=_STORY_SOURCE, owner_id="other-writer"
    )
    assert held is not None
    index = WeaviateStoryIndex(
        _FakeAdapter(client),  # type: ignore[arg-type]
        sync=SyncService(store=store, owner_id="exporter"),
    )
    with pytest.raises(ConcurrentSyncRejectedError, match="concurrent sync"):
        index.index_story(
            story_id="AK3-1", project_id="acme", objects=[_story_object("a")]
        )
    assert client.objects == {}, "a rejected export writes nothing"


def test_n38_a_divergent_object_project_id_is_rejected() -> None:
    """N06 stays: cross-project indexing is refused before anything is written."""
    client = RecordingWeaviateClient()
    with pytest.raises(ValueError, match="diverges from the bound"):
        _index(client).index_story(
            story_id="AK3-1",
            project_id="acme",
            objects=[_story_object("a", project_id="other")],
        )
    assert client.objects == {}


def test_n38_an_object_without_a_source_file_is_rejected() -> None:
    """A source_file is what a claim and a completion are keyed on."""
    client = RecordingWeaviateClient()
    broken = _story_object("a")
    broken["source_file"] = ""
    with pytest.raises(ValueError, match="usable 'source_file'"):
        _index(client).index_story(
            story_id="AK3-1", project_id="acme", objects=[broken]
        )
    assert client.objects == {}


def test_index_story_rejects_an_empty_project_id() -> None:
    client = RecordingWeaviateClient()
    with pytest.raises(ValueError, match="project_id is empty"):
        _index(client).index_story(story_id="AK3-1", project_id="", objects=[])


def test_index_story_propagates_write_error_fail_closed() -> None:
    """NEGATIVE: an indexing write failure still blocks the export (FK-21 §21.11.4)."""

    class _Failing(RecordingWeaviateClient):
        def upsert(self, *, collection: str, objects: object) -> int:  # type: ignore[override]
            raise VectorDbWriteError("rejected")

    client = _Failing()
    with pytest.raises(VectorDbWriteError):
        _index(client).index_story(
            story_id="AK3-1", project_id="acme", objects=[_story_object("a")]
        )


def test_n38_the_index_refuses_a_client_without_the_corpus_surface() -> None:
    """Fail-closed: no silent fallback to a second, unclaimed write path."""
    from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

    class _TooNarrow:
        def upsert(self, *, collection: str, objects: object) -> int:
            return 0

    with pytest.raises(VectorDbUnavailableError, match="second write path"):
        WeaviateStoryIndex(_FakeAdapter(_TooNarrow()))  # type: ignore[arg-type]


def test_n38_the_store_is_the_only_stamping_write_path() -> None:
    """Structural: the corpus store is the ONLY place that stamps a generation."""
    import inspect

    from agentkit.backend.vectordb import engine

    source = inspect.getsource(engine.WeaviateCorpusStore.upsert_objects)
    assert OWNING_GENERATION_PROPERTY in source
    # ... and nothing else in the production tree writes StoryContext objects.
    adapter_source = inspect.getsource(
        __import__(
            "agentkit.integration_clients.vectordb.weaviate_adapter",
            fromlist=["_x"],
        )
    )
    assert "def story_sync(" not in adapter_source
    assert isinstance(corpus_store(RecordingWeaviateClient()), WeaviateCorpusStore)
