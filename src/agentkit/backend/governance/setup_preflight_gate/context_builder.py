"""Build StoryContext from a GitHub issue."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.governance.errors import StoryModeResolutionError
from agentkit.backend.governance.setup_preflight_gate.mode_determination import determine_mode
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.sizing import estimate_size
from agentkit.backend.story_context_manager.story_model import (
    ChangeImpact,
    ConceptQuality,
    WireStoryMode,
)
from agentkit.backend.story_context_manager.types import StoryType, get_profile
from agentkit.integration_clients.github.issues import get_issue

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.story_context_manager.service import StoryService


def _extract_story_type(labels: tuple[str, ...]) -> StoryType:
    """Extract story type from issue labels.

    Searches labels for a recognised story-type name (case-insensitive).
    ``"bug"`` and ``"bugfix"`` both map to :attr:`StoryType.BUGFIX`.

    Args:
        labels: Tuple of label names from the issue.

    Returns:
        The matched ``StoryType``, or ``IMPLEMENTATION`` as default.
    """
    for label in labels:
        normalized = label.strip().lower()
        if normalized in ("bug", "bugfix"):
            return StoryType.BUGFIX
        if normalized == "concept":
            return StoryType.CONCEPT
        if normalized == "research":
            return StoryType.RESEARCH
    return StoryType.IMPLEMENTATION


def _extract_mode(labels: tuple[str, ...]) -> WireStoryMode:
    """Extract the fast/standard mode from issue labels (legacy/standalone only).

    The fast/standard ``mode`` is a SEPARATE axis from the
    ``execution_route`` (EXECUTION/EXPLORATION) path. A ``fast`` label
    (AG3-018) opts the run into fast mode; everything else is ``standard``.

    FIX-1 (FK-24 §24.3.3, CLAUDE.md SINGLE SOURCE OF TRUTH): GitHub fields are
    setup INPUT, NOT operative truth. The authoritative ``mode`` is the one
    persisted by ``StoryService`` (``Story.mode``); :func:`build_story_context`
    reads it from there. This label-based extractor remains ONLY for the
    standalone/legacy path where no ``StoryService`` record is available.

    Args:
        labels: Tuple of label names from the issue.

    Returns:
        :attr:`WireStoryMode.FAST` if a ``fast`` label is present, else
        :attr:`WireStoryMode.STANDARD`.
    """
    for label in labels:
        if label.strip().lower() == "fast":
            return WireStoryMode.FAST
    return WireStoryMode.STANDARD


def _resolve_authoritative_mode(
    story_service: StoryService | None,
    story_display_id: str,
    labels: tuple[str, ...],
) -> WireStoryMode:
    """Resolve the operative fast/standard ``mode`` (FIX-1, FK-24 §24.3.3).

    The AUTHORITATIVE source is the ``StoryService`` record (``Story.mode``); the
    GitHub label is only the legacy/standalone fallback when no service is wired.
    Fail-closed (CLAUDE.md FAIL-CLOSED): a wired service that does not know the
    story raises :class:`StoryModeResolutionError` rather than silently defaulting
    to a label-derived or ``standard`` mode (an unverifiable mode would let an
    invalid Fast/Standard run proceed).

    Args:
        story_service: The authoritative ``StoryService`` (``None`` =>
            standalone/legacy; the label fallback then applies).
        story_display_id: The story display ID used to look the record up.
        labels: Issue labels (the legacy fallback source only).

    Returns:
        The authoritative :class:`WireStoryMode`.

    Raises:
        StoryModeResolutionError: When a service is wired but the story record
            is missing.
    """
    if story_service is None:
        return _extract_mode(labels)
    story = story_service.get_story(story_display_id)
    if story is None:
        raise StoryModeResolutionError(
            f"cannot resolve the authoritative mode: story {story_display_id!r} "
            "is not in the StoryService store (FIX-1, fail-closed -- the GitHub "
            "label is not operative truth, FK-24 §24.3.3)",
            detail={"story_display_id": story_display_id},
        )
    # ``Story.mode`` is ``WireStoryMode | None``; ``None`` (an older record
    # created before the mode field) is the standard default.
    return story.mode if story.mode is not None else WireStoryMode.STANDARD


def _resolve_trigger_inputs(
    story_service: StoryService | None,
    story_display_id: str,
) -> tuple[ChangeImpact | None, ConceptQuality | None, bool, bool, tuple[str, ...]]:
    """Resolve the 4-trigger inputs from the authoritative StoryService record.

    AG3-057 (FK-22 §22.8.1): trigger inputs are read from the Story stammdaten
    record and its StorySpecification (Single Source of Truth).  When no
    StoryService is wired (standalone / legacy path) the trigger inputs are
    unknown; returning ``None`` for ``change_impact`` and ``concept_quality``
    causes ``determine_mode`` to fail-closed (→ Exploration via Trigger 2 / 4
    WARNING branch).  An empty ``concept_refs`` tuple causes Trigger 1 to fire
    (fail-closed).

    ``concept_refs`` is the same StorySpecification reference list projected into
    the typed run context; it is consumed by the sandbox guard in
    :func:`~.mode_determination._has_valid_concept_refs`.

    Args:
        story_service: The authoritative ``StoryService`` (``None`` =>
            standalone/legacy; fail-closed defaults apply).
        story_display_id: The story display ID used to look the record up.

    Returns:
        A 5-tuple of ``(change_impact, concept_quality, new_structures,
        vectordb_conflict_resolved, concept_refs)`` where ``change_impact`` and
        ``concept_quality`` are ``None`` when the record is unavailable
        (fail-closed → Exploration), ``vectordb_conflict_resolved`` projects the
        authoritative AG3-068 producer flag (default ``False`` when the record
        is absent), and ``concept_refs`` is an empty tuple when the spec is
        absent or ``concept_refs`` is None/empty (fail-closed → Trigger 1 fires).
    """
    if story_service is None:
        # No record available; fail-closed: None signals "unknown" to determine_mode.
        return None, None, False, False, ()

    detail = story_service.get_story_detail(story_display_id)
    if detail is None:
        # Record absent; fail-closed: None signals "unknown".
        return None, None, False, False, ()

    story, spec = detail
    # AC8: project StorySpecification.concept_refs into the run context.
    # Empty tuple when spec absent or refs genuinely absent (fail-closed → Trigger 1).
    concept_refs: tuple[str, ...] = (
        tuple(ref for ref in spec.concept_refs if ref)
        if spec is not None and spec.concept_refs
        else ()
    )

    return (
        story.change_impact,
        story.concept_quality,
        story.new_structures,
        story.vectordb_conflict_resolved,
        concept_refs,
    )


def build_story_context(
    owner: str,
    repo: str,
    issue_nr: int,
    project_root: Path,
    project_key: str,
    story_id: str | None = None,
    *,
    story_service: StoryService | None = None,
) -> StoryContext:
    """Build a ``StoryContext`` by reading a GitHub issue.

    Steps:
        1. Fetch the issue via :func:`~agentkit.integration_clients.github.issues.get_issue`.
        2. Extract ``story_type`` from labels.
        3. Determine execution route from the story-type profile's default.
        3a. Resolve the fast/standard ``mode`` axis (FK-24 §24.3.3) from the
            AUTHORITATIVE ``StoryService`` record (FIX-1) -- NOT from labels;
            GitHub fields are setup INPUT, not operative truth (CLAUDE.md). The
            label is the standalone/legacy fallback only.
        4. Estimate size from labels and title.
        5. Generate ``story_id`` if not provided.
        6. Build and return the ``StoryContext`` (the model enforces fast-only-
           for-impl/bugfix fail-closed, AC7).

    Args:
        owner: GitHub repository owner.
        repo: GitHub repository name.
        issue_nr: Issue number to read.
        project_root: Path to the target project root.
        story_id: Optional explicit story ID.  If ``None``, derived
            as ``"STORY-{issue_nr}"``.
        story_service: The authoritative ``StoryService`` (FIX-1). When wired the
            operative ``mode`` is read from its record; when ``None`` the
            standalone/legacy label fallback applies.

    Returns:
        Populated ``StoryContext`` with all fields from the issue.
    """
    issue = get_issue(owner, repo, issue_nr)

    story_type = _extract_story_type(issue.labels)

    resolved_story_id = story_id if story_id is not None else f"STORY-{issue_nr}"
    story_mode = _resolve_authoritative_mode(
        story_service, resolved_story_id, issue.labels
    )
    story_number = _story_number_from_id(resolved_story_id) or issue.number

    # AG3-057: build a preliminary context without execution_route to derive the
    # trigger-input fields, then call determine_mode for the real route.
    # For the standalone/GitHub path, trigger inputs are not available from the
    # issue itself — they come from the StoryService record.  When no service is
    # wired, we fall back to fail-closed defaults (execution_route=EXPLORATION
    # for implementing types via determine_mode's Trigger 1: no concept_refs).
    (
        change_impact_val,
        concept_quality_val,
        new_structures_val,
        vectordb_conflict_resolved_val,
        concept_refs_val,
    ) = _resolve_trigger_inputs(story_service, resolved_story_id)

    # Build a minimal context shell to pass to determine_mode.
    _shell = StoryContext(
        project_key=project_key,
        story_number=story_number,
        story_id=resolved_story_id,
        story_type=story_type,
        # Temporary: allowed_modes validator requires a valid route; use profile
        # default so the shell validates, then we overwrite via determine_mode.
        execution_route=get_profile(story_type).default_mode,
        mode=story_mode,
        change_impact=change_impact_val,
        concept_quality=concept_quality_val,
        new_structures=new_structures_val,
        vectordb_conflict_resolved=vectordb_conflict_resolved_val,
        concept_refs=concept_refs_val,
        issue_nr=issue.number,
        title=issue.title,
        story_size=estimate_size(list(issue.labels), issue.title),
        project_root=project_root,
        participating_repos=[repo],
        labels=list(issue.labels),
        created_at=datetime.now(tz=UTC),
    )
    real_route = determine_mode(_shell, project_root=project_root)

    return StoryContext(
        project_key=project_key,
        story_number=story_number,
        story_id=resolved_story_id,
        story_type=story_type,
        execution_route=real_route,
        mode=story_mode,
        change_impact=change_impact_val,
        concept_quality=concept_quality_val,
        new_structures=new_structures_val,
        vectordb_conflict_resolved=vectordb_conflict_resolved_val,
        concept_refs=concept_refs_val,
        issue_nr=issue.number,
        title=issue.title,
        story_size=estimate_size(list(issue.labels), issue.title),
        project_root=project_root,
        participating_repos=[repo],
        labels=list(issue.labels),
        created_at=datetime.now(tz=UTC),
    )


def build_internal_story_context(
    project_root: Path,
    project_key: str,
    story_id: str,
    *,
    story_service: StoryService | None = None,
) -> StoryContext:
    """Build a ``StoryContext`` for an INTERNAL (non-code-producing) story (#2).

    ERROR-2 fix (FK-12 §12.7.1): an internal story (CONCEPT/RESEARCH) has no
    GitHub worktree/merge and therefore NO GitHub coordinates. It must NEVER hit
    GitHub: this path builds the context from the AUTHORITATIVE ``StoryService``
    record (the operative truth for an internal story's stammdaten) and the
    state-backend, WITHOUT calling :func:`get_issue`. There is no dummy
    owner/repo/issue passed into a GitHub-reading code path.

    The story-type / mode / title / size are read from the ``StoryService``
    record. Fail-closed (CLAUDE.md FAIL-CLOSED): a wired service that does not
    know the story raises :class:`StoryModeResolutionError` -- an internal setup
    must not fabricate stammdaten for an unknown story. When no service is wired
    (standalone/legacy), the caller-supplied initial context is the fallback and
    a minimal CONCEPT context is built (no GitHub, the documented absent-service
    case).

    Args:
        project_root: Path to the target project root.
        project_key: The project key.
        story_id: The story display ID.
        story_service: The authoritative ``StoryService``. When wired the
            stammdaten are read from its record; when ``None`` a minimal internal
            context is built (standalone/legacy).

    Returns:
        A ``StoryContext`` for the internal story, built without GitHub.

    Raises:
        StoryModeResolutionError: When a service is wired but the story record
            is missing.
    """
    if story_service is None:
        # Standalone/legacy: no authoritative record. Build a minimal internal
        # context (CONCEPT, standard) -- still NO GitHub read.
        _concept_profile = get_profile(StoryType.CONCEPT)
        return StoryContext(
            project_key=project_key,
            story_number=_story_number_from_id(story_id) or 0,
            story_id=story_id,
            story_type=StoryType.CONCEPT,
            # determine_mode returns None for CONCEPT — use the profile default
            # directly (no trigger evaluation needed for non-implementing types).
            execution_route=_concept_profile.default_mode,
            mode=WireStoryMode.STANDARD,
            project_root=project_root,
            created_at=datetime.now(tz=UTC),
        )

    detail = story_service.get_story_detail(story_id)
    if detail is None:
        raise StoryModeResolutionError(
            f"cannot build the internal story context: story {story_id!r} is not "
            "in the StoryService store (fail-closed -- an internal setup must not "
            "fabricate stammdaten or read GitHub for an unknown story; "
            "FK-12 §12.7.1).",
            detail={"story_display_id": story_id},
        )
    story, spec = detail
    story_type = StoryType(story.story_type.value)
    story_mode = story.mode if story.mode is not None else WireStoryMode.STANDARD

    # Resolve trigger inputs from the authoritative Story record + spec (AC8).
    change_impact_val: ChangeImpact | None = story.change_impact
    concept_quality_val: ConceptQuality | None = story.concept_quality
    new_structures_val = story.new_structures
    # AG3-068 (FK-21 §21.12): project the authoritative VectorDB-conflict producer
    # flag so determine_mode reads the SSOT instead of the fail-closed default.
    vectordb_conflict_resolved_val = story.vectordb_conflict_resolved
    # AC8: project StorySpecification.concept_refs into the run context.
    # Fail-closed: empty tuple when spec absent or refs genuinely absent
    # (Trigger 1 fires for implementing stories without concept references).
    concept_refs_val: tuple[str, ...] = (
        tuple(ref for ref in spec.concept_refs if ref)
        if spec is not None and spec.concept_refs
        else ()
    )

    # AG3-057: Build a preliminary shell to drive determine_mode.
    _shell = StoryContext(
        project_key=project_key,
        story_number=_story_number_from_id(story_id) or story.story_number,
        story_id=story_id,
        story_type=story_type,
        execution_route=get_profile(story_type).default_mode,
        mode=story_mode,
        change_impact=change_impact_val,
        concept_quality=concept_quality_val,
        new_structures=new_structures_val,
        vectordb_conflict_resolved=vectordb_conflict_resolved_val,
        concept_refs=concept_refs_val,
        title=story.title,
        story_size=story.size,
        project_root=project_root,
        participating_repos=list(story.participating_repos),
        labels=list(story.labels),
        created_at=datetime.now(tz=UTC),
    )
    real_route = determine_mode(_shell, project_root=project_root)

    return StoryContext(
        project_key=project_key,
        story_number=_story_number_from_id(story_id) or story.story_number,
        story_id=story_id,
        story_type=story_type,
        execution_route=real_route,
        mode=story_mode,
        change_impact=change_impact_val,
        concept_quality=concept_quality_val,
        new_structures=new_structures_val,
        vectordb_conflict_resolved=vectordb_conflict_resolved_val,
        concept_refs=concept_refs_val,
        title=story.title,
        story_size=story.size,
        project_root=project_root,
        participating_repos=list(story.participating_repos),
        labels=list(story.labels),
        created_at=datetime.now(tz=UTC),
    )


def _story_number_from_id(story_id: str) -> int | None:
    suffix = story_id.rsplit("-", maxsplit=1)[-1]
    if not suffix.isdigit():
        return None
    return int(suffix)
