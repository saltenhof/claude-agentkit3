"""Layer-3 -> Layer-2 mandatory-target feedback (FK-48 §48.2.5, AG3-079 AC8).

A deterministic Zone-2 pipeline script: it reads ``mandatory_target_results`` from
``adversarial.json`` and, for every UNFULFILLED target, sets the mapped Layer-2
finding's resolution status to at least
:data:`~agentkit.backend.verify_system.remediation.finding_resolution.FindingResolutionStatus.PARTIALLY_RESOLVED`
as input to the next remediation round (the existing finding-resolution mechanism,
no new status lifecycle, FK-48 §48.2.5).

The :data:`FindingKey` comes from the typed target-source mapping loaded from
the canonical spawn envelope. A target-id spelling is not used to reconstruct
provenance and the mapping does not alter ``adversarial.json`` schema 3.1.

A target is FULFILLED iff:

* ``status == TESTED`` AND the addressing test PASSed, or
* ``status == UNRESOLVABLE`` with a non-empty justification.

Otherwise (no test / TESTED + test FAIL / UNRESOLVABLE without reason) it is
UNFULFILLED and the mapped finding is forced to ``PARTIALLY_RESOLVED`` so the
remediation loop keeps it open (FK-48 §48.2.5 / DK-04 §4.6.3). The result is
written into the SAME resolution map the existing loop consumes
(``RemediationFeedback.finding_resolution`` / ``serialize_resolution_map``), not a
new artefact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.verify_system.remediation.finding_resolution import (
    FindingKey,
    FindingResolutionStatus,
)

if TYPE_CHECKING:
    from agentkit.backend.verify_system.adversarial_orchestrator.runtime.models import (
        AdversarialResultArtifact,
        AdversarialTargetSource,
        MandatoryTargetResult,
    )

#: Mandatory-target status meaning a test was written (FK-48 §48.2.4).
_STATUS_TESTED: str = "TESTED"

#: Mandatory-target status meaning the case is justified non-testable.
_STATUS_UNRESOLVABLE: str = "UNRESOLVABLE"

#: Sandbox-test outcome meaning the addressing test passed.
_OUTCOME_PASS: str = "PASS"


def mandatory_target_resolution_feedback(
    artifact: AdversarialResultArtifact,
    *,
    target_sources: tuple[AdversarialTargetSource, ...],
) -> dict[FindingKey, FindingResolutionStatus]:
    """Map UNFULFILLED mandatory targets to a Layer-2 finding-resolution map.

    For every unfulfilled mandatory target the mapped ``(layer, check)`` finding
    is set to ``PARTIALLY_RESOLVED`` (FK-48 §48.2.5). A fulfilled target
    (``TESTED`` + test PASS, or justified ``UNRESOLVABLE``) contributes nothing
    (it does not re-open a finding).

    Args:
        artifact: The materialised ``adversarial.json`` payload (schema 3.1).
        target_sources: Proven target-to-source mapping from the spawn envelope.

    Returns:
        A ``{(layer, check) -> PARTIALLY_RESOLVED}`` map for the unfulfilled
        targets (empty when every target is fulfilled). This is written into the
        existing ``RemediationFeedback.finding_resolution`` model.
    """
    source_by_target = {source.target_id: (source.source_result_name, source.source_check_id) for source in target_sources}
    if len(source_by_target) != len(target_sources):
        raise ValueError("adversarial target_sources contains duplicate target ids")
    fulfilled_target_ids = fulfilled_mandatory_target_ids(artifact)
    feedback: dict[FindingKey, FindingResolutionStatus] = {}
    for target in artifact.mandatory_target_results:
        if target.target_id in fulfilled_target_ids:
            continue
        key = source_by_target.get(target.target_id)
        if key is None:
            raise ValueError(f"adversarial mandatory target has no typed Layer-2 source: {target.target_id!r}")
        feedback[key] = FindingResolutionStatus.PARTIALLY_RESOLVED
    return feedback


def fulfilled_mandatory_target_ids(
    artifact: AdversarialResultArtifact,
) -> frozenset[str]:
    """Return targets backed by a passing test or justified non-testability."""
    test_passed_by_target: dict[str, bool] = {}
    for test in artifact.tests:
        if test.target_id is None:
            continue
        passed = test.outcome.upper() == _OUTCOME_PASS
        test_passed_by_target[test.target_id] = test_passed_by_target.get(test.target_id, True) and passed
    return frozenset(
        target.target_id for target in artifact.mandatory_target_results if _is_fulfilled(target, test_passed_by_target)
    )


def _is_fulfilled(
    target: MandatoryTargetResult,
    test_passed_by_target: dict[str, bool],
) -> bool:
    """Whether a mandatory target is fulfilled (FK-48 §48.2.5)."""
    status = target.status.upper()
    if status == _STATUS_TESTED:
        # A TESTED claim without a correlated test is not evidence.
        return test_passed_by_target.get(target.target_id, False)
    if status == _STATUS_UNRESOLVABLE:
        # Justified non-testable: fulfilled only WITH a non-empty reason.
        return bool(target.reason and target.reason.strip())
    # Any other status (e.g. missing / not addressed) is unfulfilled.
    return False


__all__ = [
    "fulfilled_mandatory_target_ids",
    "mandatory_target_resolution_feedback",
]
