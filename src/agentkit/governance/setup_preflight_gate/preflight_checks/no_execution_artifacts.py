"""Preflight Check 5 — ``no_execution_artifacts`` (FK-22 §22.3.1).

No leftover execution artifacts from a prior, unfinished run.  The default
probe inspects the ``_temp/stories/{story_id}/`` directory for residual
files (story.md §2.1.1); a custom probe may be injected via
:class:`PreflightContext`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightCheckResult,
    PreflightStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.governance.setup_preflight_gate.preflight import PreflightContext

_CHECK_ID = PreflightCheckId.NO_EXECUTION_ARTIFACTS


def _default_probe(project_root: Path, story_display_id: str) -> bool:
    """Return ``True`` when ``_temp/stories/{story_id}/`` holds leftover files.

    An absent or empty directory means there are no execution artifacts.
    """
    residue_dir = project_root / "_temp" / "stories" / story_display_id
    if not residue_dir.is_dir():
        return False
    return any(residue_dir.iterdir())


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Verify no leftover execution artifacts exist (FK-22 §22.3.1, Check 5).

    Args:
        ctx: The preflight context.

    Returns:
        ``PASS`` when no residual artifacts exist; ``FAIL`` otherwise.
    """
    probe = ctx.execution_artifacts_present or _default_probe
    if probe(ctx.project_root, ctx.story_display_id):
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.FAIL,
            detail=(
                f"Execution artifacts from an unfinished prior run found for "
                f"{ctx.story_display_id!r}"
            ),
            cleanup_hint=(
                f"Run `agentkit cleanup --story {ctx.story_display_id}` to "
                "remove leftover execution artifacts, then restart."
            ),
        )
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.PASS,
        detail=f"No leftover execution artifacts for {ctx.story_display_id!r}",
    )
