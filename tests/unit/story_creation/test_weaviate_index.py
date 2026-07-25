"""The story index routes through the ONE claim-aware corpus write path (N38/N42).

Two properties are load-bearing here, and one of them was once "proved" by a fixture
shape:

1. **One write path.** Story export/split/repair used to index through the thin
   adapter's own ``story_sync``, which upserted directly: no claim, no generation
   stamp, no completion.
2. **The typed identity.** The port used to carry flattened property dicts, so the
   indexer had to re-derive the identity input the uuid was built from. Substituting
   ``content_hash`` for ``chunk_id`` produced uuids that production rejects for EVERY
   normally projected story -- and the old test fabricated its uuid the same wrong way,
   so it never noticed.

So the objects here are produced by the REAL projection (``story_file_to_objects`` over
a written ``story.md``), and the double sits at the Weaviate CLIENT seam: the real
``WeaviateCorpusStore`` and ``SyncService`` run underneath.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
from tests.unit.vectordb.corpus_doubles import RecordingWeaviateClient, corpus_store

from agentkit.backend.story_creation.weaviate_index import WeaviateStoryIndex
from agentkit.backend.vectordb.engine import WeaviateCorpusStore
from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects
from agentkit.backend.vectordb.schema import (
    OWNING_GENERATION_PROPERTY,
    StoryContextObject,
    deterministic_uuid,
)
from agentkit.backend.vectordb.sync import ConcurrentSyncRejectedError, SyncService
from agentkit.integration_clients.vectordb import VectorDbWriteError

if TYPE_CHECKING:
    from pathlib import Path

_STORY_SOURCE = "stories/AK3-1/story.md"

_STORY_MD = dedent(
    """\
    ---
    story_id: AK3-1
    title: A real story title
    status: Done
    story_type: implementation
    ---

    # A real story title

    ## Problem

    Something needs doing, and it needs enough prose that the chunker produces a
    real section rather than a degenerate one.

    ## Solution

    Do the thing, deterministically, and record what was done.
    """
)


class _StubAdapter:
    """Only the connection-ownership surface the index needs."""

    def __init__(self, client: object) -> None:
        self._client = client

    @property
    def corpus_client(self) -> object:
        return self._client


def _write(tmp_path: Path, body: str = _STORY_MD) -> Path:
    story_md = tmp_path / "stories" / "AK3-1" / "story.md"
    story_md.parent.mkdir(parents=True, exist_ok=True)
    story_md.write_text(body, encoding="utf-8")
    return story_md


def _projected(
    tmp_path: Path, *, body: str = _STORY_MD, project_id: str = "acme"
) -> list[StoryContextObject]:
    """Project a REAL story.md exactly as the export path does."""
    return story_file_to_objects(
        project_id, _write(tmp_path, body), source_file=_STORY_SOURCE
    )


def _index(
    client: RecordingWeaviateClient, *, owner: str = "exporter"
) -> WeaviateStoryIndex:
    return WeaviateStoryIndex(
        _StubAdapter(client),  # type: ignore[arg-type]
        sync=SyncService(store=corpus_store(client), owner_id=owner),
    )


def test_n42_the_projected_identity_is_not_the_content_hash(tmp_path: Path) -> None:
    """Guard the premise: chunk_id and content_hash are DIFFERENT identity inputs."""
    objects = _projected(tmp_path)
    assert objects
    for obj in objects:
        assert obj.chunk_id.startswith("story-")
        assert obj.chunk_id != obj.properties["content_hash"]
        assert obj.uuid == deterministic_uuid("acme", _STORY_SOURCE, obj.chunk_id)
        # ... and the substitution the previous code made would NOT have matched.
        assert obj.uuid != deterministic_uuid(
            "acme", _STORY_SOURCE, str(obj.properties["content_hash"])
        )


def test_n38_an_exported_story_is_claimed_stamped_and_completed(tmp_path: Path) -> None:
    """The export goes through the sync owner: generation stamp AND completion."""
    client = RecordingWeaviateClient()
    objects = _projected(tmp_path)
    written = _index(client).index_story(
        story_id="AK3-1", project_id="acme", objects=objects
    )
    assert written == len(objects)
    assert set(client.objects) == {obj.uuid for obj in objects}
    for props in client.objects.values():
        assert props[OWNING_GENERATION_PROPERTY] == 1, "an export must not be unstamped"
    receipt = corpus_store(client).get_receipt(
        project_id="acme", source_file=_STORY_SOURCE
    )
    assert receipt is not None
    assert receipt.source_type == "story"
    assert receipt.generation == 1


def test_n38_export_then_resync_then_vanished_delete_is_one_closed_chain(
    tmp_path: Path,
) -> None:
    """The AC3 chain: an exported story can be re-synced AND deleted afterwards."""
    client = RecordingWeaviateClient()
    first = _projected(tmp_path)
    _index(client).index_story(story_id="AK3-1", project_id="acme", objects=first)
    assert set(client.objects) == {obj.uuid for obj in first}

    # 1. RESYNC with CHANGED content through the MCP-side sync owner.
    changed = _projected(
        tmp_path, body=_STORY_MD.replace("Do the thing", "Do a different thing")
    )
    store = corpus_store(client)
    service = SyncService(store=store)
    resync = service.reconcile_sources(
        project_id="acme",
        producer="story_sync",
        objects_by_source={_STORY_SOURCE: changed},
        corpus_revision="rev-2",
    )
    assert sum(r.written for r in resync) == len(changed)
    assert set(client.objects) == {obj.uuid for obj in changed}
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
    assert sum(r.deleted for r in vanished) == len(changed)
    assert client.objects == {}, "an exported story participates in the delete closure"


def test_n38_a_concurrent_export_of_the_same_story_is_rejected(tmp_path: Path) -> None:
    """The export now takes the source claim, so D3 applies to it too."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    held = store.try_claim_source(
        project_id="acme", source_file=_STORY_SOURCE, owner_id="other-writer"
    )
    assert held is not None
    index = WeaviateStoryIndex(
        _StubAdapter(client),  # type: ignore[arg-type]
        sync=SyncService(store=store, owner_id="exporter"),
    )
    with pytest.raises(ConcurrentSyncRejectedError, match="concurrent sync"):
        index.index_story(
            story_id="AK3-1", project_id="acme", objects=_projected(tmp_path)
        )
    assert client.objects == {}, "a rejected export writes nothing"


def test_n38_a_divergent_object_project_id_is_rejected(tmp_path: Path) -> None:
    """N06 stays: cross-project indexing is refused before anything is written."""
    client = RecordingWeaviateClient()
    foreign = _projected(tmp_path, project_id="other")
    with pytest.raises(ValueError, match="diverges from the bound"):
        _index(client).index_story(story_id="AK3-1", project_id="acme", objects=foreign)
    assert client.objects == {}


def test_n38_an_object_without_a_source_file_is_rejected(tmp_path: Path) -> None:
    """A source_file is what a claim and a completion are keyed on."""
    client = RecordingWeaviateClient()
    objects = _projected(tmp_path)
    objects[0].properties["source_file"] = ""
    with pytest.raises(ValueError, match="usable 'source_file'"):
        _index(client).index_story(story_id="AK3-1", project_id="acme", objects=objects)
    assert client.objects == {}


def test_index_story_rejects_an_empty_project_id() -> None:
    client = RecordingWeaviateClient()
    with pytest.raises(ValueError, match="project_id is empty"):
        _index(client).index_story(story_id="AK3-1", project_id="", objects=[])


def test_index_story_propagates_write_error_fail_closed(tmp_path: Path) -> None:
    """NEGATIVE: an indexing write failure still blocks the export (FK-21 §21.11.4)."""

    class _Failing(RecordingWeaviateClient):
        def upsert(self, *, collection: str, objects: object) -> int:  # type: ignore[override]
            raise VectorDbWriteError("rejected")

    client = _Failing()
    with pytest.raises(VectorDbWriteError):
        _index(client).index_story(
            story_id="AK3-1", project_id="acme", objects=_projected(tmp_path)
        )


def test_n38_the_index_refuses_a_client_without_the_corpus_surface() -> None:
    """Fail-closed: no silent fallback to a second, unclaimed write path."""
    from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

    class _TooNarrow:
        def upsert(self, *, collection: str, objects: object) -> int:
            return 0

    with pytest.raises(VectorDbUnavailableError, match="second write path"):
        WeaviateStoryIndex(_StubAdapter(_TooNarrow()))  # type: ignore[arg-type]


def test_n38_the_store_is_the_only_stamping_write_path() -> None:
    """Structural: the corpus store is the ONLY place that stamps a generation."""
    import inspect

    from agentkit.backend.vectordb import engine

    source = inspect.getsource(engine.WeaviateCorpusStore.upsert_objects)
    assert OWNING_GENERATION_PROPERTY in source
    adapter_source = inspect.getsource(
        __import__(
            "agentkit.integration_clients.vectordb.weaviate_adapter",
            fromlist=["_x"],
        )
    )
    assert "def story_sync(" not in adapter_source
    assert isinstance(corpus_store(RecordingWeaviateClient()), WeaviateCorpusStore)
