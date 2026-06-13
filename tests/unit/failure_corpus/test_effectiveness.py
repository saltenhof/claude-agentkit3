"""Unit tests for CheckEffectivenessTracker (FK-41 §41.6.7, AG3-078).

Tests cover:
- No ACTIVE checks -> empty report
- ACTIVE check with tp>0 stays ACTIVE
- ACTIVE check with tp==0 AND fp>3 -> auto-deactivated (RETIRED)
- CRITICAL risk check exempt from auto-deactivation
- check_accept_frequency pure function
- SonarAcceptFrequencySignal.evaluate with injected threshold (no config needed)
"""

from __future__ import annotations

import pytest

from agentkit.failure_corpus.sonar_signal import SonarAcceptFrequencySignal, check_accept_frequency

# ---------------------------------------------------------------------------
# check_accept_frequency (pure function)
# ---------------------------------------------------------------------------


class TestCheckAcceptFrequency:
    def test_zero_total_returns_false(self) -> None:
        assert check_accept_frequency(accept_count=0, total_count=0, threshold=0.2) is False

    def test_below_threshold_returns_false(self) -> None:
        # 1/10 = 0.1 <= 0.2
        assert check_accept_frequency(accept_count=1, total_count=10, threshold=0.2) is False

    def test_at_threshold_returns_false(self) -> None:
        # 2/10 = 0.2 == threshold -> NOT exceeded (strictly ">")
        assert check_accept_frequency(accept_count=2, total_count=10, threshold=0.2) is False

    def test_above_threshold_returns_true(self) -> None:
        # 3/10 = 0.3 > 0.2 -> exceeded
        assert check_accept_frequency(accept_count=3, total_count=10, threshold=0.2) is True

    def test_all_accepted_returns_true(self) -> None:
        assert check_accept_frequency(accept_count=10, total_count=10, threshold=0.5) is True


# ---------------------------------------------------------------------------
# SonarAcceptFrequencySignal (with injected threshold)
# ---------------------------------------------------------------------------


class TestSonarAcceptFrequencySignalEvaluate:
    def _make_signal(self) -> SonarAcceptFrequencySignal:
        """Build the signal with a stubbed record_incident_fn."""
        recorded: list[object] = []

        def _record(candidate: object) -> str:
            recorded.append(candidate)
            return "FC-2026-0001"

        sig = SonarAcceptFrequencySignal(
            record_incident_fn=_record,  # type: ignore[arg-type]
            project_key="proj-sonar",
            story_id="AG3-078",
            run_id="run-sonar-1",
        )
        sig._recorded = recorded  # type: ignore[attr-defined]
        return sig

    def test_below_threshold_returns_none(self) -> None:
        sig = self._make_signal()
        result = sig.evaluate(accept_count=1, total_count=10, threshold=0.5)
        assert result is None

    def test_above_threshold_records_incident_and_returns_id(self) -> None:
        sig = self._make_signal()
        result = sig.evaluate(accept_count=6, total_count=10, threshold=0.5)
        assert result == "FC-2026-0001"

    def test_zero_total_returns_none(self) -> None:
        sig = self._make_signal()
        result = sig.evaluate(accept_count=0, total_count=0, threshold=0.2)
        assert result is None

    def test_no_project_root_and_no_threshold_raises_runtime_error(self) -> None:
        def _record(candidate: object) -> str:
            return "FC-2026-0001"

        sig = SonarAcceptFrequencySignal(
            record_incident_fn=_record,  # type: ignore[arg-type]
            project_key="proj-test",
            story_id="AG3-078",
            run_id="run-1",
            project_root=None,
        )
        with pytest.raises(RuntimeError, match="project_root"):
            sig.evaluate(accept_count=5, total_count=10)  # no threshold injected


# ---------------------------------------------------------------------------
# CheckEffectivenessTracker (integration: real SQLite)
# ---------------------------------------------------------------------------


class TestCheckEffectivenessTracker:
    def test_no_active_checks_returns_empty_report(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.failure_corpus.effectiveness import CheckEffectivenessTracker
        from agentkit.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.state_backend.store.fc_check_proposal_repository import (
            StateBackendFcCheckProposalRepository,
        )
        from agentkit.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )
        from agentkit.state_backend.store.projection_repositories import (
            build_projection_repositories,
        )
        from agentkit.telemetry.projection_accessor import ProjectionAccessor

        reset_backend_cache_for_tests()
        try:
            accessor = ProjectionAccessor(build_projection_repositories(tmp_path))  # type: ignore[arg-type]
            check_repo = StateBackendFcCheckProposalRepository(tmp_path)  # type: ignore[arg-type]
            pattern_repo = StateBackendFcPatternRepository(tmp_path)  # type: ignore[arg-type]
            tracker = CheckEffectivenessTracker(
                accessor=accessor,
                check_repo=check_repo,
                pattern_repo=pattern_repo,
                project_key="proj-eff",
            )
            report = tracker.report_effectiveness(window_days=90)
            assert report.updated_count == 0
            assert report.deactivated_count == 0
        finally:
            reset_backend_cache_for_tests()

    def test_auto_deactivation_tp_zero_fp_gt_3(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Auto-deactivation: tp==0 AND fp>3 -> RETIRED (non-CRITICAL)."""
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from datetime import UTC, datetime

        from agentkit.core_types import CheckStatus, CheckType
        from agentkit.failure_corpus.check_proposal import CheckProposalRecord, FalsePositiveRisk
        from agentkit.failure_corpus.effectiveness import CheckEffectivenessTracker
        from agentkit.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.state_backend.store.fc_check_proposal_repository import (
            StateBackendFcCheckProposalRepository,
        )
        from agentkit.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )
        from agentkit.state_backend.store.projection_repositories import (
            build_projection_repositories,
        )
        from agentkit.telemetry.projection_accessor import (
            ProjectionAccessor,
            ProjectionKind,
        )
        from agentkit.verify_system.stage_registry.records import (
            CheckOutcome,
            QACheckOutcomeRecord,
        )

        reset_backend_cache_for_tests()
        try:
            accessor = ProjectionAccessor(build_projection_repositories(tmp_path))  # type: ignore[arg-type]
            check_repo = StateBackendFcCheckProposalRepository(tmp_path)  # type: ignore[arg-type]
            pattern_repo = StateBackendFcPatternRepository(tmp_path)  # type: ignore[arg-type]

            from agentkit.core_types import FailureCategory, PatternStatus
            from agentkit.failure_corpus.pattern import FailurePatternRecord, PatternRiskLevel, PromotionRule

            # Seed the parent pattern first (FK constraint: pattern_ref must exist)
            parent_pattern = FailurePatternRecord(
                pattern_id="FP-0001",
                project_key="proj-deact",
                status=PatternStatus.ACCEPTED,
                category=FailureCategory.SCOPE_DRIFT,
                promotion_rule=PromotionRule.HIGH_SEVERITY,
                invariant="scope MUST NOT be exceeded",
                risk_level=PatternRiskLevel.MEDIUM,
                confirmed_by="human",
                incident_refs=[],
                incident_count=0,
            )
            pattern_repo.save(parent_pattern)

            # Seed an ACTIVE check proposal (non-CRITICAL pattern risk)
            proposal = CheckProposalRecord(
                check_id="CHK-0001",
                project_key="proj-deact",
                status=CheckStatus.ACTIVE,
                pattern_ref="FP-0001",
                invariant="scope invariant",
                check_type=CheckType.CHANGED_FILE_POLICY,
                pipeline_stage="structural",
                pipeline_layer=1,
                owner="failure-corpus",
                false_positive_risk=FalsePositiveRisk.LOW,
                created_at=datetime.now(UTC),
                approved_at=datetime.now(UTC),
                approved_by="human",
                rejected_reason=None,
                true_positives_90d=0,
                false_positives_90d=0,
                no_findings_90d=None,
                effectiveness_last_checked_at=None,
            )
            check_repo.save(proposal)

            # Seed 4 OVERRIDDEN (false positive) outcomes for this check
            now = datetime.now(UTC)
            for i in range(4):
                outcome_record = QACheckOutcomeRecord(
                    project_key="proj-deact",
                    story_id=f"AG3-{i:03d}",
                    run_id=f"run-{i}",
                    attempt_no=1,
                    stage_id="layer1-structural",
                    check_id="changed_file_policy",
                    check_proposal_ref="CHK-0001",
                    outcome=CheckOutcome.OVERRIDDEN,
                    occurred_at=now,
                )
                accessor.write_projection(ProjectionKind.QA_CHECK_OUTCOMES, outcome_record)

            tracker = CheckEffectivenessTracker(
                accessor=accessor,
                check_repo=check_repo,
                pattern_repo=pattern_repo,
                project_key="proj-deact",
            )
            report = tracker.report_effectiveness(window_days=90)
            assert report.updated_count == 1
            assert report.deactivated_count == 1

            # Verify the proposal is now RETIRED
            updated = check_repo.load("CHK-0001")
            assert updated is not None
            assert updated.status is CheckStatus.RETIRED
        finally:
            reset_backend_cache_for_tests()

    def test_not_deactivated_when_tp_zero_fp_eq_3(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ERROR 7: tp==0 AND fp==3 (exactly 3) MUST NOT deactivate (boundary: fp > 3, not >=3)."""
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from datetime import UTC, datetime

        from agentkit.core_types import CheckStatus, CheckType
        from agentkit.failure_corpus.check_proposal import CheckProposalRecord, FalsePositiveRisk
        from agentkit.failure_corpus.effectiveness import CheckEffectivenessTracker
        from agentkit.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.state_backend.store.fc_check_proposal_repository import (
            StateBackendFcCheckProposalRepository,
        )
        from agentkit.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )
        from agentkit.state_backend.store.projection_repositories import (
            build_projection_repositories,
        )
        from agentkit.telemetry.projection_accessor import ProjectionAccessor, ProjectionKind
        from agentkit.verify_system.stage_registry.records import (
            CheckOutcome,
            QACheckOutcomeRecord,
        )

        reset_backend_cache_for_tests()
        try:
            accessor = ProjectionAccessor(build_projection_repositories(tmp_path))  # type: ignore[arg-type]
            check_repo = StateBackendFcCheckProposalRepository(tmp_path)  # type: ignore[arg-type]
            pattern_repo = StateBackendFcPatternRepository(tmp_path)  # type: ignore[arg-type]

            from agentkit.core_types import FailureCategory, PatternStatus
            from agentkit.failure_corpus.pattern import FailurePatternRecord, PatternRiskLevel, PromotionRule

            parent_pattern = FailurePatternRecord(
                pattern_id="FP-0002",
                project_key="proj-boundary",
                status=PatternStatus.ACCEPTED,
                category=FailureCategory.SCOPE_DRIFT,
                promotion_rule=PromotionRule.HIGH_SEVERITY,
                invariant="scope MUST NOT be exceeded",
                risk_level=PatternRiskLevel.MEDIUM,
                confirmed_by="human",
                incident_refs=[],
                incident_count=0,
            )
            pattern_repo.save(parent_pattern)

            proposal = CheckProposalRecord(
                check_id="CHK-0002",
                project_key="proj-boundary",
                status=CheckStatus.ACTIVE,
                pattern_ref="FP-0002",
                invariant="scope invariant",
                check_type=CheckType.CHANGED_FILE_POLICY,
                pipeline_stage="structural",
                pipeline_layer=1,
                owner="failure-corpus",
                false_positive_risk=FalsePositiveRisk.LOW,
                created_at=datetime.now(UTC),
                approved_at=datetime.now(UTC),
                approved_by="human",
            )
            check_repo.save(proposal)

            # Seed exactly 3 OVERRIDDEN outcomes (fp==3, NOT > 3)
            now = datetime.now(UTC)
            for i in range(3):
                outcome_record = QACheckOutcomeRecord(
                    project_key="proj-boundary",
                    story_id=f"AG3-{i:03d}",
                    run_id=f"run-{i}",
                    attempt_no=1,
                    stage_id="layer1-structural",
                    check_id="changed_file_policy",
                    check_proposal_ref="CHK-0002",
                    outcome=CheckOutcome.OVERRIDDEN,
                    occurred_at=now,
                )
                accessor.write_projection(ProjectionKind.QA_CHECK_OUTCOMES, outcome_record)

            tracker = CheckEffectivenessTracker(
                accessor=accessor,
                check_repo=check_repo,
                pattern_repo=pattern_repo,
                project_key="proj-boundary",
            )
            report = tracker.report_effectiveness(window_days=90)
            # fp==3 does NOT exceed threshold (threshold is fp > 3, i.e. at least 4)
            assert report.deactivated_count == 0
            updated = check_repo.load("CHK-0002")
            assert updated is not None
            assert updated.status is CheckStatus.ACTIVE  # still ACTIVE
        finally:
            reset_backend_cache_for_tests()

    def test_not_deactivated_when_tp_gt_0_fp_gt_3(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ERROR 7: tp>0 AND fp>3 MUST NOT deactivate (tp>0 means real finds exist)."""
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from datetime import UTC, datetime

        from agentkit.core_types import CheckStatus, CheckType
        from agentkit.failure_corpus.check_proposal import CheckProposalRecord, FalsePositiveRisk
        from agentkit.failure_corpus.effectiveness import CheckEffectivenessTracker
        from agentkit.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.state_backend.store.fc_check_proposal_repository import (
            StateBackendFcCheckProposalRepository,
        )
        from agentkit.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )
        from agentkit.state_backend.store.projection_repositories import (
            build_projection_repositories,
        )
        from agentkit.telemetry.projection_accessor import ProjectionAccessor, ProjectionKind
        from agentkit.verify_system.stage_registry.records import (
            CheckOutcome,
            QACheckOutcomeRecord,
        )

        reset_backend_cache_for_tests()
        try:
            accessor = ProjectionAccessor(build_projection_repositories(tmp_path))  # type: ignore[arg-type]
            check_repo = StateBackendFcCheckProposalRepository(tmp_path)  # type: ignore[arg-type]
            pattern_repo = StateBackendFcPatternRepository(tmp_path)  # type: ignore[arg-type]

            from agentkit.core_types import FailureCategory, PatternStatus
            from agentkit.failure_corpus.pattern import FailurePatternRecord, PatternRiskLevel, PromotionRule

            parent_pattern = FailurePatternRecord(
                pattern_id="FP-0003",
                project_key="proj-tp-fp",
                status=PatternStatus.ACCEPTED,
                category=FailureCategory.SCOPE_DRIFT,
                promotion_rule=PromotionRule.HIGH_SEVERITY,
                invariant="scope MUST NOT be exceeded",
                risk_level=PatternRiskLevel.MEDIUM,
                confirmed_by="human",
                incident_refs=[],
                incident_count=0,
            )
            pattern_repo.save(parent_pattern)

            proposal = CheckProposalRecord(
                check_id="CHK-0003",
                project_key="proj-tp-fp",
                status=CheckStatus.ACTIVE,
                pattern_ref="FP-0003",
                invariant="scope invariant",
                check_type=CheckType.CHANGED_FILE_POLICY,
                pipeline_stage="structural",
                pipeline_layer=1,
                owner="failure-corpus",
                false_positive_risk=FalsePositiveRisk.LOW,
                created_at=datetime.now(UTC),
                approved_at=datetime.now(UTC),
                approved_by="human",
            )
            check_repo.save(proposal)

            now = datetime.now(UTC)
            # 1 TRIGGERED (tp=1) and 4 OVERRIDDEN (fp=4) -> tp>0, so NOT deactivated
            accessor.write_projection(
                ProjectionKind.QA_CHECK_OUTCOMES,
                QACheckOutcomeRecord(
                    project_key="proj-tp-fp",
                    story_id="AG3-TP",
                    run_id="run-tp",
                    attempt_no=1,
                    stage_id="layer1-structural",
                    check_id="changed_file_policy",
                    check_proposal_ref="CHK-0003",
                    outcome=CheckOutcome.TRIGGERED,
                    occurred_at=now,
                ),
            )
            for i in range(4):
                accessor.write_projection(
                    ProjectionKind.QA_CHECK_OUTCOMES,
                    QACheckOutcomeRecord(
                        project_key="proj-tp-fp",
                        story_id=f"AG3-FP-{i:03d}",
                        run_id=f"run-fp-{i}",
                        attempt_no=1,
                        stage_id="layer1-structural",
                        check_id="changed_file_policy",
                        check_proposal_ref="CHK-0003",
                        outcome=CheckOutcome.OVERRIDDEN,
                        occurred_at=now,
                    ),
                )

            tracker = CheckEffectivenessTracker(
                accessor=accessor,
                check_repo=check_repo,
                pattern_repo=pattern_repo,
                project_key="proj-tp-fp",
            )
            report = tracker.report_effectiveness(window_days=90)
            # tp>0 means real finds exist -> NOT deactivated even with fp>3
            assert report.deactivated_count == 0
            updated = check_repo.load("CHK-0003")
            assert updated is not None
            assert updated.status is CheckStatus.ACTIVE
        finally:
            reset_backend_cache_for_tests()

    def test_critical_risk_never_auto_deactivated(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ERROR 7: CRITICAL risk pattern check is NEVER auto-deactivated regardless of tp/fp."""
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from datetime import UTC, datetime

        from agentkit.core_types import CheckStatus, CheckType
        from agentkit.failure_corpus.check_proposal import CheckProposalRecord, FalsePositiveRisk
        from agentkit.failure_corpus.effectiveness import CheckEffectivenessTracker
        from agentkit.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.state_backend.store.fc_check_proposal_repository import (
            StateBackendFcCheckProposalRepository,
        )
        from agentkit.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )
        from agentkit.state_backend.store.projection_repositories import (
            build_projection_repositories,
        )
        from agentkit.telemetry.projection_accessor import ProjectionAccessor, ProjectionKind
        from agentkit.verify_system.stage_registry.records import (
            CheckOutcome,
            QACheckOutcomeRecord,
        )

        reset_backend_cache_for_tests()
        try:
            accessor = ProjectionAccessor(build_projection_repositories(tmp_path))  # type: ignore[arg-type]
            check_repo = StateBackendFcCheckProposalRepository(tmp_path)  # type: ignore[arg-type]
            pattern_repo = StateBackendFcPatternRepository(tmp_path)  # type: ignore[arg-type]

            from agentkit.core_types import FailureCategory, PatternStatus
            from agentkit.failure_corpus.pattern import FailurePatternRecord, PatternRiskLevel, PromotionRule

            # CRITICAL risk level pattern
            parent_pattern = FailurePatternRecord(
                pattern_id="FP-0004",
                project_key="proj-critical",
                status=PatternStatus.ACCEPTED,
                category=FailureCategory.SCOPE_DRIFT,
                promotion_rule=PromotionRule.HIGH_SEVERITY,
                invariant="security MUST NOT be bypassed",
                risk_level=PatternRiskLevel.CRITICAL,
                confirmed_by="human",
                incident_refs=[],
                incident_count=0,
            )
            pattern_repo.save(parent_pattern)

            proposal = CheckProposalRecord(
                check_id="CHK-0004",
                project_key="proj-critical",
                status=CheckStatus.ACTIVE,
                pattern_ref="FP-0004",
                invariant="security invariant",
                check_type=CheckType.CHANGED_FILE_POLICY,
                pipeline_stage="structural",
                pipeline_layer=1,
                owner="failure-corpus",
                false_positive_risk=FalsePositiveRisk.LOW,
                created_at=datetime.now(UTC),
                approved_at=datetime.now(UTC),
                approved_by="human",
            )
            check_repo.save(proposal)

            now = datetime.now(UTC)
            # tp==0 AND fp>3 — normally would deactivate but CRITICAL is exempt
            for i in range(5):
                accessor.write_projection(
                    ProjectionKind.QA_CHECK_OUTCOMES,
                    QACheckOutcomeRecord(
                        project_key="proj-critical",
                        story_id=f"AG3-CRIT-{i:03d}",
                        run_id=f"run-crit-{i}",
                        attempt_no=1,
                        stage_id="layer1-structural",
                        check_id="changed_file_policy",
                        check_proposal_ref="CHK-0004",
                        outcome=CheckOutcome.OVERRIDDEN,
                        occurred_at=now,
                    ),
                )

            tracker = CheckEffectivenessTracker(
                accessor=accessor,
                check_repo=check_repo,
                pattern_repo=pattern_repo,
                project_key="proj-critical",
            )
            report = tracker.report_effectiveness(window_days=90)
            # CRITICAL risk: NEVER auto-deactivated
            assert report.deactivated_count == 0
            updated = check_repo.load("CHK-0004")
            assert updated is not None
            assert updated.status is CheckStatus.ACTIVE
        finally:
            reset_backend_cache_for_tests()

    def test_effectiveness_tracker_finds_checks_beyond_old_fixed_bound(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Effectiveness tracker must find ACTIVE checks with high numeric check_ids.

        Seeds CHK-0250 (beyond old 200-entry scan) and CHK-9999 (beyond old
        9999-entry scan after the band-aid), both ACTIVE.  Asserts that
        report_effectiveness sees both — proving list_for_project is used
        (not a fixed-range scan).
        """
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from datetime import UTC, datetime

        from agentkit.core_types import CheckStatus, CheckType
        from agentkit.failure_corpus.check_proposal import CheckProposalRecord, FalsePositiveRisk
        from agentkit.failure_corpus.effectiveness import CheckEffectivenessTracker
        from agentkit.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.state_backend.store.fc_check_proposal_repository import (
            StateBackendFcCheckProposalRepository,
        )
        from agentkit.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )
        from agentkit.state_backend.store.projection_repositories import (
            build_projection_repositories,
        )
        from agentkit.telemetry.projection_accessor import ProjectionAccessor

        reset_backend_cache_for_tests()
        try:
            accessor = ProjectionAccessor(build_projection_repositories(tmp_path))  # type: ignore[arg-type]
            check_repo = StateBackendFcCheckProposalRepository(tmp_path)  # type: ignore[arg-type]
            pattern_repo = StateBackendFcPatternRepository(tmp_path)  # type: ignore[arg-type]

            from agentkit.core_types import FailureCategory, PatternStatus
            from agentkit.failure_corpus.pattern import (
                FailurePatternRecord,
                PatternRiskLevel,
                PromotionRule,
            )

            parent_pattern = FailurePatternRecord(
                pattern_id="FP-0005",
                project_key="proj-highid",
                status=PatternStatus.ACCEPTED,
                category=FailureCategory.SCOPE_DRIFT,
                promotion_rule=PromotionRule.HIGH_SEVERITY,
                invariant="scope invariant",
                risk_level=PatternRiskLevel.MEDIUM,
                confirmed_by="human",
                incident_refs=[],
                incident_count=0,
            )
            pattern_repo.save(parent_pattern)

            now = datetime.now(UTC)
            for cid in ("CHK-0250", "CHK-9999"):
                check_repo.save(
                    CheckProposalRecord(
                        check_id=cid,
                        project_key="proj-highid",
                        status=CheckStatus.ACTIVE,
                        pattern_ref="FP-0005",
                        invariant="inv",
                        check_type=CheckType.CHANGED_FILE_POLICY,
                        pipeline_stage="structural",
                        pipeline_layer=1,
                        owner="failure-corpus",
                        false_positive_risk=FalsePositiveRisk.LOW,
                        positive_fixtures=[],
                        negative_fixtures=[],
                        created_at=now,
                        approved_at=now,
                        approved_by="human",
                    )
                )

            tracker = CheckEffectivenessTracker(
                accessor=accessor,
                check_repo=check_repo,
                pattern_repo=pattern_repo,
                project_key="proj-highid",
            )
            report = tracker.report_effectiveness(window_days=90)
            # Both CHK-0250 and CHK-9999 must be processed (updated_count == 2)
            assert report.updated_count == 2
        finally:
            reset_backend_cache_for_tests()
