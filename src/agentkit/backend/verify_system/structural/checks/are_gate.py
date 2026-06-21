"""ARE-Gate check (FK-27 §27.4.4, optional).

The ARE-Gate runs ONLY when ``features.are == true`` (FK-27 §27.4.4 /
AG3-030 ``RequirementsCoverage.is_enabled``). The ``StructuralChecker`` is
responsible for the activation gate: it includes this stage only when ARE is
enabled (registry ``layer1_stages_for(..., are_enabled=...)``). This check
itself receives the resolved :class:`CoverageVerdict` (the dock-point-4 gate
result) and turns it into a Layer-1 finding.

FAIL-CLOSED: when ARE is enabled but the coverage verdict is missing
(``None``) or not PASS, the gate FAILS BLOCKING (FK-27 §27.4.4: a mandatory
requirement without evidence is a FAIL; NO ERROR BYPASSING). Trust class A
(ARE is an authoritative system, FK-33 §33.5.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.requirements_coverage.contract import AreDockpointStatus
from agentkit.backend.verify_system.protocols import Finding, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.core_types import Severity
    from agentkit.backend.requirements_coverage.contract import CoverageVerdict
    from agentkit.backend.story_context_manager.models import StoryContext

__all__ = ["check_are_gate"]

_PASS_VERDICT = "PASS"


def check_are_gate(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    coverage_verdict: CoverageVerdict | None,
) -> Finding | None:
    """FK-27 §27.4.4 ``are.gate``: all ``must_cover`` requirements have evidence.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory (unused; uniform signature).
        severity: Registry-resolved severity (FK-27 §27.4.4: BLOCKING).
        coverage_verdict: The ARE dock-point-4 ``check_gate`` verdict resolved
            by the caller, or ``None`` when no verdict was produced.

    Returns:
        ``None`` on PASS; a BLOCKING finding when the gate is unconfirmable or
        not PASS.
    """
    del ctx, story_dir
    if coverage_verdict is None:
        return Finding(
            layer="structural",
            check="are.gate",
            severity=severity,
            message="ARE enabled but no coverage verdict produced -> "
            "fail-closed (FK-27 §27.4.4, NO ERROR BYPASSING)",
            trust_class=TrustClass.SYSTEM,
        )
    if (
        coverage_verdict.status is not AreDockpointStatus.PASS
        or coverage_verdict.verdict != _PASS_VERDICT
    ):
        return Finding(
            layer="structural",
            check="are.gate",
            severity=severity,
            message=(
                "ARE coverage gate not PASS "
                f"(status={coverage_verdict.status.value}, "
                f"verdict={coverage_verdict.verdict!r}); a must_cover "
                "requirement lacks evidence (FK-27 §27.4.4)"
            ),
            trust_class=TrustClass.SYSTEM,
        )
    return None
