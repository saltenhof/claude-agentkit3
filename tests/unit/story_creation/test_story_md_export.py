"""Unit tests for the deterministic story.md export (AG3-068 / FK-21 §21.11).

The story-attribute read surface and the Weaviate index are the injected
boundaries (the index is the Weaviate boundary => mocks exception). The
rendering, validation and fail-closed indexing policy run for real.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest
from tests.unit.vectordb.corpus_doubles import (
    RecordingWeaviateClient,
    corpus_store,
)

from agentkit.backend.story_context_manager.story_model import (
    Story,
    StorySpecification,
    WireStoryType,
)
from agentkit.backend.story_creation.story_md_export import (
    StoryMdExportResult,
    canonical_story_source_file,
    export_story_md,
)
from agentkit.backend.story_creation.weaviate_index import WeaviateStoryIndex
from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects
from agentkit.backend.vectordb.schema import OWNING_GENERATION_PROPERTY, StoryContextObject, deterministic_uuid
from agentkit.backend.vectordb.sync import SyncService
from agentkit.integration_clients.vectordb import VectorDbWriteError

if TYPE_CHECKING:
    from pathlib import Path


def _story(title: str = "Implement broker adapter") -> Story:
    return Story(
        project_key="ak3",
        story_number=42,
        story_display_id="AK3-042",
        title=title,
        story_type=WireStoryType.IMPLEMENTATION,
        module="backend/app",
        epic="payments",
        participating_repos=["backend"],
        labels=["story", "backend"],
    )


def _spec() -> StorySpecification:
    return StorySpecification(
        need="The broker adapter mishandles partial fills.",
        solution="Introduce an idempotent reconciliation step in the adapter.",
        acceptance=["Partial fills reconcile", "No duplicate orders"],
        concept_refs=["FK-13", "FK-21"],
        definition_of_done=["Tests green", "Reviewed"],
    )


class _FakeAttrs:
    def __init__(self, detail: object) -> None:
        self._detail = detail

    def get_story_detail(self, story_display_id: str) -> object:
        del story_display_id
        return self._detail


class _OkIndex:
    """Records the TYPED projection the export hands to the index port (N42)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.last_objects: list[StoryContextObject] = []

    def index_story(self, *, story_id: str, project_id: str, objects: object) -> int:
        del project_id
        self.calls.append(story_id)
        self.last_objects = list(objects)  # type: ignore[arg-type]
        return len(self.last_objects)


def _story_dir(tmp_path: Path, story_id: str = "AK3-042") -> Path:
    """Create the CANONICAL story directory ``<root>/stories/<story-id>/`` (N21).

    The export verifies containment under a ``stories/`` root and agreement with
    the story id, because the indexed ``source_file`` must be the path
    ``story_sync`` also discovers.
    """
    directory = tmp_path / "stories" / story_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class _FailIndex:
    def index_story(self, *, story_id: str, project_id: str, objects: object) -> int:
        del story_id, project_id, objects
        raise VectorDbWriteError("weaviate write rejected")


def test_export_success_writes_frontmatter_and_indexes(tmp_path: Path) -> None:
    index = _OkIndex()
    story_dir = _story_dir(tmp_path)
    result = export_story_md(
        "AK3-042",
        story_dir,
        project_id="acme",
        project_root=tmp_path,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=index,
    )
    assert isinstance(result, StoryMdExportResult)
    assert result.success is True
    assert result.error == ""
    md = (story_dir / "story.md").read_text(encoding="utf-8")
    assert md.startswith("---\n")
    assert "story_id: AK3-042" in md
    assert "exported_at:" in md
    assert "# Implement broker adapter" in md
    assert result.file_size_bytes > 500
    assert index.calls == ["AK3-042"]
    # R04: exported objects carry the full StoryContext projection, not the old
    # minimal problem/solution shape.
    assert index.last_objects
    obj = index.last_objects[0]
    props = obj.properties
    assert props["project_id"] == "acme"
    assert props["source_type"] == "story"
    assert props["content"]
    assert props["content_hash"]
    assert "section_heading" in props
    # N42: the identity travels as the TYPED object -- uuid AND the chunk_id it was
    # derived from -- instead of being flattened into a property dict.
    assert obj.uuid
    assert obj.chunk_id
    # R04: the REAL caller indexes the PROJECT-RELATIVE canonical corpus path and
    # the REAL title/status from the exported frontmatter -- not an absolute path
    # and not the story id as a stand-in title.
    rel = "stories/AK3-042/story.md"
    assert canonical_story_source_file(story_dir, "AK3-042", tmp_path) == rel
    assert {str(o.properties["source_file"]) for o in index.last_objects} == {rel}
    assert props["title"] == "Implement broker adapter"
    assert props["status"] == "Backlog"
    assert props["story_type"] == "implementation"
    assert props["module"] == "backend/app"
    assert props["epic"] == "payments"
    # The uuid is the deterministic identity of the RELATIVE path.
    # ...and the exported frontmatter itself carries the real metadata (R04).
    assert "title: Implement broker adapter" in md
    assert "status: Backlog" in md
    assert "story_type: implementation" in md


def test_r04_indexed_identity_is_derived_from_the_relative_path(tmp_path: Path) -> None:
    """R04: re-projecting the written file yields the SAME uuids as the export."""
    index = _OkIndex()
    story_dir = _story_dir(tmp_path)
    result = export_story_md(
        "AK3-042",
        story_dir,
        project_id="acme",
        project_root=tmp_path,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=index,
    )
    assert result.success is True
    rel = canonical_story_source_file(story_dir, "AK3-042", tmp_path)
    reprojected = story_file_to_objects("acme", story_dir / "story.md", source_file=rel)
    assert {o.uuid for o in reprojected} == {o.uuid for o in index.last_objects}
    for obj in reprojected:
        assert obj.uuid == deterministic_uuid("acme", rel, obj.chunk_id)
    # N42: the identity INPUT travels with the object. Flattening the projection to
    # property dicts dropped `chunk_id`, and any reconstruction from another field
    # (e.g. content_hash) yields uuids the production identity check rejects.
    assert {o.chunk_id for o in index.last_objects} == {o.chunk_id for o in reprojected}
    for obj in index.last_objects:
        assert obj.uuid == deterministic_uuid("acme", rel, obj.chunk_id)
        assert obj.chunk_id != str(obj.properties["content_hash"])


def test_n21_directory_outside_a_stories_root_is_rejected(tmp_path: Path) -> None:
    """N21: exporting into an arbitrary folder must NOT fabricate a corpus path."""
    stray = tmp_path / "tmp" / "AK3-042"
    stray.mkdir(parents=True)
    with pytest.raises(ValueError, match="is not contained in the 'stories' root"):
        canonical_story_source_file(stray, "AK3-042", tmp_path)


def test_n31_absolute_path_outside_the_project_root_is_rejected(tmp_path: Path) -> None:
    """N31: a path whose parent merely happens to be named 'stories' is NOT enough."""
    foreign = tmp_path / "elsewhere" / "stories" / "AK3-042"
    foreign.mkdir(parents=True)
    project_root = tmp_path / "project"
    project_root.mkdir()
    with pytest.raises(ValueError, match="resolves OUTSIDE the project root"):
        canonical_story_source_file(foreign, "AK3-042", project_root)


def test_n31_nested_story_directory_is_rejected(tmp_path: Path) -> None:
    """Only ``<project>/stories/<story>`` is canonical -- not a deeper nesting."""
    nested = tmp_path / "stories" / "archive" / "AK3-042"
    nested.mkdir(parents=True)
    with pytest.raises(ValueError, match="is not contained in the 'stories' root"):
        canonical_story_source_file(nested, "AK3-042", tmp_path)


def test_n21_directory_name_must_identify_the_story(tmp_path: Path) -> None:
    """N21: ``stories/foo/story.md`` must not be indexed as story ``AK3-042``."""
    foreign = tmp_path / "stories" / "foo"
    foreign.mkdir(parents=True)
    with pytest.raises(ValueError, match="does not identify story"):
        canonical_story_source_file(foreign, "AK3-042", tmp_path)
    other_story = tmp_path / "stories" / "AK3-999"
    other_story.mkdir(parents=True)
    with pytest.raises(ValueError, match="does not identify story"):
        canonical_story_source_file(other_story, "AK3-042", tmp_path)


def test_n21_slugged_story_directory_is_accepted(tmp_path: Path) -> None:
    """The corpus convention allows ``<STORY-ID>-<slug>`` (as in this repo)."""
    slugged = tmp_path / "stories" / "AK3-042-broker-adapter"
    slugged.mkdir(parents=True)
    assert (
        canonical_story_source_file(slugged, "AK3-042", tmp_path)
        == "stories/AK3-042-broker-adapter/story.md"
    )


def test_n21_export_rejects_a_non_canonical_directory(tmp_path: Path) -> None:
    """Through the REAL export: a stray directory neither WRITES nor indexes (N31)."""
    index = _OkIndex()
    stray = tmp_path / "scratch" / "AK3-042"
    stray.mkdir(parents=True)
    result = export_story_md(
        "AK3-042",
        stray,
        project_id="acme",
        project_root=tmp_path,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=index,
    )
    assert result.success is False
    assert "is not contained in the 'stories' root" in result.error
    assert index.calls == []
    # N31 ZERO-WRITE: the artefact must not exist -- validation precedes rendering.
    assert not (stray / "story.md").exists()
    assert list(stray.iterdir()) == []


def test_n31_supplied_source_file_cannot_bypass_the_verification(tmp_path: Path) -> None:
    """An explicitly supplied source_file is a cross-check, never a bypass (N31)."""
    index = _OkIndex()
    story_dir = _story_dir(tmp_path)
    result = export_story_md(
        "AK3-042",
        story_dir,
        project_id="acme",
        project_root=tmp_path,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=index,
        source_file="stories/somewhere-else/story.md",
    )
    assert result.success is False
    assert "diverges from the verified canonical corpus path" in result.error
    assert index.calls == []
    assert not (story_dir / "story.md").exists()


def test_n31_matching_supplied_source_file_is_accepted(tmp_path: Path) -> None:
    index = _OkIndex()
    story_dir = _story_dir(tmp_path)
    result = export_story_md(
        "AK3-042",
        story_dir,
        project_id="acme",
        project_root=tmp_path,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=index,
        source_file="stories/AK3-042/story.md",
    )
    assert result.success is True
    assert index.calls == ["AK3-042"]


def test_export_result_has_exactly_four_fields() -> None:
    """AC8: StoryMdExportResult is frozen with EXACTLY the four FK fields."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(StoryMdExportResult)}
    assert fields == {"success", "story_md_path", "file_size_bytes", "error"}
    assert StoryMdExportResult.__dataclass_params__.frozen is True


def test_indexing_failure_blocks_export_fail_closed(tmp_path: Path) -> None:
    """NEGATIVE: an indexing failure blocks the export (no catch-up, §21.11.4)."""
    result = export_story_md(
        "AK3-042",
        _story_dir(tmp_path),
        project_id="acme",
        project_root=tmp_path,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=_FailIndex(),
    )
    assert result.success is False
    assert "indexing failed" in result.error.lower()
    # The file was written (size carried) but the export is a hard FAIL.
    assert result.file_size_bytes > 0


def test_too_short_story_fails_validation(tmp_path: Path) -> None:
    """NEGATIVE: a < 500-byte render fails validation (no indexing attempted)."""
    index = _OkIndex()
    short = _story(title="x")
    result = export_story_md(
        "AK3-042",
        _story_dir(tmp_path),
        project_id="acme",
        project_root=tmp_path,
        story_attributes=_FakeAttrs((short, None)),
        index=index,
    )
    assert result.success is False
    assert "bytes" in result.error
    assert index.calls == []


def test_unknown_story_fails_closed(tmp_path: Path) -> None:
    """NEGATIVE: an unknown story fails closed (no fabricated master data)."""
    story_dir = _story_dir(tmp_path, "AK3-999")
    result = export_story_md(
        "AK3-999",
        story_dir,
        story_attributes=_FakeAttrs(None),
        project_id="acme", project_root=tmp_path, index=_OkIndex(),
    )
    assert result.success is False
    assert "not in the AK3 story backend" in result.error
    assert not (story_dir / "story.md").exists()


def test_export_renders_all_optional_sections(tmp_path: Path) -> None:
    """Spec-driven sections (problem/solution/AC/refs/DoD) are all rendered."""
    story_dir = _story_dir(tmp_path)
    result = export_story_md(
        "AK3-042",
        story_dir,
        story_attributes=_FakeAttrs((_story(), _spec())),
        project_id="acme", project_root=tmp_path, index=_OkIndex(),
    )
    assert result.success is True
    md = (story_dir / "story.md").read_text(encoding="utf-8")
    assert "## Problemstellung" in md
    assert "## Loesungsansatz" in md
    assert "## Akzeptanzkriterien" in md
    assert "## Konzept-Referenzen" in md
    assert "## Definition of Done" in md
    assert "vectordb_conflict_resolved: false" in md


def test_export_write_failure_is_fail_closed(tmp_path: Path) -> None:
    """NEGATIVE: an OSError on write yields success=False with the cause."""
    # A pre-existing *file* at the story-dir path makes the parent mkdir fail.
    (tmp_path / "stories").mkdir()
    blocking = tmp_path / "stories" / "AK3-042"
    blocking.write_text("not a dir", encoding="utf-8")
    result = export_story_md(
        "AK3-042",
        blocking,
        story_attributes=_FakeAttrs((_story(), _spec())),
        project_id="acme", project_root=tmp_path, index=_OkIndex(),
    )
    assert result.success is False
    assert result.error != ""


def test_export_is_deterministic_modulo_timestamp(tmp_path: Path) -> None:
    """The body (minus the exported_at line) is byte-stable across runs."""
    out1 = _story_dir(tmp_path / "a")
    out2 = _story_dir(tmp_path / "b")
    export_story_md(
        "AK3-042", out1, story_attributes=_FakeAttrs((_story(), _spec())),
        project_id="acme", project_root=tmp_path / "a", index=_OkIndex(),
    )
    export_story_md(
        "AK3-042", out2, story_attributes=_FakeAttrs((_story(), _spec())),
        project_id="acme", project_root=tmp_path / "b", index=_OkIndex(),
    )

    def _strip_ts(text: str) -> list[str]:
        return [line for line in text.splitlines() if not line.startswith("exported_at:")]

    assert _strip_ts((out1 / "story.md").read_text(encoding="utf-8")) == _strip_ts(
        (out2 / "story.md").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# N26 / D2: the split composition binds the AUTHORITATIVE project id
# ---------------------------------------------------------------------------


def _write_project_config_with_prefix(root: Path, key: str, prefix: str) -> None:
    """Write a project.yaml whose project_key DIVERGES from its project_prefix."""
    config_dir = root / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.yaml").write_text(
        f"project_key: {key}\n"
        "project_name: Acme\n"
        f"project_prefix: {prefix}\n"
        "repositories:\n  - name: app\n    path: .\n"
        "pipeline:\n"
        "  config_version: '3.0'\n"
        "  features:\n    multi_llm: false\n"
        "  sonarqube:\n    available: false\n    enabled: false\n"
        "  ci:\n    available: false\n    enabled: false\n",
        encoding="utf-8",
    )


def test_n26_split_composition_indexes_under_the_authoritative_project_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N26/D2: with project_key=acme / project_prefix=AC the chunks must land
    under ``AC`` -- the binding FK-13 §13.4.3 gives the MCP server -- not under the
    project KEY, which the AC-bound server would never see.

    Exercises the REAL production composition: only the Weaviate connect seam and
    the story read surface are doubled.
    """
    from agentkit.backend.bootstrap import composition_project
    from agentkit.backend.story_creation.story_md_export import export_story_md

    project_root = tmp_path / "project"
    _write_project_config_with_prefix(project_root, key="acme", prefix="AC")
    story_dir = project_root / "stories" / "AK3-042"
    story_dir.mkdir(parents=True)
    monkeypatch.delenv("PROJECT_ID", raising=False)

    captured: list[str] = []

    class _RecordingIndex:
        def index_story(self, *, story_id: str, project_id: str, objects: object) -> int:
            del story_id, objects
            captured.append(project_id)
            return 1

    # The REAL production helper the composition uses to resolve the binding.
    bound = composition_project.resolve_split_export_project_id(str(project_root))
    assert bound == "AC", "the authoritative binding is the project_prefix (FK-13 §13.4.3)"
    assert bound != "acme", "the project KEY must never become the project_id"

    result = export_story_md(
        "AK3-042",
        story_dir,
        project_id=bound,
        project_root=project_root,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=_RecordingIndex(),
    )
    assert result.success is True
    assert captured == ["AC"]

    # ...and the production composition binds from that helper only: no call site
    # may pass the project KEY as the project id (static invariant, N26).
    source = inspect.getsource(composition_project.build_story_split_service)
    assert "project_id=project_key" not in source
    assert "project_id = project_key" not in source
    assert "resolve_split_export_project_id(project_root)" in source
    assert source.count("project_id=project_id") == 2  # both export paths


# --------------------------------------------------------------------------- #
# N42: the REAL export -> REAL index -> REAL store chain
#
# The previous proof fabricated its uuid from `content_hash`, which is exactly the
# substitution the production identity validation rejects -- a fixture-only shape. The
# double here sits at the Weaviate CLIENT seam, so `story_file_to_objects`, the port,
# `WeaviateStoryIndex`, `WeaviateCorpusStore` and `SyncService` all run for real.
# --------------------------------------------------------------------------- #


def _real_index(client: RecordingWeaviateClient) -> WeaviateStoryIndex:
    class _Adapter:
        @property
        def corpus_client(self) -> object:
            return client

    return WeaviateStoryIndex(
        _Adapter(),  # type: ignore[arg-type]
        sync=SyncService(store=corpus_store(client)),
    )


def test_n42_the_real_export_path_passes_the_production_identity_check(
    tmp_path: Path,
) -> None:
    """A normally projected story must be indexable -- identity included."""
    client = RecordingWeaviateClient()
    story_dir = _story_dir(tmp_path)
    result = export_story_md(
        "AK3-042",
        story_dir,
        project_id="acme",
        project_root=tmp_path,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=_real_index(client),
    )
    assert result.success is True, result.error
    assert client.objects, "the real export must actually index its chunks"
    rel = canonical_story_source_file(story_dir, "AK3-042", tmp_path)
    expected = story_file_to_objects("acme", story_dir / "story.md", source_file=rel)
    assert set(client.objects) == {o.uuid for o in expected}
    # ... written under a claim, generation-stamped, with a published completion.
    for props in client.objects.values():
        assert props[OWNING_GENERATION_PROPERTY] == 1
    receipt = corpus_store(client).get_receipt(project_id="acme", source_file=rel)
    assert receipt is not None and receipt.source_type == "story"


def test_n42_a_sync_fault_blocks_the_export_instead_of_escaping(tmp_path: Path) -> None:
    """The export's handler must catch SyncError too, not only VectorDbError."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    story_dir = _story_dir(tmp_path)
    rel = canonical_story_source_file(story_dir, "AK3-042", tmp_path)
    # Another writer holds the source, so the export's claim is rejected (D3).
    held = store.try_claim_source(
        project_id="acme", source_file=rel, owner_id="other-writer"
    )
    assert held is not None
    index = WeaviateStoryIndex(
        _StubAdapter(client),  # type: ignore[arg-type]
        sync=SyncService(store=store, owner_id="exporter"),
    )
    result = export_story_md(
        "AK3-042",
        story_dir,
        project_id="acme",
        project_root=tmp_path,
        story_attributes=_FakeAttrs((_story(), _spec())),
        index=index,
    )
    assert result.success is False
    assert "indexing failed" in result.error
    assert "concurrent sync" in result.error
    assert client.objects == {}, "a blocked export indexes nothing"


class _StubAdapter:
    """Only the connection-ownership surface the index needs."""

    def __init__(self, client: object) -> None:
        self._client = client

    @property
    def corpus_client(self) -> object:
        return self._client
