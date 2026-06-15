"""Real ``stability_gate`` Verify-Stage producer for integration_stabilization.

FK-05 §5.10 / FK-37 §37.1.3 / AC5 / AC12.

This module is the REAL producer of the ``stability_gate`` Layer-4 QA result. It
is invoked by the VerifySystem QA-subflow (``_run_qa_subflow``) ONLY for stories
whose ``implementation_contract == integration_stabilization``. It:

1. loads the approved manifest, approval record and live budget from the story
   directory (fail-closed: absent state -> BLOCK),
2. evaluates the four FK-37 §37.1.3 checks plus the two named preconditions via
   :func:`~agentkit.integration_stabilization.fk37_checks.check_fk37_stability_gate`
   over the actually-touched surfaces (from the QA-subflow change evidence),
3. produces a real Layer-4 :class:`~agentkit.verify_system.protocols.LayerResult`
   that the PolicyEngine aggregation consumes (its ``stage_ids`` metadata marks
   ``stability_gate`` + ``integration.integration_target_matrix_passed`` as
   produced, so the registry-bound fail-closed missing-stage check is satisfied
   only when the gate actually ran),
4. persists ``integration_stability_gate.json`` (the closure precondition reads
   it, FK-05 §5.11), and
5. emits the ``stability_gate_passed`` telemetry event on PASS (AC11).

A normal QA PASS is NOT sufficient for IS: without this produced Layer-4 result
the PolicyEngine reports the two IS Layer-4 stages missing (BLOCKING), so closure
is blocked fail-closed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.core_types import Severity
from agentkit.core_types.qa_artifact_names import STABILITY_GATE_PRODUCER
from agentkit.integration_stabilization.fk37_checks import (
    FK37CheckName,
    check_fk37_stability_gate,
)
from agentkit.integration_stabilization.models import StabilizationBudget
from agentkit.integration_stabilization.seam_allowlist_guard import (
    materialize_seam_allowlist,
)
from agentkit.integration_stabilization.state import (
    load_integration_manifest,
    load_manifest_approval,
)
from agentkit.verify_system.protocols import Finding, LayerResult, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.telemetry.emitters import EventEmitter

__all__ = [
    "IS_BUDGET_COUNTER_FILE",
    "IS_STABILITY_GATE_FILE",
    "IS_TARGETS_FILE",
    "produce_stability_gate_layer_result",
]

#: Canonical filename for the persisted live budget counters.
IS_BUDGET_COUNTER_FILE: str = "integration_budget.json"

#: Canonical filename for the achieved integration targets (worker/verify output).
IS_TARGETS_FILE: str = "integration_targets.json"

#: Canonical filename for the persisted stability_gate result (closure reads it).
IS_STABILITY_GATE_FILE: str = "integration_stability_gate.json"

#: The Layer-4 result name produced by the stability_gate (matches the registered
#: ``stability_gate`` stage id, so ``_produced_stage_ids`` records it as produced).
_STABILITY_GATE_LAYER: str = "stability_gate"

#: Exact registered stage ids for the two IS Layer-4 stages (ERROR C fix).
#: ``stability_gate`` is registered without a namespace prefix (data.py ~409).
#: ``integration.integration_target_matrix_passed`` carries the ``integration.``
#: prefix (data.py ~396).  These must match the registry verbatim so the
#: PolicyEngine missing-stage check recognises them as produced.
_IS_LAYER4_STAGE_IDS: tuple[str, str] = (
    "stability_gate",
    "integration.integration_target_matrix_passed",
)


def _load_budget(story_dir: Path, manifest_caps: object) -> StabilizationBudget:
    """Load the live budget counters from the persisted file (zeroed if absent)."""
    from agentkit.integration_stabilization.models import StabilizationBudgetCaps

    assert isinstance(manifest_caps, StabilizationBudgetCaps)  # noqa: S101
    budget_path = story_dir / IS_BUDGET_COUNTER_FILE
    counters: dict[str, object] = {}
    if budget_path.exists():
        try:
            counters = json.loads(budget_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            counters = {}

    def _int(key: str) -> int:
        value = counters.get(key, 0)
        return int(value) if isinstance(value, (int, float)) else 0

    return StabilizationBudget(
        caps=manifest_caps,
        loops_used=_int("loops_used"),
        new_surfaces_used=_int("new_surfaces_used"),
        contract_changes_used=_int("contract_changes_used"),
        regressions_this_cycle=_int("regressions_this_cycle"),
    )


def _load_achieved_targets(story_dir: Path) -> frozenset[str]:
    """Load the achieved integration targets (empty if no evidence persisted)."""
    targets_path = story_dir / IS_TARGETS_FILE
    if not targets_path.exists():
        return frozenset()
    try:
        data = json.loads(targets_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    raw = data.get("achieved_targets") if isinstance(data, dict) else data
    if isinstance(raw, list):
        return frozenset(str(t) for t in raw)
    return frozenset()


def produce_stability_gate_layer_result(
    *,
    story_dir: Path,
    run_id: str,
    touched_paths: tuple[str, ...],
    emitter: EventEmitter | None = None,
    story_id: str,
    project_key: str,
) -> LayerResult:
    """Run the stability_gate and produce its real Layer-4 QA result (AC5/AC12).

    Fail-closed: an absent manifest or approval record yields a BLOCKING
    Layer-4 result (no produced gate = closure blocked). The result is also
    persisted to ``integration_stability_gate.json`` so the closure
    precondition (FK-05 §5.11) reads the same authoritative gate verdict.

    Args:
        story_dir: The story working directory (manifest/approval/budget source).
        run_id: The current pipeline run identifier (binding-integrity check).
        touched_paths: The surfaces actually touched this cycle (from the QA
            change evidence) -- the declared_surfaces_only check input.
        emitter: Optional telemetry emitter; the ``stability_gate_passed`` event
            is emitted on PASS (AC11). ``None`` => no emission (test path).
        story_id: The story display id (telemetry + persisted artefact).
        project_key: The owning project key (telemetry).

    Returns:
        A Layer-4 :class:`LayerResult` for the ``stability_gate`` stage. Its
        ``metadata["stage_ids"]`` marks ``stability_gate`` and
        ``integration.integration_target_matrix_passed`` produced.
    """
    manifest = load_integration_manifest(story_dir)
    approval = load_manifest_approval(story_dir)

    # Use exact registered stage ids (ERROR C fix: FK37CheckName values carry the
    # short wire keys; the registry uses ``integration.`` prefix for the matrix
    # check).  _IS_LAYER4_STAGE_IDS matches data.py verbatim.
    stage_ids = _IS_LAYER4_STAGE_IDS

    if manifest is None:
        finding = Finding(
            layer=_STABILITY_GATE_LAYER,
            check=FK37CheckName.STABILITY_GATE,
            severity=Severity.BLOCKING,
            message=(
                "No approved IntegrationScopeManifest found; the stability_gate "
                "cannot pass. Integration-stabilization closure is fail-closed "
                "blocked without an approved manifest (FK-05 §5.10/§5.11, AC5)."
            ),
            trust_class=TrustClass.SYSTEM,
        )
        _persist_gate_result(
            story_dir,
            passed=False,
            achieved_targets=(),
            block_reasons=(finding.message,),
        )
        return LayerResult(
            layer=_STABILITY_GATE_LAYER,
            passed=False,
            findings=(finding,),
            metadata={"stage_ids": stage_ids, "producer": STABILITY_GATE_PRODUCER},
        )

    budget = _load_budget(story_dir, manifest.stabilization_budget)
    achieved_targets = _load_achieved_targets(story_dir)
    seam_allowlist = materialize_seam_allowlist(manifest)

    gate = check_fk37_stability_gate(
        touched_paths=touched_paths,
        manifest=manifest,
        budget=budget,
        achieved_targets=achieved_targets,
        approval_record=approval,
        current_run_id=run_id,
        seam_allowlist=seam_allowlist,
    )

    findings: tuple[Finding, ...] = ()
    if not gate.passed:
        findings = (
            Finding(
                layer=_STABILITY_GATE_LAYER,
                check=FK37CheckName.STABILITY_GATE,
                severity=Severity.BLOCKING,
                message=(
                    "stability_gate FAILED (FK-37 §37.1.3, AC5/AC12): "
                    + "; ".join(gate.block_reasons)
                ),
                trust_class=TrustClass.SYSTEM,
            ),
        )

    _persist_gate_result(
        story_dir,
        passed=gate.passed,
        achieved_targets=tuple(sorted(achieved_targets)),
        block_reasons=gate.block_reasons,
    )

    if gate.passed and emitter is not None:
        from agentkit.integration_stabilization.events import (
            emit_stability_gate_passed,
        )

        emitter.emit(
            emit_stability_gate_passed(
                story_id=story_id,
                project_key=project_key,
                run_id=run_id,
                achieved_targets=sorted(achieved_targets),
            )
        )

    return LayerResult(
        layer=_STABILITY_GATE_LAYER,
        passed=gate.passed,
        findings=findings,
        metadata={"stage_ids": stage_ids, "producer": STABILITY_GATE_PRODUCER},
    )


def _persist_gate_result(
    story_dir: Path,
    *,
    passed: bool,
    achieved_targets: tuple[str, ...],
    block_reasons: tuple[str, ...],
) -> None:
    """Persist the stability_gate verdict for the closure precondition (FK-05 §5.11).

    The closure precondition reads ``integration_stability_gate.json`` as the
    authoritative gate verdict. Producing it here (the QA-subflow) is the single
    write path; the closure consumes it (single source of truth, no second gate).
    """
    payload = {
        "passed": passed,
        "achieved_targets": list(achieved_targets),
        "open_violations": 0 if passed else len(block_reasons),
        "replan_needed": False,
        "block_reasons": list(block_reasons),
    }
    (story_dir / IS_STABILITY_GATE_FILE).write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
