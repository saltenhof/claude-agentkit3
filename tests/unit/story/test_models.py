"""Unit tests for agentkit.story.models."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentkit.core_types import PauseReason
from agentkit.story_context_manager.models import (
    ClosurePayload,
    ClosureProgress,
    MultiRepoClosureState,
    PhaseName,
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.sizing import StorySize
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)


class TestPhaseStatus:
    """Tests for the PhaseStatus enum."""

    def test_all_values(self) -> None:
        assert set(PhaseStatus) == {
            PhaseStatus.PENDING,
            PhaseStatus.IN_PROGRESS,
            PhaseStatus.PAUSED,
            PhaseStatus.COMPLETED,
            PhaseStatus.FAILED,
            PhaseStatus.ESCALATED,
            PhaseStatus.BLOCKED,
        }

    def test_string_values(self) -> None:
        assert PhaseStatus.PENDING.value == "pending"
        assert PhaseStatus.IN_PROGRESS.value == "in_progress"
        assert PhaseStatus.PAUSED.value == "paused"
        assert PhaseStatus.COMPLETED.value == "completed"
        assert PhaseStatus.FAILED.value == "failed"
        assert PhaseStatus.ESCALATED.value == "escalated"
        assert PhaseStatus.BLOCKED.value == "blocked"


class TestPhaseName:
    """Tests for the canonical top-level phase enum."""

    def test_has_exactly_four_values(self) -> None:
        assert tuple(phase.value for phase in PhaseName) == (
            "setup",
            "exploration",
            "implementation",
            "closure",
        )

    def test_verify_is_not_valid_phase_state(self) -> None:
        with pytest.raises(ValidationError):
            PhaseState(
                story_id="AG3-001",
                phase="verify",
                status=PhaseStatus.PENDING,
            )


class TestClosureProgress:
    """Tests for closure checkpoint ordering."""

    def test_has_concept_ordered_fields(self) -> None:
        # FK-29 §29.1.0: EXACTLY six checkpoints (FIX-4). The mode-lock release
        # (FK-24 §24.3.3) is NOT a seventh checkpoint -- its idempotency is the
        # durable per-story acquire marker alone.
        assert tuple(ClosureProgress.model_fields) == (
            "integrity_passed",
            "story_branch_pushed",
            "merge_done",
            "story_closed",
            "metrics_written",
            "postflight_done",
        )

    def test_story_branch_push_requires_integrity_passed(self) -> None:
        with pytest.raises(ValidationError, match="story_branch_pushed"):
            ClosureProgress(story_branch_pushed=True)

    def test_complete_progress_is_valid(self) -> None:
        progress = ClosureProgress(
            integrity_passed=True,
            story_branch_pushed=True,
            merge_done=True,
            story_closed=True,
            metrics_written=True,
            postflight_done=True,
        )

        assert progress.story_branch_pushed is True
        assert progress.story_closed is True


class TestMultiRepoClosureState:
    """Tests for multi-repo closure substates."""

    def test_has_concept_fields_with_empty_defaults(self) -> None:
        state = MultiRepoClosureState()

        assert tuple(MultiRepoClosureState.model_fields) == (
            "pre_merge_check_passed",
            "pushed_repos",
            "merged_repos",
            "rolled_back_repos",
            "failed_repo",
        )
        assert state.pre_merge_check_passed == []
        assert state.pushed_repos == []
        assert state.merged_repos == []
        assert state.rolled_back_repos == []
        assert state.failed_repo is None

    def test_frozen_model(self) -> None:
        state = MultiRepoClosureState(pushed_repos=["api"])

        with pytest.raises(ValidationError):
            state.failed_repo = "worker"  # type: ignore[misc]  # frozen-test by design

    def test_json_serialization_is_deterministic(self) -> None:
        state = MultiRepoClosureState(
            pre_merge_check_passed=["api", "worker"],
            pushed_repos=["api"],
            merged_repos=["api"],
            rolled_back_repos=["worker"],
            failed_repo="worker",
        )

        assert state.model_dump(mode="json") == {
            "pre_merge_check_passed": ["api", "worker"],
            "pushed_repos": ["api"],
            "merged_repos": ["api"],
            "rolled_back_repos": ["worker"],
            "failed_repo": "worker",
        }


class TestClosurePayload:
    """Tests for closure payload multi-repo binding."""

    def test_defaults_to_single_repo_payload(self) -> None:
        payload = ClosurePayload()

        assert payload.progress == ClosureProgress()
        assert payload.multi_repo is None

    def test_multi_repo_is_required_with_multi_repo_context(self) -> None:
        with pytest.raises(ValidationError, match="multi_repo"):
            ClosurePayload.model_validate(
                {},
                context={"participating_repos": ["api", "worker"]},
            )

    def test_multi_repo_context_accepts_explicit_state(self) -> None:
        payload = ClosurePayload.model_validate(
            {"multi_repo": {"pushed_repos": ["api"]}},
            context={"participating_repos": ["api", "worker"]},
        )

        assert payload.multi_repo == MultiRepoClosureState(pushed_repos=["api"])


class TestStoryContext:
    """Tests for the StoryContext model."""

    def test_minimal_creation(self) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXPLORATION,
        )
        assert ctx.story_id == "AG3-001"
        assert ctx.story_type == StoryType.IMPLEMENTATION
        assert ctx.execution_route == StoryMode.EXPLORATION
        assert ctx.implementation_contract == ImplementationContract.STANDARD
        assert ctx.issue_nr is None
        assert ctx.title == ""
        assert ctx.story_size == StorySize.S
        assert ctx.project_root is None
        assert ctx.worktree_path is None
        assert ctx.participating_repos == []
        assert ctx.labels == []
        assert ctx.created_at is None

    def test_full_creation(self) -> None:
        now = datetime.now(tz=UTC)
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-042",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXECUTION,
            implementation_contract=None,
            issue_nr=42,
            title="Fix null pointer in setup phase",
            project_root=Path("/tmp/project"),
            worktree_path=Path("/tmp/worktrees/AG3-042"),
            participating_repos=["saltenhof/claude-agentkit3"],
            labels=["bugfix", "size:small"],
            created_at=now,
        )
        assert ctx.issue_nr == 42
        assert ctx.title == "Fix null pointer in setup phase"
        assert ctx.project_root == Path("/tmp/project")
        assert ctx.worktree_path == Path("/tmp/worktrees/AG3-042")
        assert ctx.participating_repos == ["saltenhof/claude-agentkit3"]
        assert ctx.labels == ["bugfix", "size:small"]
        assert ctx.story_size == StorySize.S
        assert ctx.created_at == now

    def test_implementation_defaults_standard_contract(self) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-051",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )
        assert ctx.implementation_contract == ImplementationContract.STANDARD

    def test_non_implementation_keeps_contract_none(self) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-052",
            story_type=StoryType.CONCEPT,
            execution_route=None,
        )
        assert ctx.implementation_contract is None

    def test_invalid_contract_for_bugfix_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="implementation_contract"):
            StoryContext(
                project_key="test-project",
                story_id="AG3-053",
                story_type=StoryType.BUGFIX,
                execution_route=StoryMode.EXECUTION,
                implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
            )

    def test_invalid_mode_for_concept_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="execution_route"):
            StoryContext(
                project_key="test-project",
                story_id="AG3-054",
                story_type=StoryType.CONCEPT,
                execution_route=StoryMode.EXECUTION,
            )

    def test_execution_route_alias_matches_mode(self) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-055",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXPLORATION,
        )
        assert ctx.execution_route == StoryMode.EXPLORATION
        assert ctx.execution_route == StoryMode.EXPLORATION

    def test_creation_via_execution_route_field(self) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-056",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )
        assert ctx.execution_route == StoryMode.EXECUTION
        assert ctx.execution_route == StoryMode.EXECUTION

    def test_empty_project_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="project_key"):
            StoryContext(
                project_key="",
                story_id="AG3-057",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
            )

    def test_frozen_model(self) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXPLORATION,
        )
        with pytest.raises(ValidationError):
            ctx.story_id = "AG3-002"  # type: ignore[misc]  # frozen-test by design

    def test_requires_story_id(self) -> None:
        with pytest.raises(ValidationError):
            StoryContext(
                project_key="test-project",
                story_type=StoryType.IMPLEMENTATION,  # type: ignore[call-arg]
                execution_route=StoryMode.EXPLORATION,
            )

    def test_requires_story_type(self) -> None:
        with pytest.raises(ValidationError):
            StoryContext(
                project_key="test-project",
                story_id="AG3-001",  # type: ignore[call-arg]
                execution_route=StoryMode.EXPLORATION,
            )

    def test_requires_mode(self) -> None:
        with pytest.raises(ValidationError):
            StoryContext(
                project_key="test-project",
                story_id="AG3-001",
                story_type=StoryType.IMPLEMENTATION,
            )

    def test_serialization_roundtrip(self) -> None:
        now = datetime.now(tz=UTC)
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXPLORATION,
            issue_nr=1,
            title="Test story",
            created_at=now,
        )
        data = ctx.model_dump(mode="json")
        assert data["execution_route"] == StoryMode.EXPLORATION.value
        restored = StoryContext.model_validate(data)
        assert restored.story_id == ctx.story_id
        assert restored.story_type == ctx.story_type
        assert restored.execution_route == ctx.execution_route
        assert restored.story_size == ctx.story_size
        assert restored.execution_route == ctx.execution_route
        assert restored.implementation_contract == ctx.implementation_contract
        assert restored.issue_nr == ctx.issue_nr

    def test_mode_defaults_to_standard(self) -> None:
        """The fast/standard ``mode`` axis defaults to ``standard`` (FK-24 §24.3.3)."""
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )
        assert ctx.mode is WireStoryMode.STANDARD

    def test_mode_is_separate_axis_from_execution_route(self) -> None:
        """``mode=fast`` is NOT conflated into ``execution_route`` (FK-24 §24.3.3).

        A fast run still carries a valid EXECUTION/EXPLORATION execution_route;
        the two axes are independent.
        """
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            mode=WireStoryMode.FAST,
        )
        assert ctx.mode is WireStoryMode.FAST
        # execution_route is untouched by the fast axis.
        assert ctx.execution_route is StoryMode.EXECUTION

    def test_fast_mode_allowed_for_bugfix(self) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-001",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXECUTION,
            mode=WireStoryMode.FAST,
        )
        assert ctx.mode is WireStoryMode.FAST

    @pytest.mark.parametrize("story_type", [StoryType.CONCEPT, StoryType.RESEARCH])
    def test_fast_mode_rejected_for_non_codeproducing(
        self, story_type: StoryType
    ) -> None:
        """FK-24 §24.3.3/§24.3.4: fast is only legal for implementation/bugfix."""
        with pytest.raises(ValidationError, match="mode=fast"):
            StoryContext(
                project_key="test-project",
                story_id="AG3-001",
                story_type=story_type,
                execution_route=None,
                mode=WireStoryMode.FAST,
            )

    def test_mode_serialization_roundtrip(self) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            mode=WireStoryMode.FAST,
        )
        data = ctx.model_dump(mode="json")
        assert data["mode"] == WireStoryMode.FAST.value
        restored = StoryContext.model_validate(data)
        assert restored.mode is WireStoryMode.FAST

    def test_story_size_is_estimated_from_labels_when_missing(self) -> None:
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-058",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            labels=["size:l"],
            title="Implement closure metrics",
        )
        assert ctx.story_size == StorySize.L

    def test_default_lists_are_independent(self) -> None:
        """Verify mutable default lists are not shared between instances."""
        ctx1 = StoryContext(
            project_key="test-project",
            story_id="AG3-001",
            story_type=StoryType.CONCEPT,
            execution_route=None,
        )
        ctx2 = StoryContext(
            project_key="test-project",
            story_id="AG3-002",
            story_type=StoryType.CONCEPT,
            execution_route=None,
        )
        assert ctx1.labels is not ctx2.labels
        assert ctx1.participating_repos is not ctx2.participating_repos


class TestPhaseState:
    """Tests for the PhaseState model."""

    def test_minimal_creation(self) -> None:
        state = PhaseState(
            story_id="AG3-001",
            phase="setup",
            status=PhaseStatus.PENDING,
        )
        assert state.story_id == "AG3-001"
        assert state.phase == "setup"
        assert state.status == PhaseStatus.PENDING
        assert state.paused_reason is None
        assert state.review_round == 0
        assert state.errors == []
        assert state.attempt_id is None

    def test_full_creation(self) -> None:
        state = PhaseState(
            story_id="AG3-001",
            phase="implementation",
            status=PhaseStatus.PAUSED,
            paused_reason=PauseReason.GOVERNANCE_INCIDENT,
            review_round=2,
            errors=["Test coverage below threshold"],
            attempt_id="attempt-abc123",
        )
        assert state.paused_reason == PauseReason.GOVERNANCE_INCIDENT
        assert state.review_round == 2
        assert state.errors == ["Test coverage below threshold"]
        assert state.attempt_id == "attempt-abc123"

    def test_mutable_update(self) -> None:
        """PhaseState is mutable -- status changes during execution."""
        state = PhaseState(
            story_id="AG3-001",
            phase="setup",
            status=PhaseStatus.PENDING,
        )
        state.status = PhaseStatus.IN_PROGRESS
        assert state.status == PhaseStatus.IN_PROGRESS

    def test_serialization_roundtrip(self) -> None:
        state = PhaseState(
            story_id="AG3-001",
            phase="implementation",
            status=PhaseStatus.FAILED,
            errors=["Build failed"],
            review_round=1,
        )
        data = state.model_dump(mode="json")
        restored = PhaseState.model_validate(data)
        assert restored.story_id == state.story_id
        assert restored.phase == state.phase
        assert restored.status == state.status
        assert restored.errors == state.errors

    def test_default_errors_are_independent(self) -> None:
        s1 = PhaseState(story_id="A", phase="setup", status=PhaseStatus.PENDING)
        s2 = PhaseState(story_id="B", phase="closure", status=PhaseStatus.PENDING)
        assert s1.errors is not s2.errors


class TestPhaseSnapshot:
    """Tests for the PhaseSnapshot model."""

    def test_creation(self) -> None:
        now = datetime.now(tz=UTC)
        snap = PhaseSnapshot(
            story_id="AG3-001",
            phase="setup",
            status=PhaseStatus.COMPLETED,
            completed_at=now,
            artifacts=["context.json"],
            evidence={"worktree_created": True},
        )
        assert snap.story_id == "AG3-001"
        assert snap.phase == "setup"
        assert snap.status == PhaseStatus.COMPLETED
        assert snap.completed_at == now
        assert snap.artifacts == ["context.json"]
        assert snap.evidence == {"worktree_created": True}

    def test_frozen_model(self) -> None:
        now = datetime.now(tz=UTC)
        snap = PhaseSnapshot(
            story_id="AG3-001",
            phase="setup",
            status=PhaseStatus.COMPLETED,
            completed_at=now,
        )
        with pytest.raises(ValidationError):
            snap.status = PhaseStatus.FAILED  # type: ignore[misc]  # frozen-test by design

    def test_defaults(self) -> None:
        now = datetime.now(tz=UTC)
        snap = PhaseSnapshot(
            story_id="AG3-001",
            phase="setup",
            status=PhaseStatus.COMPLETED,
            completed_at=now,
        )
        assert snap.artifacts == []
        assert snap.evidence == {}

    def test_serialization_roundtrip(self) -> None:
        now = datetime.now(tz=UTC)
        snap = PhaseSnapshot(
            story_id="AG3-001",
            phase="implementation",
            status=PhaseStatus.COMPLETED,
            completed_at=now,
            artifacts=["semantic_review.json", "guardrail.json"],
            evidence={"qa_passed": True, "layers_completed": 4},
        )
        data = snap.model_dump(mode="json")
        restored = PhaseSnapshot.model_validate(data)
        assert restored.story_id == snap.story_id
        assert restored.artifacts == snap.artifacts
        assert restored.evidence == snap.evidence
