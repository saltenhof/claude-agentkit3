"""Tests for deterministic measure selection (FK-35 §35.3.8).

Covers the complete measure decision table.
"""

from __future__ import annotations

import pytest

from agentkit.governance.governance_observer.measures import select_measure
from agentkit.governance.governance_observer.models import (
    AdjudicationSeverity,
    GovernanceMeasure,
)


@pytest.mark.parametrize(
    ("severity", "confidence", "expected_measure"),
    [
        # critical + high confidence -> pause_story (FK-06-119)
        (AdjudicationSeverity.CRITICAL, 0.8, GovernanceMeasure.PAUSE_STORY),
        (AdjudicationSeverity.CRITICAL, 0.9, GovernanceMeasure.PAUSE_STORY),
        (AdjudicationSeverity.CRITICAL, 1.0, GovernanceMeasure.PAUSE_STORY),
        # critical + low confidence -> document + monitoring
        (
            AdjudicationSeverity.CRITICAL,
            0.7,
            GovernanceMeasure.DOCUMENT_INCIDENT_INCREASE_MONITORING,
        ),
        (
            AdjudicationSeverity.CRITICAL,
            0.0,
            GovernanceMeasure.DOCUMENT_INCIDENT_INCREASE_MONITORING,
        ),
        # high (any confidence) -> document + monitoring (FK-06-120)
        (
            AdjudicationSeverity.HIGH,
            0.5,
            GovernanceMeasure.DOCUMENT_INCIDENT_INCREASE_MONITORING,
        ),
        (
            AdjudicationSeverity.HIGH,
            0.9,
            GovernanceMeasure.DOCUMENT_INCIDENT_INCREASE_MONITORING,
        ),
        # medium -> document_incident (FK-06-121)
        (AdjudicationSeverity.MEDIUM, 0.5, GovernanceMeasure.DOCUMENT_INCIDENT),
        (AdjudicationSeverity.MEDIUM, 0.9, GovernanceMeasure.DOCUMENT_INCIDENT),
        # low -> governance_log_only (FK-06-122)
        (AdjudicationSeverity.LOW, 0.5, GovernanceMeasure.GOVERNANCE_LOG_ONLY),
        (AdjudicationSeverity.LOW, 0.0, GovernanceMeasure.GOVERNANCE_LOG_ONLY),
    ],
)
def test_select_measure(
    severity: AdjudicationSeverity,
    confidence: float,
    expected_measure: GovernanceMeasure,
) -> None:
    """Measure decision table is exact per FK-35 §35.3.8."""
    assert select_measure(severity, confidence) == expected_measure


def test_critical_confidence_boundary_at_08() -> None:
    """Boundary check: exactly 0.8 confidence triggers pause_story for critical."""
    assert select_measure(AdjudicationSeverity.CRITICAL, 0.8) == GovernanceMeasure.PAUSE_STORY


def test_critical_confidence_just_below_08() -> None:
    """Boundary check: 0.79 confidence gives document+monitoring for critical."""
    assert (
        select_measure(AdjudicationSeverity.CRITICAL, 0.79)
        == GovernanceMeasure.DOCUMENT_INCIDENT_INCREASE_MONITORING
    )
