"""Unit tests for the FK-51 §51.7 cleanup mode (AG3-089 AC6 / AC8).

AC6: cleanup removes obsolete bindings/config remnants (non-customized targets).

AC8 / F-51-023: a cleanup write path that would touch a detected customization
RAISES ``CustomizationPreservationError`` fail-closed and mutates NOTHING (no
partial deletion).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.installer.upgrade.cleanup import (
    CleanupAction,
    CleanupPlan,
    run_cleanup,
)
from agentkit.installer.upgrade.footprint import (
    CustomizationFootprint,
    CustomizationKind,
    CustomizationPoint,
    CustomizationPreservationError,
)

if TYPE_CHECKING:
    from pathlib import Path


def _footprint_with(identifier: str) -> CustomizationFootprint:
    return CustomizationFootprint(
        points=(
            CustomizationPoint(
                kind=CustomizationKind.PIPELINE_CONFIG,
                identifier=identifier,
                detail="detected",
            ),
        )
    )


def test_cleanup_removes_obsolete_targets(tmp_path: Path) -> None:
    """AC6: non-customized obsolete targets are removed."""
    obsolete = tmp_path / "obsolete-binding"
    obsolete.write_text("stale\n", encoding="utf-8")
    other = tmp_path / "obsolete-remnant"
    other.write_text("stale2\n", encoding="utf-8")

    plan = CleanupPlan(
        obsolete_link_targets=((obsolete, "binding:obsolete"),),
        obsolete_config_targets=((other, "config:obsolete"),),
    )
    # Empty footprint -> nothing is a customization -> both removed.
    outcome = run_cleanup(plan, CustomizationFootprint())

    assert not obsolete.exists()
    assert not other.exists()
    assert obsolete in outcome.removed
    assert other in outcome.removed
    actions = {r.identifier: r.action for r in outcome.results}
    assert actions["binding:obsolete"] is CleanupAction.REMOVED
    assert actions["config:obsolete"] is CleanupAction.REMOVED


def test_cleanup_absent_target_is_reported(tmp_path: Path) -> None:
    """A target that does not exist is reported ABSENT (no error)."""
    plan = CleanupPlan(
        obsolete_link_targets=((tmp_path / "missing", "binding:missing"),),
    )

    outcome = run_cleanup(plan, CustomizationFootprint())

    assert outcome.results[0].action is CleanupAction.ABSENT
    assert outcome.removed == ()


def test_cleanup_raises_on_detected_customization_no_mutation(tmp_path: Path) -> None:
    """AC8 / F-51-023: a detected customization RAISES and deletes nothing.

    The cleanup write path blocks fail-closed BEFORE any removal: even the
    legitimate obsolete sibling in the same plan stays on disk (no partial
    deletion).
    """
    customised = tmp_path / "tuned"
    customised.write_text("keep me\n", encoding="utf-8")
    obsolete = tmp_path / "obsolete"
    obsolete.write_text("stale\n", encoding="utf-8")

    plan = CleanupPlan(
        obsolete_link_targets=((obsolete, "binding:obsolete"),),
        obsolete_config_targets=((customised, "config:tuned"),),
    )

    with pytest.raises(CustomizationPreservationError) as exc:
        run_cleanup(plan, _footprint_with("config:tuned"))

    assert "F-51-023" in str(exc.value)
    # No partial deletion: BOTH targets remain (fail-closed before any removal).
    assert customised.exists()
    assert customised.read_text(encoding="utf-8") == "keep me\n"
    assert obsolete.exists()


def test_cleanup_removes_directory_remnant(tmp_path: Path) -> None:
    """A local config directory remnant is removed (FK-51 §51.7)."""
    remnant = tmp_path / "remnant-dir"
    remnant.mkdir()
    (remnant / "leftover.txt").write_text("x\n", encoding="utf-8")

    plan = CleanupPlan(
        obsolete_config_targets=((remnant, "config:remnant-dir"),),
    )
    outcome = run_cleanup(plan, CustomizationFootprint())

    assert not remnant.exists()
    assert remnant in outcome.removed
