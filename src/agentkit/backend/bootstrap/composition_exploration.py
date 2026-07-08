"""Exploration-phase composition builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.bootstrap.composition_artifacts import build_artifact_manager

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.bootstrap import composition_exploration_types as exploration_types
    from agentkit.backend.bootstrap import composition_project_types as project_types
    from agentkit.backend.bootstrap import composition_verify_types as verify_types


def build_exploration_review(
    ctx: project_types.StoryContext,
    story_dir: Path,
    *,
    llm_client: verify_types.LlmClient | None = None,
    conformance_config: project_types.ConformanceConfig | None = None,
) -> exploration_types.ExplorationReview:
    """Wire the three-stage exploration exit-gate (AG3-046, FK-23 §23.5).

    Composition root for :class:`ExplorationReview`: builds the Stage 1
    document-fidelity checker and the Stage 2a design-review runner over the
    Layer-2 :class:`StructuredEvaluator`, the
    :class:`PromptRuntimeMaterializer` (FK-44 §44.4.2 prompt source) and the
    :class:`ArtifactReviewResultSink` (QA-artifact persistence). Stage 2b
    design-challenge is wired as ``None`` (mandate-gated activation is AG3-047).

    The LLM transport defaults to the fail-closed :class:`FailClosedLlmClient`
    (no LLM pool is wired productively yet, FK-11 follow-up): every gate stage
    then FAILS CLOSED at the LLM boundary rather than silently approving (NO
    ERROR BYPASSING). Once the pool adapter exists the caller injects it here.

    Args:
        ctx: The story context for the run (carries ``project_root`` /
            ``story_id``; required by the prompt materializer).
        story_dir: Story working directory (run-scope + artifact store root).
        llm_client: Optional Layer-2 LLM transport. ``None`` => the fail-closed
            :class:`FailClosedLlmClient` (gate fails closed until a pool exists).
        conformance_config: Optional FK-32 §32.4b.3 prompt-size thresholds.
            ``None`` => the service's built-in defaults (50 KB / 500 KB) are used.
            Pass ``project_config.pipeline.conformance`` to make the configured
            thresholds effective for this exploration review.

    Returns:
        A wired :class:`ExplorationReview`.
    """
    from agentkit.backend.exploration.review.design_review import DesignReviewRunner
    from agentkit.backend.exploration.review.doc_fidelity import DocFidelityChecker
    from agentkit.backend.exploration.review.persistence import ArtifactReviewResultSink
    from agentkit.backend.exploration.review.review import ExplorationReview as _Review
    from agentkit.backend.state_backend.store.verify_story_context_repository import (
        StateBackendVerifyStoryContextAdapter,
    )
    from agentkit.backend.telemetry.storage import StateBackendEmitter
    from agentkit.backend.verify_system.conformance_service import (
        ConformanceService,
        StructuredEvaluatorConformanceAdapter,
    )
    from agentkit.backend.verify_system.llm_evaluator.llm_client import FailClosedLlmClient
    from agentkit.backend.verify_system.llm_evaluator.prompt_materializer import (
        PromptRuntimeMaterializer,
    )
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluator,
    )

    manager = build_artifact_manager(story_dir)
    client = llm_client or FailClosedLlmClient()
    materializer = PromptRuntimeMaterializer(
        ctx=ctx,
        story_dir=story_dir,
        artifact_manager=manager,
        story_context_port=StateBackendVerifyStoryContextAdapter(),
    )
    evaluator = StructuredEvaluator(client, materializer)
    sink = ArtifactReviewResultSink(manager)
    conformance_kwargs: dict[str, int] = {}
    if conformance_config is not None:
        conformance_kwargs["file_upload_threshold"] = conformance_config.file_upload_threshold
        conformance_kwargs["hard_limit"] = conformance_config.hard_limit
    conformance = ConformanceService(
        StructuredEvaluatorConformanceAdapter(evaluator),
        emitter=StateBackendEmitter(story_dir),
        **conformance_kwargs,
    )
    return _Review(
        stage1_doc_fidelity=DocFidelityChecker(
            evaluator,
            sink,
            story_context=ctx,
            conformance_service=conformance,
        ),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=None,
        artifact_manager=manager,
    )


def build_exploration_phase_handler(
    story_dir: Path,
    *,
    review: exploration_types.ExplorationReview | None = None,
    fine_design_evaluator: exploration_types.FineDesignEvaluator | None = None,
) -> exploration_types.ExplorationPhaseHandler:
    """Wire the registrable ``ExplorationPhaseHandler`` surface (AG3-045/AG3-046).

    Composition root for the exploration-phase handler (BC 5,
    ``exploration-and-design``): wires the bloodgroup-A handler to the
    state-backend adapter that fulfils the two boundary ports
    (``RunScopeResolver`` + ``ChangeFrameReader``). The A-core therefore does
    NOT import ``state_backend.store`` itself and does no direct filesystem I/O
    (ARCH-22 / ARCH-31).

    Per PO decision 2026-06-05 ("Option Y") the handler produces NO change-frame:
    it consumes / validates the change-frame persisted by the exploration worker
    (AG3-055). Without a valid change-frame the phase is fail-closed (ESCALATED).

    AG3-046: when a valid change-frame is present the handler runs the three-stage
    exit-gate (:class:`ExplorationReview`). The review is built per-run (it needs
    the ``StoryContext`` for the prompt materializer) via
    :func:`build_exploration_review`; the productive per-run injection +
    ``PhaseHandlerRegistry`` registration is owned by AG3-054. ``review=None``
    (the default here) fails closed: a valid frame with no review wired returns
    ``FAILED`` (never auto-APPROVE, NO ERROR BYPASSING).

    AG3-047: the handler is additionally wired with the mandate-classification
    collaborators (FK-25 §25.3-25.8): :class:`MandateClassification` (over the
    :class:`ScopeExplosionDetector` + :class:`ImpactExceedanceChecker`), the
    :class:`FineDesignSubprocess` skeleton, the :class:`DesignFreezeMarker`
    (freeze-on-PASS, FK-23 §23.4.3), the :class:`MandateTelemetry` emitter wired
    to the canonical :class:`StateBackendEmitter`, and the ``DeclaredImpactReader``
    boundary port (state-backend ``StoryRepository`` read of the story's declared
    ``change_impact``). The bloodgroup-A core imports none of these I/O sources
    directly; the telemetry / state-backend / clock wiring lives HERE.

    AG3-097: the fine-design subprocess is wired with the CONCRETE multi-LLM-hub
    evaluator :class:`HubFineDesignEvaluator` by DEFAULT (built by
    :func:`build_hub_fine_design_evaluator` over the real :class:`HubClient`
    transport + a productive prompt builder + the LLM-delegating convergence
    judge). The REAL build path therefore drives the hub (ChatGPT + a mandatory
    second advisor are acquired/sent over the hub, FK-25 §25.5.2), NOT a stand-in
    that never touches the hub. The convergence VERDICT is delegated to the
    fail-closed LLM client until the FK-11 pool selection is wired, so a class-2
    frame: drives the real hub advisors, then -- per D4-Override (FK-25 §25.5.4
    Z. 642-650) -- ends ``FAILED`` after the bounded retry (cause in
    ``AttemptRecord.failure_cause``) rather than fabricating an APPROVED / freeze
    with no real verdict (ZERO DEBT / FAIL-CLOSED; NO ``infra_unavailable``
    triple). ``fine_design_evaluator`` lets a caller inject an explicit evaluator
    (e.g. the fail-closed :class:`_UnavailableFineDesignEvaluator` for a justified
    hub-absent config, or a scripted evaluator in tests); the DEFAULT is the
    hub-backed evaluator. The :class:`FineDesignSubprocess` shell is unchanged.

    Args:
        story_dir: Story working directory (bound ``FlowExecution`` + the read
            surface root). Passed to the adapter's ``ArtifactManager`` and the
            handler config.
        review: Optional pre-built three-stage exit-gate. ``None`` fails closed
            on a valid change-frame (AG3-054 injects the per-run review).
        fine_design_evaluator: Optional explicit fine-design evaluator. ``None``
            (the default) wires the hub-backed :class:`HubFineDesignEvaluator`
            over the real transport; a caller may inject the fail-closed stand-in
            for a justified hub-absent config or a scripted evaluator in tests.

    Returns:
        A wired ``ExplorationPhaseHandler`` (incl. the AG3-047 mandate flow).
    """
    from datetime import UTC, datetime

    from agentkit.backend.exploration.freeze import DesignFreezeMarker
    from agentkit.backend.exploration.mandate import (
        FineDesignSubprocess,
        ImpactExceedanceChecker,
        MandateClassification,
        ScopeExplosionDetector,
    )
    from agentkit.backend.exploration.mandate.telemetry import MandateTelemetry
    from agentkit.backend.exploration.phase import (
        ExplorationConfig,
    )
    from agentkit.backend.exploration.phase import (
        ExplorationPhaseHandler as _ExplorationPhaseHandler,
    )
    from agentkit.backend.installer.paths import project_root_for_story_dir
    from agentkit.backend.state_backend.store.exploration_change_frame_repository import (
        StateBackendExplorationChangeFrameAdapter,
    )
    from agentkit.backend.telemetry.storage import StateBackendEmitter

    adapter = StateBackendExplorationChangeFrameAdapter(build_artifact_manager(story_dir))
    mandate = MandateClassification(
        scope_detector=ScopeExplosionDetector(),
        impact_checker=ImpactExceedanceChecker(),
    )
    evaluator = fine_design_evaluator or build_hub_fine_design_evaluator(story_dir)
    fine_design = FineDesignSubprocess(evaluator)
    freeze_marker = DesignFreezeMarker(writer=adapter, clock=lambda: datetime.now(UTC))
    telemetry = MandateTelemetry(StateBackendEmitter(story_dir))
    # AG3-055 produce->consume loop: wire the productive ExplorationDrafting A-core
    # (CONSUMER) + the draft-presence reader so the handler drives the typed loop
    # (consume a present worker draft vs emit a spawn order). The project root is
    # derived from the canonical ``<project_root>/stories/<story_id>`` layout; an
    # off-layout story_dir leaves drafting unwired (the handler keeps the
    # fail-closed branch rather than materializing a prompt against an unknown
    # root). The worker-runner resolves the authoritative StoryContext at draft
    # time (ERROR-2 scope cross-check).
    project_root = project_root_for_story_dir(story_dir)
    drafting = _build_exploration_drafting(story_dir, project_root=project_root) if project_root is not None else None
    return _ExplorationPhaseHandler(
        change_frame_reader=adapter,
        run_scope_resolver=adapter,
        review=review,
        config=ExplorationConfig(story_dir=story_dir),
        mandate_classification=mandate,
        declared_impact_reader=_StateBackendDeclaredImpactReader(story_dir),
        fine_design=fine_design,
        freeze_marker=freeze_marker,
        telemetry=telemetry,
        drafting=drafting,
        draft_presence=adapter if drafting is not None else None,
    )


def build_hub_fine_design_evaluator(
    story_dir: Path,
    *,
    hub_client: project_types.HubClientProtocol | None = None,
    llm_client: verify_types.LlmClient | None = None,
    owner: str | None = None,
) -> exploration_types.FineDesignEvaluator:
    """Wire the productive multi-LLM-hub fine-design evaluator (AG3-097).

    Composition root for :class:`HubFineDesignEvaluator` (FK-25 §25.5.2/§25.5.4):
    binds the REAL :class:`HubClient` transport (resolved from
    :func:`load_multi_llm_hub_config`, default localhost) plus the productive
    :class:`ChangeFrameFineDesignPromptBuilder` and the LLM-delegating
    :class:`LlmConvergenceJudge`. The judge's verdict transport defaults to the
    fail-closed :class:`FailClosedLlmClient` (no FK-11 LLM pool is wired yet), so
    the assembled evaluator REALLY drives the hub (acquire/send ChatGPT + a
    mandatory second advisor) and then fails closed at the convergence verdict ->
    the caller edge maps that to D4 bounded-retry-then-``FAILED`` (no fabricated
    convergence; ZERO DEBT / FAIL-CLOSED). Once the pool adapter exists the caller
    passes a real ``llm_client`` and the verdict becomes live with no transport
    change.

    Args:
        story_dir: Story working directory (telemetry root + story-id correlation
            via the canonical ``<project_root>/stories/<story_id>`` layout).
        hub_client: Optional hub transport. ``None`` => the real
            :class:`HubClient` over the resolved hub base URL.
        llm_client: Optional convergence-verdict LLM transport. ``None`` => the
            fail-closed :class:`FailClosedLlmClient` (FK-11 pool is a follow-up).
        owner: Optional hub session owner id. ``None`` => a story-correlated
            default.

    Returns:
        A wired :class:`HubFineDesignEvaluator` (typed as the
        :class:`FineDesignEvaluator` port).
    """
    from agentkit.backend.exploration.mandate.hub_fine_design import HubFineDesignEvaluator
    from agentkit.backend.exploration.mandate.hub_fine_design_wiring import (
        ChangeFrameFineDesignPromptBuilder,
        LlmConvergenceJudge,
    )
    from agentkit.backend.telemetry.storage import StateBackendEmitter
    from agentkit.backend.verify_system.llm_evaluator.llm_client import FailClosedLlmClient
    from agentkit.integration_clients.multi_llm_hub.client import HubClient
    from agentkit.integration_clients.multi_llm_hub.config import load_multi_llm_hub_config

    story_id = story_dir.name
    client = hub_client or HubClient(load_multi_llm_hub_config().base_url)
    verdict_client = llm_client or FailClosedLlmClient()
    return HubFineDesignEvaluator(
        client,
        emitter=StateBackendEmitter(story_dir),
        judge=LlmConvergenceJudge(verdict_client),
        prompt_builder=ChangeFrameFineDesignPromptBuilder(),
        owner=owner or f"exploration-fine-design-{story_id}",
        story_id=story_id,
    )


def build_exploration_drafting(
    story_dir: Path,
    ctx: project_types.StoryContext,
) -> exploration_types.ExplorationDrafting:
    """Wire the productive ``ExplorationDrafting`` sub (AG3-055, FK-23 §23.3).

    Composition root for the exploration-worker drafting (BC 5,
    ``exploration-and-design``, ``ExplorationDrafting`` sub). Wires the
    bloodgroup-A core to its three boundary ports with PRODUCTIVE adapters:

    * the LLM/worker boundary -- the
      :class:`StateBackendExplorationWorkerRunner` that materializes
      ``worker-exploration.md`` over the AG3-044 worker-spawn path
      (``WorkerSession`` -> ``PromptRuntime``, FK-44; the selector picks
      ``worker-exploration`` for an EXPLORATION ``execution_route``) and reads
      back the worker's raw seven-part draft. No parallel spawn path;
    * the ENTWURF-envelope persistence -- :class:`ArtifactChangeFrameSink` over
      the productive :class:`ArtifactManager` (the AG3-045-registered producer);
    * the protected change-frame FILE writer -- the AG3-045
      :class:`StateBackendExplorationChangeFrameAdapter` (writes
      ``_temp/qa/{story_id}/change_frame.json``, the very path the AG3-045
      handler's reader consumes -- closing the produce->consume loop).

    The A-core imports none of these I/O sources directly (ARCH-22 / ARCH-31).
    The drafting is the PRODUCER; the AG3-045 handler (built by
    :func:`build_exploration_phase_handler`) is the CONSUMER/VALIDATOR of the
    same artifact -- there is NO engine-/handler-side change-frame generation.

    Args:
        story_dir: Story working directory (worker spawn context + the
            ``_temp/qa/{story_id}/`` change-frame location).
        ctx: The authoritative story context for the run (drives the prompt
            materialization + the worker spawn; carries ``project_root``).

    Returns:
        A wired :class:`ExplorationDrafting` ready to produce the change-frame.

    Raises:
        ProjectError: When ``ctx.project_root`` is unset (the prompt runtime
            needs it to materialize ``worker-exploration.md``; fail-closed).
    """
    from agentkit.backend.exceptions import ProjectError

    if ctx.project_root is None:
        raise ProjectError(
            "Exploration drafting requires ctx.project_root to materialize the "
            "worker-exploration prompt (FK-44); refusing fail-closed.",
            detail={"story_id": ctx.story_id, "story_dir": str(story_dir)},
        )
    return _build_exploration_drafting(story_dir, project_root=ctx.project_root)


def _build_exploration_drafting(
    story_dir: Path,
    *,
    project_root: Path,
) -> exploration_types.ExplorationDrafting:
    """Wire the productive ``ExplorationDrafting`` from ``story_dir`` + root.

    Shared wiring for :func:`build_exploration_drafting` (ctx-driven) and
    :func:`build_exploration_phase_handler` (story_dir-driven; the handler is
    built at run start before any per-call ``StoryContext`` is in hand, and the
    productive worker-runner resolves the authoritative ``StoryContext`` from
    ``story_dir`` at draft time -- with the ERROR-2 scope cross-check). The three
    boundary ports are the productive adapters; the A-core imports none of these
    I/O sources directly (ARCH-22 / ARCH-31).

    Args:
        story_dir: Story working directory (worker spawn context + the
            ``_temp/qa/{story_id}/`` change-frame location).
        project_root: The project root the prompt runtime materializes against
            (FK-44).

    Returns:
        A wired :class:`ExplorationDrafting`.
    """
    from agentkit.backend.exploration.drafting import ExplorationDrafting as _Drafting
    from agentkit.backend.exploration.drafting.persistence import ArtifactChangeFrameSink
    from agentkit.backend.prompt_runtime import PromptRuntime
    from agentkit.backend.state_backend.store.exploration_change_frame_repository import (
        StateBackendExplorationChangeFrameAdapter,
    )
    from agentkit.backend.state_backend.store.exploration_worker_runner import (
        StateBackendExplorationWorkerRunner,
    )

    manager = build_artifact_manager(story_dir)
    prompt_runtime = PromptRuntime(project_root, manager)
    worker_runner = StateBackendExplorationWorkerRunner(story_dir, prompt_runtime)
    sink = ArtifactChangeFrameSink(manager)
    writer = StateBackendExplorationChangeFrameAdapter(manager)
    return _Drafting(
        worker_runner=worker_runner,
        change_frame_sink=sink,
        change_frame_writer=writer,
    )


@dataclass(frozen=True)
class _StateBackendDeclaredImpactReader:
    """State-backed ``DeclaredImpactReader`` (FK-25 §25.7.1, AG3-047).

    Resolves the story's authoritative declared ``change_impact`` via the
    state-backend :class:`StateBackendStoryRepository` (the GitHub-input story
    stammdaten). The bloodgroup-A exploration core never reads the story store
    directly; this composition-root adapter owns the read.

    FAIL-CLOSED (FK-25 §25.7.1 / FIX-THE-MODEL): an absent / unresolvable story
    RAISES ``CorruptStateError`` rather than defaulting to ``LOCAL`` -- the
    declared impact is the load-bearing input of the Klasse-4 check and must
    never be silently fabricated (no second source of truth, no fail-open).

    Attributes:
        store_dir: State-backend base dir (SQLite); Postgres ignores it.
    """

    store_dir: Path

    def declared_change_impact(self, *, story_id: str) -> project_types.ChangeImpact:
        """Return the story's declared change impact (fail-closed).

        Args:
            story_id: The story display id.

        Returns:
            The authoritative declared :class:`ChangeImpact`.

        Raises:
            CorruptStateError: When the story (or its declared impact) cannot be
                resolved (never a silent ``LOCAL`` default).
        """
        from agentkit.backend.exceptions import CorruptStateError
        from agentkit.backend.state_backend.store.story_repository import (
            StateBackendStoryRepository,
        )

        story = StateBackendStoryRepository(self.store_dir).get_by_display_id(story_id)
        if story is None:
            raise CorruptStateError(
                "Cannot resolve declared change_impact: no persisted story for "
                "the exploration mandate Klasse-4 check (FK-25 §25.7.1, "
                "fail-closed -- no LOCAL default).",
                detail={"story_id": story_id},
            )
        return story.change_impact


@dataclass(frozen=True)
class _UnavailableFineDesignEvaluator:
    """Fail-closed fine-design evaluator for a justified hub-absent config.

    AG3-097: the DEFAULT canonical production wiring now uses the concrete
    :class:`HubFineDesignEvaluator` (see :func:`build_hub_fine_design_evaluator`),
    which drives the real hub. This stand-in remains for a justified config where
    the hub is intentionally absent -- the caller injects it explicitly via
    ``build_exploration_phase_handler(..., fine_design_evaluator=...)``. It must
    NEVER fabricate a converged outcome for a class-2 (fine_design) frame -- that
    would let a story with unresolved design points reach APPROVED / freeze with
    no real fine-design (an Attrappe passing as productive core logic, forbidden).

    It raises :class:`FineDesignEvaluatorUnavailableError` on every round -- the
    honest FK-25 §25.5.4 non-reachability signal ("no LLM is available"). The
    :class:`FineDesignSubprocess` shell does NOT swallow it; per D4-Override
    (FK-25 §25.5.4 Z. 642-650) the exploration phase handler treats
    non-reachability as an OPERATIONAL error -> bounded retry, then ``FAILED``
    (cause in AttemptRecord.failure_cause) -- NOT a pause, NO ``infra_unavailable``
    triple.
    """

    def run_round(
        self,
        change_frame: exploration_types.ChangeFrame,
        *,
        round_number: int,
    ) -> exploration_types.FineDesignRoundOutcome:
        """Raise fail-closed: no real fine-design evaluator is wired yet.

        Args:
            change_frame: The change-frame being refined (unused; no real
                discussion is held).
            round_number: The 1-based round number (unused).

        Raises:
            FineDesignEvaluatorUnavailableError: Always -- the productive
                multi-LLM evaluator is a follow-up (FK-25 §25.5.4). Never returns
                a fabricated convergence (ZERO DEBT / FAIL-CLOSED).
        """
        from agentkit.backend.exploration.mandate.fine_design import (
            FineDesignEvaluatorUnavailableError,
        )

        del change_frame, round_number
        msg = (
            "fine-design evaluator unavailable: the productive multi-LLM "
            "fine-design discussion (FK-25 §25.5) is a follow-up story; "
            "escalating the class-2 frame fail-closed (FK-25 §25.5.4)"
        )
        raise FineDesignEvaluatorUnavailableError(msg)
