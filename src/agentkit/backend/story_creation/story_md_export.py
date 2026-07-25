"""Deterministic ``story.md`` export (FK-21 §21.11).

``story.md`` is NOT an LLM product: it is rendered deterministically from the
story attributes via this module (FK-21 §21.11.1). The export writes YAML
frontmatter + an H1 title + the structured attributes, validates the artefact
(file exists, > 500 bytes, frontmatter carries ``story_id`` + ``exported_at``),
and then performs an automatic incremental Weaviate indexing as a HARD blocker:
an indexing failure makes the export fail (fail-closed, no warning / catch-up,
FK-21 §21.11.4).

``StoryMdExportResult`` is FK-conform: a ``@dataclass(frozen=True)`` with
EXACTLY ``{success, story_md_path, file_size_bytes, error}``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import yaml

from agentkit.backend.utils.io import atomic_write_text
from agentkit.backend.vectordb.ingest.classify import (
    STORIES_DIR_NAME as _STORIES_DIR_NAME,
)
from agentkit.backend.vectordb.ingest.classify import (
    STORY_DIR_RE as _STORY_DIR_RE,
)
from agentkit.backend.vectordb.sync import SyncError
from agentkit.integration_clients.vectordb import VectorDbError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from agentkit.backend.story_context_manager.story_model import Story, StorySpecification
    from agentkit.backend.vectordb.schema import StoryContextObject

#: Minimum acceptable ``story.md`` size in bytes (FK-21 §21.11.5).
MIN_STORY_MD_BYTES = 500

#: Canonical export filename inside the story directory.
STORY_MD_FILENAME = "story.md"


@dataclass(frozen=True)
class StoryMdExportResult:
    """FK-conform export result (FK-21 §21.11, ``@dataclass(frozen=True)``).

    EXACTLY four fields (English wire keys, ARCH-55):

    Attributes:
        success: ``True`` only when the file was written, validated AND indexed.
        story_md_path: Absolute path of the target ``story.md``.
        file_size_bytes: Actual on-disk size after the write (0 when no file).
        error: Empty on success; the blocker cause otherwise (write error,
            < 500 bytes, missing frontmatter, indexing failure).
    """

    success: bool
    story_md_path: str
    file_size_bytes: int
    error: str


@runtime_checkable
class StoryAttributesPort(Protocol):
    """Narrow read surface over the authoritative AK3 story service.

    Returns the ``(Story, StorySpecification|None)`` pair for a display-ID, or
    ``None`` when the story is unknown (fail-closed: the export refuses to
    fabricate master data).
    """

    def get_story_detail(
        self, story_display_id: str
    ) -> tuple[Story, StorySpecification | None] | None:
        """Return the story detail tuple, or ``None`` when unknown."""
        ...


@runtime_checkable
class StoryIndexPort(Protocol):
    """Incremental Weaviate indexing surface (FK-21 §21.11.4).

    A thin seam over ``story_sync`` so the export depends on an indexing
    contract, not the transport. ``index_story`` raises
    :class:`~agentkit.integration_clients.vectordb.VectorDbError` on failure (hard
    blocker, fail-closed).
    """

    def index_story(
        self, *, story_id: str, project_id: str, objects: Sequence[StoryContextObject]
    ) -> int:
        """Index the story chunks; return the count written. Raises on failure.

        The objects are the TYPED projection (N42). Flattening them to property dicts
        dropped ``chunk_id``, and the indexer then had to re-derive that identity input
        -- which produced uuids the production identity validation rejects for every
        normally projected story. The identity now travels with the object.
        """
        ...


def _render_frontmatter(story: Story, exported_at: str) -> str:
    """Render the YAML frontmatter block (FK-21 §21.11.3).

    Carries the REAL story ``title``, ``status`` and ``story_type`` (R04): the
    exported ``story.md`` is the ingest source for the StoryContext projection, so
    the frontmatter must hold the actual metadata instead of leaving the ingest to
    fall back to the story id / an empty status.
    """
    data = {
        "story_id": story.story_display_id,
        "title": story.title,
        "status": story.status.value,
        "story_type": story.story_type.value,
        "labels": list(story.labels),
        "exported_at": exported_at,
    }
    body = yaml.safe_dump(data, sort_keys=True, allow_unicode=True, default_flow_style=False)
    return f"---\n{body}---\n"


def _render_section(heading: str, lines: Sequence[str]) -> list[str]:
    """Render a markdown section only when it carries content."""
    items = [line for line in lines if line.strip()]
    if not items:
        return []
    out = [f"## {heading}", ""]
    out.extend(f"- {item}" for item in items)
    out.append("")
    return out


def _render_body(story: Story, spec: StorySpecification | None) -> str:
    """Render the deterministic markdown body from the story attributes.

    ARCH-55 corpus-data exception: the section headings emitted here
    (``Metadaten``, ``Problemstellung``, ``Loesungsansatz``,
    ``Akzeptanzkriterien``, ``Konzept-Referenzen``, ``Guardrail-Referenzen``,
    ``Definition of Done`` ...) are DELIBERATELY German because the ``story.md``
    corpus is German Fachprosa and downstream parsers (e.g. the repo-affinity
    ``## Betroffene Dateien`` scan, FK-21 §21.9.1) and reviewers read the
    corpus' German section names. They match the real heading inventory of the
    existing ``stories/AG3-0XX/story.md`` files; emitting English headings here
    would diverge the generated export from the corpus. The operational wire
    keys inside the frontmatter (``story_id``, ``labels``, ``exported_at``) and
    all metadata field keys stay English per ARCH-55.
    """
    parts: list[str] = [f"# {story.title}", ""]
    parts.extend(
        _render_section(
            "Metadaten",
            [
                f"story_type: {story.story_type.value}",
                f"size: {story.size.value}",
                f"module: {story.module}" if story.module else "",
                f"epic: {story.epic}" if story.epic else "",
                f"change_impact: {story.change_impact.value}",
                f"concept_quality: {story.concept_quality.value}",
                f"new_structures: {str(story.new_structures).lower()}",
                f"vectordb_conflict_resolved: {str(story.vectordb_conflict_resolved).lower()}",
                f"participating_repos: {', '.join(story.participating_repos)}",
            ],
        )
    )
    if spec is not None:
        if spec.need:
            parts.extend(["## Problemstellung", "", spec.need, ""])
        if spec.solution:
            parts.extend(["## Loesungsansatz", "", spec.solution, ""])
        parts.extend(_render_section("Akzeptanzkriterien", spec.acceptance))
        # Corpus heading is "Konzept-Referenzen" (17x in the real story.md
        # corpus), not "Konzeptquellen"; keep the export consistent with it.
        parts.extend(_render_section("Konzept-Referenzen", spec.concept_refs or []))
        parts.extend(_render_section("Externe Quellen", spec.external_sources or []))
        parts.extend(_render_section("Guardrail-Referenzen", spec.guardrail_refs or []))
        parts.extend(_render_section("Definition of Done", spec.definition_of_done or []))
    return "\n".join(parts).rstrip("\n") + "\n"


#: Story corpus root name and the canonical story-directory pattern are owned by
#: the ingest classifier (ONE definition shared by export, repair and ingest).
STORIES_DIR_NAME = _STORIES_DIR_NAME
STORY_DIR_RE = _STORY_DIR_RE


def canonical_story_source_file(
    story_dir: Path, story_id: str, project_root: Path
) -> str:
    """Verify and return the PROJECT-RELATIVE corpus path of a story artefact (R04).

    FK-13 §13.3.2/§13.3.1 fix the story corpus layout as
    ``stories/<story>/story.md``; the indexed ``source_file`` must be that
    project-relative path, never an absolute filesystem path (the content hash and
    the deterministic object identity are derived from it). Using the SAME shape
    the ingest classifier recognises keeps export and ``story_sync`` on ONE corpus
    identity.

    The path is VERIFIED against the AUTHORITATIVE project root, not fabricated
    (N21/N31):

    - ``story_dir`` must resolve INSIDE ``project_root`` (no ``..`` escape, no
      foreign drive, no arbitrary absolute path whose parent merely happens to be
      called ``stories``);
    - its project-relative path must be exactly ``stories/<directory>``;
    - the directory must IDENTIFY ``story_id`` (``<STORY-ID>[-slug]``).

    Args:
        story_dir: The story directory.
        story_id: Story display-ID the export was requested for.
        project_root: The authoritative project root the corpus is relative to.

    Returns:
        e.g. ``stories/AK3-042/story.md``.

    Raises:
        ValueError: On any containment or identity violation (fail-closed).
    """
    from agentkit.backend.vectordb.ingest.classify import (
        classify_source_file,
        story_id_from_story_dir_name,
    )

    resolved = story_dir.resolve()
    root = project_root.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"story directory {resolved} resolves OUTSIDE the project root {root}; "
            "the corpus path must be project-relative (R04/N31, fail-closed)."
        ) from exc
    parts = relative.as_posix().split("/")
    if len(parts) != 2 or parts[0] != STORIES_DIR_NAME:
        raise ValueError(
            f"story directory {relative.as_posix()!r} is not contained in the "
            f"{STORIES_DIR_NAME!r} root of {root}; the canonical corpus layout is "
            "'<project>/stories/<story>/story.md' (R04/N21/N31, fail-closed)."
        )
    directory = parts[1]
    if story_id_from_story_dir_name(directory) != story_id:
        raise ValueError(
            f"story directory {directory!r} does not identify story {story_id!r}; the "
            f"corpus identity would be '{STORIES_DIR_NAME}/{directory}/"
            f"{STORY_MD_FILENAME}' and story_sync could never resolve it back to "
            "this story (R04/N21, fail-closed)."
        )
    rel = f"{STORIES_DIR_NAME}/{directory}/{STORY_MD_FILENAME}"
    if classify_source_file(rel) != "story":
        raise ValueError(
            f"{rel!r} is not a canonical story source path "
            f"(expected '{STORIES_DIR_NAME}/<story>/{STORY_MD_FILENAME}'); "
            "fail-closed (R04)."
        )
    return rel


def story_dir_story_id(directory_name: str) -> str | None:
    """Return the story id a story-directory name identifies (``None`` if none).

    Delegates to the SHARED canonical parser owned by the ingest classifier, so
    export, repair scan and research ingest agree (N32).
    """
    from agentkit.backend.vectordb.ingest.classify import story_id_from_story_dir_name

    return story_id_from_story_dir_name(directory_name)


def _story_index_objects(
    project_id: str,
    story: Story,
    story_md_path: Path,
    source_file: str,
) -> list[StoryContextObject]:
    """Build the indexing payload via the typed AG3-174 story-ingest projection (R04).

    Re-chunks the WRITTEN ``story.md`` through the SSOT chunker so every object
    carries ``content``/``project_id``/``source_type``/``source_file``/
    ``content_hash``/headings and a deterministic UUID derived from the
    PROJECT-RELATIVE ``source_file`` (AC3/R04). The export never sends the old
    minimal ``problem/solution`` shape.
    """
    from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects

    objects = story_file_to_objects(project_id, story_md_path, source_file=source_file)
    # Carry the story-level metadata that is not part of the story.md frontmatter
    # (module/epic) onto each chunk for filtering.
    for obj in objects:
        if story.module:
            obj.properties["module"] = story.module
        if story.epic:
            obj.properties["epic"] = story.epic
    # The TYPED objects are handed on unchanged (N42): ``chunk_id`` is the input the
    # deterministic uuid was derived from, so flattening them here would force the
    # indexer to guess it back and produce identities production rejects.
    return objects


def _validate_frontmatter(text: str) -> str | None:
    """Return an error string when frontmatter is missing required fields."""
    if not text.startswith("---\n"):
        return "story.md is missing a YAML frontmatter block (FK-21 §21.11.5)"
    end = text.find("\n---\n", 4)
    if end == -1:
        return "story.md frontmatter block is not terminated (FK-21 §21.11.5)"
    try:
        parsed = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:
        return f"story.md frontmatter is not valid YAML: {exc}"
    if not isinstance(parsed, dict):
        return "story.md frontmatter is not a YAML mapping"
    missing = [key for key in ("story_id", "exported_at") if not parsed.get(key)]
    if missing:
        return f"story.md frontmatter is missing required field(s): {sorted(missing)}"
    return None


def export_story_md(
    story_id: str,
    story_dir: Path,
    *,
    project_id: str,
    project_root: Path,
    story_attributes: StoryAttributesPort,
    index: StoryIndexPort,
    source_file: str | None = None,
) -> StoryMdExportResult:
    """Deterministically export a story as ``story.md`` (FK-21 §21.11).

    Args:
        story_id: Story display-ID (e.g. ``"AK3-042"``).
        story_dir: The story directory; ``story.md`` is written inside it.
        project_id: Bound multi-tenant discriminator for the indexed objects (R04).
        project_root: AUTHORITATIVE project root. ``story_dir`` and any supplied
            ``source_file`` are resolved and validated against it BEFORE anything
            is rendered or written (N31): a rejected path leaves no file on disk.
        story_attributes: Authoritative story-attribute read surface.
        index: Incremental Weaviate indexing surface (hard blocker on failure).
        source_file: PROJECT-RELATIVE corpus path of the exported artefact (R04).
            When given it must EQUAL the verified canonical path -- it is a
            cross-check, never a bypass.

    Returns:
        A :class:`StoryMdExportResult`; on ANY blocker ``success=False`` with a
        populated ``error`` and the actual ``file_size_bytes``.
    """
    target = story_dir / STORY_MD_FILENAME
    target_str = str(target)

    # N31: the corpus path is validated FIRST -- before rendering, before writing.
    # A non-canonical or non-contained directory must leave NOTHING on disk.
    try:
        rel_source = canonical_story_source_file(story_dir, story_id, project_root)
        if source_file is not None and source_file != rel_source:
            raise ValueError(
                f"supplied source_file {source_file!r} diverges from the verified "
                f"canonical corpus path {rel_source!r}; it is a cross-check, not a "
                "bypass (R04/N31, fail-closed)."
            )
    except ValueError as exc:
        return StoryMdExportResult(
            success=False,
            story_md_path=target_str,
            file_size_bytes=_safe_size(target),
            error=f"story corpus path rejected: {exc}",
        )

    detail = story_attributes.get_story_detail(story_id)
    if detail is None:
        return StoryMdExportResult(
            success=False,
            story_md_path=target_str,
            file_size_bytes=_safe_size(target),
            error=(
                f"story {story_id!r} is not in the AK3 story backend "
                "(fail-closed: export does not fabricate master data)"
            ),
        )
    story, spec = detail

    exported_at = datetime.now(UTC).isoformat()
    content = _render_frontmatter(story, exported_at) + "\n" + _render_body(story, spec)

    try:
        atomic_write_text(target, content)
    except OSError as exc:
        return StoryMdExportResult(
            success=False,
            story_md_path=target_str,
            file_size_bytes=_safe_size(target),
            error=f"failed to write story.md: {exc}",
        )

    size = _safe_size(target)
    if not target.is_file():
        return StoryMdExportResult(
            success=False,
            story_md_path=target_str,
            file_size_bytes=0,
            error="story.md was not written (file missing after write)",
        )
    if size <= MIN_STORY_MD_BYTES:
        return StoryMdExportResult(
            success=False,
            story_md_path=target_str,
            file_size_bytes=size,
            error=f"story.md is {size} bytes (<= {MIN_STORY_MD_BYTES}; FK-21 §21.11.5)",
        )
    frontmatter_error = _validate_frontmatter(content)
    if frontmatter_error is not None:
        return StoryMdExportResult(
            success=False,
            story_md_path=target_str,
            file_size_bytes=size,
            error=frontmatter_error,
        )

    # Automatic incremental Weaviate indexing -- HARD blocker (FK-21 §21.11.4).
    # Routed through the typed AG3-174 story-ingest projection (R04): full
    # StoryContext fields + deterministic UUIDs from the PROJECT-RELATIVE path,
    # project-bounded.
    try:
        objects = _story_index_objects(project_id, story, target, rel_source)
    except ValueError as exc:
        return StoryMdExportResult(
            success=False,
            story_md_path=target_str,
            file_size_bytes=size,
            error=f"story indexing projection rejected the export: {exc}",
        )
    try:
        index.index_story(
            story_id=story.story_display_id,
            project_id=project_id,
            objects=objects,
        )
    except (VectorDbError, SyncError) as exc:
        # SyncError too (N42): the index routes through the claim-aware sync
        # owner, so a rejected claim, an unpublishable generation or a superseded
        # window arrives as a SyncError -- and it must block the export exactly
        # like a transport fault instead of escaping unhandled.
        indexing_error = f"Weaviate indexing failed: {exc} (fail-closed: indexing " \
            "failure blocks the export, no catch-up path, FK-21 §21.11.4)"
        return StoryMdExportResult(
            success=False,
            story_md_path=target_str,
            file_size_bytes=size,
            error=indexing_error,
        )

    return StoryMdExportResult(
        success=True,
        story_md_path=target_str,
        file_size_bytes=size,
        error="",
    )


def _safe_size(path: Path) -> int:
    """Return the file size in bytes, or 0 when the file is absent."""
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


__all__ = [
    "MIN_STORY_MD_BYTES",
    "STORIES_DIR_NAME",
    "STORY_DIR_RE",
    "STORY_MD_FILENAME",
    "StoryAttributesPort",
    "StoryIndexPort",
    "StoryMdExportResult",
    "canonical_story_source_file",
    "export_story_md",
    "story_dir_story_id",
]
