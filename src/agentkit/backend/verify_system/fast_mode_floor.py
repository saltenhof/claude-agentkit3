"""Fast-mode QA floor enforces structural verification plus the required tests-green evidence."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.core_types import PolicyVerdict
from agentkit.backend.verify_system import _artifact_specs
from agentkit.backend.verify_system.contract import (
    QaSubflowOutcome,
    VerifyContextBundle,
)
from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
from agentkit.backend.verify_system.protocols import (
    LayerResult,
    Severity,
)
from agentkit.backend.verify_system.qa_cycle import integration as _qa
from agentkit.backend.verify_system.routing import QALayerKind

logger = logging.getLogger(__name__)

if TYPE_CHECKING:

    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.verify_system.system import VerifySystem


def _run_fast_floor(
    system: VerifySystem,
    *,
    ctx: VerifyContextBundle,
    story_id: str,
    story_ctx: StoryContext | None,
) -> QaSubflowOutcome:
    """Run the fast-mode QA floor: Layer 1 (structural) + tests-green.

    FK-24 §24.3.4 Mode-Profil: in ``mode == fast`` the QA-subflow degenerates
    to Layer 1 (deterministic structural checks) AND the hard, non-disableable
    tests-green floor. Layers 2-4, the Sonar gate and the feedback/remediation
    loop are SKIPPED (``OUT``). The floor PASSes only when BOTH the structural
    layer passes AND the injected ``fast_test_runner`` confirms tests green.

    FAIL-CLOSED (NO ERROR BYPASSING): a red test -> FAIL; an unconfirmable
    result (no ``fast_test_runner`` wired) -> FAIL. The cycle is still
    resolved (idle -> ``start_cycle``) so the four identity fields are
    surfaced for the state owner; there is no remediation/escalation loop on
    the fast path (the human accompanies the story).

    Args:
        ctx: Run-time context bundle.
        story_id: Story display-ID.
        story_ctx: The pre-resolved fast-mode ``StoryContext``.

    Returns:
        A ``QaSubflowOutcome`` carrying the floor verdict (PASS/FAIL).
    """
    self = system
    now_str = _qa.utc_now_iso()
    cycle_state = self.qa_cycle_lifecycle.start_cycle(ctx.story_dir)
    qa_cycle_fields = _qa.qa_cycle_state_to_fields(cycle_state)

    structural = self._execute_layer(
        self.layer_1, ctx, story_id, QALayerKind.STRUCTURAL, story_context=story_ctx
    )
    tests_finding = self._fast_tests_green_finding(ctx.story_dir)
    floor_findings = (
        (*structural.findings, tests_finding)
        if tests_finding is not None
        else structural.findings
    )
    floor_passed = structural.passed and tests_finding is None
    floor_result = LayerResult(
        layer=self.layer_1.name,
        passed=floor_passed,
        findings=floor_findings,
        metadata={
            **structural.metadata,
            "fast_mode": True,
            "tests_green": tests_finding is None,
        },
    )

    self._write_layer_envelope(
            spec=_artifact_specs.LAYER_1_ARTIFACTS[0],
        result=floor_result,
        ctx=ctx,
        story_id=story_id,
        now_str=now_str,
        qa_cycle_fields=qa_cycle_fields,
    )

    verdict = PolicyVerdict.PASS if floor_passed else PolicyVerdict.FAIL
    summary = (
        "fast-mode QA floor PASS (structural + tests green)"
        if floor_passed
        else "fast-mode QA floor FAIL (structural or tests-green floor not met)"
    )
    decision = VerifyDecision(
        passed=floor_passed,
        verdict=verdict,
        layer_results=(floor_result,),
        all_findings=floor_findings,
        blocking_findings=tuple(
            f for f in floor_findings if f.severity == Severity.BLOCKING
        ),
        summary=summary,
    )
    logger.info(
        "run_qa_subflow fast-mode floor: story=%s verdict=%s tests_green=%s",
        story_id,
        verdict,
        tests_finding is None,
    )
    return QaSubflowOutcome(
        verdict=verdict,
        decision=decision,
            artifact_refs=(_artifact_specs.LAYER_1_ARTIFACTS[0].filename,),
        attempt_nr=ctx.attempt,
        qa_cycle_round=cycle_state.round,
        feedback=None,
        qa_cycle_id=cycle_state.qa_cycle_id,
        evidence_epoch=cycle_state.evidence_epoch,
        evidence_fingerprint=cycle_state.evidence_fingerprint,
        escalated=False,
        closure_blocked=False,
    )
