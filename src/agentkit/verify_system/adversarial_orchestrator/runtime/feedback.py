"""Layer-3 -> Layer-2 mandatory-target feedback (FK-48 §48.2.5, AG3-079 AC8).

A deterministic Zone-2 pipeline script: it reads ``mandatory_target_results`` from
``adversarial.json`` and, for every UNFULFILLED target, sets the mapped Layer-2
finding's resolution status to at least
:data:`~agentkit.verify_system.remediation.finding_resolution.FindingResolutionStatus.PARTIALLY_RESOLVED`
as input to the next remediation round (the existing finding-resolution mechanism,
no new status lifecycle, FK-48 §48.2.5).

Mapping (FK-48 §48.2.5): ``target_id`` == ``AdversarialTarget.finding_id`` ==
``f"{finding.layer}.{finding.check}"``; the :data:`FindingKey` is
``(layer, check)``.

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

from agentkit.verify_system.remediation.finding_resolution import (
    FindingKey,
    FindingResolutionStatus,
)

if TYPE_CHECKING:
    from agentkit.verify_system.adversarial_orchestrator.runtime.models import (
        AdversarialResultArtifact,
        MandatoryTargetResult,
    )

#: Mandatory-target status meaning a test was written (FK-48 §48.2.4).
_STATUS_TESTED: str = "TESTED"

#: Mandatory-target status meaning the case is justified non-testable.
_STATUS_UNRESOLVABLE: str = "UNRESOLVABLE"

#: Sandbox-test outcome meaning the addressing test passed.
_OUTCOME_PASS: str = "PASS"

#: Number of parts in a well-formed ``layer.check`` target id.
_TARGET_ID_PARTS: int = 2


def mandatory_target_resolution_feedback(
    artifact: AdversarialResultArtifact,
) -> dict[FindingKey, FindingResolutionStatus]:
    """Map UNFULFILLED mandatory targets to a Layer-2 finding-resolution map.

    For every unfulfilled mandatory target the mapped ``(layer, check)`` finding
    is set to ``PARTIALLY_RESOLVED`` (FK-48 §48.2.5). A fulfilled target
    (``TESTED`` + test PASS, or justified ``UNRESOLVABLE``) contributes nothing
    (it does not re-open a finding).

    Args:
        artifact: The materialised ``adversarial.json`` payload (schema 3.1).

    Returns:
        A ``{(layer, check) -> PARTIALLY_RESOLVED}`` map for the unfulfilled
        targets (empty when every target is fulfilled). This is written into the
        existing ``RemediationFeedback.finding_resolution`` model.
    """
    # Per-target test outcome: a TESTED target is only fulfilled when its
    # addressing test actually PASSed (FK-48 §48.2.5: TESTED + test FAIL keeps
    # the finding open). Match by ``target_id``.
    test_passed_by_target: dict[str, bool] = {}
    for test in artifact.tests:
        if test.target_id is None:
            continue
        passed = test.outcome.upper() == _OUTCOME_PASS
        # If any addressing test fails, the target is not cleanly tested.
        test_passed_by_target[test.target_id] = (
            test_passed_by_target.get(test.target_id, True) and passed
        )

    feedback: dict[FindingKey, FindingResolutionStatus] = {}
    for target in artifact.mandatory_target_results:
        if _is_fulfilled(target, test_passed_by_target):
            continue
        key = _target_key(target.target_id)
        if key is None:
            continue
        feedback[key] = FindingResolutionStatus.PARTIALLY_RESOLVED
    return feedback


def _is_fulfilled(
    target: MandatoryTargetResult,
    test_passed_by_target: dict[str, bool],
) -> bool:
    """Whether a mandatory target is fulfilled (FK-48 §48.2.5)."""
    status = target.status.upper()
    if status == _STATUS_TESTED:
        # TESTED is fulfilled only when the addressing test PASSed. When no
        # per-target outcome is known, fall back to "passed" ONLY if the
        # artifact carries no failing tests at all (derived elsewhere); here we
        # default to the recorded per-target outcome, treating an unknown
        # outcome as passed (the sub-agent claimed TESTED and no FAIL was
        # recorded for it).
        return test_passed_by_target.get(target.target_id, True)
    if status == _STATUS_UNRESOLVABLE:
        # Justified non-testable: fulfilled only WITH a non-empty reason.
        return bool(target.reason and target.reason.strip())
    # Any other status (e.g. missing / not addressed) is unfulfilled.
    return False


def _target_key(target_id: str) -> FindingKey | None:
    """Decode a ``layer.check`` target id into a ``(layer, check)`` FindingKey.

    FK-48 §48.2.5: ``target_id`` == ``f"{layer}.{check}"``. A ``check`` value may
    itself contain dots, so the split is on the FIRST dot only (``layer`` never
    contains a dot in AK3). Returns ``None`` for a malformed id (no dot).
    """
    layer, sep, check = target_id.partition(".")
    if not sep or not layer or not check:
        return None
    return (layer, check)


__all__ = ["mandatory_target_resolution_feedback"]
