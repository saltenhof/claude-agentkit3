"""Remediation feedback maps QA findings into escalation and mandatory-target feedback evidence."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from agentkit.backend.core_types import ArtifactClass

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agentkit.backend.verify_system.protocols import Finding, LayerResult
    from agentkit.backend.verify_system.system import VerifySystem


def _layer_escalation_requested(layer_results: tuple[LayerResult, ...]) -> bool:
    """Whether any layer stamped an immediate-escalation request (FIX-5).

    FK-27 §27.4.2/§27.4.5: the structural layer sets
    ``metadata["escalated"]=True`` when an ``escalated`` stage
    (``impact.violation``) FAILs BLOCKING. Such a finding must escalate
    immediately to a human -- it must NOT traverse the normal remediation loop.
    """
    return any(lr.metadata.get("escalated") is True for lr in layer_results)


def _mandatory_target_feedback_findings(
    system: VerifySystem,
    *,
    story_id: str,
    run_id: str,
    qa_cycle_round: int,
) -> tuple[Finding, ...]:
    """Load Layer-3 mandatory target results and map unmet targets for feedback.

    Fail-closed (AG3-067 AC8 remediation): only a GENUINELY-absent adversarial
    artifact (:class:`ArtifactNotFoundError`) means "no mandatory targets" — the
    adversarial stage did not run or produced nothing. Any OTHER failure (broken
    envelope/payload access, missing ``artifact_manager`` precondition) is a
    broken state that must NOT disappear as "no targets" (that would silently drop
    a BLOCKING mandatory target the remediation loop needs); it is surfaced as a
    hard :class:`MandatoryTargetReadError` instead of being swallowed.
    """
    if qa_cycle_round < 2:
        return ()
    from agentkit.backend.artifacts import ArtifactNotFoundError
    from agentkit.backend.core_types.qa_artifact_names import ADVERSARIAL_STAGE
    from agentkit.backend.verify_system.errors import MandatoryTargetReadError
    from agentkit.backend.verify_system.remediation.feedback import (
        mandatory_target_findings_from_adversarial,
    )

    try:
        envelope = system.artifact_manager.read_latest(
            story_id=story_id,
            run_id=run_id,
            artifact_class=ArtifactClass.QA,
            stage=ADVERSARIAL_STAGE,
        )
    except ArtifactNotFoundError:
        # Genuinely absent adversarial.json -> no mandatory targets (not an error).
        return ()
    except Exception as exc:  # noqa: BLE001 -- fail-closed: broken read must surface
        raise MandatoryTargetReadError(
            "Failed to read the Layer-3 adversarial artifact for mandatory-target "
            f"feedback (story={story_id!r}, run={run_id!r}, stage={ADVERSARIAL_STAGE!r}): "
            f"{type(exc).__name__}: {exc}. A broken adversarial artifact must not "
            "silently drop a mandatory target (FAIL-CLOSED)."
        ) from exc
    # AC8 remediation r2: a PRESENT envelope with a None/broken (non-mapping)
    # payload is a broken artifact, NOT "no targets". ``payload or {}`` would
    # mask it into an empty dict and silently drop any mandatory target — that
    # is exactly the FAIL-CLOSED hole the genuinely-absent path is meant to
    # exclude. Only ``ArtifactNotFoundError`` (handled above) means "no targets";
    # a present-but-unusable payload fails closed here.
    payload = envelope.payload
    if not isinstance(payload, Mapping):
        raise MandatoryTargetReadError(
            "The Layer-3 adversarial artifact is present but its payload is "
            f"unusable (story={story_id!r}, run={run_id!r}, "
            f"stage={ADVERSARIAL_STAGE!r}): expected a mapping, got "
            f"{type(payload).__name__}. A present-but-broken adversarial payload "
            "must not silently drop a mandatory target (FAIL-CLOSED)."
        )
    return mandatory_target_findings_from_adversarial(dict(payload))
