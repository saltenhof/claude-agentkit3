"""Pipeline-engine composition builders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.bootstrap.composition_closure import build_closure_phase_handler
from agentkit.backend.bootstrap.composition_exploration import build_exploration_phase_handler
from agentkit.backend.bootstrap.composition_governance import build_setup_phase_handler

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.bootstrap import composition_project_types as project_types
    from agentkit.backend.bootstrap import composition_verify_types as verify_types


def build_pipeline_handler_registry(
    story_dir: Path,
    *,
    story_type: project_types.StoryType,
    project_key: str = "",
    project_root: Path | None = None,
    setup_config: object | None = None,
    layer2_llm_client: verify_types.LlmClient | None = None,
) -> project_types.PhaseHandlerRegistry:
    """Wire ONE ``PhaseHandlerRegistry`` for a story run (AG3-054, FK-20 §20.1.1).

    Pure WIRING over the phase-owning self-registration surfaces (bc-cut-decisions
    BC 5/6/7): the exploration / implementation / closure BCs own their handler
    internals; this composition-root function only registers the per-story-type
    subset of handlers at ONE registry instance and threads the shared foundation
    collaborator (``story_dir``) through each phase's own build function. It pulls
    NO handler / gate / merge / QA innards into a central plan (no God-composition).

    The registered subset follows the typed workflow for the story type
    (:func:`~agentkit.backend.process.language.definitions.resolve_workflow`); only phases
    actually present in that workflow get a handler:

    * ``setup`` -> :func:`build_setup_phase_handler`
    * ``exploration`` (implementation-mode only) -> the AG3-045
      :class:`ExplorationPhaseHandler` via :func:`build_exploration_phase_handler`
    * ``implementation`` -> the AG3-026 ``ImplementationPhaseHandler`` (QA-subflow
      already wired in ``implementation/phase.py``)
    * ``closure`` -> the AG3-053 ``ClosurePhaseHandler`` via
      :func:`build_closure_phase_handler`

    Args:
        story_dir: The story working directory (shared foundation collaborator
            threaded into each phase build function -- e.g. the ``PhaseEnvelopeStore``
            / state-backend read seams the handlers consume).
        story_type: The story type whose typed workflow decides which phases are
            present (and therefore which handlers are registered).
        project_key: Owning project key (threaded to the closure governance seam).
        project_root: The Backend-resolved workspace anchor (AG3-123), threaded
            into the closure handler so its pre-merge ``ci``/``sonarqube`` config
            root is read from the workspace, never a dev-supplied
            ``ctx.project_root``. ``None`` => structural fallback to the canonical
            story_dir layout (the identical anchor).
        setup_config: The run-specific ``SetupConfig`` carrying the authoritative
            GitHub coordinates the Setup handler needs (E1). The PRODUCTIVE path
            (``build_pipeline_engine`` <- dispatch) ALWAYS supplies a real config
            built by :func:`build_setup_config_for_run`. ``None`` registers a
            FAIL-CLOSED setup handler (E4) -- never a runnable dummy. A non-setup
            follow-up dispatch (which never enters setup) is fine; if setup is
            ever entered without a resolved real config it ESCALATES rather than
            running against empty/dummy coordinates.
        layer2_llm_client: The Layer-2 LLM transport (AG3-067 AC7). Threaded into
            BOTH the implementation handler (-> ``build_verify_system`` -> the
            QA-subflow Layer-2 reviewers) AND the closure handler (-> the level-4
            ``ProductiveDocFidelityFeedbackPort``) so ONE transport reaches both
            the verify-system Layer-2 path and the closure feedback port (single
            source of truth). ``None`` => the fail-closed
            :class:`FailClosedLlmClient` default inside ``build_verify_system`` /
            the feedback port (the seams still RUN and fail closed; honest until
            the productive LLM pool lands, AG3-070).

    Returns:
        A ``PhaseHandlerRegistry`` with exactly the workflow's phase handlers.
    """
    from agentkit.backend.closure.phase import ClosureConfig
    from agentkit.backend.implementation.phase import (
        ImplementationConfig,
        ImplementationPhaseHandler,
    )
    from agentkit.backend.pipeline_engine.lifecycle import PhaseHandlerRegistry
    from agentkit.backend.process.language.definitions import resolve_workflow

    workflow = resolve_workflow(story_type)
    phases = set(workflow.phase_names)
    registry = PhaseHandlerRegistry()

    if "setup" in phases:
        # E4 fix (#4): NEVER register a runnable dummy setup config on the
        # productive path. A resolved real ``SetupConfig`` => the real handler; a
        # ``None`` config (the run's coordinates were not resolvable, or a
        # follow-up dispatch never resolved them) => a FAIL-CLOSED setup handler
        # that escalates if entered, so setup can never run against an empty/dummy
        # project_root. A non-setup follow-up dispatch never enters it.
        if setup_config is not None:
            setup_handler: object = build_setup_phase_handler(
                setup_config,
                store_dir=story_dir,
            )
        else:
            setup_handler = _UnresolvedSetupCoordinatesHandler()
        registry.register("setup", setup_handler)  # type: ignore[arg-type]
    if "exploration" in phases:
        registry.register("exploration", build_exploration_phase_handler(story_dir))
    if "implementation" in phases:
        from agentkit.backend.bootstrap.composition_verify import (
            build_change_evidence_port,
        )
        from agentkit.backend.control_plane.repository import EdgeCommandRepository
        from agentkit.backend.verify_system.evidence.edge_preparation import (
            VerifyEvidencePreparationCoordinator,
        )
        from agentkit.backend.verify_system.evidence.preflight_sender import (
            FailClosedPreflightReviewSender,
            LlmPreflightReviewSender,
        )

        preflight_sender = (
            LlmPreflightReviewSender(layer2_llm_client)
            if layer2_llm_client is not None
            else FailClosedPreflightReviewSender()
        )
        registry.register(
            "implementation",
            ImplementationPhaseHandler(
                ImplementationConfig(
                    story_dir=story_dir,
                    # AG3-067 AC7: same transport as the closure feedback port.
                    layer2_llm_client=layer2_llm_client,
                    evidence_preparation=VerifyEvidencePreparationCoordinator(
                        edge_commands=EdgeCommandRepository(),
                        sender=preflight_sender,
                        change_evidence_port=build_change_evidence_port(),
                    ),
                )
            ),
        )
    if "closure" in phases:
        registry.register(
            "closure",
            build_closure_phase_handler(
                ClosureConfig(story_dir=story_dir),
                store_dir=story_dir,
                project_key=project_key,
                # AG3-123: thread the Backend-resolved workspace anchor so the
                # closure pre-merge config root never reads ``ctx.project_root``.
                project_root=project_root,
                # AG3-067 AC7: the SAME Layer-2 transport build_verify_system uses
                # reaches the level-4 ProductiveDocFidelityFeedbackPort here.
                layer2_llm_client=layer2_llm_client,
            ),
        )
    return registry


class _UnresolvedSetupCoordinatesHandler:
    """Fail-closed setup handler registered when no real config resolved (E4/#4).

    Registered in place of the real :class:`SetupPhaseHandler` when
    ``build_pipeline_handler_registry`` received ``setup_config=None`` (the run's
    authoritative coordinates could not be resolved, or a non-setup follow-up
    dispatch never resolved them). Registering this instead of a runnable dummy
    ``SetupConfig`` with an empty ``project_root`` guarantees the productive setup
    path can NEVER run against empty/dummy coordinates: a non-setup follow-up
    dispatch (which never enters setup) is unaffected, but any attempt to actually
    ENTER setup ESCALATES fail-closed (FK-20 §20.8.2 / ZERO DEBT -- no second
    source of truth, no enterable dummy on the productive path). Satisfies the
    ``PhaseHandler`` protocol.
    """

    _REASON = (
        "Setup cannot run: the run's authoritative setup coordinates were not "
        "resolved when the registry was built (no real SetupConfig). The "
        "fresh-setup-start dispatch must resolve them first (FK-20 §20.8.2); a "
        "dummy project_root is never permitted on the productive path "
        "(fail-closed; E4/#4)."
    )

    def _escalation(self) -> project_types.HandlerResult:
        from agentkit.backend.pipeline_engine.lifecycle import HandlerResult
        from agentkit.backend.pipeline_engine.phase_executor import PhaseStatus

        return HandlerResult(
            status=PhaseStatus.ESCALATED,
            errors=(self._REASON,),
            suggested_reaction="setup_coordinates_unresolved",
        )

    def on_enter(self, ctx: project_types.StoryContext, envelope: project_types.PhaseEnvelope) -> project_types.HandlerResult:
        """Escalate fail-closed: setup must never run on unresolved coordinates."""
        _ = ctx, envelope
        return self._escalation()

    def on_exit(self, ctx: project_types.StoryContext, envelope: project_types.PhaseEnvelope) -> None:
        """No-op exit (the phase escalated before doing any work)."""
        _ = ctx, envelope

    def on_resume(
        self,
        ctx: project_types.StoryContext,
        envelope: project_types.PhaseEnvelope,
        trigger: str,
    ) -> project_types.HandlerResult:
        """Escalate fail-closed on resume too (coordinates still unresolved)."""
        _ = ctx, envelope, trigger
        return self._escalation()


def build_pipeline_engine(
    story_dir: Path,
    *,
    story_type: project_types.StoryType,
    project_key: str = "",
    project_root: Path | None = None,
    setup_config: object | None = None,
    layer2_llm_client: verify_types.LlmClient | None = None,
) -> project_types.PipelineEngine:
    """Wire a ``PipelineEngine`` for a story run (AG3-054, FK-20 §20.1.1).

    Resolves the typed workflow for ``story_type`` and constructs the engine over
    the :func:`build_pipeline_handler_registry` wiring. The engine itself is the
    existing deterministic interpreter (AG3-earlier) -- this is pure composition,
    no new engine / transition / handler mechanic.

    Args:
        story_dir: The story working directory (engine persistence root).
        story_type: The story type whose typed workflow the engine interprets.
        project_key: Owning project key (threaded to the closure governance seam).
        project_root: The Backend-resolved workspace anchor (AG3-123), threaded
            into the closure handler's pre-merge config resolution so it no longer
            reads a dev-supplied ``ctx.project_root``. ``None`` => structural
            fallback to the canonical story_dir layout.
        setup_config: The run-specific ``SetupConfig`` carrying the authoritative
            ``project_root`` (E1 fix). The PRODUCTIVE caller resolves it from the
            run ``StoryContext`` via :func:`build_setup_config_for_run` and passes
            it here; it is threaded into the Setup handler so setup never runs
            against an empty ``project_root``. ``None`` falls back to the
            test-boundary config (dispatch-contract tests only).
        layer2_llm_client: The Layer-2 LLM transport (AG3-067 AC7). Threaded
            through :func:`build_pipeline_handler_registry` into BOTH the
            verify-system Layer-2 path and the closure level-4 feedback port so a
            single transport reaches both. ``None`` => the fail-closed default
            inside both seams (honest until the productive pool lands, AG3-070).

    Returns:
        A wired ``PipelineEngine``.
    """
    from agentkit.backend.pipeline_engine.engine import PipelineEngine
    from agentkit.backend.process.language.definitions import resolve_workflow

    workflow = resolve_workflow(story_type)
    registry = build_pipeline_handler_registry(
        story_dir,
        story_type=story_type,
        project_key=project_key,
        project_root=project_root,
        setup_config=setup_config,
        layer2_llm_client=layer2_llm_client,
    )
    return PipelineEngine(workflow, registry, story_dir)
