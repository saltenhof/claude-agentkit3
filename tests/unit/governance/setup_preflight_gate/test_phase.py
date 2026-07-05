"""Unit tests for SetupPhaseHandler.

Mocks only the external system boundaries:
  - run_preflight  (StoryService-based, mocked)
  - build_story_context  (AK3 Story-Service record read)
  - the edge-provisioning coordinator (AG3-145: edge-commissioned worktrees)

AG3-031 Pass-4 Fix E9: save_story_context is no longer a module-level name.
Tests use a _RecordingContextRepo test-double for the persist-failure path.
AG3-145 sub-step C: the backend worktree-git path is removed; worktree
provisioning is edge-commissioned via the ``EdgeProvisioningCoordinator`` port
(``preflight_probe`` / ``provision_worktree`` commands) with a fail-closed PAUSE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from tests.phase_state_factory import make_phase_state

from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.backend.core_types import PauseReason
from agentkit.backend.governance.setup_preflight_gate.edge_provisioning import (
    ProbeOutcome,
    ProvisioningOutcome,
)
from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig, SetupPhaseHandler
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import (
    AreBundleStatus,
    PhaseState,
    PhaseStatus,
    SetupPayload,
)
from agentkit.backend.requirements_coverage.contract import (
    AreDockpointStatus,
    ContextLoadResult,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import WireStoryType
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

#: AG3-056: code-producing projects must declare the ci stanza explicitly.
_OPT_OUT_CI = JenkinsConfig(available=False, enabled=False)
_ACTIVE_CI = JenkinsConfig(
    available=True,
    enabled=True,
    base_url="http://jenkins:9900",
    token_env="JENKINS_TOKEN",
    pipeline="ak3-premerge",
)


# ---------------------------------------------------------------------------
# Recording test-double for SetupContextRepository (Fix E9)
# ---------------------------------------------------------------------------


class _RecordingContextRepo:
    """Recording test-double for SetupContextRepository.

    Configurable: ``_raises_on_call`` controls whether ``save`` raises an
    exception on the N-th call.
    """

    def __init__(self, raises_on_call: int | None = None, exc: Exception | None = None) -> None:
        self.calls: list[tuple[object, object]] = []
        self._raises_on_call = raises_on_call
        self._exc = exc or OSError("disk full")

    def save(self, story_dir: Path, ctx: StoryContext) -> None:
        call_no = len(self.calls) + 1
        self.calls.append((story_dir, ctx))
        if self._raises_on_call is not None and call_no == self._raises_on_call:
            raise self._exc


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_preflight_pass() -> object:
    """Return a fake PreflightResult that passes all checks."""

    class _Result:
        passed = True
        checks: list[object] = []

    return _Result()


def _make_preflight_fail(message: str = "issue not open") -> object:
    """Return a fake PreflightResult that fails (AG3-034 model)."""
    from agentkit.backend.governance.setup_preflight_gate.preflight import (
        PreflightCheckId,
        PreflightCheckResult,
        PreflightResult,
        PreflightStatus,
    )

    failing = PreflightCheckResult(
        check_id=PreflightCheckId.STORY_EXISTS,
        status=PreflightStatus.FAIL,
        detail=message,
        cleanup_hint="resolve the precondition before restarting",
    )
    return PreflightResult(
        overall=PreflightStatus.FAIL,
        checks=(failing,),
        failed_check_ids=(PreflightCheckId.STORY_EXISTS,),
    )


def _make_story_context(
    story_id: str = "AG3-001",
    story_type: StoryType = StoryType.IMPLEMENTATION,
    project_root: Path | None = None,
    project_key: str = "test-project",
) -> StoryContext:
    """Build a minimal StoryContext for testing."""
    mode: StoryMode | None = (
        StoryMode.EXPLORATION
        if story_type == StoryType.IMPLEMENTATION
        else None
    )
    return StoryContext(
        project_key=project_key,
        story_id=story_id,
        story_type=story_type,
        execution_route=mode,
        title="Test Story",
        project_root=project_root,
        participating_repos=["repo"],
    )


def _make_phase_state(story_id: str = "AG3-001") -> PhaseState:
    return make_phase_state(
        story_id=story_id,
        phase="setup",
        status=PhaseStatus.IN_PROGRESS,
    )


def _make_project_config(repo_path: Path) -> ProjectConfig:
    return ProjectConfig(
        project_key="test-project",
        project_name="Test Project",
        repositories=[RepositoryConfig(name="repo", path=repo_path)],
        # AG3-052 E6 / AG3-056: code-producing default story_types => declare
        # the sonarqube + ci stanzas explicitly.
        pipeline=PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=_OPT_OUT_CI,
        ),
    )


# ---------------------------------------------------------------------------
# Helpers (continued)
# ---------------------------------------------------------------------------


class _NoOpStoryService:
    """No-op stub for tests that don't test begin_progress; resolves a repo.

    ``get_story`` returns a minimal AUTHORITATIVE story record carrying
    ``story_type`` + ``participating_repos`` so the setup phase can derive the
    edge-provisioning plan from the authoritative record (AG3-145
    ``_resolve_worktree_plan``, Codex r1 fail-open fix) -- NOT from the sparse
    incoming context. ``story_type`` defaults to IMPLEMENTATION (a worktree
    story); pass ``WireStoryType.CONCEPT`` for a genuinely non-worktree story.
    """

    def __init__(
        self,
        repos: tuple[str, ...] = ("repo",),
        story_type: WireStoryType = WireStoryType.IMPLEMENTATION,
    ) -> None:
        self._repos = list(repos)
        self._story_type = story_type

    def begin_progress(self, story_id: str, *, correlation_id: str = "") -> object:
        return object()

    def get_story(self, story_display_id: str) -> object:
        del story_display_id
        repos = self._repos
        wire_type = self._story_type

        class _Story:
            participating_repos = repos
            story_type = wire_type

        return _Story()


class _FakeEdgeCoordinator:
    """Test-double :class:`EdgeProvisioningCoordinator` (AG3-145 sub-step C).

    Records commission calls and returns scripted probe/provision outcomes so the
    staged setup flow (probe PAUSE -> preflight -> provision PAUSE -> populate) can
    be driven without a real Postgres command queue or an edge process.
    """

    def __init__(
        self,
        *,
        probe: ProbeOutcome | None = None,
        provision: ProvisioningOutcome | None = None,
        on_provision: object | None = None,
        teardown_error: Exception | None = None,
    ) -> None:
        self._probe = probe or ProbeOutcome(pending=False, evidence={}, ownership=None)
        self._provision = provision or ProvisioningOutcome(pending=False)
        self._on_provision = on_provision
        self._teardown_error = teardown_error
        self.probe_calls = 0
        self.provision_calls = 0
        #: AG3-145 D: records the repos passed to each ``ensure_teardown`` call
        #: (the setup-failure cleanup path).
        self.teardown_calls: list[tuple[str, ...]] = []

    def ensure_preflight_probes(
        self, *, project_key: str, story_id: str, run_id: str,
        repos: tuple[str, ...], branch: str,
    ) -> ProbeOutcome:
        del project_key, story_id, run_id, repos, branch
        self.probe_calls += 1
        return self._probe

    def ensure_provisioning(
        self, *, project_key: str, story_id: str, run_id: str,
        repos: tuple[str, ...], branch: str, base_ref: str,
    ) -> ProvisioningOutcome:
        del project_key, story_id, run_id, repos, branch, base_ref
        self.provision_calls += 1
        if callable(self._on_provision):
            self._on_provision()
        return self._provision

    def ensure_teardown(
        self, *, project_key: str, story_id: str, run_id: str,
        repos: tuple[str, ...], branch: str,
    ) -> None:
        del project_key, story_id, run_id, branch
        self.teardown_calls.append(repos)
        if self._teardown_error is not None:
            raise self._teardown_error


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSetupPhaseHandlerWorktree:
    """Tests for edge-commissioned worktree provisioning in on_enter (AG3-145)."""

    def test_worktree_map_populated_from_edge_report(
        self, tmp_path: Path
    ) -> None:
        """on_enter populates worktree_map from the edge worktree_report."""
        coordinator = _FakeEdgeCoordinator(
            provision=ProvisioningOutcome(
                pending=False,
                worktree_map={"repo": tmp_path / "worktrees" / "AG3-001"},
            ),
        )
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=True,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_RecordingContextRepo(),  # type: ignore[arg-type]
            edge_provisioning_coordinator=coordinator,
        )
        ctx = _make_story_context(project_root=tmp_path)
        state = _make_phase_state()
        enriched = _make_story_context(project_root=tmp_path)

        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status == PhaseStatus.COMPLETED
        assert coordinator.probe_calls == 1
        assert coordinator.provision_calls == 1
        assert result.updated_context is not None
        # The path is the EDGE-REPORTED one -- the backend derived none.
        assert result.updated_context.worktree_map == {
            "repo": tmp_path / "worktrees" / "AG3-001",
        }

    def test_probe_pending_pauses_fail_closed(self, tmp_path: Path) -> None:
        """A not-yet-reported probe PAUSES with AWAITING_EDGE_PROVISIONING."""
        coordinator = _FakeEdgeCoordinator(probe=ProbeOutcome(pending=True))
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=True,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_RecordingContextRepo(),  # type: ignore[arg-type]
            edge_provisioning_coordinator=coordinator,
        )
        result = handler.on_enter(
            _make_story_context(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_phase_state()),
        )
        assert result.status is PhaseStatus.PAUSED
        assert result.yield_status == PauseReason.AWAITING_EDGE_PROVISIONING.value
        # Fail-closed: no provisioning is commissioned before the probe decides.
        assert coordinator.provision_calls == 0

    def test_provision_pending_pauses_fail_closed(self, tmp_path: Path) -> None:
        """A reported probe but a not-yet-reported worktree PAUSES fail-closed."""
        coordinator = _FakeEdgeCoordinator(
            provision=ProvisioningOutcome(pending=True),
        )
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=True,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_RecordingContextRepo(),  # type: ignore[arg-type]
            edge_provisioning_coordinator=coordinator,
        )
        enriched = _make_story_context(project_root=tmp_path)
        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
        ):
            result = handler.on_enter(
                _make_story_context(project_root=tmp_path),
                PhaseEnvelopeStore.make_fresh_envelope(_make_phase_state()),
            )
        assert result.status is PhaseStatus.PAUSED
        assert result.yield_status == PauseReason.AWAITING_EDGE_PROVISIONING.value

    def test_provision_failure_commissions_teardown(self, tmp_path: Path) -> None:
        """AG3-145 D (AC7): a provisioning FAILURE commissions teardown cleanup.

        A setup that failed after the edge already provisioned another repo must
        not silently leak a worktree (the C->D teardown gap). ``on_enter`` returns
        FAILED and commissions one ``teardown_worktree`` per participating repo.
        """
        coordinator = _FakeEdgeCoordinator(
            provision=ProvisioningOutcome(pending=False, failed_repos=("repo",)),
        )
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=True,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_RecordingContextRepo(),  # type: ignore[arg-type]
            edge_provisioning_coordinator=coordinator,
        )
        enriched = _make_story_context(project_root=tmp_path)
        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
        ):
            result = handler.on_enter(
                _make_story_context(project_root=tmp_path),
                PhaseEnvelopeStore.make_fresh_envelope(_make_phase_state()),
            )
        assert result.status is PhaseStatus.FAILED
        assert "edge_provisioning_failed" in result.errors[0]
        # The teardown cleanup was commissioned for the participating repo.
        assert coordinator.teardown_calls == [("repo",)]

    def test_teardown_commission_failure_is_surfaced_not_silent(
        self, tmp_path: Path
    ) -> None:
        """AG3-145 D (AC7): a teardown-commission failure is SURFACED, not swallowed.

        When commissioning the setup-failure teardown itself fails (an edge/DB
        error), the FAILED result must carry an ADDITIONAL, auditable cleanup
        error -- never end silent (a swallowed cleanup failure is an ignored
        finding = ZERO DEBT / SEVERITY-SEMANTIK breach). The original setup
        failure is preserved as the first error.
        """
        coordinator = _FakeEdgeCoordinator(
            provision=ProvisioningOutcome(pending=False, failed_repos=("repo",)),
            teardown_error=RuntimeError("edge command queue insert failed"),
        )
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=True,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_RecordingContextRepo(),  # type: ignore[arg-type]
            edge_provisioning_coordinator=coordinator,
        )
        enriched = _make_story_context(project_root=tmp_path)
        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
        ):
            result = handler.on_enter(
                _make_story_context(project_root=tmp_path),
                PhaseEnvelopeStore.make_fresh_envelope(_make_phase_state()),
            )
        assert result.status is PhaseStatus.FAILED
        assert coordinator.teardown_calls == [("repo",)]
        # The teardown-commission failure is surfaced as an auditable error.
        assert any(
            "worktree_teardown_cleanup_failed" in e for e in result.errors
        ), result.errors
        # The original setup failure is preserved as the first error.
        assert "edge_provisioning_failed" in result.errors[0]

    def test_worktree_story_without_coordinator_fails_closed(
        self, tmp_path: Path
    ) -> None:
        """A worktree story with NO wired coordinator fails closed (no fallback)."""
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=True,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())  # type: ignore[arg-type]
        result = handler.on_enter(
            _make_story_context(project_root=tmp_path),
            PhaseEnvelopeStore.make_fresh_envelope(_make_phase_state()),
        )
        assert result.status is PhaseStatus.FAILED
        assert "edge_provisioning_unavailable" in result.errors[0]

    def test_create_worktree_not_called_for_concept(
        self, tmp_path: Path
    ) -> None:
        """on_enter commissions no edge worktree for an authoritative concept story.

        Positive non-worktree case (Codex r1 fix): the AUTHORITATIVE StoryService
        record is CONCEPT, so ``_resolve_worktree_plan`` classifies it non-worktree
        and the edge stages / Checks 7/8 correctly no-op -- setup completes without
        any edge command. This must keep working after the fail-open fix that now
        derives the classification from the authoritative record.
        """
        coordinator = _FakeEdgeCoordinator()
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-002",
            create_worktree=True,
            story_service=_NoOpStoryService(  # type: ignore[arg-type]
                story_type=WireStoryType.CONCEPT
            ),
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_RecordingContextRepo(),  # type: ignore[arg-type]
            edge_provisioning_coordinator=coordinator,
        )
        ctx = _make_story_context(
            story_id="AG3-002",
            story_type=StoryType.CONCEPT,
            project_root=tmp_path,
        )
        state = _make_phase_state(story_id="AG3-002")
        enriched = _make_story_context(
            story_id="AG3-002",
            story_type=StoryType.CONCEPT,
            project_root=tmp_path,
        )

        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            # AG3-120: EVERY story type builds its context from the AK3
            # Story-Service record via the single ``build_story_context`` (NO
            # GitHub). A CONCEPT story simply provisions no worktree.
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ) as mock_build_ctx,
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status == PhaseStatus.COMPLETED
        # No edge command commissioned for a non-worktree story.
        assert coordinator.probe_calls == 0
        assert coordinator.provision_calls == 0
        # The record-based builder was used; no worktree for a concept story.
        mock_build_ctx.assert_called_once()

    def test_internal_story_setup_does_not_contact_github(
        self, tmp_path: Path
    ) -> None:
        """AG3-120: an internal RESEARCH story setup never contacts GitHub.

        The setup phase builds the context purely from the AK3 Story-Service
        record via ``build_story_context``; the GitHub issue adapter has been
        removed entirely (no module to import). The story-context builder module
        must carry no reference to a GitHub issue read.
        """
        import agentkit.backend.governance.setup_preflight_gate.context_builder as cb
        import agentkit.integration_clients.github as gh

        # The GitHub issue adapter is gone: no issue CRUD is exported, and the
        # context builder never imported a GitHub issue read.
        assert not hasattr(cb, "get_issue")
        assert not hasattr(gh, "get_issue")
        assert "get_issue" not in gh.__all__

        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-700",
            create_worktree=False,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())  # type: ignore[arg-type]
        ctx = _make_story_context(
            story_id="AG3-700",
            story_type=StoryType.RESEARCH,
            project_root=tmp_path,
        )
        state = _make_phase_state(story_id="AG3-700")
        enriched = _make_story_context(
            story_id="AG3-700",
            story_type=StoryType.RESEARCH,
            project_root=tmp_path,
        )

        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ) as mock_build_ctx,
        ):
            result = handler.on_enter(
                ctx, PhaseEnvelopeStore.make_fresh_envelope(state)
            )

        assert result.status == PhaseStatus.COMPLETED
        mock_build_ctx.assert_called_once()

    def test_code_producing_story_setup_builds_context_from_record(
        self, tmp_path: Path
    ) -> None:
        """AG3-120: a code-producing story builds its context from the record.

        AK3 owns the story; the single ``build_story_context`` reads the AK3
        Story-Service record for every story type (no GitHub issue read).
        """
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-005",
            create_worktree=False,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())  # type: ignore[arg-type]
        ctx = _make_story_context(
            story_id="AG3-005",
            story_type=StoryType.IMPLEMENTATION,
            project_root=tmp_path,
        )
        state = _make_phase_state(story_id="AG3-005")
        enriched = _make_story_context(story_id="AG3-005", project_root=tmp_path)

        from agentkit.backend.governance.setup_preflight_gate.green_main import (
            MainGreenResult,
            MainGreenStatus,
        )

        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ) as mock_build_ctx,
            # A code-producing story evaluates the green-main precondition; stub it
            # GREEN so this test isolates the context-builder assertion.
            patch(
                "agentkit.backend.governance.setup_preflight_gate.green_main."
                "check_main_green_precondition",
                return_value=MainGreenResult(status=MainGreenStatus.GREEN),
            ),
        ):
            result = handler.on_enter(
                ctx, PhaseEnvelopeStore.make_fresh_envelope(state)
            )

        assert result.status == PhaseStatus.COMPLETED
        # Every story type uses the single record-based builder.
        mock_build_ctx.assert_called_once()

    def test_edge_provisioning_failure_report_returns_failed(
        self, tmp_path: Path
    ) -> None:
        """on_enter returns FAILED when the edge reports a provisioning failure."""
        coordinator = _FakeEdgeCoordinator(
            provision=ProvisioningOutcome(pending=False, failed_repos=("repo",)),
        )
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-003",
            create_worktree=True,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_RecordingContextRepo(),  # type: ignore[arg-type]
            edge_provisioning_coordinator=coordinator,
        )
        ctx = _make_story_context(story_id="AG3-003", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-003")
        enriched = _make_story_context(story_id="AG3-003", project_root=tmp_path)

        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status == PhaseStatus.FAILED
        assert "edge_provisioning_failed" in result.errors[0]

    def test_preflight_failure_returns_failed(self, tmp_path: Path) -> None:
        """on_enter returns FAILED immediately when preflight fails."""
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-004",
            create_worktree=False,
        )
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())
        ctx = _make_story_context(story_id="AG3-004", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-004")

        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_fail("issue is closed"),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context"
            ) as mock_build,
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status == PhaseStatus.FAILED
        assert "issue is closed" in result.errors[0]
        mock_build.assert_not_called()


class TestSetupPhaseBeginProgress:
    """Tests for begin_progress call on successful setup."""

    def test_begin_progress_called_on_success(self, tmp_path: Path) -> None:
        """begin_progress is called when story_service is provided and setup succeeds."""
        calls: list[str] = []

        class _StubService:
            def begin_progress(self, story_id: str, *, correlation_id: str = "") -> object:
                calls.append(story_id)
                return object()

        svc = _StubService()
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=False,
            story_service=svc,  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())
        ctx = _make_story_context(project_root=tmp_path)
        state = _make_phase_state()
        enriched = _make_story_context(project_root=tmp_path)

        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status == PhaseStatus.COMPLETED
        assert calls == ["AG3-001"]

    def test_begin_progress_called_via_default_service_when_none(
        self, tmp_path: Path
    ) -> None:
        """When story_service is None, a default StoryService is constructed and used.

        Befund 9: story_service=None must NOT silently skip begin_progress.
        A default StoryService is constructed so begin_progress is always called.
        """
        calls: list[str] = []

        class _TrackingService:
            def begin_progress(self, story_id: str, *, correlation_id: str = "") -> object:
                calls.append(story_id)
                return object()

        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=False,
            story_service=None,
        )
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())
        ctx = _make_story_context(project_root=tmp_path)
        state = _make_phase_state()
        enriched = _make_story_context(project_root=tmp_path)

        tracking_svc = _TrackingService()
        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
            # Patch StoryService at its source so the default construction
            # inside on_enter returns our tracking service (Befund 9).
            patch(
                "agentkit.backend.story_context_manager.service.StoryService",
                return_value=tracking_svc,
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status == PhaseStatus.COMPLETED
        # begin_progress must be called even when story_service=None (Befund 9)
        assert calls == ["AG3-001"]

    def test_begin_progress_failure_returns_failed(self, tmp_path: Path) -> None:
        """on_enter returns FAILED when begin_progress raises."""

        class _FailingService:
            def begin_progress(self, story_id: str, *, correlation_id: str = "") -> object:
                raise RuntimeError("transition error: not Approved")

        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=False,
            story_service=_FailingService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(cfg, context_repository=_RecordingContextRepo())
        ctx = _make_story_context(project_root=tmp_path)
        state = _make_phase_state()
        enriched = _make_story_context(project_root=tmp_path)

        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status == PhaseStatus.FAILED
        assert "begin_progress failed" in result.errors[0]
        assert "transition error" in result.errors[0]


class TestSetupPhaseGreenMain:
    """Green-main precondition + Check-10 mode-lock wiring (AG3-034 T3/T6)."""

    def _run(self, tmp_path: Path, *, available: bool, port: object):  # type: ignore[no-untyped-def]
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-009",
            create_worktree=False,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_RecordingContextRepo(),  # type: ignore[arg-type]
            green_main_port=port,  # type: ignore[arg-type]
        )
        ctx = _make_story_context(story_id="AG3-009", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-009")
        enriched = _make_story_context(story_id="AG3-009", project_root=tmp_path)
        config = ProjectConfig(
            project_key="test-project",
            project_name="Test Project",
            repositories=[RepositoryConfig(name="repo", path=tmp_path)],
            pipeline=PipelineConfig(  # type: ignore[call-arg]
                config_version=SUPPORTED_CONFIG_VERSION,
                features=Features(multi_llm=False),
                sonarqube=SonarQubeConfig(
                    available=available,
                    enabled=available,
                    base_url="http://sonar" if available else None,
                    token_env="SONAR_TOKEN" if available else None,
                    scanner_version="5.0.1" if available else None,
                ),
                ci=_ACTIVE_CI if available else _OPT_OUT_CI,
            ),
        )
        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=config,
            ),
        ):
            return handler.on_enter(
                ctx, PhaseEnvelopeStore.make_fresh_envelope(state)
            )

    def test_red_main_fails_setup_closed(self, tmp_path: Path) -> None:
        class _RedPort:
            def main_head_revision(self) -> str:
                return "head-1"

            def read_main_attestation(self) -> object | None:
                return None  # configured-but-unreachable -> RED

        result = self._run(tmp_path, available=True, port=_RedPort())
        assert result.status == PhaseStatus.FAILED
        assert "sonarqube_main_green: RED" in result.errors[0]
        assert "blame_free" in result.errors[0]

    def test_unavailable_sonar_skips_green_main(self, tmp_path: Path) -> None:
        # available:false -> green-main SKIPPED -> setup proceeds (no port needed).
        result = self._run(tmp_path, available=False, port=None)
        assert result.status == PhaseStatus.COMPLETED

    def test_mode_lock_read_wired_into_preflight(self, tmp_path: Path) -> None:
        # Check-10 wiring: the mode-lock repository read path reaches preflight.
        from agentkit.backend.state_backend.store.mode_lock_repository import ModeLockRecord

        seen: list[object] = []

        acquired: list[tuple[str, str]] = []

        class _Repo:
            def read_lock(self, project_key: str) -> object:
                seen.append(project_key)
                return ModeLockRecord(
                    project_key=project_key,
                    active_mode="standard",
                    holder_count=1,
                    updated_at="t",
                )

            def acquire(self, project_key: str, mode: str) -> object:
                # AG3-018: Setup atomically acquires the mode-lock on the PASS
                # success path (after begin_progress).
                acquired.append((project_key, mode))
                return ModeLockRecord(
                    project_key=project_key,
                    active_mode=mode,
                    holder_count=1,
                    updated_at="t",
                )

        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-010",
            create_worktree=False,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_RecordingContextRepo(),  # type: ignore[arg-type]
            mode_lock_repository=_Repo(),  # type: ignore[arg-type]
        )
        ctx = _make_story_context(story_id="AG3-010", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-010")
        captured: dict[str, object] = {}

        def _fake_run_preflight(*_a: object, **kw: object) -> object:
            # E-E: the handler now injects a fail-closed ``mode_lock_reader``
            # callable (NOT a pre-resolved ``mode_lock``); Check 10 reads it.
            captured["mode_lock_reader"] = kw.get("mode_lock_reader")
            return _make_preflight_pass()

        enriched = _make_story_context(story_id="AG3-010", project_root=tmp_path)
        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                _fake_run_preflight,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=ProjectConfig(
                    project_key="test-project",
                    project_name="Test Project",
                    repositories=[RepositoryConfig(name="repo", path=tmp_path)],
                    pipeline=PipelineConfig(  # type: ignore[call-arg]
                        config_version=SUPPORTED_CONFIG_VERSION,
                        features=Features(multi_llm=False),
                        sonarqube=SonarQubeConfig(available=False, enabled=False),
                        ci=_OPT_OUT_CI,
                    ),
                ),
            ),
        ):
            handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        reader = captured["mode_lock_reader"]
        assert callable(reader)
        # The reader delegates straight to the repository read path (Check 10).
        record = reader("test-project")
        assert seen == ["test-project"]
        assert record is not None


class TestSetupPhaseAreBundle:
    """ARE bundle setup step (AG3-077 / FK-22 §22.4b)."""

    def test_loaded_signal_after_context_before_worktree(self, tmp_path: Path) -> None:
        events: list[str] = []

        class _ContextRepo(_RecordingContextRepo):
            def save(self, story_dir: Path, ctx: StoryContext) -> None:
                events.append("context_saved")
                super().save(story_dir, ctx)

        class _Loader:
            def load_context(
                self,
                story_id: str,
                run_id: str,
            ) -> ContextLoadResult:
                del story_id, run_id
                events.append("are_bundle")
                return ContextLoadResult(
                    status=AreDockpointStatus.PASS,
                    are_bundle_ref="are_bundle_ref",
                    requirement_count=2,
                )

        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-001",
            create_worktree=True,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        coordinator = _FakeEdgeCoordinator(
            provision=ProvisioningOutcome(
                pending=False,
                worktree_map={"repo": tmp_path / "worktrees" / "AG3-001"},
            ),
            on_provision=lambda: events.append("worktree"),
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_ContextRepo(),  # type: ignore[arg-type]
            are_bundle_loader=_Loader(),
            edge_provisioning_coordinator=coordinator,
        )
        ctx = _make_story_context(project_root=tmp_path)
        state = _make_phase_state()
        enriched = _make_story_context(project_root=tmp_path)

        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status is PhaseStatus.COMPLETED
        # AG3-145: the ARE bundle loads after the initial context save and BEFORE
        # the edge-commissioned provisioning; the reported worktree is persisted last.
        assert events == ["context_saved", "are_bundle", "worktree", "context_saved"]
        assert "are_bundle_ref" in result.artifacts_produced
        assert result.updated_state is not None
        payload = result.updated_state.payload
        assert isinstance(payload, SetupPayload)
        assert payload.are_bundle is not None
        assert payload.are_bundle.status is AreBundleStatus.LOADED
        assert payload.are_bundle.requirement_count == 2

    def test_skipped_signal_allows_setup_to_continue(self, tmp_path: Path) -> None:
        class _Loader:
            def load_context(
                self,
                story_id: str,
                run_id: str,
            ) -> ContextLoadResult:
                del story_id, run_id
                return ContextLoadResult(
                    status=AreDockpointStatus.SKIPPED,
                    reason="feature_disabled",
                )

        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-002",
            create_worktree=False,
            story_service=_NoOpStoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_RecordingContextRepo(),  # type: ignore[arg-type]
            are_bundle_loader=_Loader(),
        )
        ctx = _make_story_context(story_id="AG3-002", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-002")
        enriched = _make_story_context(story_id="AG3-002", project_root=tmp_path)

        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.load_project_config",
                return_value=_make_project_config(tmp_path),
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status is PhaseStatus.COMPLETED
        assert result.updated_state is not None
        payload = result.updated_state.payload
        assert isinstance(payload, SetupPayload)
        assert payload.are_bundle is not None
        assert payload.are_bundle.status is AreBundleStatus.SKIPPED

    def test_failed_signal_aborts_before_worker_paths(self, tmp_path: Path) -> None:
        begin_calls: list[str] = []

        class _StoryService(_NoOpStoryService):
            def begin_progress(self, story_id: str, *, correlation_id: str = "") -> object:
                del correlation_id
                begin_calls.append(story_id)
                return object()

        class _Loader:
            def load_context(
                self,
                story_id: str,
                run_id: str,
            ) -> ContextLoadResult:
                del story_id, run_id
                return ContextLoadResult(
                    status=AreDockpointStatus.FAIL,
                    reason="are_gate_unavailable",
                )

        coordinator = _FakeEdgeCoordinator()
        cfg = SetupConfig(
            project_root=tmp_path,
            story_id="AG3-003",
            create_worktree=True,
            story_service=_StoryService(),  # type: ignore[arg-type]
        )
        handler = SetupPhaseHandler(
            cfg,
            context_repository=_RecordingContextRepo(),  # type: ignore[arg-type]
            are_bundle_loader=_Loader(),
            edge_provisioning_coordinator=coordinator,
        )
        ctx = _make_story_context(story_id="AG3-003", project_root=tmp_path)
        state = _make_phase_state(story_id="AG3-003")
        enriched = _make_story_context(story_id="AG3-003", project_root=tmp_path)

        with (
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.run_preflight",
                return_value=_make_preflight_pass(),
            ),
            patch(
                "agentkit.backend.governance.setup_preflight_gate.phase.build_story_context",
                return_value=enriched,
            ),
        ):
            result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(state))

        assert result.status is PhaseStatus.FAILED
        assert result.errors == ("are_gate_unavailable",)
        assert begin_calls == []
        # The ARE-bundle FAIL aborts BEFORE the edge worktree is commissioned.
        assert coordinator.provision_calls == 0
        assert result.updated_state is not None
        payload = result.updated_state.payload
        assert isinstance(payload, SetupPayload)
        assert payload.are_bundle is not None
        assert payload.are_bundle.status is AreBundleStatus.FAILED
