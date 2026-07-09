"""Unit tests for ProjectionAccessor ownership of FC_PATTERNS/FC_CHECK_PROPOSALS.

Tests verify (AG3-078):
- FC_PATTERNS and FC_CHECK_PROPOSALS are in _ACCESSOR_OWNED_KINDS
- PHASE_STATE_PROJECTION is NOT accessor-owned (externally owned)
- write_projection(FC_PATTERNS) accepts FailurePatternRecord
- write_projection(FC_CHECK_PROPOSALS) accepts CheckProposalRecord
- read_projection(FC_PATTERNS) requires project_key (FAIL-CLOSED)
- read_projection(FC_CHECK_PROPOSALS) requires project_key (FAIL-CLOSED)
- purge_run does NOT touch FC_PATTERNS/FC_CHECK_PROPOSALS (FK-41 §41.3.3)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.core_types import (
    CheckStatus,
    CheckType,
    FailureCategory,
    PatternStatus,
)
from agentkit.backend.failure_corpus.check_proposal import CheckProposalRecord, FalsePositiveRisk
from agentkit.backend.failure_corpus.pattern import FailurePatternRecord, PatternRiskLevel, PromotionRule
from agentkit.backend.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)


@pytest.fixture()
def accessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ProjectionAccessor:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
    from agentkit.backend.state_backend.store.telemetry_projection_repository_misc import (
        build_projection_repositories,
    )

    reset_backend_cache_for_tests()
    repos = build_projection_repositories(tmp_path)
    return ProjectionAccessor(repos)


def _make_pattern(project_key: str = "proj-own", pid: str = "FP-0001") -> FailurePatternRecord:
    return FailurePatternRecord(
        pattern_id=pid,
        project_key=project_key,
        status=PatternStatus.ACCEPTED,
        category=FailureCategory.SCOPE_DRIFT,
        promotion_rule=PromotionRule.HIGH_SEVERITY,
        invariant="scope MUST NOT be exceeded",
        risk_level=PatternRiskLevel.HIGH,
        confirmed_by="human",
        incident_refs=["FC-2026-0001"],
        incident_count=1,
    )


def _make_check(
    project_key: str = "proj-own",
    check_id: str = "CHK-0001",
    pattern_ref: str = "FP-0001",
) -> CheckProposalRecord:
    return CheckProposalRecord(
        check_id=check_id,
        project_key=project_key,
        status=CheckStatus.DRAFT,
        pattern_ref=pattern_ref,
        invariant="scope MUST be checked",
        check_type=CheckType.CHANGED_FILE_POLICY,
        pipeline_stage="structural",
        pipeline_layer=1,
        owner="failure-corpus",
        false_positive_risk=FalsePositiveRisk.LOW,
        created_at=datetime.now(UTC),
        approved_by=None,
        rejected_reason=None,
        true_positives_90d=0,
        false_positives_90d=0,
        no_findings_90d=None,
        effectiveness_last_checked_at=None,
    )


class TestOwnershipContract:
    def test_fc_patterns_is_accessor_owned(self) -> None:
        assert ProjectionAccessor.is_accessor_owned(ProjectionKind.FC_PATTERNS)

    def test_fc_check_proposals_is_accessor_owned(self) -> None:
        assert ProjectionAccessor.is_accessor_owned(ProjectionKind.FC_CHECK_PROPOSALS)

    def test_phase_state_projection_is_not_accessor_owned(self) -> None:
        assert not ProjectionAccessor.is_accessor_owned(ProjectionKind.PHASE_STATE_PROJECTION)


class TestWriteProjectionFcPatterns:
    def test_write_failure_pattern_record_succeeds(
        self, accessor: ProjectionAccessor
    ) -> None:
        pattern = _make_pattern()
        accessor.write_projection(ProjectionKind.FC_PATTERNS, pattern)

    def test_write_rejects_wrong_type(self, accessor: ProjectionAccessor) -> None:
        from agentkit.backend.telemetry.errors import ProjectionRecordTypeMismatchError

        with pytest.raises(ProjectionRecordTypeMismatchError):
            # QACheckOutcomeRecord is NOT a FailurePatternRecord
            accessor.write_projection(
                ProjectionKind.FC_PATTERNS,
                _make_check(),  # type: ignore[arg-type]
            )


class TestWriteProjectionFcCheckProposals:
    def test_write_check_proposal_record_succeeds(
        self, accessor: ProjectionAccessor
    ) -> None:
        # Parent pattern must exist first (FK constraint: pattern_ref -> fc_patterns)
        accessor.write_projection(ProjectionKind.FC_PATTERNS, _make_pattern())
        check = _make_check()
        accessor.write_projection(ProjectionKind.FC_CHECK_PROPOSALS, check)

    def test_write_rejects_wrong_type(self, accessor: ProjectionAccessor) -> None:
        from agentkit.backend.telemetry.errors import ProjectionRecordTypeMismatchError

        with pytest.raises(ProjectionRecordTypeMismatchError):
            accessor.write_projection(
                ProjectionKind.FC_CHECK_PROPOSALS,
                _make_pattern(),  # type: ignore[arg-type]
            )


class TestReadProjectionFcPatterns:
    def test_requires_project_key_fail_closed(
        self, accessor: ProjectionAccessor
    ) -> None:
        with pytest.raises(ValueError, match="project_key"):
            accessor.read_projection(
                ProjectionKind.FC_PATTERNS,
                ProjectionFilter(project_key=None),
            )

    def test_read_returns_written_pattern(
        self, accessor: ProjectionAccessor
    ) -> None:
        pattern = _make_pattern()
        accessor.write_projection(ProjectionKind.FC_PATTERNS, pattern)
        results = accessor.read_projection(
            ProjectionKind.FC_PATTERNS,
            ProjectionFilter(project_key="proj-own"),
        )
        assert len(results) == 1
        assert results[0].pattern_id == "FP-0001"  # type: ignore[union-attr]


class TestReadProjectionFcCheckProposals:
    def test_requires_project_key_fail_closed(
        self, accessor: ProjectionAccessor
    ) -> None:
        with pytest.raises(ValueError, match="project_key"):
            accessor.read_projection(
                ProjectionKind.FC_CHECK_PROPOSALS,
                ProjectionFilter(project_key=None),
            )

    def test_read_returns_written_check(
        self, accessor: ProjectionAccessor
    ) -> None:
        # Parent pattern must exist first (FK constraint: pattern_ref -> fc_patterns)
        accessor.write_projection(ProjectionKind.FC_PATTERNS, _make_pattern())
        check = _make_check()
        accessor.write_projection(ProjectionKind.FC_CHECK_PROPOSALS, check)
        results = accessor.read_projection(
            ProjectionKind.FC_CHECK_PROPOSALS,
            ProjectionFilter(project_key="proj-own"),
        )
        assert any(r.check_id == "CHK-0001" for r in results)  # type: ignore[union-attr]


class TestReadProjectionFcCheckProposalsBeyondOldBound:
    def test_read_finds_check_beyond_old_9999_scan(
        self, accessor: ProjectionAccessor
    ) -> None:
        """FC_CHECK_PROPOSALS read must return checks with high numeric id (no fixed-range scan).

        With the band-aided range(1, 10000) scan, CHK-9999 was the last visible
        entry.  With list_for_project, all ids are visible regardless of numeric
        value. Seeds CHK-9999 and verifies read_projection returns it.
        """
        accessor.write_projection(
            ProjectionKind.FC_PATTERNS,
            _make_pattern(project_key="proj-highid", pid="FP-0001"),
        )
        accessor.write_projection(
            ProjectionKind.FC_CHECK_PROPOSALS,
            _make_check(project_key="proj-highid", check_id="CHK-9999"),
        )
        results = accessor.read_projection(
            ProjectionKind.FC_CHECK_PROPOSALS,
            ProjectionFilter(project_key="proj-highid"),
        )
        ids = [r.check_id for r in results]  # type: ignore[union-attr]
        assert "CHK-9999" in ids


class TestPurgeRunDoesNotTouchFcKinds:
    def test_purge_run_does_not_remove_fc_patterns(
        self, accessor: ProjectionAccessor
    ) -> None:
        """FK-41 §41.3.3: fc_patterns excluded from purge_run."""
        pattern = _make_pattern(project_key="proj-purge")
        accessor.write_projection(ProjectionKind.FC_PATTERNS, pattern)

        accessor.purge_run("proj-purge", "AG3-001", "run-1")

        # Pattern must still exist
        results = accessor.read_projection(
            ProjectionKind.FC_PATTERNS,
            ProjectionFilter(project_key="proj-purge"),
        )
        assert len(results) == 1

    def test_purge_run_does_not_remove_fc_check_proposals(
        self, accessor: ProjectionAccessor
    ) -> None:
        """FK-41 §41.3.3: fc_check_proposals excluded from purge_run."""
        # Parent pattern must exist first (FK constraint: pattern_ref -> fc_patterns)
        accessor.write_projection(ProjectionKind.FC_PATTERNS, _make_pattern(project_key="proj-purge2"))
        check = _make_check(project_key="proj-purge2")
        accessor.write_projection(ProjectionKind.FC_CHECK_PROPOSALS, check)

        accessor.purge_run("proj-purge2", "AG3-002", "run-2")

        results = accessor.read_projection(
            ProjectionKind.FC_CHECK_PROPOSALS,
            ProjectionFilter(project_key="proj-purge2"),
        )
        assert len(results) == 1
