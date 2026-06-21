"""QA-cycle integration helpers for ``VerifySystem.run_qa_subflow`` (AG3-041).

Free functions extracted from ``VerifySystem`` (LOC discipline: keep the
facade class focused). They drive the :class:`QaCycleLifecycle` for a single
subflow run and project the resulting identities into QA-artefact payload
fields. No state is held here; the caller owns persistence (the phase handler).

Source: FK-27 §27.2 / AG3-041 §2.1.7.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.core_types import QaContext
from agentkit.backend.verify_system.qa_cycle.lifecycle import QaCycleLifecycle
from agentkit.backend.verify_system.remediation.loop_counter import (
    RemediationDecision,
    RemediationLoopController,
)

if TYPE_CHECKING:
    from agentkit.backend.core_types import PolicyVerdict
    from agentkit.backend.verify_system.contract import VerifyContextBundle
    from agentkit.backend.verify_system.protocols import Finding, LayerResult
    from agentkit.backend.verify_system.qa_cycle.lifecycle import QaCycleState
    from agentkit.backend.verify_system.remediation.finding_resolution import (
        FindingKey,
        FindingResolutionStatus,
    )

_REMEDIATION_CONTEXTS = (
    QaContext.IMPLEMENTATION_REMEDIATION,
    QaContext.EXPLORATION_REMEDIATION,
)


def resolve_qa_cycle_state(
    lifecycle: QaCycleLifecycle,
    ctx: VerifyContextBundle,
    story_id: str,
    qa_context: QaContext,
) -> QaCycleState:
    """Drive the QA-cycle lifecycle for one subflow run (AG3-041 §2.1.7).

    Decision (FK-27 §27.2 / §27.2.2 ``idle -> awaiting_qa``):

    * No active cycle (no ``phase_envelope`` view OR a view without a set
      ``qa_cycle_id``) -> ``start_cycle`` (round 1, epoch 1). This is the
      ``idle -> awaiting_qa`` transition; the FIRST QA-subflow call ALWAYS
      starts a cycle (AC1/AC6 — no fail-open idle pass-through).
    * Active cycle AND remediation context -> ``advance_qa_cycle`` (round/epoch
      +1, fresh ``qa_cycle_id``, recompute fingerprint, invalidate cycle-bound
      artefacts, §27.2.3).
    * Active cycle in an INITIAL context -> reuse the caller-supplied identities
      verbatim (the handler already started the cycle; AG3-026 §AK8).

    A cycle is ALWAYS resolved (never ``None``): the QA-subflow has no idle
    pass-through. The returned identities are surfaced in the outcome and
    persisted by the state owner (the phase handler), FK-27 §27.2.1.

    Args:
        lifecycle: The QA-cycle lifecycle coordinator.
        ctx: Run-time context bundle (carries the phase-envelope view).
        story_id: Story display-ID (artefact path segment).
        qa_context: Invocation context (initial vs remediation).

    Returns:
        The resolved :class:`QaCycleState` (always present).
    """
    view = ctx.phase_envelope
    current = lifecycle.get_current_state(view) if view is not None else None
    if view is None or current is None:
        # idle -> awaiting_qa: first call always starts a cycle (FK-27 §27.2.2).
        return lifecycle.start_cycle(ctx.story_dir)
    if qa_context in _REMEDIATION_CONTEXTS:
        next_state, _events = lifecycle.advance_qa_cycle(
            view, ctx.story_dir, story_id, project_root=ctx.project_root
        )
        return next_state
    return current


def qa_cycle_state_to_fields(state: QaCycleState) -> dict[str, object]:
    """Project a resolved cycle state into QA-artefact payload fields.

    Sources the values from the freshly-resolved :class:`QaCycleState`
    (FK-27 §27.2.1). Datetimes serialise to ISO-8601 strings for JSON
    portability.

    Args:
        state: The resolved cycle state.

    Returns:
        Dict with ``qa_cycle_id``, ``qa_cycle_round``, ``evidence_epoch`` and
        ``evidence_fingerprint``.
    """
    return {
        "qa_cycle_id": state.qa_cycle_id,
        "qa_cycle_round": state.round,
        "evidence_epoch": state.evidence_epoch.isoformat(),
        "evidence_fingerprint": state.evidence_fingerprint,
    }


def assess_finding_resolution(
    qa_context: QaContext,
    previous_findings: tuple[Finding, ...],
    current_findings: tuple[Finding, ...],
) -> dict[FindingKey, FindingResolutionStatus] | None:
    """Classify previous-round findings against this round (FK-34, §2.1.5).

    Only meaningful in a remediation context (where previous findings exist).
    Outside a remediation context, or with no previous findings, returns
    ``None`` (no resolution map; ``closure_blocked`` stays False).

    Args:
        qa_context: Invocation context (initial vs remediation).
        previous_findings: Findings carried forward from the prior round.
        current_findings: All findings from the just-completed round.

    Returns:
        The ``(layer, check) -> FindingResolutionStatus`` map, or ``None`` when
        not applicable.
    """
    from agentkit.backend.verify_system.remediation.finding_resolution import (
        FindingResolutionAssessor,
    )

    if qa_context not in _REMEDIATION_CONTEXTS or not previous_findings:
        return None
    return dict(
        FindingResolutionAssessor().assess(previous_findings, current_findings)
    )


def merge_llm_finding_resolutions(
    base_map: dict[FindingKey, FindingResolutionStatus] | None,
    layer_results: tuple[LayerResult, ...],
) -> dict[FindingKey, FindingResolutionStatus] | None:
    """Merge the LLM Layer-2 resolution verdicts into the ONE resolution SSOT (E5).

    FK-34 §34.9: in a remediation round the Layer-2 LLM evaluators judge, per
    previous finding, whether it is fully/partially/not resolved. Those verdicts
    are the authoritative (Trust-B) resolution signal and are carried in each
    Layer-2 ``LayerResult.metadata`` (``finding_resolutions``). This merges them
    into the deterministic assessor's ``base_map`` so a still-open
    (``partially_resolved`` / ``not_resolved``) LLM verdict reaches the canonical
    ``closure_blocked`` derivation (AG3-041 §2.1.6) -- it does not live only in
    metadata anymore (E5 root fix). The merge is fail-closed: for a key present
    in both, the MORE OPEN status wins (an open status never gets weakened by a
    FULLY_RESOLVED from the other source).

    Args:
        base_map: The deterministic assessor map (``None`` outside remediation).
        layer_results: All layer results of the round (Layer-2 entries carry the
            LLM verdicts).

    Returns:
        The merged ``(layer, check) -> status`` map, or ``None`` when there is
        neither a base map nor any LLM verdict (no remediation context).
    """
    from agentkit.backend.verify_system.remediation.finding_resolution import (
        is_open_resolution_status,
        resolution_map_from_metadata,
    )

    merged: dict[FindingKey, FindingResolutionStatus] = dict(base_map or {})
    saw_llm = False
    for result in layer_results:
        llm_map = resolution_map_from_metadata(result.metadata)
        for key, status in llm_map.items():
            saw_llm = True
            existing = merged.get(key)
            # Fail-closed: keep whichever is open. Only overwrite a non-open
            # existing entry, or set a new key.
            if existing is None or (
                is_open_resolution_status(status)
                and not is_open_resolution_status(existing)
            ):
                merged[key] = status
    if not merged and not saw_llm and base_map is None:
        return None
    return merged


def utc_now_iso() -> str:
    """Return the current UTC instant as an ISO-8601 string.

    Returns:
        The current UTC time formatted via ``boundary.shared.time.now_iso``.
    """
    from agentkit.backend.boundary.shared.time import now_iso

    return now_iso()


def serialize_layer_result_payload(
    result: LayerResult, attempt: int
) -> dict[str, object]:
    """Serialise a ``LayerResult`` into a JSON-compatible envelope payload.

    Args:
        result: The layer evaluation result to serialise.
        attempt: QA-subflow attempt counter.

    Returns:
        Dict suitable for use as ``ArtifactEnvelope.payload``.
    """
    from agentkit.backend.verify_system.policy_engine.projections import (
        serialize_layer_result,
    )

    return serialize_layer_result(result, attempt_nr=attempt)


def evaluate_escalation(
    controller: RemediationLoopController,
    cycle_state: QaCycleState,
    verdict: PolicyVerdict,
) -> bool:
    """Run the remediation loop controller and return the escalation flag.

    Wraps :meth:`RemediationLoopController.check_and_advance` (FK-27 §27.2.2):
    a FAIL at/over the round ceiling -> ESCALATE -> ``True`` (hard FAIL). PASS
    or FAIL below the ceiling -> ``False``. The cycle is always resolved
    (``resolve_qa_cycle_state`` never returns ``None``), so the controller
    always bounds against the authoritative ``round`` — there is no idle
    fallback that could skip the ceiling (NO ERROR BYPASSING).

    Args:
        controller: The bounded remediation-loop controller.
        cycle_state: The resolved cycle state (always present).
        verdict: The policy-engine verdict of the just-completed round.

    Returns:
        ``True`` iff the loop escalated (``RemediationDecision.ESCALATE``).
    """
    decision = controller.check_and_advance(cycle_state, verdict)
    return decision is RemediationDecision.ESCALATE


__all__ = [
    # Re-exported factories so ``system.py`` imports them from one module
    # (keeps the facade module-top LOC under the PY_MODULE_TOP_LEVEL limit).
    "QaCycleLifecycle",
    "RemediationLoopController",
    "assess_finding_resolution",
    "evaluate_escalation",
    "merge_llm_finding_resolutions",
    "qa_cycle_state_to_fields",
    "resolve_qa_cycle_state",
    "serialize_layer_result_payload",
    "utc_now_iso",
]
