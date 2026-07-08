"""Implementation evidence preconditions fail closed when implementation QA lacks required terminal evidence."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.core_types import PolicyVerdict, QaContext
from agentkit.backend.verify_system.contract import (
    QaSubflowOutcome,
    VerifyContextBundle,
)
from agentkit.backend.verify_system.implementation_evidence_gate import (
    evaluate_implementation_evidence_gate,
)
from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
from agentkit.backend.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:

    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.verify_system.system import VerifySystem


def _evaluate_implementation_terminality_precondition(
    system: VerifySystem,
    *,
    ctx: VerifyContextBundle,
    story_id: str,
    story_ctx: StoryContext | None,
    qa_context: QaContext,
) -> QaSubflowOutcome | None:
    """Run the FK-24 implementation-evidence gate before implementation QA."""
    if qa_context not in (
        QaContext.IMPLEMENTATION_INITIAL,
        QaContext.IMPLEMENTATION_REMEDIATION,
    ):
        return None
    if story_ctx is None:
        return _implementation_terminality_blocked_outcome(
            ctx=ctx,
            story_id=story_id,
            reason=(
                "Implementation-Evidence-Gate: StoryContext is missing for "
                "implementation QA; cannot prove FK-24 implementation "
                "terminality -> fail-closed "
                "(IMPLEMENTATION_REQUIRED_AFTER_EXPLORATION)."
            ),
        )
    story_type = story_ctx.story_type
    evidence = system.implementation_change_evidence_port.collect(ctx.story_dir)
    gate = evaluate_implementation_evidence_gate(
        story_type=story_type,
        story_dir=ctx.story_dir,
        change_evidence=evidence,
    )
    if gate.passed:
        return None
    reason = (
        gate.blocking_reason
        or "Implementation-Evidence-Gate: implementation evidence is missing."
    )
    return _implementation_terminality_blocked_outcome(
        ctx=ctx,
        story_id=story_id,
        reason=reason,
    )


def _implementation_terminality_blocked_outcome(
    *,
    ctx: VerifyContextBundle,
    story_id: str,
    reason: str,
) -> QaSubflowOutcome:
    """Build the fail-closed AG3-058 terminality outcome."""
    finding = Finding(
        layer="structural",
        check="implementation_evidence.required_after_exploration",
        severity=Severity.BLOCKING,
        message=reason,
        trust_class=TrustClass.SYSTEM,
        file_path=str(ctx.story_dir),
    )
    layer_result = LayerResult(
        layer="structural",
        passed=False,
        findings=(finding,),
        metadata={"terminality_precondition": "implementation_evidence"},
    )
    decision = VerifyDecision(
        passed=False,
        verdict=PolicyVerdict.FAIL,
        layer_results=(layer_result,),
        all_findings=(finding,),
        blocking_findings=(finding,),
        summary=reason,
    )
    logger.warning(
        "implementation evidence precondition failed: story=%s reason=%s",
        story_id,
        reason,
    )
    return QaSubflowOutcome(
        verdict=PolicyVerdict.FAIL,
        decision=decision,
        artifact_refs=(),
        attempt_nr=ctx.attempt,
        qa_cycle_round=0,
        escalated=True,
    )
