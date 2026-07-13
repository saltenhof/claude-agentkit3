"""Productive closure runtime port adapters (AG3-053, wired by the comp-root).

These adapters fulfil the closure collaborator Protocols
(``merge_sequence``/``post_merge_finalization``) by CONSUMING the existing
capabilities at the real external boundaries (the verify-system level-4
evaluator, the VectorDB sync, the governance top surface). They build NO second
merge/gate/Sonar/lock truth -- each is a thin seam.

The integrated-candidate Build/Test + Sonar scan ports are NOT defined here:
they are the AG3-056 Pre-Merge-Verification-Runner's productive
``CiBuildTestRunner`` / ``CiSonarScanRunner``, wired by the composition root via
``verify_system.pre_merge_runner.runtime_wiring.build_pre_merge_runners`` (the
old fail-open ``build_sonar_gate_port_for_run`` scan path is REMOVED -- AG3-053
consumes AG3-056 instead). The fast-mode Sanity-Gate (``ProductiveSanityGatePort``)
stays here (closure-owned fast path; AG3-018 will parametrize it later).

The composition root (``build_closure_phase_handler``) is the one productive
wiring point. The handler never builds these itself (DI / truth boundary).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.closure.merge_sequence import SanityOutcome

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.closure.gates import TelemetryEvidenceVerdict
    from agentkit.backend.closure.multi_repo_saga import ClosureRepo, GitBackend
    from agentkit.backend.governance import Governance
    from agentkit.backend.state_backend.store.mode_lock_repository import ModeLockRepository
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.types import StoryType
    from agentkit.backend.verify_system.conformance_service import FidelityResult
    from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductiveSanityGatePort:
    """Fast-mode Sanity-Gate seam (FK-29 §29.1a.6).

    The fast-mode sanity precondition is "tests green AND worktree clean AND
    pre-merge rebase onto ``main`` OK". This adapter genuinely exercises the two
    git-mechanic predicates it can confirm at the real git boundary -- it is NOT
    a blanket no-op:

    1. worktree clean -- ``git status --porcelain`` is empty;
    2. pre-merge rebase OK -- a dry ``git rebase`` of the story branch onto
       ``origin/main`` succeeds (a conflict aborts the rebase and escalates,
       FK-29 §29.1a.6 "Rebase-Konflikt -> Eskalation").

    The third predicate ("tests green") needs a live test run. The fast-mode
    live test runner is the AG3-018 boundary (FK-24 §24.3.4); when no
    ``test_runner`` is injected this adapter fails closed AFTER the real git
    checks -- a fast story without a confirmed test result escalates rather than
    silently merging (FAIL-CLOSED). When AG3-018 injects a real ``test_runner``
    the adapter confirms all three predicates.

    Attributes:
        git_backend: An explicitly injected legacy-test Git port. Productive
            Closure never wires this adapter after AG3-152.
        test_runner: Optional fast-mode test runner returning ``(green, reason)``.
            ``None`` => the tests-green predicate is unconfirmable (AG3-018 not
            yet wired) and the gate fails closed after the git checks.
    """

    git_backend: GitBackend
    test_runner: Callable[[Path], tuple[bool, str | None]] | None = None

    def evaluate(self, story_dir: Path, story_type: StoryType) -> SanityOutcome:
        """Evaluate the fast-mode sanity precondition (real git checks first)."""
        del story_type
        from agentkit.backend.closure.multi_repo_saga import ClosureRepo

        repo = ClosureRepo(name=story_dir.name, repo_root=story_dir)
        clean = self._worktree_clean(repo)
        if not clean.passed:
            return clean
        rebase = self._pre_merge_rebase_ok(repo)
        if not rebase.passed:
            return rebase
        return self._tests_green(story_dir)

    def _worktree_clean(self, repo: ClosureRepo) -> SanityOutcome:
        """Confirm the worktree is clean via ``git status --porcelain``."""
        result = self.git_backend.run(repo, "status", "--porcelain")
        if not result.ok:
            return SanityOutcome(
                passed=False,
                reason=f"git status failed: {result.stderr.strip() or result.returncode}",
            )
        if result.stdout.strip():
            return SanityOutcome(
                passed=False,
                reason="worktree is not clean (uncommitted changes present)",
            )
        return SanityOutcome(passed=True)

    def _pre_merge_rebase_ok(self, repo: ClosureRepo) -> SanityOutcome:
        """Confirm a clean rebase onto ``origin/main`` (abort on conflict)."""
        self.git_backend.run(repo, "fetch", "origin", "main")
        rebase = self.git_backend.run(repo, "rebase", "origin/main")
        if rebase.ok:
            return SanityOutcome(passed=True)
        # A rebase conflict leaves the rebase in progress -- abort it so the
        # worktree is not left mid-rebase, then escalate (FK-29 §29.1a.6).
        self.git_backend.run(repo, "rebase", "--abort")
        return SanityOutcome(
            passed=False,
            reason=(
                "pre-merge rebase onto origin/main failed (conflict): "
                f"{rebase.stderr.strip() or rebase.returncode}"
            ),
        )

    def _tests_green(self, story_dir: Path) -> SanityOutcome:
        """Confirm tests are green via the injected runner (fail-closed if absent)."""
        if self.test_runner is None:
            return SanityOutcome(
                passed=False,
                reason=(
                    "fast-mode sanity gate: worktree clean and rebase OK, but the "
                    "tests-green predicate has no live test runner (AG3-018 boundary) "
                    "-> cannot confirm tests green, escalate"
                ),
            )
        green, reason = self.test_runner(story_dir)
        if green:
            return SanityOutcome(passed=True)
        return SanityOutcome(
            passed=False,
            reason=reason or "fast-mode tests are not green",
        )


@dataclass(frozen=True)
class ProductiveDocFidelityFeedbackPort:
    """Level-4 doc-fidelity feedback seam (FK-38 §38.3.1, non-blocking).

    Runs a REAL level-4 evaluation through the SAME productive
    ``ConformanceService.check_fidelity(level=feedback)`` path the Layer-2
    reviewers use: the ``StructuredEvaluator`` over the injected Layer-2
    :class:`LlmClient` (``role=doc_fidelity``), the ``doc-fidelity-feedback.md``
    prompt (``expected_checks=["feedback_fidelity"]``), evaluating the final diff
    against the existing project docs (FK-38 §38.3.1).

    The ``llm_client`` is the SAME transport ``build_verify_system`` resolves for
    Layer 2 (composition-root injected). Until the productive LLM pool lands
    (AG3-070 ``RolePoolResolver``) that transport is the fail-closed
    :class:`FailClosedLlmClient`; the conformance service then returns a real
    ``FidelityResult(conformance_verdict=FAIL)`` (NOT an exception-to-warning) and
    once a pool is wired the EXACT same path yields a genuine PASS/FAIL verdict —
    no second doc-fidelity logic, no hard-coded transport.

    The step is mandatory but NON-BLOCKING (FK-38 §38.3): a FAIL verdict (or a
    setup-time failure) yields a human Warning + failure-corpus incident
    candidate, never a closure blockade (the story is already merged).

    Attributes:
        llm_client: The Layer-2 LLM transport (composition-root injected; the
            same one Layer-2 reviewers use). ``None`` => the fail-closed
            :class:`FailClosedLlmClient` default, so the level-4 evaluation still
            RUNS and returns a real FAIL verdict rather than silently skipping.
    """

    llm_client: LlmClient | None = None

    def evaluate_feedback_fidelity(
        self, ctx: StoryContext, story_dir: Path
    ) -> tuple[bool, str | None]:
        """Run the level-4 feedback check through the conformance facade."""
        try:
            result = _run_feedback_fidelity_conformance(
                ctx, story_dir, llm_client=self.llm_client
            )
        except Exception as exc:  # noqa: BLE001 -- post-merge step is non-blocking
            logger.warning("feedback fidelity evaluation failed: %s", exc)
            return (
                False,
                "feedback_fidelity evaluator failed; failure-corpus incident "
                f"candidate: {type(exc).__name__}: {exc}",
            )
        from agentkit.backend.verify_system.conformance_service import ConformanceVerdict

        if result.conformance_verdict is ConformanceVerdict.FAIL:
            return (
                False,
                "feedback_fidelity FAIL; failure-corpus incident candidate: "
                f"{result.reason}",
            )
        return (True, None)


@dataclass(frozen=True)
class ProductiveVectorDbSyncPort:
    """VectorDB sync seam (FK-13 §13.7.1, fire-and-forget, non-blocking).

    Triggers an async ``story_sync`` so the freshly closed story is searchable.
    The VectorDB integration is not yet available in the target project (FK-13);
    the step is MANDATORY but NON-BLOCKING: this seam records a human Warning when
    the sync cannot be triggered (never a silent skip; the STEP still runs).
    """

    def trigger_sync(
        self, ctx: StoryContext, story_dir: Path
    ) -> tuple[bool, str | None]:
        """Trigger the (async) VectorDB sync; non-blocking Warning when absent."""
        del ctx, story_dir
        return (
            False,
            "VectorDB sync (story_sync, FK-13 §13.7.1) has no productive "
            "integration yet -- closed story not yet indexed for retrieval",
        )


def _run_feedback_fidelity_conformance(
    ctx: StoryContext,
    story_dir: Path,
    *,
    llm_client: LlmClient | None = None,
) -> FidelityResult:
    """Run FK-38 feedback fidelity through ``ConformanceService``.

    The ``llm_client`` is the SAME Layer-2 transport ``build_verify_system``
    resolves (composition-root injected). When ``None`` it defaults to the
    fail-closed :class:`FailClosedLlmClient` so the evaluation still RUNS and
    returns a real ``FidelityResult`` (the service maps a fail-closed transport
    to a FAIL verdict internally — never an exception-to-warning at this seam).
    """
    from agentkit.backend.artifacts import ArtifactManager, EnvelopeValidator, ProducerRegistry
    from agentkit.backend.prompt_runtime.register import register_prompt_runtime_producers
    from agentkit.backend.state_backend.store.artifact_repository import (
        StateBackendArtifactRepository,
    )
    from agentkit.backend.state_backend.store.verify_story_context_repository import (
        StateBackendVerifyStoryContextAdapter,
    )
    from agentkit.backend.telemetry.storage import StateBackendEmitter
    from agentkit.backend.verify_system.conformance_service import (
        ConformanceService,
        FidelityContext,
        FidelityLevel,
        StructuredEvaluatorConformanceAdapter,
    )
    from agentkit.backend.verify_system.llm_evaluator.llm_client import FailClosedLlmClient
    from agentkit.backend.verify_system.llm_evaluator.prompt_materializer import (
        PromptRuntimeMaterializer,
    )
    from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
        StructuredEvaluator,
    )

    project_root = ctx.project_root or _project_root_for_feedback(story_dir)
    registry = ProducerRegistry()
    register_prompt_runtime_producers(registry)
    manager = ArtifactManager(
        repository=StateBackendArtifactRepository(store_dir=story_dir),
        validator=EnvelopeValidator(registry),
    )
    materializer = PromptRuntimeMaterializer(
        ctx=ctx,
        story_dir=story_dir,
        artifact_manager=manager,
        story_context_port=StateBackendVerifyStoryContextAdapter(),
    )
    resolved_client = llm_client if llm_client is not None else FailClosedLlmClient()
    evaluator = StructuredEvaluator(resolved_client, materializer)
    service = ConformanceService(
        StructuredEvaluatorConformanceAdapter(evaluator),
        emitter=StateBackendEmitter(story_dir),
    )
    context = FidelityContext(
        story_id=ctx.story_id,
        run_id=_run_id_for_feedback(story_dir),
        project_root=project_root,
        story_type=ctx.story_type.value,
        module=ctx.participating_repos[0] if ctx.participating_repos else "*",
        subject=(
            f"Merged edge candidate for {ctx.story_id}. Physical diff acquisition "
            "is edge-resident; backend feedback evaluation must not re-read Git."
        ),
        story_description=ctx.title,
        tags=("feedback", "document-fidelity"),
        qa_cycle_round=1,
    )
    return service.check_fidelity(FidelityLevel.FEEDBACK, context)


def _project_root_for_feedback(story_dir: Path) -> Path:
    if story_dir.parent.name == "stories":
        return story_dir.parent.parent
    return story_dir


def _run_id_for_feedback(story_dir: Path) -> str:
    try:
        from agentkit.backend.state_backend.runtime_scope_resolver import (
            resolve_runtime_scope,
        )

        scope = resolve_runtime_scope(story_dir)
    except Exception:  # noqa: BLE001 -- non-blocking fallback correlation
        return "feedback-fidelity"
    return str(getattr(scope, "run_id", None) or "feedback-fidelity")


@dataclass(frozen=True)
class ProductiveTelemetryEvidencePort:
    """Closure Telemetry-Evidence-Block seam (FK-68 §68.4, AG3-081 AC3).

    Builds the ``TelemetryContract`` over the canonical
    :class:`~agentkit.backend.telemetry.storage.StateBackendExecutionEventReader` and runs
    the six-rule ``check_all`` for the run. The authoritative review roles, the
    mandatory llm role→pool slice and the web-call budget are resolved from the
    project config (the composition root owns the config truth boundary, FK-68
    §68.4: checked against configuration, not against hardcoded provider names).

    Fail-closed: any FAIL among the six proofs yields a
    :class:`~agentkit.backend.closure.gates.TelemetryEvidenceVerdict` with ``passed ==
    False`` (NO ERROR BYPASSING). A config-resolution fault is ALSO fail-closed —
    a Closure that cannot prove the telemetry evidence must NOT merge.

    Attributes:
        project_key: The owning project key (FK-68 mandatory scope key).
        project_root: Project root used to resolve the pipeline/telemetry config.
    """

    project_key: str
    project_root: Path

    def evaluate(
        self, story_dir: Path, *, story_id: str, run_id: str
    ) -> TelemetryEvidenceVerdict:
        """Run the six FK-68 §68.4 proofs for the run (fail-closed on violation)."""
        from agentkit.backend.closure.gates import TelemetryEvidenceVerdict
        from agentkit.backend.telemetry.contract.results import TelemetryScope
        from agentkit.backend.telemetry.contract.telemetry_contract import TelemetryContract
        from agentkit.backend.telemetry.storage import (
            StateBackendEmitter,
            StateBackendExecutionEventReader,
        )

        try:
            review_roles, role_pools, web_budget = self._resolve_config()
        except Exception as exc:  # noqa: BLE001 -- fail-closed: cannot prove evidence
            # S1110: the message is hoisted into a local so the kwarg value is a
            # plain identifier (no parenthesised grouping at the call site). The
            # string value is byte-identical to the prior inline form.
            blocking_reason = "Telemetry-Evidence-Block (FK-68 §68.4): the authoritative " \
                f"review/llm/web budget config could not be resolved ({exc}) " \
                "-> fail-closed (cannot verify telemetry evidence -> cannot " \
                "merge)"
            return TelemetryEvidenceVerdict(
                passed=False,
                blocking_reason=blocking_reason,
            )

        reader = StateBackendExecutionEventReader(
            story_dir, project_key=self.project_key, story_id=story_id
        )
        scope = TelemetryScope(
            project_key=self.project_key, story_id=story_id, run_id=run_id
        )
        contract = TelemetryContract(
            reader,
            StateBackendEmitter(story_dir, default_project_key=self.project_key),
            scope,
        )
        result = contract.check_all(
            run_id,
            review_roles,
            role_pools,
            web_call_budget=web_budget,
        )
        if result.passed:
            return TelemetryEvidenceVerdict(passed=True)
        failing = tuple(r.rule_id for r in result.failures)
        details = "; ".join(f"{r.rule_id}: {r.detail}" for r in result.failures)
        return TelemetryEvidenceVerdict(
            passed=False,
            failing_rule_ids=failing,
            blocking_reason=(
                "Telemetry-Evidence-Block (FK-68 §68.4) failed at Closure "
                f"(fail-closed): {details}"
            ),
        )

    def _resolve_config(self) -> tuple[set[str], dict[str, str], int]:
        """Resolve review roles, role→pool slice and the web budget from config.

        FK-68 §68.4: the gate reads ``llm_roles`` + the mandatory reviewer roles
        from the pipeline config and the web budget from ``telemetry.web_call_limit``
        — never hardcoded provider names. The role→pool slice maps each mandatory
        reviewer role to its assigned pool from ``llm_roles`` (only roles present
        in ``llm_roles`` are pool-checked; reviewer-role coverage is checked
        independently against the ``review_request`` stream).
        """
        from agentkit.backend.config.loader import load_project_config

        config = load_project_config(self.project_root)
        review_roles = set(config.pipeline.review.required_roles)
        web_budget = config.pipeline.telemetry.web_call_limit
        role_pools: dict[str, str] = {}
        llm_roles = config.pipeline.llm_roles
        if llm_roles is not None:
            assignments = llm_roles.model_dump(exclude_none=True)
            for role in review_roles:
                pool = assignments.get(role)
                if isinstance(pool, str) and pool:
                    role_pools[role] = pool
        return review_roles, role_pools, web_budget


@dataclass(frozen=True)
class ProductiveGuardDeactivationPort:
    """Guard-deactivation seam (FK-29 §29.5, governance top surface).

    Delegates to ``Governance.deactivate_locks`` (the governance top surface).
    Closure holds NO lock logic itself (single delegation step). Non-blocking: a
    deactivation error is collected as a human Warning, never an ESCALATED verdict
    (the story is already merged).

    Attributes:
        governance: The wired ``Governance`` top surface.
    """

    governance: Governance

    def deactivate(self, story_id: str) -> tuple[bool, str | None]:
        """Deactivate the story locks; non-blocking Warning on any error."""
        try:
            result = self.governance.deactivate_locks(story_id)
        except Exception as exc:  # noqa: BLE001 -- non-blocking step (post-merge)
            logger.warning("guard deactivation failed for story=%s: %s", story_id, exc)
            return (False, f"deactivate_locks raised: {exc}")
        if result.errors:
            return (False, "; ".join(result.errors))
        return (True, None)


@dataclass(frozen=True)
class ProductiveGuardCounterFlushPort:
    """Closure guard-counter flush seam (FK-61 §61.4.3 Trigger 1, AG3-081).

    Delegates to the kpi-owned
    :class:`~agentkit.backend.kpi_analytics.fact_store.guard_counter.GuardCounterService.flush_on_closure`
    over the productive
    :class:`~agentkit.backend.state_backend.store.guard_counter_repository.StateBackendGuardCounterRepository`.
    Closure holds no counter logic itself (single delegation step). Non-blocking: a
    flush error is surfaced as a human Warning, never an escalation (the story is
    already merged + closed). The actual ``fact_guard_period`` drain is AG3-082;
    this flush deterministically reads + deletes the story's counter rows.

    Attributes:
        store_dir: Base directory for the state-backend counter store.
    """

    store_dir: Path

    def flush_on_closure(
        self, story_dir: Path, *, project_key: str, story_id: str
    ) -> tuple[bool, str | None]:
        """Drain the story's guard counters at Closure; non-blocking Warning on error."""
        del story_dir
        from agentkit.backend.kpi_analytics import GuardCounterService
        from agentkit.backend.state_backend.store.guard_counter_repository import (
            StateBackendGuardCounterRepository,
        )

        try:
            GuardCounterService(
                StateBackendGuardCounterRepository(self.store_dir)
            ).flush_on_closure(project_key, story_id)
        except Exception as exc:  # noqa: BLE001 -- non-blocking post-close step
            logger.warning(
                "guard-counter Closure flush failed for story=%s: %s", story_id, exc
            )
            return (False, f"guard-counter Closure flush raised: {exc}")
        return (True, None)


@dataclass(frozen=True)
class ProductiveModeLockReleasePort:
    """Project mode-lock release seam at story close (FK-24 §24.3.3, AG3-018).

    The release half of the Fast/Standard between-modes mutex. Delegates to the
    atomic ``ModeLockRepository.release`` for the mode THIS story acquired (read
    from the durable per-story acquire marker written by Setup). Closure holds no
    mode-lock logic itself (single delegation step).

    Idempotency (FIX-4): the durable per-story acquire marker is the SOLE
    idempotency truth -- NOT a seventh ``ClosureProgress`` checkpoint (FK-29
    §29.1.0 defines exactly six). A story that never acquired (no marker) owes no
    release; after a successful release the marker is CLEARED, so a resumed /
    cancelled closure finds no marker and never double-releases (recovery / cancel
    safety -- never an over-release).

    Non-blocking: a release error is surfaced as a human Warning (never an
    ESCALATED verdict; the story is already merged + closed).

    Attributes:
        mode_lock_repo: The atomic ``ModeLockRepository`` (CAS acquire/release).
    """

    mode_lock_repo: ModeLockRepository

    def release(self, story_dir: Path, project_key: str) -> tuple[bool, str | None]:
        """Release this story's mode-lock holder; non-blocking Warning on error."""
        from agentkit.backend.governance.setup_preflight_gate.mode_lock_marker import (
            acquired_mode,
            clear_mode_lock_marker,
        )

        mode = acquired_mode(story_dir)
        if mode is None:
            # This story never acquired the lock (e.g. standalone/legacy run, or
            # acquire was skipped), OR a prior release already cleared the marker
            # (resumed closure) -> no release owed (idempotent no-op).
            return (True, None)
        try:
            self.mode_lock_repo.release(project_key, mode)
        except Exception as exc:  # noqa: BLE001 -- non-blocking post-close step
            logger.warning(
                "mode-lock release failed for project=%s mode=%s: %s",
                project_key,
                mode,
                exc,
            )
            return (False, f"mode-lock release raised: {exc}")
        # FIX-4: clear the marker so the release is idempotent without a seventh
        # checkpoint -- a resumed/cancelled closure then finds no marker and owes
        # nothing (no double-release of the holder count).
        clear_mode_lock_marker(story_dir)
        return (True, None)


__all__ = [
    "ProductiveDocFidelityFeedbackPort",
    "ProductiveGuardCounterFlushPort",
    "ProductiveGuardDeactivationPort",
    "ProductiveModeLockReleasePort",
    "ProductiveSanityGatePort",
    "ProductiveTelemetryEvidencePort",
    "ProductiveVectorDbSyncPort",
]
