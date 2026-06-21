"""Deterministic 4-trigger mode determination for the Setup phase (AG3-057).

Implements ``determine_mode`` as specified in FK-22 §22.8.1 / §22.8.2 and
FK-23 §23.2.1.  The function derives the ``execution_route`` (EXECUTION or
EXPLORATION) from four independent triggers rather than from a story-type
default.

Design decisions (from the story):
- Non-implementing story types (concept / research) return ``None`` immediately
  without trigger evaluation (FK-24 §24.3.2).
- VektorDB-conflict has precedence over the four triggers (FK-22 §22.8.1).
- Any unresolvable field value (``None``) is fail-closed: Exploration + WARNING.
- Default when all inputs are clean: Execution (not Exploration; Exploration is
  only triggered by an explicit signal, missing field, or VektorDB-conflict).
- Default/fallback when uncertainty is detected: Exploration (FK-23 §23.2.1).

Imports are intentionally kept minimal; no circular dependency with
``context_builder`` (this module is imported BY context_builder).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.story_context_manager.story_model import ChangeImpact, ConceptQuality
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from agentkit.backend.story_context_manager.models import StoryContext

_log = logging.getLogger(__name__)

#: Story types for which mode determination applies (FK-23 §23.1).
_IMPLEMENTING_TYPES: frozenset[StoryType] = frozenset(
    {StoryType.IMPLEMENTATION, StoryType.BUGFIX}
)


def determine_mode(
    context: StoryContext,
    *,
    project_root: Path | None = None,
) -> StoryMode | None:
    """Derive the ``execution_route`` from the four independent triggers.

    Implements FK-22 §22.8.1 (reference implementation) in a typed,
    ARCH-55-conformant form.  The decision order is:

    1. Story-type gate: non-implementing types (concept / research) return
       ``None`` immediately; no trigger evaluation (FK-24 §24.3.2).
    2. VektorDB-conflict precedence: ``vectordb_conflict_resolved`` forces
       Exploration before any trigger check (FK-22 §22.8.1).
    3. Trigger 1 — no valid concept paths: ``_has_valid_concept_paths`` fails
       → Exploration + WARNING.
    4. Trigger 2 — Architecture Impact: ``change_impact is None`` (unknown) →
       Exploration + WARNING (fail-closed); ``change_impact ==
       ChangeImpact.ARCHITECTURE_IMPACT`` → Exploration + INFO.
    5. Trigger 3 — new structures: ``new_structures`` is ``True`` → Exploration
       + INFO.
    6. Trigger 4 — low concept quality: ``concept_quality is None`` (unknown) →
       Exploration + WARNING (fail-closed); ``concept_quality ==
       ConceptQuality.LOW`` → Exploration + INFO.
    7. No trigger active → Execution Mode.

    Args:
        context: The populated ``StoryContext`` for this run.  The trigger
            inputs are read from its fields (``vectordb_conflict_resolved``,
            ``concept_paths``, ``change_impact``, ``new_structures``,
            ``concept_quality``).
        project_root: Filesystem root of the target project.  Forwarded to
            ``_has_valid_concept_paths`` as the sandbox boundary.  When
            ``None`` the guard falls back to ``Path.cwd()`` and emits a
            WARNING (FK-22 §22.8.1 bug-fix note).

    Returns:
        ``StoryMode.EXPLORATION`` or ``StoryMode.EXECUTION`` for implementing
        story types; ``None`` for concept / research stories (FK-24 §24.3.2).
    """
    # --- Step 1: story-type gate -------------------------------------------
    if StoryType(context.story_type) not in _IMPLEMENTING_TYPES:
        _log.debug(
            "determine_mode: story_type=%r is not implementing — returning None "
            "(FK-24 §24.3.2)",
            context.story_type,
        )
        return None

    # --- Step 2: VektorDB-conflict precedence --------------------------------
    if context.vectordb_conflict_resolved:
        _log.info(
            "determine_mode: vectordb_conflict_resolved=True — "
            "Exploration (VektorDB-conflict precedence, FK-22 §22.8.1)",
        )
        return StoryMode.EXPLORATION

    # --- Trigger 1: no valid concept paths -----------------------------------
    if not _has_valid_concept_paths(context.concept_paths, project_root=project_root):
        _log.warning(
            "determine_mode: no valid concept reference — Exploration (Trigger 1, "
            "FK-22 §22.8.1)",
        )
        return StoryMode.EXPLORATION

    # --- Trigger 2: change impact --------------------------------------------
    if context.change_impact is None:
        # Unresolvable field value → fail-closed
        _log.warning(
            "determine_mode: change_impact is None (unresolvable) — "
            "Exploration + WARNING (fail-closed, FK-22 §22.8.2)",
        )
        return StoryMode.EXPLORATION

    if context.change_impact is ChangeImpact.ARCHITECTURE_IMPACT:
        _log.info(
            "determine_mode: change_impact=ARCHITECTURE_IMPACT — "
            "Exploration (Trigger 2, FK-22 §22.8.1)",
        )
        return StoryMode.EXPLORATION

    # --- Trigger 3: new structures -------------------------------------------
    if context.new_structures:
        _log.info(
            "determine_mode: new_structures=True — "
            "Exploration (Trigger 3, FK-22 §22.8.1)",
        )
        return StoryMode.EXPLORATION

    # --- Trigger 4: concept quality ------------------------------------------
    if context.concept_quality is None:
        # Unresolvable field value → fail-closed
        _log.warning(
            "determine_mode: concept_quality is None (unresolvable) — "
            "Exploration + WARNING (fail-closed, FK-22 §22.8.2)",
        )
        return StoryMode.EXPLORATION

    if context.concept_quality is ConceptQuality.LOW:
        _log.info(
            "determine_mode: concept_quality=LOW — "
            "Exploration (Trigger 4, FK-22 §22.8.1)",
        )
        return StoryMode.EXPLORATION

    # --- No trigger active → Execution ---------------------------------------
    _log.debug(
        "determine_mode: no trigger active — Execution Mode (FK-22 §22.8.1)",
    )
    return StoryMode.EXECUTION


def _has_valid_concept_paths(
    concept_paths: tuple[str, ...],
    *,
    project_root: Path | None,
) -> bool:
    """Validate that at least one concept path is non-empty, exists, and is in-sandbox.

    FK-22 §22.8.1 Sandbox-Guard: a path outside ``project_root``, an empty
    string, or a non-existent file counts as "no valid concept" and causes
    Trigger 1 to fire.

    Args:
        concept_paths: Candidate concept-reference paths from ``StoryContext``.
        project_root: Filesystem boundary for the sandbox guard.  ``None``
            causes a CWD fallback with a WARNING (FK-22 §22.8.1 bug-fix note).

    Returns:
        ``True`` if at least one path is non-empty, lies inside
        ``project_root``, and exists on the filesystem.  ``False`` otherwise.
    """
    if project_root is None:
        _log.warning(
            "_has_valid_concept_paths: project_root is None — "
            "falling back to CWD as sandbox boundary (FK-22 §22.8.1 bug-fix)",
        )
        resolved_root = Path.cwd().resolve()
    else:
        resolved_root = Path(project_root).resolve()

    for raw_path in concept_paths:
        if not raw_path or not raw_path.strip():
            # Empty or whitespace-only path — skip.
            continue

        candidate = Path(raw_path)
        if not candidate.is_absolute():
            # Relative paths are anchored to project_root.
            candidate = resolved_root / candidate

        try:
            resolved_candidate = candidate.resolve()
        except (OSError, ValueError):
            # Unresolvable (e.g. null bytes on some platforms) — skip.
            continue

        # Sandbox check: must be inside project_root.
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError:
            _log.warning(
                "_has_valid_concept_paths: path %r is outside project_root %r "
                "— skipping (sandbox violation, FK-22 §22.8.1)",
                str(resolved_candidate),
                str(resolved_root),
            )
            continue

        # Existence check.
        if resolved_candidate.exists():
            return True

    return False


__all__ = [
    "determine_mode",
]
