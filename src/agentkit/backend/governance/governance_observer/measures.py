"""Deterministic measure selection (FK-35 §35.3.8).

The final governance action is ALWAYS deterministic and rule-based —
never chosen by an LLM.  The table below exactly mirrors FK-35 §35.3.8.

Boundary note (AG3-085 scope limit)
------------------------------------
:func:`select_measure` **selects** the measure and returns it as a typed enum
value.  The :class:`~agentkit.backend.governance.governance_observer.observer.GovernanceObserver`
**emits** ``governance_measure_applied`` as the governance-decision record.

The ACTUAL enforcement of each measure is owned by SEPARATE layers:

* ``stop_process`` (immediate hard-stop via hook): FK-35 §35.3.8 / FK-06-118
  — owned by the AG3-086 hook/sensorik layer.  For immediate-stop signals
  (``governance_file_manipulation`` / ``secret_access``) the observer bypasses
  adjudication entirely and emits ONLY ``governance_measure_applied`` (FK-35
  §35.3.8 FK-06-118 direct path).
* ``pause_story`` (Phase-State PAUSED) and ``stop_process`` from adjudicated
  verdicts: FK-35 §35.3.8 / §35.4.1 — owned by the orchestrator/escalation
  layer.

Neither the observer nor this module wire or invoke enforcement.
Enforcement wiring is explicitly out of AG3-085 scope (story §2.2 Out of Scope).
"""

from __future__ import annotations

from agentkit.backend.governance.governance_observer.models import (
    AdjudicationSeverity,
    GovernanceMeasure,
)

#: Confidence threshold for CRITICAL -> PAUSE_STORY (FK-35 §35.3.8 FK-06-119).
_HIGH_CONFIDENCE_THRESHOLD: float = 0.8


def select_measure(
    severity: AdjudicationSeverity,
    confidence: float,
) -> GovernanceMeasure:
    """Select the deterministic governance measure (FK-35 §35.3.8).

    Decision table (in priority order):

    1. ``critical`` + ``confidence >= 0.8``  -> :attr:`~GovernanceMeasure.PAUSE_STORY`
    2. ``high``     + ``confidence < 0.8``   -> :attr:`~GovernanceMeasure.DOCUMENT_INCIDENT_INCREASE_MONITORING`
    3. ``high``     + ``confidence >= 0.8``  -> :attr:`~GovernanceMeasure.DOCUMENT_INCIDENT_INCREASE_MONITORING`
       (high always documents + increases monitoring regardless of confidence)
    4. ``medium``                            -> :attr:`~GovernanceMeasure.DOCUMENT_INCIDENT`
    5. ``low``                               -> :attr:`~GovernanceMeasure.GOVERNANCE_LOG_ONLY`

    Note: ``stop_process`` for hard governance violations (secrets /
    governance-file manipulation) is issued DIRECTLY by
    :meth:`~agentkit.backend.governance.governance_observer.observer.GovernanceObserver.handle_signal`
    WITHOUT calling adjudication.  This function is only called AFTER a
    completed adjudication (FK-35 §35.3.8 FK-06-118).

    Args:
        severity: Adjudication severity level.
        confidence: Adjudication confidence (0.0–1.0).

    Returns:
        The deterministic :class:`GovernanceMeasure` to apply.
    """
    if severity == AdjudicationSeverity.CRITICAL:
        return _measure_for_critical(confidence)
    if severity == AdjudicationSeverity.HIGH:
        return GovernanceMeasure.DOCUMENT_INCIDENT_INCREASE_MONITORING
    if severity == AdjudicationSeverity.MEDIUM:
        return GovernanceMeasure.DOCUMENT_INCIDENT
    return GovernanceMeasure.GOVERNANCE_LOG_ONLY


def _measure_for_critical(confidence: float) -> GovernanceMeasure:
    """Return the measure for a critical-severity verdict.

    Args:
        confidence: Adjudication confidence value.

    Returns:
        :attr:`~GovernanceMeasure.PAUSE_STORY` when ``confidence >= 0.8``,
        otherwise :attr:`~GovernanceMeasure.DOCUMENT_INCIDENT_INCREASE_MONITORING`.
    """
    if confidence >= _HIGH_CONFIDENCE_THRESHOLD:
        return GovernanceMeasure.PAUSE_STORY
    return GovernanceMeasure.DOCUMENT_INCIDENT_INCREASE_MONITORING
