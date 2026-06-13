"""Shared fixtures for governance_observer unit tests.

All test doubles are injected AT THE LLM BOUNDARY (GovernanceAdjudicatorPort)
or AT THE READ BOUNDARY (ExecutionEventReader) — never through domain logic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from agentkit.governance.governance_observer.models import (
    AdjudicationIncidentType,
    AdjudicationRecommendedAction,
    AdjudicationSeverity,
    GovernanceAdjudicationVerdict,
    GovernanceIncidentCandidate,
)
from agentkit.telemetry.emitters import MemoryEmitter

# ---------------------------------------------------------------------------
# Test-double: ScriptedEventReader
# ---------------------------------------------------------------------------

class ScriptedEventReader:
    """Scripted ExecutionEventReader for unit tests.

    Implements the ExecutionEventReader protocol.  Signal payloads are
    injected at construction time; the ``read_last_adjudication_ts`` result
    can be set per signal_type to simulate cooldown state.
    """

    def __init__(
        self,
        signal_payloads: list[dict[str, Any]] | None = None,
        last_adjudication_ts: dict[str, float] | None = None,
    ) -> None:
        self._signal_payloads: list[dict[str, Any]] = signal_payloads or []
        self._last_adjudication_ts: dict[str, float] = last_adjudication_ts or {}
        self.read_calls: list[dict[str, Any]] = []
        self.adjudication_ts_calls: list[dict[str, Any]] = []

    def read_governance_signals(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return the first ``limit`` payloads (simulate DESC LIMIT)."""
        self.read_calls.append(
            {
                "project_key": project_key,
                "story_id": story_id,
                "run_id": run_id,
                "limit": limit,
            }
        )
        # Return at most ``limit`` entries — simulates the DB LIMIT
        return self._signal_payloads[:limit]

    def read_last_adjudication_ts(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        *,
        signal_type: str,
    ) -> float | None:
        """Return pre-configured timestamp or None."""
        self.adjudication_ts_calls.append(
            {
                "project_key": project_key,
                "story_id": story_id,
                "run_id": run_id,
                "signal_type": signal_type,
            }
        )
        return self._last_adjudication_ts.get(signal_type)


# ---------------------------------------------------------------------------
# Test-double: ScriptedAdjudicator
# ---------------------------------------------------------------------------

class ScriptedAdjudicator:
    """Scripted GovernanceAdjudicatorPort for unit tests.

    Implements the GovernanceAdjudicatorPort protocol.  The pre-configured
    verdict is returned without calling the LLM.  Call count is tracked for
    assertions that adjudication was or was NOT called.
    """

    def __init__(
        self,
        verdict: GovernanceAdjudicationVerdict | None = None,
    ) -> None:
        self._verdict = verdict or GovernanceAdjudicationVerdict(
            incident_type=AdjudicationIncidentType.ROLE_VIOLATION,
            severity=AdjudicationSeverity.MEDIUM,
            confidence=0.8,
            evidence_summary="Test verdict",
            recommended_action=AdjudicationRecommendedAction.DOCUMENT_INCIDENT,
        )
        self.call_count: int = 0

    def adjudicate(
        self,
        candidate: GovernanceIncidentCandidate,
        *,
        story_context_summary: str,
    ) -> GovernanceAdjudicationVerdict:
        """Return pre-configured verdict and record call."""
        self.call_count += 1
        return self._verdict


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def memory_emitter() -> MemoryEmitter:
    """Return a fresh MemoryEmitter."""
    return MemoryEmitter()


@pytest.fixture()
def default_verdict() -> GovernanceAdjudicationVerdict:
    """Return a default medium-severity verdict."""
    return GovernanceAdjudicationVerdict(
        incident_type=AdjudicationIncidentType.ROLE_VIOLATION,
        severity=AdjudicationSeverity.MEDIUM,
        confidence=0.75,
        evidence_summary="Orchestrator wrote code directly.",
        recommended_action=AdjudicationRecommendedAction.DOCUMENT_INCIDENT,
    )


@pytest.fixture()
def default_candidate() -> GovernanceIncidentCandidate:
    """Return a default GovernanceIncidentCandidate."""
    return GovernanceIncidentCandidate(
        project_key="PRJ",
        story_id="AG3-085",
        run_id="run-001",
        created_at=datetime.now(UTC),
        risk_score=35,
        event_count=10,
        dominant_signals=["orchestrator_code_read_write"],
        evidence_summary="10 code-write events.",
        time_span_s=120.0,
    )
