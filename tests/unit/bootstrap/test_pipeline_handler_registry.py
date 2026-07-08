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
from tests.phase_state_factory import make_phase_state

from agentkit.backend.bootstrap.composition_root import (
    build_pipeline_engine,
    build_pipeline_handler_registry,
)
from agentkit.backend.process.language.definitions import resolve_workflow
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store import (
    save_story_context,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

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

        The old behavior fell back to a dummy ``SetupConfig`` with an empty
        ``project_root`` embedded in the productive registry -- an enterable dummy.
        The fix registers a fail-closed setup handler instead: a non-setup
        follow-up dispatch (which never enters setup) is unaffected, but if setup
        is ever ENTERED it ESCALATES rather than running against empty coordinates.
        It must NOT be a real SetupPhaseHandler carrying empty coordinates.
        """
        from agentkit.backend.governance.setup_preflight_gate.phase import SetupPhaseHandler
        from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
        from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus

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
            make_phase_state(
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
    """Write a valid ``project.yaml`` for the setup-config tests (W10/E5).

    The engine-wiring tests target a CODE-PRODUCING story type
    (implementation/bugfix), so the project config must declare a code-producing
    ``story_types`` set plus the required ``sonarqube`` stanza (FK-03 §3 / FK-33
    §33.6); a non-code-producing config (``code_producing=False``) is used only for
    the internal-story path. AG3-120: AK3 owns the story via ``story_id`` and
    GitHub is only the code backend, so ``build_setup_config_for_run`` no longer
    reads ``github_owner`` / ``github_repo`` -- they remain optional config the
    later git mechanics may use, not a setup-coordinate gate.
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


def _persist_ctx_for_run(
    project_root: Path,
    *,
    story_id: str = "AG3-920",
    story_type: StoryType = StoryType.IMPLEMENTATION,
) -> StoryContext:
    """Persist a StoryContext carrying its ``project_root`` (the run's store root).

    Defaults to a CODE-PRODUCING story type so the ``build_setup_config_for_run``
    ``create_worktree`` decision is True (AG3-120: AK3 owns the story via
    ``story_id``; GitHub is only the code backend, so no issue is carried).
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
    )
    save_story_context(story_dir, ctx)
    return ctx


class TestProductiveSetupConfigComposition:
    """W10: drive the REAL productive path; assert a real SetupConfig + run store.

    These tests exercise ``build_phase_dispatcher`` / ``build_pipeline_engine`` /
    ``build_setup_config_for_run`` -- the productive wiring, NOT injected stubs --
    and assert the Setup handler is wired with the run's authoritative
    ``project_root`` and the correct ``create_worktree`` decision, never an empty
    dummy. AG3-120: AK3 owns the story via ``story_id`` and GitHub is only the
    code backend, so the setup config no longer carries owner/repo/issue_nr; the
    story-identity fail-closed gate moved downstream into ``build_story_context``.
    """

    def test_build_setup_config_for_run_uses_real_coordinates(
        self, tmp_path: Path
    ) -> None:
        from agentkit.backend.bootstrap.composition_root import build_setup_config_for_run
        from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig

        _write_project_config(
            tmp_path, github_owner="acme-org", github_repo="trading"
        )
        ctx = _persist_ctx_for_run(tmp_path)

        config = build_setup_config_for_run(ctx, project_root=tmp_path)

        assert isinstance(config, SetupConfig)
        # AG3-123: the setup config carries the Backend-resolved project_root
        # (the run store anchor), never an empty dummy; a code-producing story
        # creates a worktree. AK3 owns the story via story_id -- no issue/owner/repo.
        assert config.project_root == tmp_path
        assert config.create_worktree is True

    def test_productive_engine_wires_real_setup_config(self, tmp_path: Path) -> None:
        """The productive engine factory threads the real SetupConfig into setup."""
        from agentkit.backend.bootstrap.composition_root import build_setup_config_for_run

        _write_project_config(
            tmp_path, github_owner="acme-org", github_repo="trading"
        )
        ctx = _persist_ctx_for_run(tmp_path)
        story_dir = tmp_path / "stories" / ctx.story_id

        engine = build_pipeline_engine(
            story_dir,
            story_type=ctx.story_type,
            project_key=ctx.project_key,
            setup_config=build_setup_config_for_run(ctx, project_root=tmp_path),
        )
        setup_handler = engine._registry.get_handler("setup")  # type: ignore[attr-defined]
        config = setup_handler._config  # type: ignore[attr-defined]

        assert config.create_worktree is True
        # The Setup handler's mode-lock + residue probe are rooted at the RUN's
        # project root (the run store), not cwd.
        assert config.project_root == tmp_path

    def test_dispatcher_engine_factory_uses_backend_resolved_workspace(
        self, tmp_path: Path
    ) -> None:
        """AG3-123: the PRODUCTIVE engine factory wires the Backend-resolved anchor.

        Drives the real dispatcher's engine factory (not an injected one) with a
        Backend-resolved :class:`StoryWorkspace` and asserts the resolved setup
        handler carries the WORKSPACE anchor (``workspace.project_root``) -- the
        setup store anchor is the resolver's, threaded structurally as
        ``build_setup_config_for_run(ctx, project_root=workspace.project_root)``.
        The dispatch-level decoupling from ``ctx.project_root`` (project_root=None)
        is proven separately in ``test_phase_dispatch`` / the e2e flow.
        """
        from agentkit.backend.control_plane.dispatch import build_phase_dispatcher
        from agentkit.backend.control_plane.workspace_locator import StoryWorkspace

        _write_project_config(
            tmp_path, github_owner="acme-org", github_repo="trading"
        )
        ctx = _persist_ctx_for_run(tmp_path)
        workspace = StoryWorkspace(
            project_key=ctx.project_key,
            story_id=ctx.story_id,
            run_id="run-1",
            project_root=tmp_path,
            story_dir=tmp_path / "stories" / ctx.story_id,
        )

        dispatcher = build_phase_dispatcher()
        engine = dispatcher.engine_factory(ctx, workspace)
        config = engine._registry.get_handler("setup")._config  # type: ignore[attr-defined]

        assert config.create_worktree is True
        # The setup store anchor is the Backend-resolved workspace root.
        assert config.project_root == tmp_path

    def test_code_producing_story_succeeds_without_github_or_issue(
        self, tmp_path: Path
    ) -> None:
        """AG3-120: a code-producing story needs NO issue and NO github_owner/repo.

        AK3 owns the user story via ``story_id``; GitHub is only the code backend.
        ``build_setup_config_for_run`` therefore succeeds for a code-producing
        story that carries only its ``project_root`` -- a worktree is created, and
        the old ``issue_nr > 0`` / github-coordinate gate is gone. The story-identity
        fail-closed check moved downstream into ``build_story_context``.
        """
        from agentkit.backend.bootstrap.composition_root import build_setup_config_for_run
        from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig

        # No github_owner/repo declared -- it is no longer a setup-coordinate gate.
        _write_project_config(tmp_path, github_owner=None, github_repo=None)
        ctx = _persist_ctx_for_run(tmp_path)

        config = build_setup_config_for_run(ctx, project_root=tmp_path)

        assert isinstance(config, SetupConfig)
        assert config.project_root == tmp_path
        assert config.create_worktree is True

    @pytest.mark.parametrize(
        "story_type",
        [StoryType.CONCEPT, StoryType.RESEARCH],
    )
    def test_internal_story_is_not_blocked_without_github_coordinates(
        self, tmp_path: Path, story_type: StoryType
    ) -> None:
        """E5: an INTERNAL (non-code-producing) story creates no worktree.

        A CONCEPT / RESEARCH story is internal (``uses_worktree``/``uses_merge``
        false): setup creates no worktree and never merges.
        ``build_setup_config_for_run`` returns a config with
        ``create_worktree=False`` for it (AG3-120: AK3 owns the story via
        ``story_id``; GitHub is only the code backend, so no issue/owner/repo is
        carried either way).
        """
        from agentkit.backend.bootstrap.composition_root import build_setup_config_for_run
        from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig

        _write_project_config(
            tmp_path,
            github_owner=None,
            github_repo=None,
            code_producing=False,
        )
        ctx = _persist_ctx_for_run(tmp_path, story_type=story_type)

        config = build_setup_config_for_run(ctx, project_root=tmp_path)

        assert isinstance(config, SetupConfig)
        assert config.create_worktree is False, (
            "an internal story creates no worktree (no GitHub backend)"
        )
        assert config.project_root == tmp_path


class _RecordingLlmClient:
    """A fake-but-REAL ``LlmClient`` (AG3-067 AC7 composition test).

    Not a stub-that-raises: it implements the ``complete(*, role, prompt) -> str``
    port and records each call, so a test can prove the productive feedback port
    received a NON-None client that would run a REAL evaluation (it is NOT the
    fail-closed :class:`FailClosedLlmClient`).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, role: str, prompt: str) -> str:
        self.calls.append((role, prompt))
        return '{"checks": {"feedback_fidelity": "PASS"}}'


class TestLayer2ClientThreadingAC7:
    """AG3-067 AC7: the SAME Layer-2 client reaches BOTH QA-subflow and closure.

    The productive bug: ``build_verify_system`` accepts ``layer2_llm_client`` but
    the pipeline composition never threaded it, so in production the closure
    feedback-fidelity port still fell back to ``FailClosedLlmClient`` (no real
    evaluation). These tests pin the end-to-end threading: a real (fake-but-real)
    client injected into ``build_pipeline_handler_registry`` /
    ``build_pipeline_engine`` reaches BOTH the implementation handler (->
    ``build_verify_system`` Layer-2 path) AND the closure level-4
    ``ProductiveDocFidelityFeedbackPort`` -- the EXACT same instance (single
    source of truth), never the fail-closed fallback.
    """

    def test_registry_threads_client_into_impl_and_closure(
        self, tmp_path: Path
    ) -> None:
        from agentkit.backend.verify_system.llm_evaluator.llm_client import FailClosedLlmClient

        client = _RecordingLlmClient()
        story_dir = _persist_ctx(tmp_path, StoryType.IMPLEMENTATION)
        registry = build_pipeline_handler_registry(
            story_dir,
            story_type=StoryType.IMPLEMENTATION,
            layer2_llm_client=client,
        )

        # Implementation handler carries the SAME client (-> build_verify_system).
        impl = registry.get_handler("implementation")
        assert impl._config.layer2_llm_client is client  # type: ignore[attr-defined]

        # Closure feedback port receives the SAME NON-None client -- and it is NOT
        # the fail-closed fallback, so it runs a REAL evaluation.
        closure = registry.get_handler("closure")
        port = closure._config.doc_fidelity_port  # type: ignore[attr-defined]
        assert port is not None
        assert port.llm_client is client
        assert not isinstance(port.llm_client, FailClosedLlmClient)

    def test_no_client_falls_back_to_failclosed_at_both_seams(
        self, tmp_path: Path
    ) -> None:
        """Honest default: no injected client -> fail-closed at both seams (not None-skip)."""
        story_dir = _persist_ctx(tmp_path, StoryType.IMPLEMENTATION)
        registry = build_pipeline_handler_registry(
            story_dir, story_type=StoryType.IMPLEMENTATION
        )
        impl = registry.get_handler("implementation")
        # ImplementationConfig carries None; build_verify_system then wires the
        # FailClosedLlmClient internally (Layer 2 still RUNS, fails closed).
        assert impl._config.layer2_llm_client is None  # type: ignore[attr-defined]
        closure = registry.get_handler("closure")
        port = closure._config.doc_fidelity_port  # type: ignore[attr-defined]
        # The port's default is None -> the port's own FailClosedLlmClient default
        # inside _run_feedback_fidelity_conformance (the seam still RUNS).
        assert port is not None
        assert port.llm_client is None

    def test_engine_threads_client_into_closure_feedback_port(
        self, tmp_path: Path
    ) -> None:
        """End-to-end through build_pipeline_engine: same client at the closure port."""
        client = _RecordingLlmClient()
        story_dir = _persist_ctx(tmp_path, StoryType.IMPLEMENTATION)
        engine = build_pipeline_engine(
            story_dir,
            story_type=StoryType.IMPLEMENTATION,
            layer2_llm_client=client,
        )
        registry = engine._registry  # type: ignore[attr-defined]
        port = registry.get_handler("closure")._config.doc_fidelity_port  # type: ignore[attr-defined]
        assert port.llm_client is client


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
