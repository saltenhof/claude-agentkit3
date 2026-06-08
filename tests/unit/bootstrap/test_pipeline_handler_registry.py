"""Unit tests for the 4-phase pipeline composition root (AG3-054).

Verifies that ``build_pipeline_handler_registry`` / ``build_pipeline_engine`` are
pure WIRING over the phase-owning self-registration surfaces (FK-20 §20.1.1,
bc-cut-decisions BC 5/6/7): exactly the typed-workflow phase subset is registered,
the DI collaborators are threaded through each phase's own build function (no
self-build of the phase-specific collaborators in the registry/engine), and the
story-type switch follows ``resolve_workflow`` (no string/flag cascade).

The closure phase build is fail-closed on the run's persisted ``StoryContext``
(FIX-2: a broken config never silently disables verification), so each test
persists a real context to the story directory first -- the same precondition the
productive dispatch path satisfies (setup persists the context before closure is
ever wired).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.bootstrap.composition_root import (
    build_pipeline_engine,
    build_pipeline_handler_registry,
)
from agentkit.process.language.definitions import resolve_workflow
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    reset_backend_cache_for_tests,
    save_story_context,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def sqlite_backend_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _persist_ctx(
    tmp_path: Path,
    story_type: StoryType,
    *,
    story_id: str = "AG3-901",
) -> Path:
    """Persist a StoryContext so the closure build's FIX-2 precondition holds."""
    story_dir = tmp_path / "stories" / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    ctx = StoryContext(
        project_key="test-project",
        story_id=story_id,
        story_type=story_type,
        execution_route=(
            StoryMode.EXECUTION
            if story_type in (StoryType.IMPLEMENTATION, StoryType.BUGFIX)
            else None
        ),
        project_root=tmp_path,
    )
    save_story_context(story_dir, ctx)
    return story_dir


class TestRegistryWiring:
    """build_pipeline_handler_registry registers exactly the workflow phases."""

    def test_implementation_registers_all_four_phases(self, tmp_path: Path) -> None:
        """An implementation story registers setup/exploration/implementation/closure."""
        story_dir = _persist_ctx(tmp_path, StoryType.IMPLEMENTATION)
        registry = build_pipeline_handler_registry(
            story_dir, story_type=StoryType.IMPLEMENTATION
        )
        assert registry.registered_phases == frozenset(
            {"setup", "exploration", "implementation", "closure"}
        )

    def test_bugfix_registers_exploration_phase(self, tmp_path: Path) -> None:
        """A bugfix story's WORKFLOW includes exploration (AG3-057, FK-23 §23.1).

        The BUGFIX_WORKFLOW now carries the exploration phase so that a
        trigger-fired EXPLORATION-route bugfix can run it.  The registry
        therefore registers exploration for bugfix stories.  An EXECUTION-route
        bugfix never enters the exploration phase at runtime (routing_rules
        removes it from the effective phase list), but the handler must be
        registered because the workflow definition carries the phase.
        """
        story_dir = _persist_ctx(tmp_path, StoryType.BUGFIX)
        registry = build_pipeline_handler_registry(
            story_dir, story_type=StoryType.BUGFIX
        )
        assert "exploration" in registry.registered_phases
        assert registry.registered_phases == frozenset(
            {"setup", "exploration", "implementation", "closure"}
        )

    @pytest.mark.parametrize(
        "story_type",
        [StoryType.CONCEPT, StoryType.RESEARCH],
    )
    def test_concept_research_register_three_phases(
        self, tmp_path: Path, story_type: StoryType
    ) -> None:
        """Concept/research stories register their own three-phase subset."""
        story_dir = _persist_ctx(tmp_path, story_type)
        registry = build_pipeline_handler_registry(
            story_dir, story_type=story_type
        )
        assert "exploration" not in registry.registered_phases
        assert registry.registered_phases == frozenset(
            {"setup", "implementation", "closure"}
        )

    def test_registered_phases_match_resolved_workflow(self, tmp_path: Path) -> None:
        """The registered phase set equals the resolved workflow's phase set.

        This pins the story-type switch to the typed ``resolve_workflow`` surface
        rather than a hand-rolled string cascade.
        """
        for index, story_type in enumerate(StoryType):
            story_dir = _persist_ctx(
                tmp_path, story_type, story_id=f"AG3-91{index}"
            )
            registry = build_pipeline_handler_registry(
                story_dir, story_type=story_type
            )
            workflow_phases = frozenset(resolve_workflow(story_type).phase_names)
            assert registry.registered_phases == workflow_phases

    def test_each_phase_has_a_real_handler(self, tmp_path: Path) -> None:
        """Every registered phase resolves a handler satisfying the protocol."""
        story_dir = _persist_ctx(tmp_path, StoryType.IMPLEMENTATION)
        registry = build_pipeline_handler_registry(
            story_dir, story_type=StoryType.IMPLEMENTATION
        )
        for phase in registry.registered_phases:
            handler = registry.get_handler(phase)
            assert hasattr(handler, "on_enter")
            assert hasattr(handler, "on_resume")

    def test_di_threads_story_dir_into_implementation_handler(
        self, tmp_path: Path
    ) -> None:
        """The shared story_dir collaborator is threaded into the impl handler."""
        story_dir = _persist_ctx(tmp_path, StoryType.BUGFIX)
        registry = build_pipeline_handler_registry(
            story_dir, story_type=StoryType.BUGFIX
        )
        handler = registry.get_handler("implementation")
        # The implementation handler keeps its config; the story_dir DI must be
        # the one we passed (no self-built default path).
        assert handler._config.story_dir == story_dir  # type: ignore[attr-defined]

    def test_setup_config_none_registers_fail_closed_setup_handler(
        self, tmp_path: Path
    ) -> None:
        """#4: with no real setup_config, setup is FAIL-CLOSED, never a runnable dummy.

        The old behavior fell back to a dummy ``SetupConfig(owner="", repo="",
        issue_nr=0)`` embedded in the productive registry -- an enterable dummy.
        The fix registers a fail-closed setup handler instead: a non-setup
        follow-up dispatch (which never enters setup) is unaffected, but if setup
        is ever ENTERED it ESCALATES rather than running against empty coordinates.
        It must NOT be a real SetupPhaseHandler carrying empty coordinates.
        """
        from agentkit.governance.setup_preflight_gate.phase import SetupPhaseHandler
        from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
        from agentkit.story_context_manager.models import (
            PhaseState,
            PhaseStatus,
        )

        story_dir = _persist_ctx(tmp_path, StoryType.IMPLEMENTATION)
        registry = build_pipeline_handler_registry(
            story_dir,
            story_type=StoryType.IMPLEMENTATION,
            setup_config=None,  # no resolvable real config
        )
        handler = registry.get_handler("setup")

        # Never a real setup handler with enterable dummy coordinates.
        assert not isinstance(handler, SetupPhaseHandler)

        # Entering it ESCALATES fail-closed (setup never runs on dummy coords).
        ctx = StoryContext(
            project_key="test-project",
            story_id="AG3-901",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=tmp_path,
        )
        envelope = PhaseEnvelopeStore.make_fresh_envelope(
            PhaseState(
                story_id="AG3-901", phase="setup", status=PhaseStatus.PENDING
            )
        )
        result = handler.on_enter(ctx, envelope)
        assert result.status is PhaseStatus.ESCALATED
        assert result.suggested_reaction == "setup_coordinates_unresolved"


def _write_project_config(
    project_root: Path,
    *,
    github_owner: str | None,
    github_repo: str | None,
    code_producing: bool = True,
) -> None:
    """Write a valid ``project.yaml`` for the setup-coordinate tests (W10/E5).

    The GitHub-coordinate-required tests target a CODE-PRODUCING story type
    (implementation/bugfix), so the project config must declare a code-producing
    ``story_types`` set plus the required ``sonarqube`` stanza (FK-03 §3 / FK-33
    §33.6); a non-code-producing config (``code_producing=False``) is used only for
    the internal-story path. The authoritative ``github_owner`` / ``github_repo``
    coordinates the Setup handler needs are carried either way.
    """
    import yaml

    config_dir = project_root / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "project_key": "test-project",
        "project_name": "Test Project",
        "repositories": [{"name": "backend", "path": "."}],
        "story_types": ["implementation"] if code_producing else ["concept"],
    }
    if code_producing:
        # A code-producing project MUST declare explicit ``sonarqube`` and ``ci``
        # stanzas (FK-03 §3 / AG3-056, under ``pipeline``); use the
        # deliberate-absent opt-outs to keep the config minimal but valid.
        # config_version is mandatory (FK-03 §3.2.1); multi_llm=False for this
        # single-LLM test fixture.
        payload["pipeline"] = {
            "config_version": "3.0",
            "features": {"multi_llm": False},
            "sonarqube": {"available": False, "enabled": False},
            "ci": {"available": False, "enabled": False},
        }
    if github_owner is not None:
        payload["github_owner"] = github_owner
    if github_repo is not None:
        payload["github_repo"] = github_repo
    (config_dir / "project.yaml").write_text(
        yaml.safe_dump(payload), encoding="utf-8"
    )


def _persist_ctx_with_issue(
    project_root: Path,
    *,
    issue_nr: int | None,
    story_id: str = "AG3-920",
    story_type: StoryType = StoryType.IMPLEMENTATION,
) -> StoryContext:
    """Persist a GitHub-backed StoryContext carrying ``issue_nr`` + ``project_root``.

    Defaults to a CODE-PRODUCING (GitHub-backed) story type so the
    ``build_setup_config_for_run`` GitHub-coordinate requirement applies (E5).
    """
    story_dir = project_root / "stories" / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    ctx = StoryContext(
        project_key="test-project",
        story_id=story_id,
        story_type=story_type,
        execution_route=(
            StoryMode.EXECUTION
            if story_type in (StoryType.IMPLEMENTATION, StoryType.BUGFIX)
            else None
        ),
        project_root=project_root,
        issue_nr=issue_nr,
    )
    save_story_context(story_dir, ctx)
    return ctx


class TestProductiveSetupConfigComposition:
    """W10: drive the REAL productive path; assert a real SetupConfig + run store.

    These tests exercise ``build_phase_dispatcher`` / ``build_pipeline_engine`` /
    ``build_setup_config_for_run`` -- the productive wiring, NOT injected stubs --
    and assert the Setup handler is wired with the run's authoritative GitHub
    coordinates (owner/repo from the project config, issue_nr from the
    StoryContext) and the run's project root, never an empty dummy. They FAIL
    against the old dummy/cwd wiring (owner="" repo="" issue_nr=0).
    """

    def test_build_setup_config_for_run_uses_real_coordinates(
        self, tmp_path: Path
    ) -> None:
        from agentkit.bootstrap.composition_root import build_setup_config_for_run
        from agentkit.governance.setup_preflight_gate.phase import SetupConfig

        _write_project_config(
            tmp_path, github_owner="acme-org", github_repo="trading"
        )
        ctx = _persist_ctx_with_issue(tmp_path, issue_nr=4242)

        config = build_setup_config_for_run(ctx)

        assert isinstance(config, SetupConfig)
        assert config.owner == "acme-org"
        assert config.repo == "trading"
        assert config.issue_nr == 4242
        assert config.project_root == tmp_path
        # The old dummy never produced these -- prove they are NOT empty.
        assert config.owner != ""
        assert config.repo != ""
        assert config.issue_nr != 0

    def test_productive_engine_wires_real_setup_config(self, tmp_path: Path) -> None:
        """The productive engine factory threads the real SetupConfig into setup."""
        from agentkit.bootstrap.composition_root import build_setup_config_for_run

        _write_project_config(
            tmp_path, github_owner="acme-org", github_repo="trading"
        )
        ctx = _persist_ctx_with_issue(tmp_path, issue_nr=4242)
        story_dir = tmp_path / "stories" / ctx.story_id

        engine = build_pipeline_engine(
            story_dir,
            story_type=ctx.story_type,
            project_key=ctx.project_key,
            setup_config=build_setup_config_for_run(ctx),
        )
        setup_handler = engine._registry.get_handler("setup")  # type: ignore[attr-defined]
        config = setup_handler._config  # type: ignore[attr-defined]

        assert config.owner == "acme-org"
        assert config.repo == "trading"
        assert config.issue_nr == 4242
        # The Setup handler's mode-lock + residue probe are rooted at the RUN's
        # project root (the run store), not cwd.
        assert config.project_root == tmp_path

    def test_dispatcher_engine_factory_uses_run_store_and_real_config(
        self, tmp_path: Path
    ) -> None:
        """The PRODUCTIVE ``build_phase_dispatcher`` engine factory uses ctx coords.

        Drives the real dispatcher's engine factory (not an injected one) and
        asserts the resolved setup handler carries the run's real coordinates and
        project root -- the W10 regression that hid E1/E7.
        """
        from agentkit.control_plane.dispatch import build_phase_dispatcher

        _write_project_config(
            tmp_path, github_owner="acme-org", github_repo="trading"
        )
        ctx = _persist_ctx_with_issue(tmp_path, issue_nr=7)

        dispatcher = build_phase_dispatcher()
        engine = dispatcher.engine_factory(ctx)
        config = engine._registry.get_handler("setup")._config  # type: ignore[attr-defined]

        assert config.owner == "acme-org"
        assert config.repo == "trading"
        assert config.issue_nr == 7
        assert config.project_root == tmp_path

    def test_productive_fresh_setup_rejects_when_coordinates_missing(
        self, tmp_path: Path
    ) -> None:
        """E1: the productive dispatcher REJECTS a fresh setup start with no coords.

        A fresh setup start whose project config declares no github_owner/repo must
        be rejected fail-closed (setup must never run against empty coordinates) --
        not silently dispatched against a dummy.
        """
        from agentkit.control_plane.dispatch import build_phase_dispatcher

        _write_project_config(tmp_path, github_owner=None, github_repo=None)
        ctx = _persist_ctx_with_issue(tmp_path, issue_nr=7)
        story_dir = tmp_path / "stories" / ctx.story_id

        from agentkit.control_plane.dispatch import PreStartGuard

        class _Allow:
            def is_approved(self, project_key: str, story_display_id: str) -> bool:
                del project_key, story_display_id
                return True

            def is_ready_and_admitted(
                self, project_key: str, story_display_id: str
            ) -> bool:
                del project_key, story_display_id
                return True

        admit = PreStartGuard(approval_reader=_Allow(), scheduling_reader=_Allow())
        base = build_phase_dispatcher()
        # Admit Tor1/Tor2 so the failure is isolated to the coordinate precheck.
        dispatcher = base.__class__(
            engine_factory=base.engine_factory,
            guard_factory=lambda c: admit,
            setup_coordinates_check=base.setup_coordinates_check,
        )

        result = dispatcher.dispatch(
            ctx=ctx,
            phase="setup",
            story_dir=story_dir,
            run_id="run-1",
            run_admitted=False,
        )

        assert result.status == "rejected"
        assert result.dispatched is False
        assert "setup coordinates" in (result.rejection_reason or "")

    def test_missing_github_coordinates_fail_closed(self, tmp_path: Path) -> None:
        """Fail-closed (E1): no github_owner/repo -> SetupCoordinatesUnavailableError."""
        from agentkit.bootstrap.composition_root import (
            SetupCoordinatesUnavailableError,
            build_setup_config_for_run,
        )

        _write_project_config(tmp_path, github_owner=None, github_repo=None)
        ctx = _persist_ctx_with_issue(tmp_path, issue_nr=7)

        with pytest.raises(SetupCoordinatesUnavailableError):
            build_setup_config_for_run(ctx)

    def test_missing_issue_nr_fail_closed(self, tmp_path: Path) -> None:
        """Fail-closed (E1): no issue_nr -> SetupCoordinatesUnavailableError."""
        from agentkit.bootstrap.composition_root import (
            SetupCoordinatesUnavailableError,
            build_setup_config_for_run,
        )

        _write_project_config(
            tmp_path, github_owner="acme-org", github_repo="trading"
        )
        ctx = _persist_ctx_with_issue(tmp_path, issue_nr=None)

        with pytest.raises(SetupCoordinatesUnavailableError):
            build_setup_config_for_run(ctx)

    def test_zero_issue_nr_fail_closed_for_github_backed_story(
        self, tmp_path: Path
    ) -> None:
        """E5: issue_nr=0 (a bogus issue) is REJECTED for a GitHub-backed story.

        ``0`` is not a real GitHub issue; a code-producing setup must never run
        against it. ``build_setup_config_for_run`` requires ``issue_nr > 0``.
        """
        from agentkit.bootstrap.composition_root import (
            SetupCoordinatesUnavailableError,
            build_setup_config_for_run,
        )

        _write_project_config(
            tmp_path, github_owner="acme-org", github_repo="trading"
        )
        ctx = _persist_ctx_with_issue(tmp_path, issue_nr=0)

        with pytest.raises(SetupCoordinatesUnavailableError):
            build_setup_config_for_run(ctx)

    @pytest.mark.parametrize(
        "story_type",
        [StoryType.CONCEPT, StoryType.RESEARCH],
    )
    def test_internal_story_is_not_blocked_without_github_coordinates(
        self, tmp_path: Path, story_type: StoryType
    ) -> None:
        """E5: an INTERNAL (non-code-producing) story needs NO GitHub coordinates.

        A CONCEPT / RESEARCH story is internal (``uses_worktree``/``uses_merge``
        false): setup creates no worktree and never merges, so it requires no
        github_owner/repo and no positive issue_nr. ``build_setup_config_for_run``
        must NOT fail-closed-block it; it returns a GitHub-free config with
        ``create_worktree=False`` even with NO issue_nr and NO owner/repo. This is
        the E5 regression: the prior E1 fix wrongly blocked these legitimately
        non-GitHub stories.
        """
        from agentkit.bootstrap.composition_root import build_setup_config_for_run
        from agentkit.governance.setup_preflight_gate.phase import SetupConfig

        # No github_owner/repo and no issue_nr -- an internal story carries none.
        _write_project_config(
            tmp_path,
            github_owner=None,
            github_repo=None,
            code_producing=False,
        )
        ctx = _persist_ctx_with_issue(
            tmp_path, issue_nr=None, story_type=story_type
        )

        config = build_setup_config_for_run(ctx)

        assert isinstance(config, SetupConfig)
        assert config.create_worktree is False, (
            "an internal story creates no worktree (no GitHub backend)"
        )
        assert config.project_root == tmp_path


class TestEngineWiring:
    """build_pipeline_engine composes the engine over the wired registry."""

    def test_engine_uses_resolved_workflow(self, tmp_path: Path) -> None:
        """The engine interprets the typed workflow for the story type."""
        story_dir = _persist_ctx(tmp_path, StoryType.IMPLEMENTATION)
        engine = build_pipeline_engine(
            story_dir, story_type=StoryType.IMPLEMENTATION
        )
        assert engine._workflow.name == "implementation"  # type: ignore[attr-defined]

    def test_engine_registry_covers_workflow_phases(self, tmp_path: Path) -> None:
        """The engine's registry covers every phase of its workflow."""
        story_dir = _persist_ctx(tmp_path, StoryType.BUGFIX)
        engine = build_pipeline_engine(story_dir, story_type=StoryType.BUGFIX)
        registry = engine._registry  # type: ignore[attr-defined]
        for phase in engine._workflow.phase_names:  # type: ignore[attr-defined]
            assert registry.has_handler(phase)
