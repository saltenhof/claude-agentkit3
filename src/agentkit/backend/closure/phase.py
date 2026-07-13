"""Closure phase handler -- orchestrates the canonical closure sequence (FK-29).

The handler calls the existing Finding-Resolution-Gate, pre-merge block, story
transition, metrics writer, and post-merge finalization in order. It owns no
second merge, gate, Sonar, lock, or metrics truth; collaborators are injected by
the composition root.

``ClosureProgress`` is the single recovery truth and is persisted before the
next irreversible side effect. Concept/research stories skip merge-only gates via
the typed story profile and still run finalization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.closure.edge_merge import (
    EdgeCandidateEvidence,
    EdgeMergeState,
    apply_merge_local_report,
)
from agentkit.backend.closure.execution_report.records import ExecutionReport
from agentkit.backend.closure.execution_report.writer import write_execution_report
from agentkit.backend.closure.gates import (
    ABSENT_TELEMETRY_EVIDENCE_PORT,
    evaluate_finding_resolution_gate,
    evaluate_implementation_evidence_gate,
)
from agentkit.backend.closure.merge_sequence import (
    ClosureRepo,
    MergeApplicability,
    MergeBlockStatus,
    run_fast_merge_block,
    run_pre_merge_and_merge_block,
)
from agentkit.backend.closure.post_merge_finalization.finalization import (
    run_post_merge_finalization,
)
from agentkit.backend.closure.post_merge_finalization.metrics import (
    build_story_metrics_record,
)
from agentkit.backend.core_types.closure import ClosureVerdict
from agentkit.backend.installer.paths import resolve_qa_story_dir
from agentkit.backend.pipeline_engine.lifecycle import HandlerResult
from agentkit.backend.pipeline_engine.phase_executor import (
    ClosurePayload,
    ClosureProgress,
    EscalationReason,
    PhaseState,
    PhaseStatus,
    QaCycleStatus,
    evolve_phase_state,
)
from agentkit.backend.state_backend.governance_runtime_store import (
    bind_ownership_fence_scope,
    resolve_ownership_fence_snapshot,
)
from agentkit.backend.state_backend.pipeline_runtime_store import (
    load_phase_snapshot,
)
from agentkit.backend.state_backend.runtime_scope_resolver import (
    resolve_runtime_scope,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    save_story_context,
)
from agentkit.backend.story_context_manager.types import get_profile
from agentkit.backend.verify_system.structural.system_evidence import (
    ABSENT_CHANGE_EVIDENCE_PORT,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import AbstractContextManager
    from datetime import datetime

    from agentkit.backend.artifacts import ArtifactManager
    from agentkit.backend.closure.edge_merge import MergeLocalCommandPort
    from agentkit.backend.closure.gates import TelemetryEvidencePort
    from agentkit.backend.closure.merge_sequence import (
        BuildTestPort,
        PreMergeScanPort,
        RepoRunners,
        SanityGatePort,
    )
    from agentkit.backend.closure.multi_repo_saga import GitBackend
    from agentkit.backend.closure.post_merge_finalization.finalization import (
        DocFidelityFeedbackPort,
        FinalizationResult,
        GuardDeactivationPort,
        VectorDbSyncPort,
    )
    from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.backend.governance.integrity_gate import IntegrityGate
    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.verify_system.pre_merge_runner.contract import CandidateRef
    from agentkit.backend.verify_system.structural.system_evidence import (
        ChangeEvidencePort,
        PushVerificationPort,
    )

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


class ModeLockReleasePort(Protocol):
    """Project mode-lock release seam at story close (FK-24 §24.3.3, AG3-018).

    The release half of the Fast/Standard between-modes mutex. Closure holds no
    mode-lock logic itself; this seam delegates to the atomic
    ``ModeLockRepository.release`` (wired by the composition root). The release is
    idempotent via the durable per-story acquire marker ALONE (FIX-4 — NOT a
    seventh ``ClosureProgress`` checkpoint; FK-29 §29.1.0 defines exactly six):
    the port releases once and clears the marker, so a resumed/cancelled closure
    finds no marker and never double-releases the holder count.
    """

    def release(self, story_dir: Path, project_key: str) -> tuple[bool, str | None]:
        """Release this story's mode-lock holder; ``(released, warning)``."""
        ...


class GuardCounterFlushPort(Protocol):
    """Closure flush trigger for the guard-invocation counters (FK-61 §61.4.3, AG3-081).

    Trigger 1 of the four FK-61 §61.4.3 flush triggers: at Closure the story's
    ``guard_invocation_counters`` rows are drained (read + deleted) so the
    (follow-up) RefreshWorker (AG3-082) can re-aggregate them into
    ``fact_guard_period``. Closure holds no counter logic itself; this seam
    delegates to the kpi-owned ``GuardCounterService.flush_on_closure`` (wired by
    the composition root). Non-blocking: a flush issue is a human Warning, never an
    escalation (the story is already merged + closed).
    """

    def flush_on_closure(
        self, story_dir: Path, *, project_key: str, story_id: str
    ) -> tuple[bool, str | None]:
        """Drain the story's guard counters at Closure; ``(flushed, warning)``."""
        ...


@dataclass
class ClosureConfig:
    """Configuration + injected collaborators for the closure phase handler.

    Attributes:
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
        telemetry_evidence_port: Telemetry-Evidence-Block seam (FK-68 §68.4,
            AG3-081). Runs the six FK-68 §68.4 proofs against the run's
            ``execution_events`` at Closure (fail-closed). The composition root
            wires ``ProductiveTelemetryEvidencePort``; ``None`` falls back to the
            vacuous ``ABSENT_TELEMETRY_EVIDENCE_PORT`` (non-telemetry test path).
        guard_counter_flush_port: Closure guard-counter flush seam (FK-61 §61.4.3
            Trigger 1, AG3-081). Drains the story's ``guard_invocation_counters``
            at Closure (non-blocking). The composition root wires
            ``ProductiveGuardCounterFlushPort``; ``None`` is a no-op (standalone /
            legacy).
    """

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
    mode_lock_release_port: ModeLockReleasePort | None = None
    change_evidence_port: ChangeEvidencePort | None = None
    telemetry_evidence_port: TelemetryEvidencePort | None = None
    guard_counter_flush_port: GuardCounterFlushPort | None = None
    merge_local_port: MergeLocalCommandPort | None = None
    push_verification_port: PushVerificationPort | None = None


class ClosurePhaseHandler:
    """Phase handler for the Closure phase (FK-29 §29.1).

    Implements the :class:`~agentkit.backend.pipeline_engine.lifecycle.PhaseHandler`
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

        terminality_error = self._validate_implementation_terminality(
            ctx, s_dir, envelope.state, _resume_progress(envelope)
        )
        if terminality_error is not None:
            return terminality_error

        prior_phases = self._prior_phases(ctx)
        missing = _validate_prior_phases(s_dir, prior_phases)
        if missing:
            return HandlerResult(status=PhaseStatus.FAILED, errors=tuple(missing))

        progress = _resume_progress(envelope)
        return self._run_sequence(ctx, s_dir, envelope.state, prior_phases, progress)

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
        terminality_error = self._validate_implementation_terminality(
            ctx, s_dir, envelope.state, _resume_progress(envelope)
        )
        if terminality_error is not None:
            return terminality_error
        prior_phases = self._prior_phases(ctx)
        progress = _resume_progress(envelope)
        return self._run_sequence(ctx, s_dir, envelope.state, prior_phases, progress)

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
        """The required prior phases from the typed story-type profile.

        AG3-018 (FK-24 §24.3.4): a fast story SKIPS the Exploration phase, so it
        never produces an exploration snapshot. The closure prior-phase
        validation must therefore not require one for a fast story (it routed
        setup -> implementation directly). The non-fast behaviour is unchanged
        (the full profile, exploration included).
        """
        from agentkit.backend.story_context_manager.story_model import WireStoryMode

        prior = get_profile(ctx.story_type).phases[:-1]
        if ctx.mode is WireStoryMode.FAST:
            return tuple(p for p in prior if p != "exploration")
        return prior

    def _validate_implementation_terminality(
        self,
        ctx: StoryContext,
        s_dir: Path,
        source_state: PhaseState,
        progress: ClosureProgress,
    ) -> HandlerResult | None:
        """Block impl/bugfix closure before prior validation when evidence is absent."""
        from agentkit.backend.story_context_manager.types import StoryType
        if ctx.story_type not in (StoryType.IMPLEMENTATION, StoryType.BUGFIX):
            return None
        if ctx.closure_allowed is False:
            return self._escalated(
                ctx,
                source_state,
                progress,
                (
                    "Implementation-Evidence-Gate: closure_allowed=false after "
                    "exploration; implementation execution is still required "
                    "(FK-24 §24.5.2 / §24.8.2).",
                ),
                reason=EscalationReason.IMPLEMENTATION_REQUIRED_AFTER_EXPLORATION,
            )
        change_evidence_port = (
            self._config.change_evidence_port or ABSENT_CHANGE_EVIDENCE_PORT
        )
        gate = evaluate_implementation_evidence_gate(
            story_type=ctx.story_type,
            story_dir=s_dir,
            change_evidence=change_evidence_port.collect(s_dir),
        )
        if gate.passed:
            return None
        return self._escalated(
            ctx,
            source_state,
            progress,
            (
                gate.blocking_reason
                or "Implementation-Evidence-Gate: implementation evidence missing.",
            ),
            reason=EscalationReason.IMPLEMENTATION_REQUIRED_AFTER_EXPLORATION,
        )

    def _run_sequence(
        self,
        ctx: StoryContext,
        s_dir: Path,
        source_state: PhaseState,
        prior_phases: tuple[str, ...],
        progress: ClosureProgress,
    ) -> HandlerResult:
        """Run the closure sequence, dispatching over the resume ``progress``."""
        cfg = self._config

        # AG3-069 (FK-05 §5.11): integration_stabilization closure precondition.
        # Checked BEFORE finalization-collaborator wiring so IS stories are
        # rejected early (fail-closed). Gated on the IS contract so standard
        # stories are completely unaffected (CORE PRINCIPLE).
        is_precondition_error = _check_integration_stabilization_closure(
            ctx, s_dir
        )
        if is_precondition_error is not None:
            return is_precondition_error

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
            merge_outcome = self._reach_merge_done(
                ctx,
                s_dir,
                source_state,
                uses_merge,
                progress,
            )
            if isinstance(merge_outcome, HandlerResult):
                return merge_outcome
            progress = merge_outcome

        # Step 4: story status Done. AK3 owns the story (FK-91 §91.2 rule 9): the
        # story is closed via the AK3 Story-Service, not a GitHub issue. On resume
        # (already closed) we do NOT re-transition; FIX-5: the authoritative closed
        # flag is ``progress.story_closed`` (never reset to False locally on resume).
        if not progress.story_closed:
            transition_error = _transition_story_done(cfg, ctx.story_id)
            if transition_error is not None:
                return transition_error
            ctx = _persist_story_done(s_dir, ctx)
            progress = _persist(store, source_state, progress, story_closed=True)
        else:
            ctx = _persist_story_done(s_dir, ctx)

        # Step 5: metrics (FIX-5: idempotent). If already written, LOAD the
        # existing metrics record instead of rebuilding + rewriting it.
        # AG3-144 (FK-91 §91.1a Rule 15): the story_metrics upsert is a fenced
        # Postgres write boundary; _bind_story_metrics_fence_scope binds the
        # early lease snapshot around it (behaviour-preserving extraction).
        status = "completed"
        with _bind_story_metrics_fence_scope(s_dir, ctx):
            metrics_or_error = _resolve_metrics(s_dir, ctx, status, progress.metrics_written)
        if isinstance(metrics_or_error, HandlerResult):
            return metrics_or_error
        metrics = metrics_or_error
        if not progress.metrics_written:
            progress = _persist(store, source_state, progress, metrics_written=True)

        # Steps 6-9: post-merge finalization (non-blocking). FIX-5: idempotent --
        # if postflight already ran (``postflight_done``) it is NOT re-run; the
        # real ``progress.story_closed`` is passed into postflight (never a reset
        # False on resume, which would raise a false postflight warning).
        finalization: FinalizationResult | None = None
        if not progress.postflight_done:
            finalization = self._run_finalization(ctx, s_dir, progress.story_closed)
            progress = _persist(store, source_state, progress, postflight_done=True)

        finalization_warnings = finalization.warnings if finalization is not None else ()

        # FK-24 §24.3.3 (AG3-018, FIX-4): RELEASE the project mode-lock holder at
        # story close (the release half of the between-modes mutex). Idempotency is
        # the durable per-story acquire marker ALONE — NOT a seventh
        # ``ClosureProgress`` checkpoint (FK-29 §29.1.0 defines exactly six). The
        # release reads the marker, releases once and CLEARS the marker; a resumed
        # closure then finds no marker and owes nothing (no double-release).
        # Non-blocking: a release issue is a human Warning, never an ESCALATED
        # verdict (the story is already merged + closed).
        release_warnings = self._release_mode_lock(ctx, s_dir)

        # FK-61 §61.4.3 Trigger 1 (Closure, AG3-081 AC5): drain the story's
        # guard-invocation counters so the RefreshWorker (AG3-082) re-aggregates
        # them into ``fact_guard_period``. Non-blocking: a flush issue is a human
        # Warning (the story is already merged + closed).
        counter_flush_warnings = self._flush_guard_counters(ctx, s_dir)

        all_warnings = (
            *finalization_warnings,
            *release_warnings,
            *counter_flush_warnings,
        )
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
            updated_state=_closure_state(source_state, progress, PhaseStatus.COMPLETED),
        )

    def _reach_merge_done(
        self,
        ctx: StoryContext,
        s_dir: Path,
        source_state: PhaseState,
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
                source_state,
                progress,
                integrity_passed=True,
                story_branch_pushed=True,
                merge_done=True,
            )
        return self._run_merge_block(ctx, s_dir, source_state, progress)

    def _store(self) -> ClosureProgressStore:
        """Return the wired checkpoint store (guaranteed non-None at this point)."""
        store = self._config.progress_store
        assert store is not None  # noqa: S101 -- guaranteed by the collaborator check
        return store

    def _run_merge_block(
        self,
        ctx: StoryContext,
        s_dir: Path,
        source_state: PhaseState,
        progress: ClosureProgress,
    ) -> ClosureProgress | HandlerResult:
        """Run the Finding-Gate + locked merge block for an impl/bugfix story."""
        cfg = self._config

        # AG3-018 (FK-24 §24.3.4 / FK-29 §29.1a.6): a FAST story produces NO QA
        # Layer-2 findings (QA-subflow layers 2-4 = OUT) so the
        # Finding-Resolution-Gate is OUT, and it uses the Sanity-Gate (not the
        # CI/9-dim block) so the CI-absent applicability gate does not apply.
        # Route straight to the merge block, which dispatches fast -> Sanity-Gate.
        if _is_fast_mode(ctx):
            return self._run_fast_merge_block(ctx, s_dir, source_state, progress)

        # FIX-3: model declared-absence at the applicability layer. A
        # code-producing story whose CI is declared absent has no Build/Test+scan
        # runner -> the integrated candidate cannot be verified -> fail-closed
        # (cannot verify => cannot merge). Decided HERE (the handler), never by
        # silently skipping inside the block (NO ERROR BYPASSING, FK-33 §33.6.5).
        if cfg.merge_applicability is MergeApplicability.CI_ABSENT:
            return self._escalated(
                ctx,
                source_state,
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
        integrity_gate, artifact_manager = _require_merge_locals(cfg)

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
                source_state,
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
                ctx,
                source_state,
                progress,
                (gate.blocking_reason or "finding resolution failed",),
            )

        # Step 2b: Telemetry-Evidence-Block (FK-68 §68.4, AG3-081 AC3). BEFORE the
        # irreversible merge block, the six FK-68 §68.4 proofs are evaluated
        # against the run's ``execution_events`` stream; a violation blocks
        # closure fail-closed (NO ERROR BYPASSING). This is the
        # "Telemetry-Evidence-Block (FK-68 §68.4)", NOT the IntegrityGate
        # dimension 8 (story §1 naming discipline). Skipped only when no port is
        # wired (the non-telemetry test fallback never softens a wired contract).
        telemetry_port = cfg.telemetry_evidence_port or ABSENT_TELEMETRY_EVIDENCE_PORT
        telemetry_verdict = telemetry_port.evaluate(
            s_dir, story_id=ctx.story_id, run_id=run_id
        )
        if not telemetry_verdict.passed:
            return self._escalated(
                ctx,
                source_state,
                progress,
                (
                    telemetry_verdict.blocking_reason
                    or "Telemetry-Evidence-Block (FK-68 §68.4) failed at Closure",
                ),
            )

        if cfg.git_backend is not None:
            return self._run_injected_standard_merge(
                ctx, s_dir, source_state, progress, integrity_gate
            )
        return self._run_edge_merge(
            ctx,
            s_dir,
            source_state,
            progress,
            run_id=run_id,
            verify_integrity=True,
            integrity_gate=integrity_gate,
        )

    def _run_fast_merge_block(
        self,
        ctx: StoryContext,
        s_dir: Path,
        source_state: PhaseState,
        progress: ClosureProgress,
    ) -> ClosureProgress | HandlerResult:
        """Run the fast-mode merge block (FK-29 §29.1a.6, FK-24 §24.3.4).

        Fast skips the Finding-Resolution-Gate (no QA Layer-2 findings produced)
        and the CI/9-dim barrier; the merge precondition is the Sanity-Gate
        (tests green + worktree clean + pre-merge rebase OK). Only the
        ``sanity_port`` collaborator is required for this path; FIX-8: it calls
        the dedicated fast-only :func:`run_fast_merge_block` entrypoint, which
        does NOT take ``integrity_gate`` -- removing the ``type: ignore`` that
        passing an optional gate into the standard entrypoint required.
        """
        if self._config.git_backend is not None:
            return self._run_injected_fast_merge(ctx, s_dir, source_state, progress)
        run_id = _resolve_run_id_fail_closed(s_dir)
        if run_id is None:
            return self._escalated(
                ctx,
                source_state,
                progress,
                ("cannot resolve run scope for edge merge commissioning",),
            )
        return self._run_edge_merge(
            ctx,
            s_dir,
            source_state,
            progress,
            run_id=run_id,
            verify_integrity=False,
            integrity_gate=None,
        )

    def _run_edge_merge(  # noqa: PLR0911 -- one fail-closed return per boundary
        self,
        ctx: StoryContext,
        s_dir: Path,
        source_state: PhaseState,
        progress: ClosureProgress,
        *,
        run_id: str,
        verify_integrity: bool,
        integrity_gate: IntegrityGate | None,
    ) -> ClosureProgress | HandlerResult:
        """Verify the edge candidate, then commission/consume ``merge_local``."""
        from agentkit.backend.core_types import PauseReason
        from agentkit.backend.verify_system.pre_merge_runner.contract import CandidateRef

        prepared = self._prepare_edge_merge(
            ctx, s_dir, source_state, progress, run_id=run_id
        )
        if isinstance(prepared, HandlerResult):
            return prepared
        port, repo_ids, candidate = prepared
        cfg = self._config
        store = self._store()
        if not progress.story_branch_pushed:
            progress = _persist(
                store, source_state, progress, story_branch_pushed=True
            )
        candidate_ref = CandidateRef(
            branch=f"story/{ctx.story_id}",
            commit_sha=candidate.commit_sha,
            tree_hash=candidate.tree_hash,
        )
        if not progress.integrity_passed:
            build_error = _verify_edge_build(cfg, candidate_ref)
            if build_error is not None:
                return self._escalated(
                    ctx, source_state, progress, (build_error,)
                )
            if verify_integrity:
                gate_error = _verify_edge_integrity(
                    cfg, s_dir, ctx, candidate_ref, integrity_gate
                )
                if gate_error is not None:
                    return self._escalated(
                        ctx, source_state, progress, (gate_error,)
                    )
            progress = _persist(
                store, source_state, progress, integrity_passed=True
            )
        outcome = port.execute(
            project_key=ctx.project_key,
            story_id=ctx.story_id,
            run_id=run_id,
            repo_ids=repo_ids,
            candidate=candidate,
            mode="fast" if _is_fast_mode(ctx) else "standard",
        )
        if outcome.state is EdgeMergeState.PENDING:
            return HandlerResult(
                status=PhaseStatus.PAUSED,
                yield_status=PauseReason.AWAITING_EDGE_PROVISIONING.value,
            )
        if outcome.state is EdgeMergeState.ESCALATED or outcome.report is None:
            return self._escalated(
                ctx,
                source_state,
                progress,
                (outcome.detail or "edge merge_local escalated",),
            )
        progress, multi_repo = apply_merge_local_report(progress, outcome.report)
        store.save_state(
            evolve_phase_state(
                source_state,
                phase="closure",
                status=PhaseStatus.IN_PROGRESS,
                payload=ClosurePayload(progress=progress, multi_repo=multi_repo),
                pause_reason=None,
            )
        )
        return progress

    def _prepare_edge_merge(
        self,
        ctx: StoryContext,
        story_dir: Path,
        source_state: PhaseState,
        progress: ClosureProgress,
        *,
        run_id: str,
    ) -> tuple[MergeLocalCommandPort, tuple[str, ...], EdgeCandidateEvidence] | HandlerResult:
        """Validate collaborators and the edge candidate before any gate runs."""
        cfg = self._config
        port = cfg.merge_local_port
        push_verification = cfg.push_verification_port
        if port is None or push_verification is None:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=("Closure edge merge collaborators are not wired",),
            )
        repo_ids = _resolve_repo_ids(ctx, cfg, story_dir)
        if len(repo_ids) != 1:
            return self._escalated(
                ctx,
                source_state,
                progress,
                ("merge_local preserves the >=2-repository fail-closed boundary",),
            )
        if not push_verification.confirm_story_pushed(story_dir):
            return self._escalated(
                ctx,
                source_state,
                progress,
                ("merge_local requires the passed AG3-147 closure-entry push checkpoint",),
            )
        candidate = port.candidate(
            project_key=ctx.project_key,
            story_id=ctx.story_id,
            run_id=run_id,
            repo_id=repo_ids[0],
        )
        if candidate is None:
            return self._escalated(
                ctx,
                source_state,
                progress,
                ("verified push has no edge-reported candidate commit/tree binding",),
            )
        candidate_error = _validate_edge_candidate(candidate)
        if candidate_error is not None:
            return self._escalated(
                ctx, source_state, progress, (candidate_error,)
            )
        return port, repo_ids, candidate

    def _run_injected_standard_merge(
        self,
        ctx: StoryContext,
        story_dir: Path,
        source_state: PhaseState,
        progress: ClosureProgress,
        integrity_gate: IntegrityGate,
    ) -> ClosureProgress | HandlerResult:
        """Preserve the explicit fake-Git unit-test seam; production never wires it."""
        cfg = self._config
        store = self._store()
        carried = _Carrier(progress)

        def checkpoint(block_progress: ClosureProgress) -> None:
            carried.progress = _persist_block_progress(
                store, source_state, carried.progress, block_progress
            )

        block = run_pre_merge_and_merge_block(
            ctx,
            story_dir=story_dir,
            repos=_resolve_repos(cfg, story_dir),
            integrity_gate=integrity_gate,
            scan_port=cfg.scan_port,
            build_test_port=cfg.build_test_port,
            sanity_port=_require_injected_sanity(cfg),
            applicability=cfg.merge_applicability,
            sonar_config=cfg.sonar_config,
            git_backend=_git_backend_for(cfg),
            checkpoint=checkpoint,
            progress=progress,
            repo_runners=_resolve_repo_runners(cfg),
        )
        progress = _persist_block_progress(
            store, source_state, carried.progress, block.progress
        )
        if block.status is MergeBlockStatus.ESCALATED:
            return self._escalated(ctx, source_state, progress, tuple(block.errors))
        return progress

    def _run_injected_fast_merge(
        self,
        ctx: StoryContext,
        story_dir: Path,
        source_state: PhaseState,
        progress: ClosureProgress,
    ) -> ClosureProgress | HandlerResult:
        """Preserve fast-mode fake-Git unit tests; production uses Project Edge."""
        cfg = self._config
        store = self._store()
        carried = _Carrier(progress)

        def checkpoint(block_progress: ClosureProgress) -> None:
            carried.progress = _persist_block_progress(
                store, source_state, carried.progress, block_progress
            )

        block = run_fast_merge_block(
            ctx,
            story_dir=story_dir,
            repos=_resolve_repos(cfg, story_dir),
            sanity_port=_require_injected_sanity(cfg),
            git_backend=_git_backend_for(cfg),
            checkpoint=checkpoint,
            progress=progress,
        )
        progress = _persist_block_progress(
            store, source_state, carried.progress, block.progress
        )
        if block.status is MergeBlockStatus.ESCALATED:
            return self._escalated(ctx, source_state, progress, tuple(block.errors))
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

    def _release_mode_lock(
        self, ctx: StoryContext, s_dir: Path
    ) -> tuple[str, ...]:
        """Release the project mode-lock holder (FK-24 §24.3.3, non-blocking).

        Delegates to the injected :class:`ModeLockReleasePort` (the atomic
        ``ModeLockRepository.release``). When no port is wired (standalone /
        legacy) the step is a no-op. Any release issue is returned as a human
        Warning (never an escalation -- the story is already closed). The port's
        own idempotency reads (and then clears) the durable acquire marker, so a
        story that never acquired -- or a resumed closure that already released --
        owes no release (FIX-4: no seventh checkpoint needed).

        Args:
            ctx: The story context.
            s_dir: The story working directory.

        Returns:
            A tuple of human Warnings (empty on success / no-op).
        """
        port = self._config.mode_lock_release_port
        if port is None:
            return ()
        try:
            released, warning = port.release(s_dir, ctx.project_key)
        except Exception as exc:  # noqa: BLE001 -- non-blocking post-close step
            logger.warning(
                "mode-lock release failed for story=%s: %s", ctx.story_id, exc
            )
            return (f"mode-lock release raised: {exc}",)
        if not released and warning is not None:
            return (warning,)
        return ()

    def _flush_guard_counters(
        self, ctx: StoryContext, s_dir: Path
    ) -> tuple[str, ...]:
        """Drain the story's guard-invocation counters at Closure (FK-61 §61.4.3).

        Trigger 1 (Closure) of the four FK-61 §61.4.3 flush triggers. Delegates to
        the injected :class:`GuardCounterFlushPort`; when no port is wired
        (standalone / legacy) the step is a no-op. Any flush issue is returned as a
        human Warning (never an escalation — the story is already merged + closed).

        Args:
            ctx: The story context.
            s_dir: The story working directory.

        Returns:
            A tuple of human Warnings (empty on success / no-op).
        """
        port = self._config.guard_counter_flush_port
        if port is None:
            return ()
        try:
            flushed, warning = port.flush_on_closure(
                s_dir, project_key=ctx.project_key, story_id=ctx.story_id
            )
        except Exception as exc:  # noqa: BLE001 -- non-blocking post-close step
            logger.warning(
                "guard-counter Closure flush failed for story=%s: %s",
                ctx.story_id,
                exc,
            )
            return (f"guard-counter Closure flush raised: {exc}",)
        if not flushed and warning is not None:
            return (warning,)
        return ()

    def _escalated(
        self,
        ctx: StoryContext,
        source_state: PhaseState,
        progress: ClosureProgress,
        errors: tuple[str, ...],
        *,
        reason: EscalationReason | None = None,
    ) -> HandlerResult:
        """Build an ESCALATED result, persisting the reached progress."""
        state = _closure_state(source_state, progress, PhaseStatus.ESCALATED)
        if reason is not None:
            state = evolve_phase_state(state, escalation_reason=reason)
        self._store().save_state(state)
        logger.error("Closure ESCALATED for story=%s: %s", ctx.story_id, errors)
        return HandlerResult(
            status=PhaseStatus.ESCALATED,
            errors=errors,
            updated_state=state,
        )


# ----------------------------------------------------------------------
# Progress / state helpers
# ----------------------------------------------------------------------


@dataclass
class _Carrier:
    """Mutable closure-progress carrier for the in-block checkpoint sink (FIX-4)."""

    progress: ClosureProgress


def _is_fast_mode(ctx: StoryContext) -> bool:
    """Whether the story runs in fast mode (FK-24 §24.3.3, decoupled axis)."""
    from agentkit.backend.story_context_manager.story_model import WireStoryMode

    return ctx.mode is WireStoryMode.FAST


def _resume_progress(envelope: PhaseEnvelope) -> ClosureProgress:
    """Read the durable ``ClosureProgress`` from the envelope (fresh => empty)."""
    payload = envelope.state.payload
    if isinstance(payload, ClosurePayload):
        return payload.progress
    return ClosureProgress()


def _closure_state(
    source_state: PhaseState, progress: ClosureProgress, status: PhaseStatus
) -> PhaseState:
    """Build the closure ``PhaseState`` carrying the current progress."""
    return evolve_phase_state(
        source_state,
        phase="closure",
        status=status,
        payload=ClosurePayload(progress=progress),
        pause_reason=None,
        escalation_reason=source_state.escalation_reason
        if status is PhaseStatus.ESCALATED
        else None,
    )


def _persist(
    store: ClosureProgressStore,
    source_state: PhaseState,
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
    store.save_state(_closure_state(source_state, updated, PhaseStatus.IN_PROGRESS))
    return updated


def _persist_block_progress(
    store: ClosureProgressStore,
    source_state: PhaseState,
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
    store.save_state(_closure_state(source_state, merged, PhaseStatus.IN_PROGRESS))
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
    edge_ports: tuple[tuple[str, object | None], ...] = (
        ()
        if cfg.git_backend is not None
        else (
            ("merge_local_port", cfg.merge_local_port),
            ("push_verification_port", cfg.push_verification_port),
        )
    )
    missing = [
        name
        for name, value in (
            ("integrity_gate", cfg.integrity_gate),
            ("artifact_manager", cfg.artifact_manager),
            *edge_ports,
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


def _require_injected_sanity(cfg: ClosureConfig) -> SanityGatePort:
    """Return the explicit fake-Git test seam's sanity port."""
    if cfg.sanity_port is None:
        raise AssertionError("the injected fake-Git test seam requires sanity_port")
    return cfg.sanity_port


def _resolve_repos(cfg: ClosureConfig, s_dir: Path) -> tuple[ClosureRepo, ...]:
    """Resolve the participating repos (single-repo => one-element saga list)."""
    if cfg.repos:
        return cfg.repos
    return (ClosureRepo(name=s_dir.name, repo_root=s_dir),)


def _resolve_repo_ids(
    ctx: StoryContext, cfg: ClosureConfig, s_dir: Path
) -> tuple[str, ...]:
    """Resolve repository identities without deriving physical paths."""
    if ctx.participating_repos:
        return tuple(ctx.participating_repos)
    if cfg.repos:
        return tuple(repo.name for repo in cfg.repos)
    return (s_dir.name,)


def _validate_edge_candidate(candidate: EdgeCandidateEvidence) -> str | None:
    """Enforce edge-reported clean/contains-main candidate preconditions."""
    if not candidate.worktree_clean:
        return "edge-reported merge candidate worktree is not clean"
    if not candidate.base_ancestor:
        return "edge-reported merge candidate does not contain closure-entry main"
    return None


def _verify_edge_build(
    cfg: ClosureConfig, candidate: CandidateRef
) -> str | None:
    """Run the commit-bound CI facet against an edge-reported candidate."""
    if cfg.build_test_port is None:
        return "pre-merge Build/Test runner is not wired (fail-closed)"
    outcome = cfg.build_test_port.run(candidate)
    if outcome.green:
        return None
    return outcome.reason or "integrated-candidate Build/Test was not green"


def _verify_edge_integrity(
    cfg: ClosureConfig,
    story_dir: Path,
    ctx: StoryContext,
    candidate: CandidateRef,
    integrity_gate: IntegrityGate | None,
) -> str | None:
    """Verify scan binding and Integrity-Gate without re-measuring git."""
    from agentkit.backend.config.models import SonarQubeConfig
    from agentkit.backend.governance.integrity_gate.dim9_sonar import FreshAttestation

    if integrity_gate is None:
        return "Closure integrity gate is not wired"
    fresh = None
    if cfg.merge_applicability is MergeApplicability.FULL:
        if cfg.scan_port is None:
            return "pre-merge scan runner is not wired (fail-closed)"
        scan = cfg.scan_port.produce_attestation(candidate)
        if (
            not scan.produced
            or scan.commit_sha != candidate.commit_sha
            or scan.tree_hash != candidate.tree_hash
            or scan.attestation is None
        ):
            return scan.reason or "scan commit/tree binding does not match edge candidate"
        sonar_config = (
            cfg.sonar_config
            if isinstance(cfg.sonar_config, SonarQubeConfig)
            else None
        )
        fresh = FreshAttestation(
            attestation=scan.attestation,
            expected_main_revision=candidate.commit_sha,
            config=sonar_config,
            gate_outcome=scan.gate_outcome,
        )
    gate = integrity_gate.evaluate(
        story_dir, ctx.story_type, fresh_attestation=fresh
    )
    if gate.passed:
        return None
    return gate.failure_reason or "IntegrityGate did not pass"


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

    from agentkit.backend.closure.merge_sequence import RepoRunners

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
    try:
        run_id = resolve_runtime_scope(s_dir).run_id
    except Exception:  # noqa: BLE001 -- a missing/corrupt scope => fail-closed (None)
        return None
    return run_id or None


def _bind_story_metrics_fence_scope(
    s_dir: Path, ctx: StoryContext,
) -> AbstractContextManager[None]:
    """Acquire the AG3-144 ownership-lease fence scope for the closure Step-5
    ``story_metrics`` write (FK-91 §91.1a Rule 15).

    Extracted from ``_run_sequence`` so the fence-scope acquisition (run-id
    resolution + early lease-snapshot capture + bind) is one named unit instead
    of inflating the closure sequence's cognitive complexity. Behaviour is
    unchanged: on Postgres the active ``run_ownership_records`` snapshot is
    bound and re-verified at the metrics upsert's commit; ``None`` on the narrow
    SQLite unit-test path (K5 Postgres-only, no fence mirror) binds the same
    inert placeholder the driver ignores.
    """
    run_id = _resolve_run_id_fail_closed(s_dir) or ""
    ownership_fence = resolve_ownership_fence_snapshot(ctx.project_key, ctx.story_id)
    owner_session_id, expected_ownership_epoch = (
        ownership_fence if ownership_fence is not None else ("sqlite-unfenced", 0)
    )
    return bind_ownership_fence_scope(
        project_key=ctx.project_key,
        story_id=ctx.story_id,
        run_id=run_id,
        owner_session_id=owner_session_id,
        expected_ownership_epoch=expected_ownership_epoch,
    )


def _require_merge_locals(
    cfg: ClosureConfig,
) -> tuple[IntegrityGate, ArtifactManager]:
    """Return the merge collaborators as non-optional locals (FIX-8).

    ``_require_merge_collaborators`` has already rejected an unwired config, so
    these are guaranteed present here. Binding them to locals removes the
    ``type: ignore`` casts the runtime-None checks did not narrow.
    """
    integrity_gate = cfg.integrity_gate
    artifact_manager = cfg.artifact_manager
    if integrity_gate is None or artifact_manager is None:
        msg = "merge collaborators must be validated before _require_merge_locals"
        raise AssertionError(msg)
    return integrity_gate, artifact_manager


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
    # AG3-144 (FK-91 §91.1a Rule 15, no-lease-no-write): capture the
    # ownership-lease snapshot right before persisting the closure report --
    # re-verified at commit time, in the SAME transaction, under
    # SELECT ... FOR UPDATE (no TOCTOU). ``None`` on the narrow SQLite
    # unit-test path (K5 Postgres-only; no fence mirroring there).
    ownership_fence = resolve_ownership_fence_snapshot(ctx.project_key, ctx.story_id)
    owner_session_id, expected_ownership_epoch = (
        ownership_fence if ownership_fence is not None else ("sqlite-unfenced", 0)
    )
    return write_execution_report(
        s_dir,
        report,
        owner_session_id=owner_session_id,
        expected_ownership_epoch=expected_ownership_epoch,
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
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor
    from agentkit.backend.telemetry.projection_accessor import ProjectionKind

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
    from agentkit.backend.state_backend.telemetry_event_store import load_story_metrics

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
    try:
        return resolve_runtime_scope(s_dir).run_id or None
    except Exception:  # noqa: BLE001 -- best-effort scope read for the metrics key
        return None


def _persist_story_done(s_dir: Path, ctx: StoryContext) -> StoryContext:
    """Persist the authoritative story terminal flag after Done is reached."""
    if ctx.story_done is True:
        return ctx
    updated = ctx.model_copy(update={"story_done": True})
    save_story_context(s_dir, updated)
    return updated


def _transition_story_done(
    cfg: ClosureConfig, story_id: str,
) -> HandlerResult | None:
    """Call ``complete_story`` (default service) — return None on success."""
    story_service = cfg.story_service
    if story_service is None:
        from agentkit.backend.story_context_manager.service import StoryService as _StoryService
        story_service = _StoryService()
    try:
        story_service.complete_story(story_id)
    except Exception as cs_err:  # noqa: BLE001
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(f"complete_story failed: {cs_err}",),
        )
    return None


def _check_integration_stabilization_closure(
    ctx: StoryContext,
    s_dir: Path,
) -> HandlerResult | None:
    """AG3-069 (FK-05 §5.11): IS closure precondition gate.

    Only runs for integration_stabilization stories. Checks all FK-05 §5.11
    conditions before the merge block: stability_gate=PASS, all integration
    targets achieved, no open manifest violations, no replan/split needed.

    Gated on the IS contract so standard stories are completely unaffected
    (CORE PRINCIPLE: gate every IS enforcement on implementation_contract).

    Args:
        ctx: Story context.
        s_dir: Story working directory.

    Returns:
        A blocking ``HandlerResult`` when an IS precondition fails, or
        ``None`` when the story is not IS or all conditions pass.
    """
    from agentkit.backend.story_context_manager.types import ImplementationContract

    if ctx.implementation_contract is not ImplementationContract.INTEGRATION_STABILIZATION:
        return None  # Standard stories: no IS precondition check.

    from agentkit.backend.integration_stabilization.preconditions import (
        check_closure_precondition,
    )
    from agentkit.backend.integration_stabilization.state import (
        load_integration_manifest,
        load_manifest_approval,
    )

    manifest = load_integration_manifest(s_dir)
    approval = load_manifest_approval(s_dir)

    # Fail closed: if manifest or approval is absent, closure is blocked.
    if manifest is None or approval is None:
        missing = "manifest" if manifest is None else "approval record"
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(
                f"Integration-stabilization closure blocked: {missing} not "
                "found in story directory. An approved manifest is required "
                "for closure (FK-05 §5.11, AC9).",
            ),
        )

    # Load stability_gate result and integration targets from budget file.
    # The stability_gate status is written by the QA-subflow. If the file is
    # absent, we cannot confirm PASS -> fail-closed block.
    import json as _json

    stability_file = s_dir / "integration_stability_gate.json"
    stability_gate_passed = False
    achieved_targets: frozenset[str] = frozenset()
    open_violations = 0
    replan_needed = False

    if stability_file.exists():
        try:
            sg_data: dict[str, object] = _json.loads(
                stability_file.read_text(encoding="utf-8")
            )
            stability_gate_passed = bool(sg_data.get("passed", False))
            raw_targets = sg_data.get("achieved_targets", [])
            achieved_targets = frozenset(raw_targets if isinstance(raw_targets, list) else [])
            raw_violations = sg_data.get("open_violations", 0)
            open_violations = int(raw_violations) if isinstance(raw_violations, (int, float)) else 0
            replan_needed = bool(sg_data.get("replan_needed", False))
        except Exception:  # noqa: BLE001
            stability_gate_passed = False

    required_targets = frozenset(manifest.integration_targets)
    result = check_closure_precondition(
        stability_gate_passed=stability_gate_passed,
        achieved_targets=achieved_targets,
        required_targets=required_targets,
        open_manifest_violations=open_violations,
        replan_needed=replan_needed,
    )
    if not result.closure_allowed:
        reasons = "; ".join(result.blocking_reasons)
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(
                f"Integration-stabilization closure precondition failed "
                f"(FK-05 §5.11, AC9): {reasons}",
            ),
        )
    return None


__all__ = [
    "ClosureConfig",
    "ClosurePhaseHandler",
    "ClosureProgressStore",
    "ClosureVerdict",
    "ModeLockReleasePort",
]
