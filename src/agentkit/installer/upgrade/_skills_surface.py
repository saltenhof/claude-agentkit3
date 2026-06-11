"""Default agent-skills top-surface builder for read-only footprint detection.

The :class:`CustomizationFootprint` reads skill bindings ONLY through the
agent-skills top surface ``Skills.resolve_binding`` (FK-51 §51.8, FK-43 §43.5).
This builds the default productive ``Skills`` surface scoped to a project root
for the read-only detection path — the same wiring the installer's default
composition uses (``_resolve_skills_and_store``), so no second skills wiring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.skills import Skills


def build_skills_surface(project_root: Path) -> Skills | None:
    """Return the default ``Skills`` top-surface scoped to ``project_root``.

    Read-only consumer of the agent-skills BC (FK-43): builds the same default
    productive ``Skills`` (state-backend binding repository scoped to the project
    root) the installer's default composition uses. Returns ``None`` when the
    surface cannot be constructed (e.g. no state backend), so footprint detection
    degrades to "no skill customization detected" rather than failing.

    Args:
        project_root: The target-project root.

    Returns:
        The ``Skills`` surface, or ``None`` when it cannot be built.
    """
    from agentkit.skills import SkillBundleStore, Skills
    from agentkit.state_backend.store.skill_binding_repository import (
        StateBackendSkillBindingRepository,
    )

    try:
        return Skills(
            bundle_store=SkillBundleStore(),
            binding_repo=StateBackendSkillBindingRepository(project_root),
        )
    except Exception:  # noqa: BLE001 - read-only detection must not hard-fail
        return None


__all__ = ["build_skills_surface"]
