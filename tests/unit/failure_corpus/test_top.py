"""Unit-Tests fuer FailureCorpus-Top-Komponente (AG3-028 §2.1.2, AK#2/#3).

``record_incident`` wird gegen einen ECHTEN ProjectionAccessor (SQLite) verprobt
(kein Mock fuer Kernlogik). Die vier nicht-implementierten Top-Methoden werden
auf ihren NotImplementedError-Vertrag gepinnt.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.bootstrap.composition_root import build_failure_corpus
from agentkit.core_types import FailureCategory
from agentkit.failure_corpus import (
    FailureCorpus,
    IncidentCandidate,
    IncidentSeverity,
)
from agentkit.failure_corpus.errors import IncidentRejectedError, IncidentRejectReason
from agentkit.failure_corpus.top import (
    CheckApprovalDecision,
    PatternDecision,
)
from agentkit.failure_corpus.types import CheckId, PatternId
from agentkit.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FailureCorpus]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    from agentkit.state_backend.store.facade import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    yield build_failure_corpus(accessor)
    reset_backend_cache_for_tests()


def _candidate(summary: str = "scope exceeded") -> IncidentCandidate:
    return IncidentCandidate(
        category=FailureCategory.SCOPE_DRIFT,
        severity=IncidentSeverity.HIGH,
        source_bc="governance-and-guards",
        story_id="AG3-001",
        run_id="run-1",
        summary=summary,
        evidence={"detail": "x"},
        observed_at=_NOW,
    )


class TestRecordIncident:
    def test_happy_path_returns_incident_id_and_persists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.state_backend.store.facade import reset_backend_cache_for_tests

        reset_backend_cache_for_tests()
        try:
            acc = ProjectionAccessor(build_projection_repositories(tmp_path))
            fc = build_failure_corpus(acc)

            incident_id = fc.record_incident(_candidate())
            assert incident_id.startswith("FC-")

            rows = acc.read_projection(
                ProjectionKind.FC_INCIDENTS,
                ProjectionFilter(story_id="AG3-001", run_id="run-1"),
            )
            assert len(rows) == 1
            assert rows[0].incident_id == incident_id
        finally:
            reset_backend_cache_for_tests()

    def test_reject_below_min_severity(self, corpus: FailureCorpus) -> None:
        with pytest.raises(IncidentRejectedError) as exc:
            corpus.record_incident(
                IncidentCandidate(
                    category=FailureCategory.SCOPE_DRIFT,
                    severity=IncidentSeverity.LOW,
                    source_bc="bc",
                    story_id="AG3-001",
                    run_id="run-1",
                    summary="trivial",
                    observed_at=_NOW,
                )
            )
        assert IncidentRejectReason.BELOW_MIN_SEVERITY in exc.value.reason_codes


class TestNotImplementedSurface:
    """AK#2: vier Folge-Story-Methoden werfen NotImplementedError mit Begruendung."""

    def test_suggest_patterns(self, corpus: FailureCorpus) -> None:
        with pytest.raises(NotImplementedError, match="PatternPromotion"):
            corpus.suggest_patterns()

    def test_confirm_pattern(self, corpus: FailureCorpus) -> None:
        with pytest.raises(NotImplementedError, match="PatternPromotion"):
            corpus.confirm_pattern(PatternId("P-1"), PatternDecision.ACCEPTED)

    def test_derive_check(self, corpus: FailureCorpus) -> None:
        with pytest.raises(NotImplementedError, match="CheckFactory"):
            corpus.derive_check(PatternId("P-1"))

    def test_approve_check(self, corpus: FailureCorpus) -> None:
        with pytest.raises(NotImplementedError, match="CheckFactory"):
            corpus.approve_check(CheckId("C-1"), CheckApprovalDecision.APPROVED)

    def test_report_effectiveness(self, corpus: FailureCorpus) -> None:
        with pytest.raises(NotImplementedError, match="Effectiveness"):
            corpus.report_effectiveness()
