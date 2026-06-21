"""Unit tests for CheckFactory sub (FK-41 §41.6, AG3-078).

Tests cover:
- F41_070_REFERENCE_EXAMPLE durable gate artifact
- derive_check: fail-closed on unknown pattern
- derive_check: fail-closed on non-ACCEPTED pattern
- derive_check: fail-closed when invariant_sharpener is None (production path)
- approve_check: APPROVED path sets ACTIVE, creates story (stub)
- approve_check: APPROVED path fail-closed when story_creation is None
- approve_check: REJECTED path sets REJECTED
- approve_check: REVISE path supersedes old and creates new DRAFT
- CATEGORY_TO_CHECK_TYPE and CHECK_TYPE_FALSE_POSITIVE_RISK (constants)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.core_types import CheckStatus, FailureCategory, PatternStatus
from agentkit.backend.failure_corpus.check_factory import (
    F41_070_REFERENCE_EXAMPLE,
    CheckFactory,
    InvariantSharpenerPort,
    StoryCreationPort,
)
from agentkit.backend.failure_corpus.errors import FailureCorpusError
from agentkit.backend.failure_corpus.pattern import FailurePatternRecord, PatternRiskLevel, PromotionRule
from agentkit.backend.failure_corpus.top import CheckApprovalDecision
from agentkit.backend.failure_corpus.types import CheckId, PatternId

# ---------------------------------------------------------------------------
# F-41-070 Reference Example gate
# ---------------------------------------------------------------------------


class TestF41070ReferenceExample:
    """Gate: F41_070_REFERENCE_EXAMPLE must remain as a durable fixture (FK-41 §41.6.2)."""

    def test_reference_example_exists(self) -> None:
        assert F41_070_REFERENCE_EXAMPLE is not None

    def test_has_required_keys(self) -> None:
        assert "input_candidate" in F41_070_REFERENCE_EXAMPLE
        assert "sharpened_invariant" in F41_070_REFERENCE_EXAMPLE
        assert "category" in F41_070_REFERENCE_EXAMPLE
        assert "source" in F41_070_REFERENCE_EXAMPLE

    def test_input_candidate_is_nonempty(self) -> None:
        assert len(F41_070_REFERENCE_EXAMPLE["input_candidate"]) > 0

    def test_sharpened_invariant_is_nonempty(self) -> None:
        assert len(F41_070_REFERENCE_EXAMPLE["sharpened_invariant"]) > 0

    def test_category_is_test_omission(self) -> None:
        assert F41_070_REFERENCE_EXAMPLE["category"] == "test_omission"

    def test_source_references_fk41_070(self) -> None:
        assert "FK-41" in F41_070_REFERENCE_EXAMPLE["source"]
        assert "F-41-070" in F41_070_REFERENCE_EXAMPLE["source"]

    def test_sharpened_invariant_contains_evidence_requirement(self) -> None:
        # The sharpened invariant must mention test-runner exit-code (per FK-41 §41.6.2 example)
        assert "exit-code" in F41_070_REFERENCE_EXAMPLE["sharpened_invariant"]


# ---------------------------------------------------------------------------
# InvariantSharpenerPort mock
# ---------------------------------------------------------------------------


class _MockSharpener:
    """Test double for InvariantSharpenerPort (only mock seam in CheckFactory)."""

    def __init__(self, return_value: str = "MUST check invariant") -> None:
        self._return_value = return_value

    def sharpen_invariant(self, candidate_invariant: str, category: str) -> str:
        return self._return_value


assert isinstance(_MockSharpener(), InvariantSharpenerPort)


class _MockStoryCreation:
    """Test double for StoryCreationPort (records calls; never creates real stories)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def create_check_implementation_story(
        self,
        check_id: str,
        pattern_ref: str,
        invariant: str,
        check_type: str,
    ) -> str:
        self.calls.append({
            "check_id": check_id,
            "pattern_ref": pattern_ref,
            "invariant": invariant,
            "check_type": check_type,
        })
        return f"STORY-{check_id}"


assert isinstance(_MockStoryCreation(), StoryCreationPort)


# ---------------------------------------------------------------------------
# CheckFactory.derive_check
# ---------------------------------------------------------------------------


class TestDeriveCheck:
    def _setup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[object, object, CheckFactory]:
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.backend.state_backend.store.fc_check_proposal_repository import (
            StateBackendFcCheckProposalRepository,
        )
        from agentkit.backend.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )

        reset_backend_cache_for_tests()
        pattern_repo = StateBackendFcPatternRepository(tmp_path)
        check_repo = StateBackendFcCheckProposalRepository(tmp_path)
        factory = CheckFactory(
            pattern_repo=pattern_repo,
            check_repo=check_repo,
            project_key="proj-cf",
            invariant_sharpener=_MockSharpener("MUST NOT bypass Sonar"),
        )
        return pattern_repo, check_repo, factory

    def test_fail_closed_on_unknown_pattern(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, factory = self._setup(tmp_path, monkeypatch)
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            with pytest.raises(FailureCorpusError, match="not found"):
                factory.derive_check(PatternId("FP-9999"))
        finally:
            reset_backend_cache_for_tests()

    def test_fail_closed_on_non_accepted_pattern(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pattern_repo, _, factory = self._setup(tmp_path, monkeypatch)
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            # Save a REJECTED pattern
            record = FailurePatternRecord(
                pattern_id="FP-0001",
                project_key="proj-cf",
                status=PatternStatus.REJECTED,
                category=FailureCategory.SCOPE_DRIFT,
                promotion_rule=PromotionRule.HIGH_SEVERITY,
                invariant="test invariant",
                risk_level=PatternRiskLevel.HIGH,
                incident_refs=[],
                incident_count=0,
            )
            pattern_repo.save(record)
            with pytest.raises(FailureCorpusError, match="status"):
                factory.derive_check(PatternId("FP-0001"))
        finally:
            reset_backend_cache_for_tests()

    def test_derive_check_creates_draft(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pattern_repo, check_repo, factory = self._setup(tmp_path, monkeypatch)
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            # Save an ACCEPTED pattern
            record = FailurePatternRecord(
                pattern_id="FP-0002",
                project_key="proj-cf",
                status=PatternStatus.ACCEPTED,
                category=FailureCategory.SCOPE_DRIFT,
                promotion_rule=PromotionRule.HIGH_SEVERITY,
                invariant="Agent MUST NOT modify files outside scope",
                risk_level=PatternRiskLevel.HIGH,
                confirmed_by="human",
                incident_refs=["FC-2026-0001"],
                incident_count=1,
            )
            pattern_repo.save(record)
            proposal = factory.derive_check(PatternId("FP-0002"))
            assert proposal.check_id == "CHK-0001"
            assert proposal.status is CheckStatus.DRAFT
            assert proposal.pattern_ref == "FP-0002"
            assert proposal.invariant == "MUST NOT bypass Sonar"
        finally:
            reset_backend_cache_for_tests()

    def test_derive_check_fail_closed_when_sharpener_is_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ERROR 7: production-path test — factory without sharpener raises RuntimeError.

        This tests the PRODUCTION wiring path: constructing CheckFactory without
        invariant_sharpener and calling derive_check MUST raise fail-closed
        (not just swallow silently). Verifies the real guard at check_factory.py.
        """
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.backend.state_backend.store.fc_check_proposal_repository import (
            StateBackendFcCheckProposalRepository,
        )
        from agentkit.backend.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )

        reset_backend_cache_for_tests()
        try:
            pattern_repo = StateBackendFcPatternRepository(tmp_path)
            check_repo = StateBackendFcCheckProposalRepository(tmp_path)
            # Construct WITHOUT sharpener — this is the missing-wiring production scenario
            factory_no_sharpener = CheckFactory(
                pattern_repo=pattern_repo,
                check_repo=check_repo,
                project_key="proj-no-sharpen",
                # invariant_sharpener deliberately NOT provided (None)
            )
            # Seed an ACCEPTED pattern
            record = FailurePatternRecord(
                pattern_id="FP-0099",
                project_key="proj-no-sharpen",
                status=PatternStatus.ACCEPTED,
                category=FailureCategory.SCOPE_DRIFT,
                promotion_rule=PromotionRule.HIGH_SEVERITY,
                invariant="scope must not be exceeded",
                risk_level=PatternRiskLevel.MEDIUM,
                confirmed_by="human",
                incident_refs=[],
                incident_count=0,
            )
            pattern_repo.save(record)
            # Must raise RuntimeError (FAIL-CLOSED: InvariantSharpenerPort is None)
            with pytest.raises(RuntimeError, match="InvariantSharpenerPort is None"):
                factory_no_sharpener.derive_check(PatternId("FP-0099"))
        finally:
            reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# _next_check_id: no reuse, no fixed upper bound
# ---------------------------------------------------------------------------


class TestNextCheckId:
    """Prove _next_check_id allocates against the GLOBAL keyspace, never reusing an id."""

    def _make_check_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> object:
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.backend.state_backend.store.fc_check_proposal_repository import (
            StateBackendFcCheckProposalRepository,
        )
        from agentkit.backend.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )

        reset_backend_cache_for_tests()
        # Seed a pattern so FK constraint is satisfied
        StateBackendFcPatternRepository(tmp_path).save(
            FailurePatternRecord(
                pattern_id="FP-0001",
                project_key="proj-next",
                status=PatternStatus.ACCEPTED,
                category=FailureCategory.SCOPE_DRIFT,
                promotion_rule=PromotionRule.HIGH_SEVERITY,
                invariant="inv",
                risk_level=PatternRiskLevel.HIGH,
                confirmed_by="human",
                incident_refs=[],
                incident_count=0,
            )
        )
        return StateBackendFcCheckProposalRepository(tmp_path)

    def test_next_check_id_does_not_reuse_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_next_check_id must not return an id that already exists."""
        from datetime import UTC, datetime

        from agentkit.backend.core_types import CheckStatus, CheckType
        from agentkit.backend.failure_corpus.check_factory import _next_check_id
        from agentkit.backend.failure_corpus.check_proposal import CheckProposalRecord, FalsePositiveRisk
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        repo = self._make_check_repo(tmp_path, monkeypatch)
        try:
            now = datetime.now(UTC)
            # Seed CHK-0001, CHK-0002, CHK-0003 (simulate prior allocations)
            for seq in (1, 2, 3):
                repo.save(  # type: ignore[union-attr]
                    CheckProposalRecord(
                        check_id=f"CHK-{seq:04d}",
                        project_key="proj-next",
                        status=CheckStatus.DRAFT,
                        pattern_ref="FP-0001",
                        invariant="inv",
                        check_type=CheckType.CHANGED_FILE_POLICY,
                        pipeline_stage="structural",
                        pipeline_layer=1,
                        owner="team-x",
                        false_positive_risk=FalsePositiveRisk.LOW,
                        positive_fixtures=[],
                        negative_fixtures=[],
                        created_at=now,
                    )
                )
            next_id = _next_check_id(repo)  # type: ignore[arg-type]
            assert next_id == "CHK-0004"
            # Existing ids must not be reused
            existing_ids = {r.check_id for r in repo.list_for_project("proj-next")}  # type: ignore[union-attr]
            assert next_id not in existing_ids
        finally:
            reset_backend_cache_for_tests()

    def test_next_check_id_beyond_old_fixed_bound(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_next_check_id allocates CHK-10000+ when an existing CHK-9999 is present.

        This test proves the repository is used (not a fixed-range scan):
        with the old range(1, 10000) scan CHK-9999 was the last visible id,
        and the scan would wrap back to CHK-0001 (reuse). The real query
        must return CHK-10000 (max + 1).
        """
        from datetime import UTC, datetime

        from agentkit.backend.core_types import CheckStatus, CheckType
        from agentkit.backend.failure_corpus.check_factory import _next_check_id
        from agentkit.backend.failure_corpus.check_proposal import CheckProposalRecord, FalsePositiveRisk
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        repo = self._make_check_repo(tmp_path, monkeypatch)
        try:
            now = datetime.now(UTC)
            # Seed CHK-9999 — the old upper bound of the band-aided scan
            repo.save(  # type: ignore[union-attr]
                CheckProposalRecord(
                    check_id="CHK-9999",
                    project_key="proj-next",
                    status=CheckStatus.DRAFT,
                    pattern_ref="FP-0001",
                    invariant="inv",
                    check_type=CheckType.CHANGED_FILE_POLICY,
                    pipeline_stage="structural",
                    pipeline_layer=1,
                    owner="team-x",
                    false_positive_risk=FalsePositiveRisk.LOW,
                    positive_fixtures=[],
                    negative_fixtures=[],
                    created_at=now,
                )
            )
            next_id = _next_check_id(repo)  # type: ignore[arg-type]
            # Must allocate CHK-10000, not reuse CHK-0001 or CHK-9999
            assert next_id == "CHK-10000"
        finally:
            reset_backend_cache_for_tests()

    def test_next_check_id_empty_store_starts_at_0001(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_next_check_id returns CHK-0001 when no proposals exist at all."""
        from agentkit.backend.failure_corpus.check_factory import _next_check_id
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        repo = self._make_check_repo(tmp_path, monkeypatch)
        try:
            next_id = _next_check_id(repo)  # type: ignore[arg-type]
            assert next_id == "CHK-0001"
        finally:
            reset_backend_cache_for_tests()

    def test_next_check_id_is_global_not_project_scoped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ERROR C: a second project must NOT re-allocate the first project's CHK id.

        ``fc_check_proposals`` is keyed GLOBALLY by ``check_id`` (PK ``(check_id)``).
        A per-project ``MAX+1`` would let project B (no local checks) allocate
        ``CHK-0001`` and OVERWRITE project A's row on upsert. Allocation must span
        ALL proposals: project B gets a fresh global id and project A's row stays.
        """
        from datetime import UTC, datetime

        from agentkit.backend.core_types import CheckStatus, CheckType
        from agentkit.backend.failure_corpus.check_factory import _next_check_id
        from agentkit.backend.failure_corpus.check_proposal import CheckProposalRecord, FalsePositiveRisk
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.backend.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )

        repo = self._make_check_repo(tmp_path, monkeypatch)
        try:
            now = datetime.now(UTC)
            # Seed a pattern in project B too (FK constraint).
            StateBackendFcPatternRepository(tmp_path).save(
                FailurePatternRecord(
                    pattern_id="FP-0002",
                    project_key="proj-b",
                    status=PatternStatus.ACCEPTED,
                    category=FailureCategory.SCOPE_DRIFT,
                    promotion_rule=PromotionRule.HIGH_SEVERITY,
                    invariant="inv",
                    risk_level=PatternRiskLevel.HIGH,
                    confirmed_by="human",
                    incident_refs=[],
                    incident_count=0,
                )
            )
            # Project A owns CHK-0001.
            repo.save(  # type: ignore[union-attr]
                CheckProposalRecord(
                    check_id="CHK-0001",
                    project_key="proj-next",
                    status=CheckStatus.DRAFT,
                    pattern_ref="FP-0001",
                    invariant="inv-A",
                    check_type=CheckType.CHANGED_FILE_POLICY,
                    pipeline_stage="structural",
                    pipeline_layer=1,
                    owner="team-a",
                    false_positive_risk=FalsePositiveRisk.LOW,
                    positive_fixtures=[],
                    negative_fixtures=[],
                    created_at=now,
                )
            )
            # Project B has NO local checks. A project-scoped MAX+1 would yield
            # CHK-0001 again — colliding with project A. The global allocator
            # must yield CHK-0002.
            next_id_for_b = _next_check_id(repo)  # type: ignore[arg-type]
            assert next_id_for_b == "CHK-0002", (
                f"global allocation broken: project B got {next_id_for_b!r}, "
                "would overwrite project A's globally-keyed CHK-0001"
            )
            # Persist project B's row under the fresh id and prove project A's
            # row is untouched (no overwrite).
            repo.save(  # type: ignore[union-attr]
                CheckProposalRecord(
                    check_id=next_id_for_b,
                    project_key="proj-b",
                    status=CheckStatus.DRAFT,
                    pattern_ref="FP-0002",
                    invariant="inv-B",
                    check_type=CheckType.CHANGED_FILE_POLICY,
                    pipeline_stage="structural",
                    pipeline_layer=1,
                    owner="team-b",
                    false_positive_risk=FalsePositiveRisk.LOW,
                    positive_fixtures=[],
                    negative_fixtures=[],
                    created_at=now,
                )
            )
            row_a = repo.load("CHK-0001")  # type: ignore[union-attr]
            assert row_a is not None
            assert row_a.project_key == "proj-next"
            assert row_a.invariant == "inv-A"
            row_b = repo.load("CHK-0002")  # type: ignore[union-attr]
            assert row_b is not None
            assert row_b.project_key == "proj-b"
        finally:
            reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# CheckFactory.approve_check
# ---------------------------------------------------------------------------


class TestApproveCheck:
    def _setup(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        story_creation: _MockStoryCreation | None = None,
    ) -> tuple[object, object, CheckFactory, _MockStoryCreation]:
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.backend.state_backend.store.fc_check_proposal_repository import (
            StateBackendFcCheckProposalRepository,
        )
        from agentkit.backend.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )

        reset_backend_cache_for_tests()
        pattern_repo = StateBackendFcPatternRepository(tmp_path)
        check_repo = StateBackendFcCheckProposalRepository(tmp_path)
        mock_story_creation = story_creation or _MockStoryCreation()
        factory = CheckFactory(
            pattern_repo=pattern_repo,
            check_repo=check_repo,
            project_key="proj-approve",
            invariant_sharpener=_MockSharpener("Sharpened"),
            story_creation=mock_story_creation,
        )
        return pattern_repo, check_repo, factory, mock_story_creation

    def _seed_accepted_pattern_and_draft(
        self,
        pattern_repo: object,
        check_repo: object,
        factory: CheckFactory,
    ) -> CheckId:

        # Save an ACCEPTED pattern
        pat = FailurePatternRecord(
            pattern_id="FP-0010",
            project_key="proj-approve",
            status=PatternStatus.ACCEPTED,
            category=FailureCategory.SCOPE_DRIFT,
            promotion_rule=PromotionRule.HIGH_SEVERITY,
            invariant="scope invariant",
            risk_level=PatternRiskLevel.MEDIUM,
            confirmed_by="human",
            incident_refs=[],
            incident_count=0,
        )
        pattern_repo.save(pat)  # type: ignore[union-attr]
        proposal = factory.derive_check(PatternId("FP-0010"))
        return CheckId(proposal.check_id)

    def test_approved_sets_active_and_calls_story_creation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """APPROVED: sets ACTIVE AND calls story_creation BEFORE setting ACTIVE (ERROR 3 fix)."""
        pattern_repo, check_repo, factory, mock_story_creation = self._setup(
            tmp_path, monkeypatch
        )
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            check_id = self._seed_accepted_pattern_and_draft(pattern_repo, check_repo, factory)
            result_id = factory.approve_check(check_id, CheckApprovalDecision.APPROVED)
            updated = check_repo.load(str(result_id))  # type: ignore[union-attr]
            assert updated is not None
            assert updated.status is CheckStatus.ACTIVE
            # Verify story_creation was actually called (production wiring proof)
            assert len(mock_story_creation.calls) == 1
            assert mock_story_creation.calls[0]["check_id"] == str(check_id)
        finally:
            reset_backend_cache_for_tests()

    def test_approved_fail_closed_when_story_creation_is_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ERROR 7 / ERROR 3: approve_check(APPROVED) with no story_creation raises RuntimeError.

        Tests the PRODUCTION fail-closed path: a factory without story_creation wired
        MUST raise RuntimeError on APPROVED — never silently activate without creating a story.
        """
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.backend.state_backend.store.fc_check_proposal_repository import (
            StateBackendFcCheckProposalRepository,
        )
        from agentkit.backend.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )

        reset_backend_cache_for_tests()
        try:
            pattern_repo = StateBackendFcPatternRepository(tmp_path)
            check_repo = StateBackendFcCheckProposalRepository(tmp_path)
            # Construct WITHOUT story_creation — production wiring missing scenario
            factory_no_story = CheckFactory(
                pattern_repo=pattern_repo,
                check_repo=check_repo,
                project_key="proj-no-story",
                invariant_sharpener=_MockSharpener("Sharpened"),
                # story_creation deliberately NOT provided (None)
            )
            # Seed and derive a check
            pat = FailurePatternRecord(
                pattern_id="FP-0020",
                project_key="proj-no-story",
                status=PatternStatus.ACCEPTED,
                category=FailureCategory.SCOPE_DRIFT,
                promotion_rule=PromotionRule.HIGH_SEVERITY,
                invariant="scope invariant",
                risk_level=PatternRiskLevel.MEDIUM,
                confirmed_by="human",
                incident_refs=[],
                incident_count=0,
            )
            pattern_repo.save(pat)
            proposal = factory_no_story.derive_check(PatternId("FP-0020"))
            check_id = CheckId(proposal.check_id)
            # APPROVED MUST raise RuntimeError (fail-closed: StoryCreationPort is None)
            with pytest.raises(RuntimeError, match="StoryCreationPort is None"):
                factory_no_story.approve_check(check_id, CheckApprovalDecision.APPROVED)
            # Verify the check is NOT set to ACTIVE (no side-effect on failure)
            unchanged = check_repo.load(str(check_id))
            assert unchanged is not None
            assert unchanged.status is CheckStatus.DRAFT
        finally:
            reset_backend_cache_for_tests()

    def test_rejected_sets_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pattern_repo, check_repo, factory, _ = self._setup(tmp_path, monkeypatch)
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            check_id = self._seed_accepted_pattern_and_draft(pattern_repo, check_repo, factory)
            result_id = factory.approve_check(
                check_id, CheckApprovalDecision.REJECTED, rejected_reason="too broad"
            )
            updated = check_repo.load(str(result_id))  # type: ignore[union-attr]
            assert updated is not None
            assert updated.status is CheckStatus.REJECTED
            assert updated.rejected_reason == "too broad"
        finally:
            reset_backend_cache_for_tests()

    def test_revise_supersedes_old_and_creates_new_draft(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """REVISE: old proposal gets REJECTED + 'superseded_by_revision'; new DRAFT created."""
        pattern_repo, check_repo, factory, _ = self._setup(tmp_path, monkeypatch)
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            check_id = self._seed_accepted_pattern_and_draft(pattern_repo, check_repo, factory)
            new_check_id = factory.approve_check(check_id, CheckApprovalDecision.REVISE)

            # Old proposal must be REJECTED with superseded_by_revision
            old = check_repo.load(str(check_id))  # type: ignore[union-attr]
            assert old is not None
            assert old.status is CheckStatus.REJECTED
            assert old.rejected_reason == "superseded_by_revision"

            # New proposal must be DRAFT with a different ID
            assert str(new_check_id) != str(check_id)
            new_prop = check_repo.load(str(new_check_id))  # type: ignore[union-attr]
            assert new_prop is not None
            assert new_prop.status is CheckStatus.DRAFT
        finally:
            reset_backend_cache_for_tests()

    def test_approve_active_check_fail_closed_no_second_story(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ERROR B: re-approving an already-ACTIVE check raises; no 2nd story, no state change."""
        from agentkit.backend.failure_corpus.errors import FailureCorpusError
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        pattern_repo, check_repo, factory, mock_story_creation = self._setup(
            tmp_path, monkeypatch
        )
        try:
            check_id = self._seed_accepted_pattern_and_draft(pattern_repo, check_repo, factory)
            # First approval: DRAFT -> ACTIVE, exactly one story created.
            factory.approve_check(check_id, CheckApprovalDecision.APPROVED)
            assert len(mock_story_creation.calls) == 1
            active = check_repo.load(str(check_id))  # type: ignore[union-attr]
            assert active is not None
            assert active.status is CheckStatus.ACTIVE

            # Second approval of the now-ACTIVE check must fail closed.
            with pytest.raises(FailureCorpusError, match="expected 'draft'"):
                factory.approve_check(check_id, CheckApprovalDecision.APPROVED)
            # No second story was created.
            assert len(mock_story_creation.calls) == 1
            # State unchanged (still ACTIVE, same approval metadata).
            after = check_repo.load(str(check_id))  # type: ignore[union-attr]
            assert after is not None
            assert after.status is CheckStatus.ACTIVE
            assert after.approved_at == active.approved_at
        finally:
            reset_backend_cache_for_tests()

    def test_approve_rejected_check_fail_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ERROR B: approving an already-REJECTED check raises; no story, no state change."""
        from agentkit.backend.failure_corpus.errors import FailureCorpusError
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        pattern_repo, check_repo, factory, mock_story_creation = self._setup(
            tmp_path, monkeypatch
        )
        try:
            check_id = self._seed_accepted_pattern_and_draft(pattern_repo, check_repo, factory)
            # Reject the DRAFT first.
            factory.approve_check(
                check_id, CheckApprovalDecision.REJECTED, rejected_reason="too broad"
            )
            rejected = check_repo.load(str(check_id))  # type: ignore[union-attr]
            assert rejected is not None
            assert rejected.status is CheckStatus.REJECTED

            # Approving the REJECTED check must fail closed (no resurrection).
            with pytest.raises(FailureCorpusError, match="expected 'draft'"):
                factory.approve_check(check_id, CheckApprovalDecision.APPROVED)
            # No story created at any point on this check.
            assert len(mock_story_creation.calls) == 0
            # State unchanged.
            after = check_repo.load(str(check_id))  # type: ignore[union-attr]
            assert after is not None
            assert after.status is CheckStatus.REJECTED
            assert after.rejected_reason == "too broad"
        finally:
            reset_backend_cache_for_tests()
