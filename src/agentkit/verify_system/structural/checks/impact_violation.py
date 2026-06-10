"""Impact-violation check (FK-27 §27.4.2 / FK-23 §23.8).

``impact.violation`` is BLOCKING and is the single FK-27 §27.4.5 exception:
a FAIL routes DIRECTLY to ESCALATED (escalation to a human; no Worker-feedback
loop, no return to the exploration phase). The :class:`StageDefinition` marks
this with ``escalated=True``; the ``StructuralChecker`` stamps the escalation
intent onto the produced :class:`LayerResult` metadata so the policy engine /
orchestrator can route accordingly.

FK-23 §23.8 compares the DECLARED change impact (the budget the worker
committed to, a worker declaration) against the ACTUAL change impact
(``actual impact <= declared impact``). Because this is a BLOCKING check, the
ACTUAL impact MUST be measured INDEPENDENTLY by the system (FK-33 §33.5.2: a
worker may not grade its own homework) -- it is computed from the system diff
and supplied via :class:`ChangeEvidence`, NOT read back from what the worker
declared as "actual" in ``worker-manifest.json``. The DECLARED budget is read
from the worker manifest (legitimate -- it IS the worker's committed budget,
not a self-graded result); a worker declaring ``Local`` while the system diff
shows ``Architecture Impact`` is the canonical AC8 violation.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.core_types import WORKER_MANIFEST_FILE
from agentkit.story_context_manager.story_model import ChangeImpact
from agentkit.verify_system.protocols import Finding, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.core_types import Severity
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.structural.system_evidence import ChangeEvidence

__all__ = ["check_impact_violation"]

#: Canonical FK-23 §23.8 impact ordering (ascending). Used to compare declared
#: vs. actual impact.
_IMPACT_ORDER: tuple[ChangeImpact, ...] = (
    ChangeImpact.LOCAL,
    ChangeImpact.COMPONENT,
    ChangeImpact.CROSS_COMPONENT,
    ChangeImpact.ARCHITECTURE_IMPACT,
)


def _rank(impact: ChangeImpact) -> int:
    """Return the FK-23 §23.8 ordinal rank of an impact level."""
    return _IMPACT_ORDER.index(impact)


def _parse_impact(value: object) -> ChangeImpact | None:
    """Parse a wire change-impact string into ``ChangeImpact`` (None on miss)."""
    if not isinstance(value, str):
        return None
    try:
        return ChangeImpact(value)
    except ValueError:
        return None


def _declared_budget(story_dir: Path) -> ChangeImpact | None:
    """Read the worker-DECLARED change-impact budget (the worker's commitment).

    This is the worker's declared budget, NOT a self-graded result: it is the
    intent the worker committed to, against which the SYSTEM-measured actual
    impact is compared. ``None`` when absent/unparseable.
    """
    path = story_dir / WORKER_MANIFEST_FILE
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(manifest, dict):
        return None
    return _parse_impact(manifest.get("declared_change_impact"))


def check_impact_violation(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    evidence: ChangeEvidence,
) -> Finding | None:
    """FK-27 §27.4.2 ``impact.violation``: actual impact <= declared budget.

    The ACTUAL impact is the SYSTEM-measured value (``evidence.actual_impact``);
    the DECLARED budget is the worker's committed declaration. FK-33 §33.5.2:
    the gating side (actual) must be independent system evidence.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory (declared-budget read).
        severity: Registry-resolved severity (FK-27 §27.4.2: BLOCKING; routes
            to ESCALATED per §27.4.5).
        evidence: Independent system change evidence (the actual impact).

    Returns:
        ``None`` on PASS; a BLOCKING finding when the SYSTEM actual impact
        exceeds the declared budget (or either side is unconfirmable).
    """
    del ctx
    if not evidence.available or evidence.actual_impact is None:
        return _finding(
            severity,
            "system change evidence unavailable; cannot measure the actual "
            "change impact independently -> fail-closed (FK-27 §27.4.2 / "
            "FK-23 §23.8, FK-33 §33.5.2)",
        )
    declared = _declared_budget(story_dir)
    if declared is None:
        return _finding(
            severity,
            "declared_change_impact (the worker's impact budget) not declared "
            "in worker-manifest.json (FK-23 §23.8)",
        )
    actual = evidence.actual_impact
    if _rank(actual) > _rank(declared):
        return _finding(
            severity,
            f"system-measured actual change impact {actual.value!r} exceeds "
            f"declared budget {declared.value!r} -> ESCALATED "
            "(FK-27 §27.4.2/§27.4.5, FK-23 §23.8)",
        )
    return None


def _finding(severity: Severity, message: str) -> Finding:
    return Finding(
        layer="structural",
        check="impact.violation",
        severity=severity,
        message=message,
        trust_class=TrustClass.SYSTEM,
    )
