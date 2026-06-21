"""Cleanup mode for obsolete bindings / local config remnants (FK-51 §51.7).

The cleanup mode removes OBSOLETE symlink bindings and local AgentKit config
remnants. It NEVER touches project code or central runtime data (FK-51 §51.7).
Before any deletion every target is checked against the
:class:`CustomizationFootprint`: if ANY target is a detected customization the
whole cleanup is blocked fail-closed (``CustomizationPreservationError`` is
raised) and NOTHING is removed — the F-51-023 invariant for the cleanup write
path (story AC8: the write path "blocks/reports and mutates not"). Legitimate
removals (non-customized obsolete remnants) only run once every target cleared
the footprint guard (no partial deletion).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.installer.upgrade.footprint import CustomizationFootprint


class CleanupAction(StrEnum):
    """The outcome of a single cleanup target (typed, story §5).

    Attributes:
        REMOVED: An obsolete target was removed.
        ABSENT: The target did not exist; nothing to do.

    There is no ``PRESERVED`` outcome: a detected customization does not
    downgrade to a soft "preserved" result — it raises
    :class:`~agentkit.backend.installer.upgrade.footprint.CustomizationPreservationError`
    fail-closed before any removal (F-51-023, story AC8).
    """

    REMOVED = "removed"
    ABSENT = "absent"


@dataclass(frozen=True)
class CleanupTargetResult:
    """The result for one cleanup target.

    Attributes:
        target: The filesystem target considered.
        identifier: The footprint identifier checked for this target.
        action: The :class:`CleanupAction` taken.
        detail: Human-readable description.
    """

    target: Path
    identifier: str
    action: CleanupAction
    detail: str


@dataclass(frozen=True)
class CleanupPlan:
    """A typed cleanup request (story §5 — typed, not loose strings).

    Attributes:
        obsolete_link_targets: ``(path, footprint_identifier)`` pairs for obsolete
            symlink bindings to remove. ``identifier`` is what the footprint check
            uses to decide preservation.
        obsolete_config_targets: ``(path, footprint_identifier)`` pairs for local
            AgentKit config remnants to remove.
    """

    obsolete_link_targets: tuple[tuple[Path, str], ...] = field(default_factory=tuple)
    obsolete_config_targets: tuple[tuple[Path, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CleanupOutcome:
    """The aggregate result of a cleanup run.

    A cleanup run that reaches removal carries NO preserved customizations: a
    detected customization aborts the run fail-closed before any removal
    (F-51-023). The outcome therefore only reports REMOVED / ABSENT targets.

    Attributes:
        results: Per-target results.
    """

    results: tuple[CleanupTargetResult, ...]

    @property
    def removed(self) -> tuple[Path, ...]:
        """Return the targets that were removed."""
        return tuple(
            r.target for r in self.results if r.action is CleanupAction.REMOVED
        )


def _remove_target(target: Path) -> None:
    """Remove a symlink/junction or a regular file/dir remnant safely (FK-51 §51.7).

    A symlink/junction is removed via ``unlink`` / ``rmdir`` (never recursively
    through the link, FK-50 §50.3 CP 8 rule). A regular file is unlinked. A
    regular directory remnant is removed with its contents (local AgentKit config
    remnant only — the plan never targets project code or central runtime data,
    FK-51 §51.7).
    """
    import os
    import shutil

    if target.is_symlink():
        target.unlink()
        return
    if os.path.isjunction(target):  # Windows directory junction (FK-43 §43.4.1.1).
        os.rmdir(target)
        return
    if target.is_dir():
        shutil.rmtree(target)
        return
    target.unlink()


def run_cleanup(
    plan: CleanupPlan,
    footprint: CustomizationFootprint,
) -> CleanupOutcome:
    """Run the cleanup mode fail-closed against the footprint (FK-51 §51.7, AC6/AC8).

    Two phases, fail-closed (story AC8 — the cleanup write path "blocks/reports
    and mutates not"):

    1. GUARD: every plan target is checked against the footprint via
       :meth:`CustomizationFootprint.guard_write`. If ANY target is a detected
       customization a :class:`CustomizationPreservationError` is raised and
       NOTHING is removed — no partial deletion (F-51-023). This is the SAME
       never-silently-overwrite truth as every other write path (story §6).
    2. REMOVE: only once every target cleared the guard, the obsolete targets are
       removed (REMOVED) or reported absent (ABSENT). Legitimate removals of
       non-customized obsolete remnants keep working (story AC6).

    Args:
        plan: The typed cleanup plan (obsolete link + config targets).
        footprint: The detected customization footprint to honour.

    Returns:
        The :class:`CleanupOutcome` (REMOVED / ABSENT targets only).

    Raises:
        CustomizationPreservationError: When ANY plan target is a detected
            customization (F-51-023 — blocked before any removal).
    """
    all_targets = (*plan.obsolete_link_targets, *plan.obsolete_config_targets)
    # Phase 1 — GUARD every target BEFORE any removal (no partial deletion).
    for _target, identifier in all_targets:
        footprint.guard_write(identifier, write_path="cleanup")
    # Phase 2 — REMOVE: every target cleared the guard.
    results: list[CleanupTargetResult] = []
    for target, identifier in all_targets:
        if not (target.exists() or target.is_symlink()):
            results.append(
                CleanupTargetResult(
                    target=target,
                    identifier=identifier,
                    action=CleanupAction.ABSENT,
                    detail=f"Target {target} already absent.",
                )
            )
            continue
        _remove_target(target)
        results.append(
            CleanupTargetResult(
                target=target,
                identifier=identifier,
                action=CleanupAction.REMOVED,
                detail=f"Removed obsolete target {target}.",
            )
        )
    return CleanupOutcome(results=tuple(results))


__all__ = [
    "CleanupAction",
    "CleanupOutcome",
    "CleanupPlan",
    "CleanupTargetResult",
    "run_cleanup",
]
