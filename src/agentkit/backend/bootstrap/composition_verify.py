"""Verify-system, push-barrier, and code-backend composition builders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentkit.backend.bootstrap import qa_boundary
from agentkit.backend.bootstrap.composition_artifacts import build_artifact_manager
from agentkit.backend.bootstrap.composition_compat import composition_root_attr
from agentkit.backend.bootstrap.push_barrier_server_head import (
    server_head_for_push_barrier_verdict,
)
from agentkit.backend.control_plane import push_barrier_lifecycle

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.bootstrap import composition_closure_types as closure_types
    from agentkit.backend.bootstrap import composition_project_types as project_types
    from agentkit.backend.bootstrap import composition_verify_types as verify_types


def build_verify_system(
    store_dir: Path,
    *,
    max_major_findings: int = 0,
    max_feedback_rounds: int | None = None,
    sonar_gate_port: verify_types.SonarGateInputPort | None = None,
    layer2_llm_client: verify_types.LlmClient | None = None,
    fast_test_runner: Callable[[Path], tuple[bool, str | None]] | None = None,
    structural_build_test_port: verify_types.BuildTestEvidencePort | None = None,
    structural_are_provider: verify_types.AreGateProvider | None = None,
    conformance_config: project_types.ConformanceConfig | None = None,
    layer2_bundle_token_limit: int = 32_000,
    structural_completion_sync_point_id: str | None = None,
) -> verify_types.VerifySystem:
    """Create a fully wired ``VerifySystem``.

    Composition root for the QA-subflow top-surface (AG3-026):
    instantiates all five sub-components and wires a real
    ``ArtifactManager`` (incl. ProducerRegistry) as the persistence facade.

    AG3-035 (real drift fix): additionally wires the
    ``StateBackendVerifyStoryContextAdapter`` as ``story_context_port`` so
    ``verify_system`` resolves the ``StoryContext`` via a port instead of a
    direct ``state_backend.store`` import (BC topology).

    AG3-052 (FK-33 §33.6): the ``sonarqube_gate`` docking point uses a
    ``SonarGateInputPort``. When ``sonarqube.available == true`` the caller
    (pipeline engine) passes in the productive
    :class:`ConfiguredSonarGateInputPort` via ``sonar_gate_port`` (built via
    :func:`build_sonar_gate_port` with the per-run resolved coordinates);
    without injection the absent-default port stays active
    (``available == false`` => stage SKIP). This keeps a
    configured-but-unreachable Sonar fail-closed without this builder having to
    know the per-story coordinates.

    Args:
        store_dir: Base directory of the state backend. Passed through to
            ``build_artifact_manager``.
        max_major_findings: Threshold for the PolicyEngine (number of
            tolerated MAJOR findings; 0 = every MAJOR blocks).
        max_feedback_rounds: Ceiling for the subflow-internal remediation loop
            (FK-03 §3.4.2 / FK-38, ``policy.max_feedback_rounds``). The caller
            (phase handler) resolves it from the pipeline config and passes it
            in; ``None`` => controller default (3). The
            ``RemediationLoopController`` is the hard owner of the bound (not
            skippable, NO ERROR BYPASSING).
        sonar_gate_port: Optional productive ``SonarGateInputPort``
            (FK-33 §33.6). ``None`` => absent-default port.
        layer2_llm_client: Optional ``LlmClient`` (AG3-043 E6, FK-27 §27.5).
            ``None`` => the composition root wires the fail-closed
            :class:`FailClosedLlmClient` so Layer 2 in the default path REALLY
            runs (three parallel LLM evaluations) instead of silently falling
            back to the deterministic stub reviewers. As long as the concrete
            LLM-pool selection (FK-11, follow-up story) is missing, the
            fail-closed client fails every ``complete`` call -> Layer 2
            FAIL-CLOSED (no silent skip, FK-34 §34.5.1). Once the pool adapter
            exists, the caller passes it in here.
        conformance_config: Optional FK-32 §32.4b.3 prompt-size thresholds
            from the per-run ``ProjectConfig.pipeline.conformance`` stanza.
            ``None`` => the ConformanceService's built-in defaults (50 KB /
            500 KB) are used. Pass
            ``project_config.pipeline.conformance`` to make the configured
            thresholds effective for impl-fidelity assessments (ERROR 4 fix,
            AG3-063 remediation 2).
        layer2_bundle_token_limit: Per-field section-aware Layer-2 packing
            limit from ``ProjectConfig.pipeline.layer2.bundle_token_limit``.
        structural_completion_sync_point_id: Current phase-completion push
            boundary correlation used by the structural ``completion.push``
            evidence source. ``None`` stays fail-closed.

    Returns:
        ``VerifySystem`` with all five sub-components and a fully wired
        ``ArtifactManager`` as well as a productively wired Layer-2 LLM
        client (E6).
    """
    from agentkit.backend.state_backend.store.verify_story_context_repository import (
        StateBackendVerifyStoryContextAdapter,
    )
    from agentkit.backend.telemetry.storage import StateBackendEmitter
    from agentkit.backend.verify_system.llm_evaluator.llm_client import FailClosedLlmClient
    from agentkit.backend.verify_system.structural.checker import FULL_STAGE_REGISTRY
    from agentkit.backend.verify_system.system import VerifySystem

    manager = build_artifact_manager(store_dir)
    resolved_llm_client = layer2_llm_client or FailClosedLlmClient()
    return VerifySystem.create_default(
        max_major_findings=max_major_findings,
        max_feedback_rounds=max_feedback_rounds,
        artifact_manager=manager,
        story_context_port=StateBackendVerifyStoryContextAdapter(),
        sonar_gate_port=sonar_gate_port,
        invalidation_sink=build_artifact_invalidation_sink(store_dir),
        # FIX-C (FK-27 §27.4.3 / §27.5.5): after each Layer-2 review artefact
        # write the QA-subflow emits a canonical ``llm_call_complete`` event
        # (per reviewer role) so ``guard.multi_llm`` counts a COMPLETED review.
        # Without this productive sink the count is always 0 and the gate is
        # inert/over-blocking. The telemetry import lives here, not in the BC.
        review_completion_sink=build_review_completion_sink(store_dir),
        conformance_emitter=StateBackendEmitter(store_dir),
        conformance_config=conformance_config,
        layer2_bundle_token_limit=layer2_bundle_token_limit,
        layer2_llm_client=resolved_llm_client,
        fast_test_runner=fast_test_runner,
        # AG3-042: the PRODUCTIVE path wires the full FK-27 §27.4 Layer-1 stage
        # catalogue (StructuralChecker + PolicyEngine fail-closed check).
        stage_registry=FULL_STAGE_REGISTRY,
        # AG3-042: the FK-27 §27.4.3 recurring guards count canonical
        # ``execution_events`` via a port so verify-system never imports
        # ``state_backend.store`` directly (BC-topology, AG3-035).
        structural_telemetry_port=_StateBackendTelemetryEventCountPort(),
        # FIX-3 (FK-33 §33.5): the BLOCKING branch/commit/push/secrets/impact
        # checks decide on INDEPENDENT system git evidence, wired here as the
        # productive subprocess-git provider (verify-system stays free of
        # subprocess; the import lives in this composition root). NEVER the
        # worker manifest.
        structural_change_evidence_port=_SubprocessGitChangeEvidenceProvider(
            push_verification_port=build_push_verification_port(required_sync_point_id=structural_completion_sync_point_id)
        ),
        # AG3-147 (FK-10 §10.2.4b boundary type 2): the QA-cycle-boundary push
        # barrier gate, delegating to the control-plane two-stage barrier.
        qa_cycle_push_barrier_gate=build_qa_cycle_push_barrier_gate(),
        qa_cycle_fingerprint_source=_StateBackedQaCycleFingerprintSource(),
        # FIX-1: the REAL build/test evidence port + the real ARE provider need
        # per-run config (the project ``ci`` stanza / ``features.are``) the
        # builder does not have, so the per-run caller (ImplementationPhaseHandler)
        # resolves and injects them via :func:`build_structural_build_test_port`
        # / :func:`build_structural_are_provider`. Absent here => the fail-closed
        # default ports (build/test BLOCKING fail, ARE stage not planned), so a
        # bare build_verify_system never over-blocks a story with a fabricated
        # green NOR silently disables ARE.
        structural_build_test_port=structural_build_test_port,
        structural_are_provider=structural_are_provider,
    )


@dataclass(frozen=True)
class _StateBackendTelemetryEventCountPort:
    """State-backed ``TelemetryEventQueryPort`` (FK-27 §27.4.3, AG3-042).

    Counts canonical ``execution_events`` of a given type for a story via the
    state-backend facade, scoped to ``(project_key, story_id, run_id)`` per
    FK-33 §33.3.2 -- a recurring-guard count must not bleed across projects or
    across prior runs of the same story. When the caller does not supply a
    ``run_id`` the adapter resolves the ACTIVE run for ``story_dir`` (via the
    persisted run scope) so a prior, reset, or replayed run never counts toward
    the current guard. The ``state_backend.store`` import lives HERE (the
    composition root), not in ``verify_system`` (BC-topology, AG3-035). Counts
    fail soft to ``0`` on any backend error so the BLOCKING guards stay
    fail-closed (a missing/unreadable event store yields ``0`` -> FAIL).
    """

    def count_events(
        self,
        story_dir: Path,
        *,
        story_id: str,
        event_type: str,
        role: str | None = None,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> int:
        """Count matching canonical ``execution_events`` (``0`` on error).

        Scoped to ``(project_key, story_id, run_id)`` (FK-33 §33.3.2). When
        ``run_id`` is ``None`` the active run for ``story_dir`` is resolved so
        a prior run's events are excluded. When ``role`` is given, only events
        whose ``payload['role']`` matches are counted (FK-27 §27.4.3 Gate 2:
        ``llm_call_complete`` events carry the reviewer role in their payload).
        """
        from agentkit.backend.state_backend.telemetry_event_store import (
            load_execution_events,
        )

        resolved_run_id = run_id or self._resolve_active_run_id(story_dir)
        if resolved_run_id is None:
            # FIX-B (FK-33 §33.3.2 run scope, fail-CLOSED): when the run scope
            # cannot be resolved we MUST NOT query unscoped. A
            # ``load_execution_events(..., run_id=None)`` would count across ALL
            # runs of the story, so the must-have-events guards
            # (``guard.review_compliance`` / ``guard.multi_llm`` /
            # ``guard.llm_reviews``) could PASS on a prior run's telemetry
            # (fail-open). Returning 0 makes every BLOCKING must-have-events
            # guard FAIL closed on an unresolvable run scope, and never lets
            # ``guard.no_violations`` free-pass on stale events: a
            # ``count_events`` of 0 there means "no integrity_violation visible
            # for this run", which is the only honest reading when the run scope
            # is unknown (the violation, if any, lives under a resolvable run).
            return 0
        try:
            events = load_execution_events(
                story_dir,
                project_key=project_key,
                story_id=story_id,
                run_id=resolved_run_id,
                event_type=event_type,
            )
        except Exception:  # noqa: BLE001 -- fail-soft to 0 (fail-closed guard).
            return 0
        if role is None:
            return len(events)
        return sum(
            1 for event in events if isinstance(getattr(event, "payload", None), dict) and event.payload.get("role") == role
        )

    def run_scope_resolvable(self, story_dir: Path) -> bool:
        """Whether the active run scope for ``story_dir`` resolves (FIX-B).

        FK-33 §33.3.2: ``guard.no_violations`` PASSES on a ``0`` count, so it
        must fail closed when the run scope is unknown rather than free-pass on
        stale/unknown telemetry. Returns ``True`` iff the persisted run scope
        yields a run id.
        """
        return self._resolve_active_run_id(story_dir) is not None

    def _resolve_active_run_id(self, story_dir: Path) -> str | None:
        """Resolve the active run id for ``story_dir`` (``None`` when unknown).

        FK-33 §33.3.2 run scope: the recurring guards count events of the
        CURRENT run only. The authoritative run correlation is the persisted
        run scope of the story's flow execution.
        """
        from agentkit.backend.state_backend.runtime_scope_resolver import resolve_runtime_scope

        try:
            scope = resolve_runtime_scope(story_dir)
        except Exception:  # noqa: BLE001 -- unresolved scope -> no run filter
            return None
        return getattr(scope, "run_id", None)


@dataclass(frozen=True)
class _BarrierPushVerification:
    """Productive ``PushVerificationPort`` over persisted barrier verdicts.

    ``completion.push`` reads the authoritative ``PushBarrierVerdict`` SSOT. It
    does not re-run the push barrier from freshness; result handling owns the
    two-stage Edge+server resolution.
    """

    required_sync_point_id: str | None = None

    def confirm_story_pushed(self, story_dir: Path) -> bool:
        """Whether the story branch is server-verified-pushed in every repo."""
        if self.required_sync_point_id is None:
            return False
        from datetime import UTC, datetime

        from agentkit.backend.control_plane.push_sync import SyncPointBarrierType
        from agentkit.backend.state_backend.runtime_scope_resolver import (
            resolve_runtime_scope,
        )
        from agentkit.backend.state_backend.story_closure_store import (
            list_push_barrier_verdicts_global,
            upsert_push_barrier_verdict_global,
        )

        try:
            scope = resolve_runtime_scope(story_dir)
        except Exception:  # noqa: BLE001 -- unresolvable scope -> fail-closed (not pushed)
            return False
        project_key = getattr(scope, "project_key", None)
        story_id = getattr(scope, "story_id", None)
        run_id = getattr(scope, "run_id", None)
        if not project_key or not story_id or not run_id:
            return False
        boundary_id = qa_boundary.boundary_id_from_sync_point(
            self.required_sync_point_id,
            expected_type=SyncPointBarrierType.PHASE_COMPLETION,
        )
        if boundary_id is None:
            return False
        self._commission_sync_push_best_effort(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            boundary_id=boundary_id,
        )
        try:
            verdicts = list_push_barrier_verdicts_global(
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
                boundary_id=boundary_id,
            )
        except Exception:  # noqa: BLE001 -- unavailable verdict SSOT -> not pushed
            return False
        evidence_factory = composition_root_attr("build_push_barrier_evidence")

        def _server_head_for_verdict(verdict: Any) -> str | None:
            return server_head_for_push_barrier_verdict(
                verdict,
                evidence_factory=evidence_factory,
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
                boundary_id=boundary_id,
            )

        return push_barrier_lifecycle.aggregate_persisted_push_barrier(
            SyncPointBarrierType.PHASE_COMPLETION,
            tuple(verdicts),
            expected_repo_ids=self._participating_repos(project_key, story_id),
            server_head_for_verdict=_server_head_for_verdict,
            persist_blocked_verdict=upsert_push_barrier_verdict_global,
            now=datetime.now(tz=UTC),
        ).passed

    @staticmethod
    def _server_head_for_verdict(verdict: Any) -> str | None:
        return server_head_for_push_barrier_verdict(
            verdict,
            evidence_factory=composition_root_attr("build_push_barrier_evidence"),
        )

    @staticmethod
    def _participating_repos(project_key: str, story_id: str) -> tuple[str, ...]:
        from agentkit.backend.state_backend.store.story_read_repository import (
            StateBackendStoryReadRepository,
        )

        ctx = StateBackendStoryReadRepository().load_story_context(project_key, story_id)
        return tuple(ctx.participating_repos) if ctx is not None else ()

    def _commission_sync_push_best_effort(
        self, *, project_key: str, story_id: str, run_id: str, boundary_id: str
    ) -> None:
        """Queue structural phase-completion ``sync_push`` evidence."""
        import logging
        from datetime import UTC, datetime

        from agentkit.backend.control_plane.push_sync import SyncPointBarrierType
        from agentkit.backend.state_backend.harness_edge_command_store import (
            commission_edge_command_record_global,
            load_edge_command_record_global,
            supersede_open_edge_command_global,
        )
        from agentkit.backend.state_backend.store.story_read_repository import (
            StateBackendStoryReadRepository,
        )
        from agentkit.backend.state_backend.story_closure_store import (
            load_push_barrier_verdict_global,
            upsert_push_barrier_verdict_global,
        )
        from agentkit.backend.state_backend.story_lifecycle_store import (
            load_active_run_ownership_record_global,
        )

        try:
            ctx = StateBackendStoryReadRepository().load_story_context(
                project_key,
                story_id,
            )
            active = load_active_run_ownership_record_global(project_key, story_id)
            if ctx is None or active is None or active.run_id != run_id:
                return
            now = datetime.now(tz=UTC)
            verdicts = push_barrier_lifecycle.bind_push_boundary(
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
                boundary_id=boundary_id,
                repo_ids=tuple(ctx.participating_repos),
                ownership_epoch=active.ownership_epoch,
                load_verdict=load_push_barrier_verdict_global,
                persist_verdict=upsert_push_barrier_verdict_global,
                now=now,
            )
            push_barrier_lifecycle.commission_sync_push_commands(
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                owner_session_id=active.owner_session_id,
                ownership_epoch=active.ownership_epoch,
                boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
                boundary_id=boundary_id,
                verdicts=verdicts,
                load_command=load_edge_command_record_global,
                commission_command=commission_edge_command_record_global,
                persist_blocked_verdict=upsert_push_barrier_verdict_global,
                supersede_open_command=supersede_open_edge_command_global,
                now=now,
            )
        except Exception as exc:  # noqa: BLE001 -- queue failure cannot open barrier
            logging.getLogger(__name__).warning(
                "sync_push commissioning failed before structural completion.push barrier: %s",
                exc,
            )


def build_push_verification_port(
    required_sync_point_id: str | None = None,
) -> closure_types.PushVerificationPort:
    """Wire the productive two-stage push-verification port (AG3-147 AC11)."""
    return _BarrierPushVerification(required_sync_point_id=required_sync_point_id)


@dataclass(frozen=True)
class _SubprocessGitChangeEvidenceProvider:
    """Productive ``ChangeEvidencePort`` (FK-33 §33.5) with AG3-147 push retarget.

    Collects INDEPENDENT system evidence about the story's change set by running
    read-only ``git`` commands in the story worktree (NEVER the worker manifest):
    the actual checked-out branch, the commit history since ``origin/main`` (the
    base ref), the diff's changed + secret-shaped files and the diff-derived
    actual change impact (FK-23 §23.8). The ``git`` import (subprocess) lives HERE
    in the composition root, keeping ``verify_system`` free of subprocess. Any git
    error yields ``available=False`` so the BLOCKING checks fail closed (NO ERROR
    BYPASSING; never a fall-back to self-report).

    AG3-147 AC11: the ``pushed`` field is NO LONGER a backend-local ``git``
    upstream check (``_is_pushed`` removed). It is sourced from the two-stage push
    barrier via the injected :class:`PushVerificationPort` (Edge report AND server
    ``ls-remote`` ref-read) -- ``completion.push`` still decides on
    ``evidence.pushed``, only the SOURCE moved (FK-10 §10.2.4a Option b).
    """

    base_ref: str = "origin/main"
    push_verification_port: closure_types.PushVerificationPort = field(default_factory=qa_boundary.default_push_verification_port)

    def collect(self, story_dir: Path) -> closure_types.ChangeEvidence:
        """Collect the system change evidence (``available=False`` on any error)."""
        from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

        branch = self._git(story_dir, "rev-parse", "--abbrev-ref", "HEAD")
        if branch is None:
            return ChangeEvidence(available=False)
        base = self._merge_base(story_dir)
        commits = self._commit_messages(story_dir, base)
        changed = self._changed_files(story_dir, base)
        secret_files = self._secret_files(changed)
        secret_content_hits = self._secret_content_hits(story_dir, base)
        actual_impact = _derive_actual_impact(changed)
        return ChangeEvidence(
            available=True,
            current_branch=branch,
            commit_messages=commits,
            # AG3-147 AC11: server-verified push barrier, NOT a local upstream check.
            pushed=self.push_verification_port.confirm_story_pushed(story_dir),
            secret_files=secret_files,
            secret_content_hits=secret_content_hits,
            changed_files=changed,
            actual_impact=actual_impact,
        )

    def _merge_base(self, story_dir: Path) -> str | None:
        """Resolve the base ref to diff against (``origin/main``, else empty)."""
        return self._git(story_dir, "merge-base", self.base_ref, "HEAD")

    def _commit_messages(self, story_dir: Path, base: str | None) -> tuple[str, ...]:
        rng = f"{base}..HEAD" if base else "HEAD"
        out = self._git(story_dir, "log", "--format=%B%x00", rng)
        if out is None:
            return ()
        return tuple(m.strip() for m in out.split("\x00") if m.strip())

    def _changed_files(self, story_dir: Path, base: str | None) -> tuple[str, ...]:
        spec = f"{base}..HEAD" if base else "HEAD"
        out = self._git(story_dir, "diff", "--name-only", spec)
        if out is None:
            return ()
        return tuple(line.strip() for line in out.splitlines() if line.strip())

    def _secret_files(self, changed: tuple[str, ...]) -> tuple[str, ...]:
        from agentkit.backend.governance.guard_system.secret_patterns import (
            find_secret_file_hits,
        )

        return tuple(hit.path for hit in find_secret_file_hits(changed))

    def _secret_content_hits(
        self,
        story_dir: Path,
        base: str | None,
    ) -> tuple[str, ...]:
        from agentkit.backend.governance.guard_system.secret_scan import scan_paths_and_diff

        spec = f"{base}..HEAD" if base else "HEAD"
        out = self._git(story_dir, "diff", "--unified=0", "--no-ext-diff", spec)
        if out is None:
            return ()
        result = scan_paths_and_diff((), out)
        return tuple(f"{hit.path}:{hit.pattern.value}" for hit in result.content_hits)

    def _git(self, story_dir: Path, *args: str) -> str | None:
        """Run a read-only git command; return stripped stdout or ``None``."""
        import subprocess  # noqa: PLC0415 -- comp-root owns the subprocess import

        try:
            # Fixed git argv, no shell.
            result = subprocess.run(  # noqa: S603
                ["git", "-C", str(story_dir), *args],  # noqa: S607
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()


#: Diff size threshold below which a single-component change stays ``LOCAL``.
_LOCAL_FILE_THRESHOLD = 3
#: Number of distinct top-level components that marks a CROSS_COMPONENT change.
_CROSS_COMPONENT_DIRS = 2


def _derive_actual_impact(changed_files: tuple[str, ...]) -> project_types.ChangeImpact | None:
    """Derive the SYSTEM actual change impact from the diff (FK-23 §23.8).

    A deterministic, diff-based proxy (no worker input): more distinct top-level
    components touched => higher impact. This is the independent measurement the
    BLOCKING ``impact.violation`` check compares against the worker's declared
    budget. ``None`` only for an empty diff (nothing changed).
    """
    from agentkit.backend.story_context_manager.story_model import ChangeImpact

    if not changed_files:
        return None
    top_dirs = {f.split("/", 1)[0] for f in changed_files if "/" in f} or {""}
    distinct = len(top_dirs)
    if distinct <= 1:
        return ChangeImpact.LOCAL if len(changed_files) <= _LOCAL_FILE_THRESHOLD else ChangeImpact.COMPONENT
    if distinct == _CROSS_COMPONENT_DIRS:
        return ChangeImpact.CROSS_COMPONENT
    return ChangeImpact.ARCHITECTURE_IMPACT


def build_artifact_invalidation_sink(store_dir: Path) -> verify_types.ArtifactInvalidationSink:
    """Build the productive ``artifact_invalidated`` telemetry sink (AG3-041 §2.1.3).

    Composition-Root wiring for FK-27 §27.2.3: every cycle-bound QA artefact
    moved to ``stale/`` on ``advance_qa_cycle`` emits an ``artifact_invalidated``
    telemetry event through the canonical :class:`StateBackendEmitter`. This is
    the productive default for ``build_verify_system`` — NOT a no-op stub.
    ``verify_system`` only knows the ``ArtifactInvalidationSink`` Protocol; the
    telemetry import lives here, keeping the BC free of a telemetry dependency.

    Args:
        store_dir: Story working directory (the canonical event store root).

    Returns:
        A productive sink that emits ``artifact_invalidated`` events.
    """
    from agentkit.backend.telemetry.storage import StateBackendEmitter

    return _TelemetryArtifactInvalidationSink(StateBackendEmitter(store_dir))


@dataclass(frozen=True)
class _TelemetryArtifactInvalidationSink:
    """Adapt ``ArtifactInvalidationEvent`` facts onto the telemetry emitter.

    Bridges the ``verify_system`` invalidation Protocol to the canonical
    telemetry ``EventEmitter`` (FK-27 §27.2.3 / FK-68). Each invalidation fact
    becomes an ``EventType.ARTIFACT_INVALIDATED`` event carrying the moved
    file, the old epoch and the source/stale paths. Emission never raises
    (``StateBackendEmitter.emit`` swallows storage errors, ARCH-20); the file
    move has already happened, so a telemetry hiccup never corrupts QA truth.
    """

    emitter: project_types.EventEmitter

    def artifact_invalidated(self, event: verify_types.ArtifactInvalidationEvent) -> None:
        """Emit an ``artifact_invalidated`` telemetry event for one moved file.

        Args:
            event: The invalidation fact (story, filename, epoch, paths).
        """
        from agentkit.backend.telemetry.events import Event, EventType

        self.emitter.emit(
            Event(
                story_id=event.story_id,
                event_type=EventType.ARTIFACT_INVALIDATED,
                phase="implementation",
                source_component="verify-system",
                payload={
                    "filename": event.filename,
                    "old_epoch": event.old_epoch,
                    "source_path": str(event.source_path),
                    "stale_path": str(event.stale_path),
                },
            )
        )


def build_review_completion_sink(store_dir: Path) -> verify_types.ReviewCompletionSink:
    """Build the productive ``llm_call_complete`` telemetry sink (FIX-C).

    Composition-Root wiring for FK-27 §27.4.3 / §27.5.5: after each Layer-2
    review artefact is written, the QA-subflow emits a canonical
    ``llm_call_complete`` execution event (carrying the reviewer role) through
    the canonical :class:`StateBackendEmitter`. This is what the
    ``guard.multi_llm`` Gate 2 counts (per mandatory reviewer role) so the gate
    is meaningful: it passes a genuine multi-LLM run and FAILS when reviews are
    missing (FK-37 §37.1.6). ``verify_system`` only knows the
    ``ReviewCompletionSink`` Protocol; the telemetry import lives HERE.

    Args:
        store_dir: Story working directory (the canonical event store root).

    Returns:
        A productive sink that emits ``llm_call_complete`` events.
    """
    from agentkit.backend.telemetry.storage import StateBackendEmitter

    return _TelemetryReviewCompletionSink(StateBackendEmitter(store_dir))


@dataclass(frozen=True)
class _TelemetryReviewCompletionSink:
    """Adapt ``ReviewCompletionEvent`` facts onto the telemetry emitter (FIX-C).

    Bridges the ``verify_system`` review-completion Protocol to the canonical
    telemetry ``EventEmitter`` (FK-27 §27.4.3 / §27.5.5). Each completion fact
    becomes an ``EventType.LLM_CALL_COMPLETE`` event whose payload ``role``
    matches the ``guard.multi_llm`` per-role filter. The event is emitted ONLY
    after the review artefact write succeeded (the caller invokes the sink after
    a successful envelope write), per FK-27 §27.4.3. Emission never raises
    (``StateBackendEmitter.emit`` swallows storage errors, ARCH-20); the review
    artefact is already written, so a telemetry hiccup never corrupts QA truth.
    The run scope is resolved by the emitter from ``store_dir`` (the SAME run
    scope the recurring-guard count reads), so the emitted event lands under the
    active run and the run-scoped Gate-2 count finds it (FK-33 §33.3.2).
    """

    emitter: project_types.EventEmitter

    def review_completed(self, event: verify_types.ReviewCompletionEvent) -> None:
        """Emit an ``llm_call_complete`` telemetry event for one completed review.

        Args:
            event: The completion fact (story, reviewer role, artefact filename).
        """
        from agentkit.backend.telemetry.events import Event, EventType

        self.emitter.emit(
            Event(
                story_id=event.story_id,
                event_type=EventType.LLM_CALL_COMPLETE,
                phase="implementation",
                source_component="verify-system",
                payload={
                    "role": event.role,
                    "artifact_filename": event.artifact_filename,
                },
            )
        )

def build_github_code_backend_port(owner: str, repo: str, *, gh_timeout_seconds: int = 30) -> closure_types.CodeBackendPort:
    """Wire the productive GitHub adapter onto the AG3-146 code-backend port.

    Composition root for :class:`CodeBackendPort` (FK-12 §12.1): binds the
    GitHub reference-provider adapter (``gh`` CLI mechanics for the
    capabilities that need them, ``git ls-remote`` for the provider-neutral
    read capabilities) to a single ``owner/repo`` coordinate. GitHub is the
    reference provider (FK-12 §12.1.1); PO Directive III (Azure DevOps
    readiness) is honored by every consumer depending only on
    :class:`CodeBackendPort` -- swapping the productive provider later means
    adding an analogous builder here, never touching a consumer.

    Args:
        owner: The GitHub owner/organisation login (opaque outside this
            builder -- ``CodeBackendPort`` itself carries no owner/repo
            semantics, FK-12 §12.1 provider-neutrality).
        repo: The GitHub repository name.
        gh_timeout_seconds: Per-invocation timeout for the adapter's ``gh``
            subprocess (``repo_probe``).

    Returns:
        A :class:`CodeBackendPort` bound to ``owner/repo``.
    """
    from agentkit.integration_clients.github.adapter import GitHubCodeBackendAdapter

    return GitHubCodeBackendAdapter(owner=owner, repo=repo, gh_timeout_seconds=gh_timeout_seconds)


def _build_repo_code_backend_port(repo: project_types.RepositoryConfig, project_root: Path) -> closure_types.CodeBackendPort:
    """Bind ONE participating repo's coordinate onto a ``CodeBackendPort`` (AG3-147).

    The provider-specific half of the push-barrier evidence port (kept OUT of the
    provider-neutral ``control_plane`` BC, PO Directive III): derives the GitHub
    ``(owner, repo)`` from the config ``remote_url`` and uses it -- or the
    configured repo path -- as the ``git ls-remote`` remote for the server
    ref-read (``remote_url_override`` accepts a URL OR a local path, so this works
    for a real GitHub remote and a local bare-repo fixture alike). Only
    ``ref_read`` is exercised by the barrier, so a non-github remote (no parseable
    owner/repo) still reads correctly via the override.
    """
    from agentkit.backend.installer.github_coordinates import parse_github_remote_url
    from agentkit.integration_clients.github.adapter import GitHubCodeBackendAdapter

    remote = repo.remote_url or str(repo.path if repo.path.is_absolute() else project_root / repo.path)
    coordinates = parse_github_remote_url(repo.remote_url) if repo.remote_url else None
    owner, name = coordinates or (repo.name, repo.name)
    return GitHubCodeBackendAdapter(owner=owner, repo=name, remote_url_override=remote)


@dataclass(frozen=True)
class _ControlPlaneQaCyclePushBarrierGate:
    """Productive QA-cycle-boundary gate delegating to the control-plane barrier.

    AG3-147 (FK-10 §10.2.4b boundary type 2, the design-decision boundary): the
    verify-system QA-cycle lifecycle reads the persisted ``PushBarrierVerdict``
    SSOT at the QA-cycle boundary. It does not re-derive from push freshness.
    """

    @staticmethod
    def _sync_point_id(current: Any) -> str:
        """Build the per-QA-round correlation id for this boundary crossing."""
        from agentkit.backend.control_plane.push_sync import SyncPointBarrierType

        if current.qa_cycle_id is None or current.qa_cycle_round is None:
            msg = "QA-cycle boundary fail-closed: incomplete QA-cycle identity"
            raise ValueError(msg)
        return f"{SyncPointBarrierType.QA_CYCLE_BOUNDARY.value}:{current.qa_cycle_id}:round-{current.qa_cycle_round}"

    def _commission_sync_push_best_effort(self, story_dir: Path, *, sync_point_id: str) -> None:
        """Queue QA-boundary ``sync_push`` commands before evaluating evidence."""
        from datetime import UTC, datetime

        from agentkit.backend.control_plane.push_sync import SyncPointBarrierType
        from agentkit.backend.state_backend.harness_edge_command_store import (
            commission_edge_command_record_global,
            load_edge_command_record_global,
            supersede_open_edge_command_global,
        )
        from agentkit.backend.state_backend.story_closure_store import (
            load_push_barrier_verdict_global,
            upsert_push_barrier_verdict_global,
        )

        try:
            boundary = self._qa_boundary_binding(story_dir, sync_point_id)
            if boundary is None:
                return
            now = datetime.now(tz=UTC)
            verdicts = push_barrier_lifecycle.bind_push_boundary(
                project_key=boundary.scope.project_key,
                story_id=boundary.scope.story_id,
                run_id=boundary.scope.run_id,
                boundary_type=SyncPointBarrierType.QA_CYCLE_BOUNDARY,
                boundary_id=boundary.boundary_id,
                repo_ids=tuple(boundary.ctx.participating_repos),
                ownership_epoch=boundary.active.ownership_epoch,
                load_verdict=load_push_barrier_verdict_global,
                persist_verdict=upsert_push_barrier_verdict_global,
                now=now,
            )
            push_barrier_lifecycle.commission_sync_push_commands(
                project_key=boundary.scope.project_key,
                story_id=boundary.scope.story_id,
                run_id=boundary.scope.run_id,
                owner_session_id=boundary.active.owner_session_id,
                ownership_epoch=boundary.active.ownership_epoch,
                boundary_type=SyncPointBarrierType.QA_CYCLE_BOUNDARY,
                boundary_id=boundary.boundary_id,
                verdicts=verdicts,
                load_command=load_edge_command_record_global,
                commission_command=commission_edge_command_record_global,
                persist_blocked_verdict=upsert_push_barrier_verdict_global,
                supersede_open_command=supersede_open_edge_command_global,
                now=now,
            )
        except Exception as exc:  # noqa: BLE001 -- queue failure cannot open barrier
            import logging

            logging.getLogger(__name__).warning("sync_push commissioning failed before QA-cycle barrier: %s", exc)

    @staticmethod
    def _qa_boundary_binding(story_dir: Path, sync_point_id: str) -> qa_boundary.QaBoundaryBinding | None:
        """Resolve QA boundary identity, story context, and active ownership."""
        from agentkit.backend.control_plane.push_sync import SyncPointBarrierType
        from agentkit.backend.state_backend.runtime_scope_resolver import (
            resolve_runtime_scope,
        )
        from agentkit.backend.state_backend.story_lifecycle_store import (
            load_active_run_ownership_record_global,
            load_story_context,
        )

        scope = resolve_runtime_scope(story_dir)
        ctx = load_story_context(story_dir)
        active = load_active_run_ownership_record_global(scope.project_key, scope.story_id)
        boundary_id = qa_boundary.boundary_id_from_sync_point(
            sync_point_id,
            expected_type=SyncPointBarrierType.QA_CYCLE_BOUNDARY,
        )
        if ctx is None or active is None or active.run_id != scope.run_id:
            return None
        if boundary_id is None:
            return None
        return qa_boundary.QaBoundaryBinding(scope=scope, ctx=ctx, active=active, boundary_id=boundary_id)

    def enforce(self, story_dir: Path, current: Any) -> None:
        """Raise when the QA_CYCLE_BOUNDARY barrier is not satisfied (fail-closed)."""
        from datetime import UTC, datetime

        from agentkit.backend.control_plane.push_sync import SyncPointBarrierType
        from agentkit.backend.state_backend.runtime_scope_resolver import (
            resolve_runtime_scope,
        )
        from agentkit.backend.state_backend.story_closure_store import (
            list_push_barrier_verdicts_global,
            upsert_push_barrier_verdict_global,
        )
        from agentkit.backend.state_backend.story_lifecycle_store import (
            load_story_context,
        )
        from agentkit.backend.verify_system.qa_cycle.lifecycle import (
            QaCycleBarrierBlockedError,
        )

        try:
            sync_point_id = self._sync_point_id(current)
        except ValueError as exc:
            raise QaCycleBarrierBlockedError(str(exc)) from exc
        self._commission_sync_push_best_effort(story_dir, sync_point_id=sync_point_id)
        try:
            scope = resolve_runtime_scope(story_dir)
        except Exception as exc:  # noqa: BLE001 -- unresolvable scope -> fail-closed block
            msg = f"QA-cycle boundary fail-closed: run scope unresolvable ({exc})"
            raise QaCycleBarrierBlockedError(msg) from exc
        project_key = getattr(scope, "project_key", None)
        story_id = getattr(scope, "story_id", None)
        run_id = getattr(scope, "run_id", None)
        if not project_key or not story_id or not run_id:
            msg = "QA-cycle boundary fail-closed: incomplete run scope"
            raise QaCycleBarrierBlockedError(msg)
        boundary_id = qa_boundary.boundary_id_from_sync_point(
            sync_point_id,
            expected_type=SyncPointBarrierType.QA_CYCLE_BOUNDARY,
        )
        if boundary_id is None:
            msg = "QA-cycle boundary fail-closed: invalid boundary correlation"
            raise QaCycleBarrierBlockedError(msg)
        try:
            verdicts = list_push_barrier_verdicts_global(
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                boundary_type=SyncPointBarrierType.QA_CYCLE_BOUNDARY,
                boundary_id=boundary_id,
            )
        except Exception as exc:  # noqa: BLE001 -- unavailable verdict SSOT -> block
            msg = f"QA-cycle boundary fail-closed: verdict SSOT unavailable ({exc})"
            raise QaCycleBarrierBlockedError(msg) from exc
        ctx = load_story_context(story_dir)
        expected_repo_ids = tuple(ctx.participating_repos) if ctx is not None else ()
        aggregate = push_barrier_lifecycle.aggregate_persisted_push_barrier(
            SyncPointBarrierType.QA_CYCLE_BOUNDARY,
            tuple(verdicts),
            expected_repo_ids=expected_repo_ids,
            server_head_for_verdict=lambda verdict: server_head_for_push_barrier_verdict(
                verdict,
                evidence_factory=composition_root_attr("build_push_barrier_evidence"),
            ),
            persist_blocked_verdict=upsert_push_barrier_verdict_global,
            now=datetime.now(tz=UTC),
        )
        if not aggregate.passed:
            blocking = ", ".join(
                f"{v.repo_id}:{v.block_code.value if v.block_code else 'unverified'}"
                for v in aggregate.repo_verdicts
                if not v.verified
            ) or "no verdict rows"
            msg = (
                "push_barrier_unverified: QA-cycle boundary blocked -- the story "
                "branch is not server-verified-pushed in every repo (FK-10 "
                f"§10.2.4b). Unverified repos: {blocking}"
            )
            raise QaCycleBarrierBlockedError(msg)


@dataclass(frozen=True)
class _StateBackedQaCycleFingerprintSource:
    """Resolve QA-cycle fingerprint heads from push-freshness records (AC11)."""

    def collect(self, story_dir: Path) -> tuple[verify_types.ReportedHeadEvidence, ...]:
        from agentkit.backend.state_backend.runtime_scope_resolver import (
            resolve_runtime_scope,
        )
        from agentkit.backend.state_backend.story_closure_store import (
            list_push_freshness_records_global,
        )
        from agentkit.backend.verify_system.qa_cycle.fingerprint import (
            FingerprintComputationError,
            ReportedHeadEvidence,
        )

        try:
            scope = resolve_runtime_scope(story_dir)
            if scope.run_id is None:
                raise FingerprintComputationError("QA-cycle fingerprint evidence has incomplete run scope")
            records = list_push_freshness_records_global(
                scope.project_key,
                scope.story_id,
                scope.run_id,
            )
        except Exception as exc:  # noqa: BLE001 -- fingerprinting is fail-closed
            msg = f"QA-cycle fingerprint evidence is unavailable: {exc}"
            raise FingerprintComputationError(msg) from exc
        heads = tuple(
            ReportedHeadEvidence(
                repo_id=record.repo_id,
                head_sha=record.last_pushed_head_sha or "",
            )
            for record in records
            if record.last_pushed_head_sha is not None and not record.backlog
        )
        if not heads:
            raise FingerprintComputationError("QA-cycle fingerprint evidence has no pushed head records")
        return heads


def build_qa_cycle_push_barrier_gate() -> verify_types.QaCyclePushBarrierGate:
    """Wire the productive QA-cycle-boundary push-barrier gate (AG3-147, AC2)."""
    return _ControlPlaneQaCyclePushBarrierGate()


def build_push_barrier_evidence() -> verify_types.PushBarrierEvidencePort:
    """Wire the productive two-stage push-barrier evidence port (AG3-147, FK-10 §10.2.4b).

    Composition root for the hard push barriers: binds the Postgres-only
    push-freshness read (the Edge report) and the provider-neutral
    ``CodeBackendPort.ref_read`` (the server ``ls-remote`` read) behind the
    ``control_plane`` port. The ``project_root`` is resolved from canonical
    level-1 state (``project_registry``) via the workspace locator (AG3-123),
    never a dev-supplied path.
    """
    from agentkit.backend.control_plane.push_verification import (
        StateBackedPushBarrierEvidence,
    )
    from agentkit.backend.control_plane.workspace_locator import (
        build_story_workspace_locator,
    )

    return StateBackedPushBarrierEvidence(
        workspace_locator=build_story_workspace_locator(),
        code_backend_factory=_build_repo_code_backend_port,
    )
