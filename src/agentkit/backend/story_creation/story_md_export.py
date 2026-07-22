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
from agentkit.integration_clients.vectordb import VectorDbError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from agentkit.backend.story_context_manager.story_model import Story, StorySpecification

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

    def index_story(self, *, story_id: str, objects: Sequence[dict[str, object]]) -> int:
        """Index the story chunks; return the count written. Raises on failure."""
        ...


def _render_frontmatter(story: Story, exported_at: str) -> str:
    """Render the YAML frontmatter block (FK-21 §21.11.3)."""
    data = {
        "story_id": story.story_display_id,
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


def _story_index_objects(story: Story, spec: StorySpecification | None) -> list[dict[str, object]]:
    """Build the indexing payload chunks (FK-21 §21.11.4 / FK-13 §13.3.1).

    Full StoryContext fields including ``content``, ``project_id``,
    ``content_hash``, ``source_type`` and deterministic ``chunk_uuid``.
    """
    from agentkit.backend.vectordb.ingest.builders import build_story_export_chunks

    body_parts: list[str] = []
    if spec is not None:
        if spec.need:
            body_parts.append(f"## Problemstellung\n\n{spec.need}")
        if spec.solution:
            body_parts.append(f"## Loesungsansatz\n\n{spec.solution}")
    body = "\n\n".join(body_parts) if body_parts else story.title
    project_id = getattr(story, "project_key", None) or getattr(story, "project_id", None) or ""
    if not project_id or not isinstance(project_id, str):
        raise VectorDbError(
            "story export indexing requires story.project_key "
            "(no invented 'default' project_id, R15)."
        )
    source_file = f"stories/{story.story_display_id}/story.md"
    records = build_story_export_chunks(
        project_id=str(project_id),
        story_id=story.story_display_id,
        title=story.title,
        body=body,
        source_file=source_file,
        meta={
            "status": getattr(getattr(story, "status", None), "value", "") or "",
            "story_type": story.story_type.value,
            "module": story.module,
            "epic": story.epic,
        },
    )
    return [r.to_properties() for r in records]


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
    story_attributes: StoryAttributesPort,
    index: StoryIndexPort,
) -> StoryMdExportResult:
    """Deterministically export a story as ``story.md`` (FK-21 §21.11).

    Args:
        story_id: Story display-ID (e.g. ``"AK3-042"``).
        story_dir: The story directory; ``story.md`` is written inside it.
        story_attributes: Authoritative story-attribute read surface.
        index: Incremental Weaviate indexing surface (hard blocker on failure).

    Returns:
        A :class:`StoryMdExportResult`; on ANY blocker ``success=False`` with a
        populated ``error`` and the actual ``file_size_bytes``.
    """
    target = story_dir / STORY_MD_FILENAME
    target_str = str(target)

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
    try:
        index.index_story(
            story_id=story.story_display_id,
            objects=_story_index_objects(story, spec),
        )
    except VectorDbError as exc:
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
    "STORY_MD_FILENAME",
    "StoryAttributesPort",
    "StoryIndexPort",
    "StoryMdExportResult",
    "export_story_md",
]
