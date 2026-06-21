"""Bridge the ``sonarqube_gate`` capability to a QA-subflow ``LayerResult``.

Wires the stage into the QA-subflow sequence (after adversarial, before
policy). Conforms to ``formal.deterministic-checks.state-machine``:

* APPLICABLE green  -> ``LayerResult(passed=True)`` (sonarqube_gate_passed),
  the run continues to the policy aggregator.
* APPLICABLE red/stale/unreadable or 0/>1 ledger match -> a BLOCKING
  SYSTEM (Trust A) finding AND ``short_circuit_failed=True``: the caller
  routes DIRECTLY to the terminal ``failed`` (``attestation_read -> failed``
  / ``stages_executed -> failed``) WITHOUT traversing ``policy_evaluated``
  (invariant ``passed-requires-sonarqube-gate-passed``).
* NOT_APPLICABLE_UNAVAILABLE -> ``LayerResult(passed=True)`` with a
  ``sonarqube_gate_not_applicable`` marker (no Sonar verdict, no
  fail-closed; the policy engine still aggregates over the other layers).
* NOT_APPLICABLE_FAST -> the stage is DROPPED entirely by the caller
  (``run_sonarqube_gate_stage`` returns ``None``): no LayerResult, no
  artefact, no Sonar status. The fast QA-subflow terminates via the
  Layer-1 tests-green floor (FK-24 §24.3.4, FK-27 §27.6a). The state
  machine knows no ``not_applicable_fast`` Sonar state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.backend.verify_system.sonarqube_gate.applicability import SonarApplicability
from agentkit.backend.verify_system.sonarqube_gate.gate import evaluate_sonarqube_gate

if TYPE_CHECKING:
    from agentkit.backend.verify_system.sonarqube_gate.port import (
        SonarGateInputPort,
        SonarGateInputs,
    )

_STAGE_NAME = "sonarqube_gate"


@dataclass(frozen=True)
class SonarStageResult:
    """Outcome of running the ``sonarqube_gate`` stage in the QA-subflow.

    Attributes:
        layer_result: The ``LayerResult`` to record as the Sonar QA
            artefact and (for the non-fail-closed cases) to feed into the
            policy aggregator.
        short_circuit_failed: ``True`` only for an APPLICABLE fail-closed
            verdict (red gate, stale/unreadable attestation, 0/>1 ledger
            match). The caller must then route DIRECTLY to the terminal
            ``failed`` WITHOUT calling the policy engine and WITHOUT
            writing a policy decision artefact (state-machine
            ``attestation_read -> failed`` / ``stages_executed -> failed``).
    """

    layer_result: LayerResult
    short_circuit_failed: bool


def _skip_result() -> SonarStageResult:
    """Build the NOT_APPLICABLE_UNAVAILABLE skip (absent Sonar)."""
    return SonarStageResult(
        layer_result=LayerResult(
            layer=_STAGE_NAME,
            passed=True,
            findings=(),
            metadata={
                "stage": _STAGE_NAME,
                "applicability": SonarApplicability.NOT_APPLICABLE_UNAVAILABLE.value,
                "gate_status": "sonarqube_gate_not_applicable",
                "skipped": True,
            },
        ),
        short_circuit_failed=False,
    )


def _evaluate(inputs: SonarGateInputs) -> SonarStageResult:
    outcome = evaluate_sonarqube_gate(
        applicability=inputs.applicability,
        attestation=inputs.attestation,
        main_head_revision=inputs.main_head_revision,
        ledger_entries=inputs.ledger_entries,
        current_issues=inputs.current_issues,
        issue_applier=inputs.issue_applier,
        post_apply_reader=inputs.post_apply_reader,
    )
    if outcome.passed:
        return SonarStageResult(
            layer_result=LayerResult(
                layer=_STAGE_NAME,
                passed=True,
                findings=(),
                metadata={
                    "stage": _STAGE_NAME,
                    "applicability": outcome.applicability.value,
                    "gate_status": outcome.gate_status,
                    "accepted_issue_keys": list(outcome.accepted_issue_keys),
                },
            ),
            short_circuit_failed=False,
        )
    finding = Finding(
        layer=_STAGE_NAME,
        check="sonarqube_green_gate",
        severity=Severity.BLOCKING,
        message=f"SonarQube-Green-Gate fail-closed: {outcome.failure_reason}",
        trust_class=TrustClass.SYSTEM,
    )
    return SonarStageResult(
        layer_result=LayerResult(
            layer=_STAGE_NAME,
            passed=False,
            findings=(finding,),
            metadata={
                "stage": _STAGE_NAME,
                "applicability": outcome.applicability.value,
                "gate_status": outcome.gate_status,
                "failure_reason": outcome.failure_reason,
            },
        ),
        # APPLICABLE fail-closed: route DIRECTLY to terminal `failed`,
        # never through the policy aggregator (FK-33 §33.6.3,
        # invariant.passed-requires-sonarqube-gate-passed).
        short_circuit_failed=True,
    )


def run_sonarqube_gate_stage(
    port: SonarGateInputPort,
    story_id: str,
    story_dir: object,
) -> SonarStageResult | None:
    """Resolve inputs via the port and evaluate the gate.

    Args:
        port: Read-port resolving the gate inputs (default = Sonar absent).
        story_id: Story display-ID.
        story_dir: Story working directory (passed through to the port).

    Returns:
        A :class:`SonarStageResult`, or ``None`` when the resolution is
        ``NOT_APPLICABLE_FAST``: in fast mode the ``sonarqube_gate`` stage
        is DROPPED entirely (no LayerResult, no artefact, no Sonar status;
        the state machine knows no fast Sonar state).
    """
    inputs = port.resolve_inputs(story_id, story_dir)
    if inputs.applicability is SonarApplicability.NOT_APPLICABLE_FAST:
        return None
    if inputs.applicability is SonarApplicability.NOT_APPLICABLE_UNAVAILABLE:
        return _skip_result()
    return _evaluate(inputs)


__all__ = ["SonarStageResult", "run_sonarqube_gate_stage"]
