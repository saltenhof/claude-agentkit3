"""Closure phase handler -- orchestrates the canonical closure sequence (FK-29).

This handler ORCHESTRATES the FK-29 §29.1/§29.1.4 closure sequence for a story.
It builds NO second merge, gate, Sonar or lock truth -- it CALLS the existing
capabilities in the normative order:

* the Finding-Resolution-Gate (``agentkit.closure.gates``, FK-29 §29.2);
* the Pre-Merge-Scan-and-Merge-Block (``agentkit.closure.merge_sequence``, FK-29
  §29.1a): integrated-candidate scan (produces the fresh attestation) -> the
  AG3-034 IntegrityGate (verifies it, FK-35 §35.2.4a) -> the AG3-009 saga
  (push/ff-merge/reconcile);
* the post-merge finalization steps 6-9 (``agentkit.closure.post_merge_finalization``,
  FK-29 §29.1.4): doc-fidelity feedback -> postflight -> VectorDB sync -> guard
  deactivation (all non-blocking, FK-29 §29.3.2).

Canonical order (impl/bugfix, FK-29 §29.1.4):

1. prior-phase validation (incl. ``qa_cycle_status == pass``);
2. Finding-Resolution-Gate (ESCALATED on an unresolved finding);
3. Pre-Merge-Scan-and-Merge-Block (ESCALATED on scan/gate/push/merge failure);
4. story status Done (``story_closed``);
5. metrics (``metrics_written``);
6-9. post-merge finalization (``postflight_done`` marks "postflight ran").

Concept/Research stories (typed via ``StoryTypeProfile.uses_merge``) skip the
Finding-Resolution-Gate, the IntegrityGate and the whole locked block;
``integrity_passed`` / ``story_branch_pushed`` / ``merge_done`` are set ``true``
directly (FK-29 §29.1.1) and the finalization steps 4-9 run normally.

``ClosureProgress`` is the single recovery truth (FK-29 §29.1.0): each substate
boolean is persisted to the phase state BEFORE the next irreversible side effect;
``on_resume`` dispatches over those booleans (FK-29 §29.1.3) and never re-runs a
completed irreversible substate.

Collaborators are injected (DI) -- the composition root
(``build_closure_phase_handler``) wires them; the handler builds none itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from agentkit.closure.execution_report.records import ExecutionReport
from agentkit.closure.execution_report.writer import write_execution_report
from agentkit.closure.gates import evaluate_finding_resolution_gate
from agentkit.closure.merge_sequence import (
    ClosureRepo,
    MergeApplicability,
    MergeBlockStatus,
    run_pre_merge_and_merge_block,
)
from agentkit.closure.post_merge_finalization.finalization import (
    run_post_merge_finalization,
)
from agentkit.closure.post_merge_finalization.metrics import (
    build_story_metrics_record,
)
from agentkit.core_types.closure import ClosureVerdict
from agentkit.exceptions import IntegrationError
from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.pipeline_engine.lifecycle import HandlerResult
from agentkit.state_backend.store import (
    load_phase_snapshot,
    save_story_context,
)
from agentkit.story_context_manager.models import (
    ClosurePayload,
    ClosureProgress,
    PhaseState,
    PhaseStatus,
    QaCycleStatus,
)
from agentkit.story_context_manager.types import get_profile

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from agentkit.artifacts import ArtifactManager
    from agentkit.closure.merge_sequence import (
        BuildTestPort,
        PreMergeScanPort,
        RepoRunners,
        SanityGatePort,
    )
    from agentkit.closure.multi_repo_saga import GitBackend
    from agentkit.closure.post_merge_finalization.finalization import (
        DocFidelityFeedbackPort,
        FinalizationResult,
        GuardDeactivationPort,
        VectorDbSyncPort,
    )
    from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.governance.integrity_gate import IntegrityGate
    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.service import StoryService

logger = logging.getLogger(__name__)


class ClosureProgressStore(Protocol):
    """Checkpoint-persistence seam for the closure phase state (FK-29 §29.1.0).

    Phase-state mutation may only happen through a pipeline surface
    (architecture-conformance AC003). The handler therefore does NOT import
    ``save_phase_state`` directly -- it persists each ``ClosureProgress``
    checkpoint through this injected seam, whose productive implementation is the
    ``pipeline_engine`` ``PhaseEnvelopeStore`` (wired by the composition root).
    """

    def save_state(self, state: PhaseState) -> None:
        """Persist the closure phase state (a checkpoint write)."""
        ...


@dataclass
class ClosureConfig:
    """Configuration + injected collaborators for the closure phase handler.

    Attributes:
        owner: GitHub repository owner (for issue close).
        repo: GitHub repository name.
        issue_nr: GitHub issue number.
        close_issue: Whether to close the GitHub issue.
        story_dir: Story artifacts directory.
        story_service: Optional ``StoryService`` (``complete_story`` on success).
        integrity_gate: AG3-034 gate (verifier of the fresh attestation). Required
            for impl/bugfix; the composition root wires it via
            ``build_integrity_gate``.
        scan_port: Integrated-candidate Sonar scan seam (FK-29 §29.1a.3 d).
        build_test_port: Integrated-candidate Build/Test seam (FK-29 §29.1a.3 c,
            fail-closed if the runner is not wired).
        sanity_port: Fast-mode Sanity-Gate seam (FK-29 §29.1a.6).
        artifact_manager: Layer-2 read seam for the Finding-Resolution-Gate.
        doc_fidelity_port: Level-4 doc-fidelity feedback seam (step 6).
        vectordb_sync_port: VectorDB sync seam (step 8).
        guard_deactivation_port: Guard-deactivation seam (step 9).
        repos: Participating repos for the merge saga (one element => single-repo;
            empty falls back to a single repo derived from ``story_dir``).
        git_backend: Optional git backend for the saga (stubbed in tests).
        merge_applicability: Typed pre-merge applicability (FIX-3, FK-33 §33.6.5)
            resolved by the composition root from the story type + ``ci``/
            ``sonarqube`` availability: ``FULL`` (CI+Sonar), ``SONAR_ABSENT``
            (CI present, Sonar declared absent -> Build/Test runs, scan+Dim9
            skipped, merge still gated), or ``CI_ABSENT`` (CI declared absent
            for a code story -> fail-closed, cannot verify -> cannot merge).
            Never inferred from ``None`` ports inside the block.
        repo_runners: Optional per-repo ``Mapping[Path, RepoRunners]`` (FIX-C)
            keyed by ``ClosureRepo.repo_root``. When set, the merge block selects
            each repo's OWN scan/build runner pair (bound to that repo's
            root/ledger/tree) instead of the single ``scan_port``/
            ``build_test_port``. Single-repo is the one-entry case; ``None`` falls
            back to the single pair (one repo).
    """

    owner: str | None = None
    repo: str | None = None
    issue_nr: int | None = None
    close_issue: bool = True
    story_dir: Path | None = None
    story_service: StoryService | None = None
    integrity_gate: IntegrityGate | None = None
    scan_port: PreMergeScanPort | None = None
    build_test_port: BuildTestPort | None = None
    sanity_port: SanityGatePort | None = None
    artifact_manager: ArtifactManager | None = None
    doc_fidelity_port: DocFidelityFeedbackPort | None = None
    vectordb_sync_port: VectorDbSyncPort | None = None
    guard_deactivation_port: GuardDeactivationPort | None = None
    sonar_config: object | None = None
    repos: tuple[ClosureRepo, ...] = ()
    git_backend: object | None = None
    progress_store: ClosureProgressStore | None = None
    merge_applicability: MergeApplicability = MergeApplicability.FULL
    repo_runners: object | None = None


class ClosurePhaseHandler:
    """Phase handler for the Closure phase (FK-29 §29.1).

    Implements the :class:`~agentkit.pipeline_engine.lifecycle.PhaseHandler`
    protocol. ``on_enter`` orchestrates the canonical closure sequence;
    ``on_resume`` dispatches recovery over the persisted ``ClosureProgress``
    booleans.
    """

    def __init__(self, config: ClosureConfig) -> None:
        self._config = config

    def on_enter(self, ctx: StoryContext, envelope: PhaseEnvelope) -> HandlerResult:
        """Execute the closure sequence (FK-29 §29.1.4).

        Args:
            ctx: The story context for this pipeline run.
            envelope: The current phase envelope (carries the durable
                ``ClosureProgress`` checkpoints).

        Returns:
            A ``HandlerResult`` describing the outcome.
        """
        cfg = self._config
        if cfg.story_dir is None:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=("story_dir is not configured in ClosureConfig",),
            )
        s_dir = cfg.story_dir
        save_story_context(s_dir, ctx)

        prior_phases = self._prior_phases(ctx)
        missing = _validate_prior_phases(s_dir, prior_phases)
        if missing:
            return HandlerResult(status=PhaseStatus.FAILED, errors=tuple(missing))

        progress = _resume_progress(envelope)
        return self._run_sequence(ctx, s_dir, prior_phases, progress)

    def on_resume(
        self, ctx: StoryContext, envelope: PhaseEnvelope, trigger: str,
    ) -> HandlerResult:
        """Resume closure by dispatching over the persisted ``ClosureProgress``.

        FK-29 §29.1.3: substates whose boolean is already ``true`` are skipped;
        the sequence continues from the first open substate. An irreversible
        substate (``merge_done``) is never re-run. There is no deterministic
        FAILED anymore (the legacy behaviour is removed).

        Args:
            ctx: The story context for this pipeline run.
            envelope: The current phase envelope (carries the checkpoints).
            trigger: The resume trigger (unused -- dispatch is by progress).

        Returns:
            A ``HandlerResult`` describing the outcome.
        """
        del trigger
        cfg = self._config
        if cfg.story_dir is None:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=("story_dir is not configured in ClosureConfig",),
            )
        s_dir = cfg.story_dir
        save_story_context(s_dir, ctx)
        prior_phases = self._prior_phases(ctx)
        progress = _resume_progress(envelope)
        return self._run_sequence(ctx, s_dir, prior_phases, progress)

    def on_exit(self, _ctx: StoryContext, _envelope: PhaseEnvelope) -> None:
        """No-op for closure phase.

        Args:
            ctx: The story context (unused).
            envelope: The current phase envelope (unused).
        """
        _ = _ctx, _envelope

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def _prior_phases(self, ctx: StoryContext) -> tuple[str, ...]:
        """The required prior phases from the typed story-type profile."""
        return get_profile(ctx.story_type).phases[:-1]

    def _run_sequence(
        self,
        ctx: StoryContext,
        s_dir: Path,
        prior_phases: tuple[str, ...],
        progress: ClosureProgress,
    ) -> HandlerResult:
        """Run the closure sequence, dispatching over the resume ``progress``."""
        cfg = self._config
        finalization_error = _require_finalization_collaborators(cfg)
        if finalization_error is not None:
            return finalization_error
        store = cfg.progress_store
        assert store is not None  # noqa: S101 -- guaranteed by the check above
        uses_merge = get_profile(ctx.story_type).uses_merge

        # Steps 2-3: Finding-Resolution-Gate + Pre-Merge-Scan-and-Merge-Block.
        # Skipped (and the merge booleans set directly true) for concept/research
        # (FK-29 §29.1.1), and skipped when already recovered (merge_done true).
        if not progress.merge_done:
            merge_outcome = self._reach_merge_done(ctx, s_dir, uses_merge, progress)
            if isinstance(merge_outcome, HandlerResult):
                return merge_outcome
            progress = merge_outcome

        # Step 4: story status Done. On resume (already closed) we do NOT re-close
        # the GitHub issue / re-transition; FIX-5: the authoritative closed flag is
        # ``progress.story_closed`` (never reset to False locally on resume).
        if not progress.story_closed:
            _story_closed_now, gh_warnings = _close_github_issue(cfg)
            transition_error = _transition_story_done(cfg, ctx.story_id)
            if transition_error is not None:
                return transition_error
            progress = _persist(store, ctx, progress, story_closed=True)
        else:
            gh_warnings = []

        # Step 5: metrics (FIX-5: idempotent). If already written, LOAD the
        # existing metrics record instead of rebuilding + rewriting it.
        status = "completed_with_warnings" if gh_warnings else "completed"
        metrics_or_error = _resolve_metrics(s_dir, ctx, status, progress.metrics_written)
        if isinstance(metrics_or_error, HandlerResult):
            return metrics_or_error
        metrics = metrics_or_error
        if not progress.metrics_written:
            progress = _persist(store, ctx, progress, metrics_written=True)

        # Steps 6-9: post-merge finalization (non-blocking). FIX-5: idempotent --
        # if postflight already ran (``postflight_done``) it is NOT re-run; the
        # real ``progress.story_closed`` is passed into postflight (never a reset
        # False on resume, which would raise a false postflight warning).
        finalization: FinalizationResult | None = None
        if not progress.postflight_done:
            finalization = self._run_finalization(ctx, s_dir, progress.story_closed)
            progress = _persist(store, ctx, progress, postflight_done=True)

        finalization_warnings = finalization.warnings if finalization is not None else ()
        all_warnings = (*gh_warnings, *finalization_warnings)
        report_status = "completed_with_warnings" if all_warnings else "completed"
        report_path = _write_report(
            ctx,
            s_dir,
            prior_phases,
            metrics,
            progress.story_closed,
            all_warnings,
            report_status,
        )
        return HandlerResult(
            status=PhaseStatus.COMPLETED,
            artifacts_produced=(str(report_path),),
            updated_state=_closure_state(ctx.story_id, progress, PhaseStatus.COMPLETED),
        )

    def _reach_merge_done(
        self,
        ctx: StoryContext,
        s_dir: Path,
        uses_merge: bool,
        progress: ClosureProgress,
    ) -> ClosureProgress | HandlerResult:
        """Reach ``merge_done`` for impl/bugfix, or set it directly for non-code."""
        store = self._store()
        if not uses_merge:
            # Concept/Research: no Finding-Gate, no IntegrityGate, no merge block;
            # the three merge booleans are set directly true (FK-29 §29.1.1).
            return _persist(
                store,
                ctx,
                progress,
                integrity_passed=True,
                story_branch_pushed=True,
                merge_done=True,
            )
        return self._run_merge_block(ctx, s_dir, progress)

    def _store(self) -> ClosureProgressStore:
        """Return the wired checkpoint store (guaranteed non-None at this point)."""
        store = self._config.progress_store
        assert store is not None  # noqa: S101 -- guaranteed by the collaborator check
        return store

    def _run_merge_block(
        self,
        ctx: StoryContext,
        s_dir: Path,
        progress: ClosureProgress,
    ) -> ClosureProgress | HandlerResult:
        """Run the Finding-Gate + locked merge block for an impl/bugfix story."""
        cfg = self._config

        # FIX-3: model declared-absence at the applicability layer. A
        # code-producing story whose CI is declared absent has no Build/Test+scan
        # runner -> the integrated candidate cannot be verified -> fail-closed
        # (cannot verify => cannot merge). Decided HERE (the handler), never by
        # silently skipping inside the block (NO ERROR BYPASSING, FK-33 §33.6.5).
        if cfg.merge_applicability is MergeApplicability.CI_ABSENT:
            return self._escalated(
                ctx,
                progress,
                (
                    "pre-merge CI is declared absent for a code-producing story: "
                    "cannot run Build/Test or the integrated-candidate scan -> "
                    "cannot verify -> cannot merge unverified code (FK-29 §29.1a "
                    "/ FK-33 §33.6.5)",
                ),
            )

        config_error = _require_merge_collaborators(cfg)
        if config_error is not None:
            return config_error
        # ``_require_merge_collaborators`` validated the non-optional collaborators
        # above; bind them to locals so no ``type: ignore`` is needed (FIX-8).
        integrity_gate, sanity_port, artifact_manager = _require_merge_locals(cfg)
        git_backend = _git_backend_for(cfg)

        # Step 2: Finding-Resolution-Gate (skipped on resume if already merged --
        # handled by the caller's ``merge_done`` guard; not separately
        # checkpointed, FK-29 §29.1.3). FIX-7: for an impl/bugfix closure a
        # missing/corrupt runtime run scope FAILS CLOSED -- it must NOT fall back
        # to ``run_id=None`` cross-run matching (a stale-finding risk). The
        # concept does not permit cross-run resolution here.
        run_id = _resolve_run_id_fail_closed(s_dir)
        if run_id is None:
            return self._escalated(
                ctx,
                progress,
                (
                    "Finding-Resolution-Gate: cannot resolve the runtime run scope "
                    "for this impl/bugfix closure -> fail-closed (no run_id=None "
                    "cross-run finding matching, FK-29 §29.2)",
                ),
            )
        gate = evaluate_finding_resolution_gate(
            artifact_manager, story_id=ctx.story_id, run_id=run_id
        )
        if not gate.passed:
            return self._escalated(
                ctx, progress, (gate.blocking_reason or "finding resolution failed",)
            )

        # Step 3: Pre-Merge-Scan-and-Merge-Block (scan -> gate -> push -> merge).
        # FIX-4/E5: the block calls ``checkpoint`` IMMEDIATELY after each durable
        # side-effect (integrity_passed after Dim 1-9 PASS, story_branch_pushed
        # after the push, merge_done after the CAS), so a crash mid-side-effect
        # never marks the next one done and ``on_resume`` continues from the right
        # substate (no double-merge). Each closure-side checkpoint is the merge of
        # the block's reached booleans onto the current progress.
        store = self._store()
        carried = _Carrier(progress)

        def _checkpoint(block_progress: ClosureProgress) -> None:
            carried.progress = _persist_block_progress(
                store, ctx, carried.progress, block_progress
            )

        block = run_pre_merge_and_merge_block(
            ctx,
            story_dir=s_dir,
            repos=_resolve_repos(cfg, s_dir),
            integrity_gate=integrity_gate,
            scan_port=cfg.scan_port,
            build_test_port=cfg.build_test_port,
            sanity_port=sanity_port,
            applicability=cfg.merge_applicability,
            sonar_config=cfg.sonar_config,
            git_backend=git_backend,
            checkpoint=_checkpoint,
            progress=progress,
            repo_runners=_resolve_repo_runners(cfg),
        )
        # Persist the durable checkpoints the block reached (idempotent with the
        # in-flight checkpoints above), BEFORE deciding the verdict.
        progress = _persist_block_progress(store, ctx, carried.progress, block.progress)
        if block.status is MergeBlockStatus.ESCALATED:
            return self._escalated(ctx, progress, tuple(block.errors))
        return progress

    def _run_finalization(
        self, ctx: StoryContext, s_dir: Path, story_closed: bool
    ) -> FinalizationResult:
        """Run the four non-blocking finalization steps (FK-29 §29.1.4 6-9).

        ``_require_finalization_collaborators`` (called at the start of
        ``_run_sequence``) guarantees the three seams are wired; bind them to
        non-optional locals so no ``type: ignore`` is needed (FIX-8).
        """
        doc_fidelity, vectordb_sync, guard_deactivation = (
            _require_finalization_locals(self._config)
        )
        return run_post_merge_finalization(
            ctx,
            story_dir=s_dir,
            story_closed=story_closed,
            doc_fidelity_port=doc_fidelity,
            vectordb_sync_port=vectordb_sync,
            guard_deactivation_port=guard_deactivation,
        )

    def _escalated(
        self,
        ctx: StoryContext,
        progress: ClosureProgress,
        errors: tuple[str, ...],
    ) -> HandlerResult:
        """Build an ESCALATED result, persisting the reached progress."""
        self._store().save_state(
            _closure_state(ctx.story_id, progress, PhaseStatus.ESCALATED)
        )
        logger.error("Closure ESCALATED for story=%s: %s", ctx.story_id, errors)
        return HandlerResult(status=PhaseStatus.ESCALATED, errors=errors)


# ----------------------------------------------------------------------
# Progress / state helpers
# ----------------------------------------------------------------------


@dataclass
class _Carrier:
    """Mutable closure-progress carrier for the in-block checkpoint sink (FIX-4)."""

    progress: ClosureProgress


def _resume_progress(envelope: PhaseEnvelope) -> ClosureProgress:
    """Read the durable ``ClosureProgress`` from the envelope (fresh => empty)."""
    payload = envelope.state.payload
    if isinstance(payload, ClosurePayload):
        return payload.progress
    return ClosureProgress()


def _closure_state(
    story_id: str, progress: ClosureProgress, status: PhaseStatus
) -> PhaseState:
    """Build the closure ``PhaseState`` carrying the current progress."""
    return PhaseState(
        story_id=story_id,
        phase="closure",
        status=status,
        payload=ClosurePayload(progress=progress),
    )


def _persist(
    store: ClosureProgressStore,
    ctx: StoryContext,
    progress: ClosureProgress,
    **updates: bool,
) -> ClosureProgress:
    """Apply checkpoint updates, persist the phase state, return new progress.

    Persists BEFORE the next irreversible side effect (FK-29 §29.1.0) through the
    injected pipeline-surface store (architecture-conformance AC003). The
    ``ClosureProgress`` validator enforces the monotonic checkpoint order, so an
    out-of-order update (e.g. ``merge_done`` without ``story_branch_pushed``)
    is rejected structurally.
    """
    updated = progress.model_copy(update=updates)
    store.save_state(_closure_state(ctx.story_id, updated, PhaseStatus.IN_PROGRESS))
    return updated


def _persist_block_progress(
    store: ClosureProgressStore,
    ctx: StoryContext,
    progress: ClosureProgress,
    block_progress: ClosureProgress,
) -> ClosureProgress:
    """Merge + persist the durable checkpoints the merge block reached.

    The block returns its own ``ClosureProgress`` (``integrity_passed`` /
    ``story_branch_pushed`` / ``merge_done`` as far as it got). This carries those
    forward onto the closure progress and persists checkpoint-safe.
    """
    merged = progress.model_copy(
        update={
            "integrity_passed": progress.integrity_passed
            or block_progress.integrity_passed,
            "story_branch_pushed": progress.story_branch_pushed
            or block_progress.story_branch_pushed,
            "merge_done": progress.merge_done or block_progress.merge_done,
        }
    )
    store.save_state(_closure_state(ctx.story_id, merged, PhaseStatus.IN_PROGRESS))
    return merged


def _require_finalization_collaborators(cfg: ClosureConfig) -> HandlerResult | None:
    """Fail closed when a mandatory finalization collaborator is unwired.

    Steps 6-9 run for EVERY story type (impl/bugfix and concept/research), so
    their seams are always required. A bare ``ClosureConfig`` without them is a
    misconfiguration -> FAILED (use ``build_closure_phase_handler``).
    """
    missing = [
        name
        for name, value in (
            ("progress_store", cfg.progress_store),
            ("doc_fidelity_port", cfg.doc_fidelity_port),
            ("vectordb_sync_port", cfg.vectordb_sync_port),
            ("guard_deactivation_port", cfg.guard_deactivation_port),
        )
        if value is None
    ]
    if missing:
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(
                f"Closure finalization collaborators not wired: {sorted(missing)} "
                "(use build_closure_phase_handler)",
            ),
        )
    return None


def _require_merge_collaborators(cfg: ClosureConfig) -> HandlerResult | None:
    """Fail closed when a mandatory impl/bugfix collaborator is unwired.

    ``scan_port`` / ``build_test_port`` are NOT in this required set: with AG3-056
    they are ``None`` for a DECLARED-ABSENT CI (``ci.available == false``, FK-29
    §29.1.1 / FK-33 §33.6.5 "absent != broken") and the merge block then runs
    without the integrated-candidate scan/build. An applicable-but-unreachable
    runner never reaches here as ``None`` -- the composition root raises
    ``PreMergeRunnerUnavailableError`` (fail-closed) before building the handler.
    The barrier itself fail-closes if exactly one of the two is wired.
    """
    missing = [
        name
        for name, value in (
            ("integrity_gate", cfg.integrity_gate),
            ("sanity_port", cfg.sanity_port),
            ("artifact_manager", cfg.artifact_manager),
        )
        if value is None
    ]
    if missing:
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(
                f"Closure merge collaborators not wired: {sorted(missing)} "
                "(use build_closure_phase_handler)",
            ),
        )
    return None


def _resolve_repos(cfg: ClosureConfig, s_dir: Path) -> tuple[ClosureRepo, ...]:
    """Resolve the participating repos (single-repo => one-element saga list)."""
    if cfg.repos:
        return cfg.repos
    return (ClosureRepo(name=s_dir.name, repo_root=s_dir),)


def _resolve_repo_runners(cfg: ClosureConfig) -> Mapping[Path, RepoRunners] | None:
    """Return the typed per-repo runner mapping (FIX-C), or ``None``.

    The composition root builds a :class:`RepoRunners` pair per
    ``ClosureRepo.repo_root`` (each bound to that repo's root/ledger/tree) and
    carries it on the config as a loosely-typed ``object``. This structurally
    validates it to ``Mapping[Path, RepoRunners]`` so the merge block selects each
    repo's own pair without a ``type: ignore`` (FIX-8). ``None`` => the single
    ``scan_port``/``build_test_port`` fallback (one repo).
    """
    from collections.abc import Mapping as _Mapping
    from typing import cast

    from agentkit.closure.merge_sequence import RepoRunners

    runners = cfg.repo_runners
    if runners is None:
        return None
    if not isinstance(runners, _Mapping):
        msg = (
            "repo_runners must be a Mapping[Path, RepoRunners]; "
            f"got {type(runners).__name__}"
        )
        raise TypeError(msg)
    for key, value in runners.items():
        if not isinstance(key, Path) or not isinstance(value, RepoRunners):
            msg = (
                "repo_runners keys must be Path and values RepoRunners; "
                f"got {type(key).__name__} -> {type(value).__name__}"
            )
            raise TypeError(msg)
    return cast("Mapping[Path, RepoRunners]", runners)


def _resolve_run_id_fail_closed(s_dir: Path) -> str | None:
    """Resolve the run-id from the runtime scope, fail-closed (FIX-7).

    For an impl/bugfix closure the Finding-Resolution-Gate MUST read the Layer-2
    artefacts of EXACTLY this run; a missing/corrupt runtime run scope must NOT
    fall back to ``run_id=None`` cross-run matching (a stale-finding risk the
    concept does not permit, FK-29 §29.2). Returns ``None`` on any failure /
    absent scope so the caller escalates (the gate is never run cross-run).
    """
    from agentkit.state_backend.store import resolve_runtime_scope

    try:
        run_id = resolve_runtime_scope(s_dir).run_id
    except Exception:  # noqa: BLE001 -- a missing/corrupt scope => fail-closed (None)
        return None
    return run_id or None


def _require_merge_locals(
    cfg: ClosureConfig,
) -> tuple[IntegrityGate, SanityGatePort, ArtifactManager]:
    """Return the merge collaborators as non-optional locals (FIX-8).

    ``_require_merge_collaborators`` has already rejected an unwired config, so
    these are guaranteed present here. Binding them to locals removes the
    ``type: ignore`` casts the runtime-None checks did not narrow.
    """
    integrity_gate = cfg.integrity_gate
    sanity_port = cfg.sanity_port
    artifact_manager = cfg.artifact_manager
    if integrity_gate is None or sanity_port is None or artifact_manager is None:
        msg = "merge collaborators must be validated before _require_merge_locals"
        raise AssertionError(msg)
    return integrity_gate, sanity_port, artifact_manager


def _require_finalization_locals(
    cfg: ClosureConfig,
) -> tuple[DocFidelityFeedbackPort, VectorDbSyncPort, GuardDeactivationPort]:
    """Return the finalization seams as non-optional locals (FIX-8).

    ``_require_finalization_collaborators`` validated these at the start of the
    sequence, so they are guaranteed present here.
    """
    doc = cfg.doc_fidelity_port
    vdb = cfg.vectordb_sync_port
    guard = cfg.guard_deactivation_port
    if doc is None or vdb is None or guard is None:
        msg = (
            "finalization collaborators must be validated before "
            "_require_finalization_locals"
        )
        raise AssertionError(msg)
    return doc, vdb, guard


def _git_backend_for(cfg: ClosureConfig) -> GitBackend | None:
    """Return the typed git backend for the merge block (``None`` => default).

    ``GitBackend`` is a (non-runtime-checkable) ``Protocol``; this structurally
    validates the duck-typed config value (``run`` + ``remove_worktree``) and
    casts it, so no ``type: ignore`` is needed for the saga call (FIX-8).
    """
    from typing import cast

    backend = cfg.git_backend
    if backend is None:
        return None
    if not (hasattr(backend, "run") and hasattr(backend, "remove_worktree")):
        msg = (
            "git_backend must implement the GitBackend protocol "
            f"(run/remove_worktree); got {type(backend).__name__}"
        )
        raise TypeError(msg)
    return cast("GitBackend", backend)


def _write_report(
    ctx: StoryContext,
    s_dir: Path,
    prior_phases: tuple[str, ...],
    metrics: StoryMetricsRecord,
    story_closed: bool,
    warnings: tuple[str, ...],
    status: str,
) -> Path:
    """Write the closure execution report (unchanged flat report, FK-29 §29.4)."""
    report = ExecutionReport(
        story_id=ctx.story_id,
        story_type=str(ctx.story_type.value),
        status=status,
        phases_executed=(*prior_phases, "closure"),
        started_at=ctx.created_at.isoformat() if ctx.created_at else None,
        completed_at=metrics.completed_at,
        story_closed=story_closed,
        warnings=warnings,
        metrics=metrics.to_metrics_payload(),
    )
    return write_execution_report(
        s_dir,
        report,
        projection_dir=resolve_qa_story_dir(
            s_dir, story_id=ctx.story_id, project_root=ctx.project_root
        ),
    )


def _completed_at() -> datetime:
    from datetime import UTC, datetime

    return datetime.now(tz=UTC)


def _validate_prior_phases(s_dir: Path, prior_phases: tuple[str, ...]) -> list[str]:
    """Return one error message per phase whose snapshot is missing or not COMPLETED."""
    missing: list[str] = []
    for phase in prior_phases:
        snapshot = load_phase_snapshot(s_dir, phase)
        if snapshot is None:
            missing.append(f"Phase '{phase}': no snapshot found")
            continue
        if snapshot.status != PhaseStatus.COMPLETED:
            missing.append(
                f"Phase '{phase}': status is "
                f"'{snapshot.status}', expected 'completed'",
            )
            continue
        if phase == "implementation":
            qa_status = snapshot.evidence.get("qa_cycle_status")
            if qa_status not in (None, QaCycleStatus.PASS.value):
                missing.append(
                    f"Phase 'implementation': qa_cycle_status is "
                    f"'{qa_status}', expected 'pass'",
                )
    return missing


def _close_github_issue(cfg: ClosureConfig) -> tuple[bool, list[str]]:
    """Best-effort GitHub issue close — returns ``(closed, warnings)``."""
    if not (
        cfg.close_issue
        and cfg.owner is not None
        and cfg.repo is not None
        and cfg.issue_nr is not None
    ):
        return False, []
    try:
        from agentkit.integrations.github.issues import (
            close_issue as gh_close_issue,
        )

        gh_close_issue(cfg.owner, cfg.repo, cfg.issue_nr)
    except IntegrationError as exc:
        issue_ref = f"{cfg.owner}/{cfg.repo}#{cfg.issue_nr}"
        warning_msg = f"Failed to close GitHub issue {issue_ref}: {exc}"
        logger.warning(warning_msg)
        return False, [warning_msg]
    logger.info(
        "Closed GitHub issue %s/%s#%d",
        cfg.owner, cfg.repo, cfg.issue_nr,
    )
    return True, []


def _resolve_metrics(
    s_dir: Path,
    ctx: StoryContext,
    status: str,
    already_written: bool,
) -> StoryMetricsRecord | HandlerResult:
    """Resolve the metrics record idempotently (FIX-5).

    If ``already_written`` (a resume after the metrics checkpoint), LOAD the
    existing persisted metrics instead of rebuilding + rewriting the projection
    (no second write, no clobber). Otherwise build the record and write the
    projection once.

    FK-29 §29.6: PostMergeFinalization is schema owner + writer for story_metrics
    via ``ProjectionAccessor.write_projection``. The accessor is built via the
    composition root (no direct facade import -- AC#7 analog).
    """
    from agentkit.bootstrap.composition_root import build_projection_accessor
    from agentkit.telemetry.projection_accessor import ProjectionKind

    if already_written:
        try:
            return _load_existing_metrics(s_dir, ctx, status)
        except Exception as exc:  # noqa: BLE001
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=(f"Failed to load existing story metrics on resume: {exc}",),
            )
    try:
        metrics = build_story_metrics_record(
            s_dir,
            ctx,
            completed_at=_completed_at(),
            final_status=status,
        )
        accessor = build_projection_accessor(s_dir)
        accessor.write_projection(ProjectionKind.STORY_METRICS, metrics)
    except Exception as exc:  # noqa: BLE001
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(f"Failed to materialize story metrics: {exc}",),
        )
    return metrics


def _load_existing_metrics(
    s_dir: Path,
    ctx: StoryContext,
    status: str,
) -> StoryMetricsRecord:
    """Return the PERSISTED metrics record on resume, NOT a rebuild (FIX-D/FIX-5).

    The ``metrics_written`` checkpoint guarantees a story_metrics projection was
    already written (it is the persisted truth). On resume the execution report
    must reuse THAT row -- not rebuild a fresh :class:`StoryMetricsRecord` with a
    NEW ``completed_at`` (which would diverge from the persisted projection).
    This loads the persisted row for exactly this run scope
    (``load_story_metrics(..., story_id, run_id)``); a missing projection on a
    ``metrics_written=true`` resume is a fail-closed corruption. The status param
    is unused on this path (the persisted record already carries its final
    status). FK-29 §29.6: the projection is written exactly once and read back
    here unchanged.
    """
    from agentkit.state_backend.store import load_story_metrics

    del status  # the persisted record is authoritative; no rebuild on resume.
    run_id = _resume_run_id(s_dir)
    persisted = load_story_metrics(
        s_dir,
        project_key=ctx.project_key,
        story_id=ctx.story_id,
        run_id=run_id,
    )
    if not persisted:
        msg = (
            "metrics_written=true but no story_metrics projection is persisted "
            f"for story={ctx.story_id!r} run_id={run_id!r} (state corruption); "
            "fail-closed rather than silently rewrite"
        )
        raise ValueError(msg)
    # The latest persisted row for this run scope is the authoritative metrics.
    return persisted[-1]


def _resume_run_id(s_dir: Path) -> str | None:
    """Resolve the run-id for the metrics-resume read (best-effort, FIX-D).

    The metrics projection is keyed by ``(project_key, story_id, run_id)``; the
    run-id is read from the runtime scope so the loaded row is exactly THIS run's
    persisted metrics. An unresolvable scope returns ``None`` (the read then
    matches on ``(project_key, story_id)`` only -- still this story's own rows).
    """
    from agentkit.state_backend.store import resolve_runtime_scope

    try:
        return resolve_runtime_scope(s_dir).run_id or None
    except Exception:  # noqa: BLE001 -- best-effort scope read for the metrics key
        return None


def _transition_story_done(
    cfg: ClosureConfig, story_id: str,
) -> HandlerResult | None:
    """Call ``complete_story`` (default service) — return None on success."""
    story_service = cfg.story_service
    if story_service is None:
        from agentkit.story_context_manager.service import StoryService as _StoryService
        story_service = _StoryService()
    try:
        story_service.complete_story(story_id)
    except Exception as cs_err:  # noqa: BLE001
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(f"complete_story failed: {cs_err}",),
        )
    return None


__all__ = [
    "ClosureConfig",
    "ClosurePhaseHandler",
    "ClosureProgressStore",
    "ClosureVerdict",
]
