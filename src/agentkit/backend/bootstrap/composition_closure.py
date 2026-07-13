"""Closure, structural evidence, and failure-corpus composition builders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.bootstrap.composition_artifacts import build_artifact_manager
from agentkit.backend.bootstrap.composition_config import _project_config_present
from agentkit.backend.bootstrap.composition_governance import build_integrity_gate
from agentkit.backend.bootstrap.composition_verify import _SubprocessGitChangeEvidenceProvider, build_push_verification_port

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.bootstrap import composition_closure_types as closure_types
    from agentkit.backend.bootstrap import composition_project_types as project_types
    from agentkit.backend.bootstrap import composition_verify_types as verify_types
    from agentkit.backend.story_context_manager.models import StoryContext


def build_closure_phase_handler(
    config: object,
    *,
    store_dir: Path | None = None,
    project_key: str = "",
    project_root: Path | None = None,
    layer2_llm_client: verify_types.LlmClient | None = None,
) -> closure_types.ClosurePhaseHandler:
    """Wire a fully-collaborated ``ClosurePhaseHandler`` (FK-29, AG3-053).

    Composition root for the Closure phase (BC 7, ``story-closure``): assembles
    the collaborators the truth-boundary-protected handler may NOT build itself
    (DI pattern, analog ``build_setup_phase_handler`` / ``build_verify_system``).
    The handler ORCHESTRATES the canonical FK-29 §29.1.4 sequence by CALLING
    these capabilities; it builds no second merge/gate/Sonar/lock truth:

    * ``integrity_gate`` -- :func:`build_integrity_gate` (AG3-034 verifier; its
      Dim 9 consumes the AG3-052 Sonar capability to verify the fresh
      attestation, FK-35 §35.2.4a).
    * ``artifact_manager`` -- :func:`build_artifact_manager` (the only Layer-2
      read seam for the Finding-Resolution-Gate, FK-29 §29.2).
    * ``scan_port`` / ``build_test_port`` -- the AG3-056 Pre-Merge-Verification-
      Runner's commit-bound ``CiSonarScanRunner`` / ``CiBuildTestRunner`` (FK-29
      §29.1a.3 steps c/d), wired via ``build_pre_merge_runners`` over one shared
      CI run. ``None`` for a declared-absent CI (``ci.available == false``);
      applicable-but-unreachable raises ``PreMergeRunnerUnavailableError``
      (fail-closed). The old fail-open ``build_sonar_gate_port_for_run`` scan path
      is REMOVED -- AG3-053 consumes AG3-056.
    * ``sonar_config`` -- the FK-03 ``sonarqube`` stanza, threaded into the
      fresh-attestation Dim-9 version-drift check (FK-35 §35.2.4a item 5).
    * ``sanity_port`` -- the fast-mode Sanity-Gate seam (FK-29 §29.1a.6).
    * ``doc_fidelity_port`` -- level-4 doc-fidelity feedback via
      ``verify_system.llm_evaluator`` (FK-38 §38.3.1, non-blocking).
    * ``vectordb_sync_port`` -- the FK-13 §13.7.1 sync trigger (non-blocking).
    * ``guard_deactivation_port`` -- ``Governance.deactivate_locks`` (FK-29 §29.5,
      governance top surface; closure holds no lock logic).

    Args:
        config: A ``ClosureConfig`` carrying ``story_dir`` (+ optional GitHub /
            story-service fields). The collaborator slots are overwritten here.
        store_dir: State-backend base dir (SQLite); ``None`` => the config's
            ``story_dir``.
        project_key: Owning project key for the governance top surface.
        project_root: The Backend-resolved
            :class:`~agentkit.backend.control_plane.workspace_locator.StoryWorkspace`
            anchor (AG3-123). The pre-merge ``ci``/``sonarqube`` config root is
            read from it — NOT by reloading the run ``StoryContext`` and reading a
            dev-supplied ``ctx.project_root``. ``None`` (test/legacy callers)
            falls back to the canonical ``<project_root>/stories/<story_id>``
            layout derived structurally from ``config.story_dir`` — the SAME
            anchor the workspace yields, never a ``cwd`` or ctx-supplied path.
        layer2_llm_client: The Layer-2 LLM transport (the same one passed to
            ``build_verify_system``), injected into the level-4 doc-fidelity
            feedback seam so it runs a REAL evaluation through the shared
            ``ConformanceService`` path. ``None`` => the fail-closed default
            (the seam still runs and yields a real FAIL verdict).

    Returns:
        A wired ``ClosurePhaseHandler``.
    """
    from agentkit.backend.closure.phase import ClosureConfig, ClosurePhaseHandler

    if not isinstance(config, ClosureConfig):
        msg = f"config must be a ClosureConfig; got {type(config).__name__}"
        raise TypeError(msg)
    from agentkit.backend.installer.paths import project_root_for_story_dir

    base_dir = store_dir or config.story_dir or Path.cwd()
    config.progress_store = _build_closure_progress_store(base_dir)
    config.integrity_gate = build_integrity_gate(base_dir)
    config.artifact_manager = build_artifact_manager(base_dir)
    # AG3-123: the pre-merge config root is the Backend-resolved workspace anchor
    # (threaded down), NOT a re-loaded ``ctx.project_root``. When omitted by a
    # test/legacy caller it is derived structurally from the canonical story_dir
    # layout -- the identical anchor, never a cwd/ctx fallback.
    effective_project_root = project_root or (
        project_root_for_story_dir(config.story_dir) if config.story_dir is not None else None
    )
    ci_config, sonar_config = _resolve_pre_merge_configs(effective_project_root)
    config.sonar_config = sonar_config
    # FIX-C: build a runner pair PER participating repo (each bound to ITS OWN
    # root/ledger/tree), so every repo is verified against its own root. The
    # single-repo path is the one-entry case (config.repos empty => the story_dir
    # repo). The applicability is resolved once (story-type + ci/sonar facets are
    # the same across repos for one story).
    repo_roots = _closure_repo_roots(config, base_dir)
    repo_runners, applicability = _build_per_repo_runners(ci_config, sonar_config, repo_roots)
    config.merge_applicability = applicability
    primary = repo_runners[repo_roots[0]]
    config.scan_port = primary.scan_port
    config.build_test_port = primary.build_test_port
    config.repo_runners = repo_runners
    from agentkit.backend.closure.edge_merge import (
        ClosureEntryPushVerificationPort,
        QueueMergeLocalCommandPort,
    )
    from agentkit.backend.control_plane.repository import EdgeCommandRepository

    merge_local_port = QueueMergeLocalCommandPort(
        edge_commands=EdgeCommandRepository()
    )
    config.merge_local_port = merge_local_port
    config.push_verification_port = ClosureEntryPushVerificationPort()
    config.doc_fidelity_port = _build_doc_fidelity_feedback_port(
        layer2_llm_client,
        change_evidence_provider=merge_local_port.feedback_change_evidence,
    )
    config.vectordb_sync_port = _build_vectordb_sync_port()
    config.guard_deactivation_port = _build_guard_deactivation_port(base_dir, project_key=project_key)
    config.mode_lock_release_port = _build_mode_lock_release_port(base_dir)
    config.change_evidence_port = _SubprocessGitChangeEvidenceProvider(push_verification_port=build_push_verification_port())
    config.telemetry_evidence_port = _build_telemetry_evidence_port(base_dir, project_key=project_key)
    config.guard_counter_flush_port = _build_guard_counter_flush_port(base_dir)
    return ClosurePhaseHandler(config)


def _build_guard_counter_flush_port(store_dir: Path) -> closure_types.GuardCounterFlushPort:
    """Build the Closure guard-counter flush seam (FK-61 §61.4.3 Trigger 1, AG3-081).

    Delegates to the kpi-owned ``GuardCounterService.flush_on_closure`` over the
    productive state-backend counter repository. Drains the story's
    ``guard_invocation_counters`` at Closure (the ``fact_guard_period`` drain is
    AG3-082).
    """
    from agentkit.backend.closure.runtime_ports import ProductiveGuardCounterFlushPort

    return ProductiveGuardCounterFlushPort(store_dir=store_dir)


def _build_telemetry_evidence_port(store_dir: Path, *, project_key: str) -> closure_types.TelemetryEvidencePort:
    """Build the Closure Telemetry-Evidence-Block seam (FK-68 §68.4, AG3-081).

    Runs the six FK-68 §68.4 proofs against the run's ``execution_events`` at
    Closure (fail-closed). The authoritative review/llm/web budget config is read
    from the project root by the port itself (truth boundary); the gate never
    knows provider names (FK-68 §68.4: checked against configuration, not against
    hardcoded provider names).
    """
    from agentkit.backend.closure.runtime_ports import ProductiveTelemetryEvidencePort

    return ProductiveTelemetryEvidencePort(project_key=project_key, project_root=store_dir)


def _build_mode_lock_release_port(store_dir: Path) -> closure_types.ModeLockReleasePort:
    """Build the project mode-lock release seam (FK-24 §24.3.3, AG3-018).

    Delegates to the atomic ``ModeLockRepository.release`` for the mode this story
    acquired at Setup (read from the durable acquire marker). Closure holds no
    mode-lock logic itself.
    """
    from agentkit.backend.closure.runtime_ports import ProductiveModeLockReleasePort
    from agentkit.backend.state_backend.store.mode_lock_repository import ModeLockRepository

    return ProductiveModeLockReleasePort(mode_lock_repo=ModeLockRepository(store_dir))


def _build_closure_progress_store(store_dir: Path) -> closure_types.ClosureProgressStore:
    """Build the closure checkpoint store (FK-29 §29.1.0, AC003 pipeline surface).

    Phase-state mutation may only happen through a pipeline surface
    (architecture-conformance AC003), so the closure checkpoint writes go through
    the ``pipeline_engine`` :class:`PhaseEnvelopeStore` (over the state-backend
    phase-envelope repository) -- NOT a direct ``save_phase_state`` import in the
    closure BC.
    """
    from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
    from agentkit.backend.state_backend.store.phase_envelope_repository import (
        StateBackendPhaseEnvelopeRepository,
    )

    return PhaseEnvelopeStore(StateBackendPhaseEnvelopeRepository(store_dir))

class ClosureConfigUnavailableError(Exception):
    """The closure pre-merge config/context is broken (fail-closed, FIX-2).

    Raised by :func:`_resolve_pre_merge_configs` when the story context or the
    project config is PRESENT-but-unreadable/malformed, as opposed to a
    DELIBERATE absence (no ``ci``/``sonarqube`` stanza or ``available == false``).
    A broken config must never silently disable the integrated-candidate
    verification (NO ERROR BYPASSING) -- the composition root surfaces this
    before building the handler so the run escalates rather than merging code
    unverified.
    """


def _resolve_pre_merge_configs(
    project_root: Path | None,
) -> tuple[object | None, object | None]:
    """Resolve the ``ci`` + ``sonarqube`` config stanzas (truth boundary, AG3-056).

    The composition root owns the project-config read (``governance``/``closure``
    stay free of direct config reads). Loads the ``ci`` (Jenkins) and ``sonarqube``
    stanzas for the AG3-056 pre-merge runner wiring + the Dim-9 version-drift check.

    AG3-123: the ``project_root`` is the Backend-resolved
    :class:`~agentkit.backend.control_plane.workspace_locator.StoryWorkspace`
    anchor threaded down from the dispatcher — it is NO LONGER re-derived by
    reloading the run ``StoryContext`` and reading its dev-supplied
    ``ctx.project_root``. The locator is the SINGLE source for the workspace
    location (FIX THE MODEL); an unresolvable workspace already failed the
    dispatch closed at the locator (FK-10 §10.6), so a valid anchor is supplied.

    FIX-2 fail-closed distinction (a broken config must NEVER silently disable
    verification, NO ERROR BYPASSING):

    * DELIBERATE absence -- no AK3 config file / no ``pipeline`` stanza (a
      non-code-producing project never declares CI/Sonar) -> ``(None, None)``:
      the runner wiring treats it as a declared skip and the applicability layer
      (FIX-3) decides per story type whether that is allowed.
    * BROKEN config -- an unresolvable project root, or a config that fails to
      load/parse -> FAIL-CLOSED (:class:`ClosureConfigUnavailableError`). Never
      downgraded to a declared absence.

    A PRESENT stanza with ``available == false`` is also a deliberate absence,
    but that is decided downstream (``build_pre_merge_runners`` returns ``None``
    for it); here we only fail closed on a genuinely broken read.
    """
    from agentkit.backend.config.loader import load_project_config

    if project_root is None:
        raise ClosureConfigUnavailableError(
            "closure config resolution requires a resolvable project_root "
            "(FIX-2 / AG3-123, fail-closed -- the Backend-resolved workspace "
            "anchor could not be determined)"
        )
    if not _project_config_present(project_root):
        # Deliberate absence: the project declares no AK3 config file at all
        # (a non-code-producing project never wires a pipeline). The
        # applicability layer (FIX-3) decides per story type whether a missing
        # runner is allowed -- it is for concept/research, fail-closed for code.
        return (None, None)
    try:
        project_config = load_project_config(project_root)
    # Broken config is fail-closed, not absence.
    except Exception as exc:  # noqa: BLE001
        raise ClosureConfigUnavailableError(
            f"project config at {project_root} is present but "
            f"unreadable/malformed (FIX-2, fail-closed -- a broken config never "
            f"silently disables Sonar/CI): {exc}"
        ) from exc
    pipeline = getattr(project_config, "pipeline", None)
    if pipeline is None:
        # Deliberate absence: no pipeline stanza (non-code-producing project).
        return (None, None)
    return (getattr(pipeline, "ci", None), getattr(pipeline, "sonarqube", None))


def _build_pre_merge_runners(
    ci_config: object | None,
    sonar_config: object | None,
    *,
    repo_root: Path,
) -> tuple[closure_types.PreMergeScanPort | None, verify_types.BuildTestPort | None, closure_types.MergeApplicability]:
    """Wire the AG3-056 pre-merge runners + resolve the typed applicability (FIX-3).

    CONSUMES AG3-056's
    :func:`verify_system.pre_merge_runner.runtime_wiring.build_pre_merge_runners`
    (the old fail-open ``build_sonar_gate_port_for_run`` scan path is REMOVED).
    The applicability is resolved HERE (the applicability layer, FIX-3) from the
    ``ci``/``sonarqube`` availability and threaded onto the handler so a declared
    absence never silently merges code unverified (FK-33 §33.6.5 "absent !=
    broken"):

    * CI DECLARED absent (no stanza / ``ci.available == false``) ->
      ``(None, None, CI_ABSENT)``: for a code-producing story the handler
      fail-closes (cannot verify => cannot merge); for concept/research the
      block is skipped entirely (``uses_merge == False``).
    * CI present + Sonar DECLARED absent (no stanza / ``sonarqube.available ==
      false``) -> ``(None, build_test, SONAR_ABSENT)``: Build/Test runs (built
      via the additive :func:`build_build_test_runner`), the integrated-candidate
      scan + Dim 9 are skipped, the merge stays gated.
    * CI present + Sonar present -> ``(scan, build_test, FULL)`` via
      ``build_pre_merge_runners`` (shared single run-cache).
    * APPLICABLE-but-unreachable (``available == true`` but the endpoint/token
      cannot be resolved) raises ``PreMergeRunnerUnavailableError`` ->
      fail-closed (NEVER a silent skip).

    Args:
        ci_config: The resolved ``JenkinsConfig`` (or ``None``).
        sonar_config: The resolved ``SonarQubeConfig`` (or ``None``).
        repo_root: The integrated-candidate repo root (tree-hash + ledger read).

    Returns:
        ``(scan_port, build_test_port, applicability)``.
    """
    from agentkit.backend.closure.merge_sequence import MergeApplicability
    from agentkit.backend.config.models import JenkinsConfig, SonarQubeConfig
    from agentkit.backend.verify_system.pre_merge_runner.runtime_wiring import (
        build_build_test_runner,
        build_pre_merge_runners,
    )

    typed_ci = ci_config if isinstance(ci_config, JenkinsConfig) else None
    typed_sonar = sonar_config if isinstance(sonar_config, SonarQubeConfig) else None

    ci_present = typed_ci is not None and typed_ci.available
    if not ci_present:
        # Declared-absent CI: no Build/Test+scan runner. The handler fail-closes
        # for code-producing stories (FIX-3); concept/research skip the block.
        return (None, None, MergeApplicability.CI_ABSENT)

    sonar_present = typed_sonar is not None and typed_sonar.available
    if not sonar_present:
        # CI present, Sonar declared absent: Build/Test only, scan+Dim9 skipped.
        build_test_port = build_build_test_runner(typed_ci, repo_root)
        return (None, build_test_port, MergeApplicability.SONAR_ABSENT)

    runners = build_pre_merge_runners(typed_ci, typed_sonar, repo_root)
    if runners is None:  # pragma: no cover - ci_present already guaranteed above
        return (None, None, MergeApplicability.CI_ABSENT)
    return (runners.scan, runners.build_test, MergeApplicability.FULL)


def _closure_repo_roots(config: object, base_dir: Path) -> list[Path]:
    """Resolve the participating repo roots for the per-repo runner wiring (FIX-C).

    Mirrors the handler's ``_resolve_repos``: the configured ``ClosureRepo`` roots
    when present, else the single story-dir repo (one entry). Order-preserving and
    de-duplicated so each distinct root gets exactly one runner pair.
    """
    from agentkit.backend.closure.phase import ClosureConfig

    assert isinstance(config, ClosureConfig)  # noqa: S101 - caller validated
    roots: list[Path] = []
    if config.repos:
        for repo in config.repos:
            if repo.repo_root not in roots:
                roots.append(repo.repo_root)
    else:
        roots.append(config.story_dir or base_dir)
    return roots


def _build_per_repo_runners(
    ci_config: object | None,
    sonar_config: object | None,
    repo_roots: list[Path],
) -> tuple[dict[Path, closure_types.RepoRunners], closure_types.MergeApplicability]:
    """Build a :class:`RepoRunners` pair per repo root + the shared applicability (FIX-C).

    Each repo root gets its OWN ``CiSonarScanRunner`` / ``CiBuildTestRunner``
    (via :func:`_build_pre_merge_runners`, so its ledger + tree-hash resolver bind
    to that root). The applicability is identical across repos (it derives from
    the story-type + the ci/sonar facets, which are project-wide for one story);
    it is resolved per repo and asserted consistent (a fail-closed invariant).
    """
    from agentkit.backend.closure.merge_sequence import RepoRunners

    runners: dict[Path, closure_types.RepoRunners] = {}
    resolved_applicability: closure_types.MergeApplicability | None = None
    for repo_root in repo_roots:
        scan_port, build_test_port, applicability = _build_pre_merge_runners(ci_config, sonar_config, repo_root=repo_root)
        if resolved_applicability is None:
            resolved_applicability = applicability
        elif applicability is not resolved_applicability:  # pragma: no cover
            msg = (
                "inconsistent pre-merge applicability across repos: "
                f"{resolved_applicability} vs {applicability} "
                "(the ci/sonar facets must be project-wide for one story)"
            )
            raise ClosureConfigUnavailableError(msg)
        runners[repo_root] = RepoRunners(scan_port=scan_port, build_test_port=build_test_port)
    # ``repo_roots`` always has at least one entry (the story-dir fallback).
    assert resolved_applicability is not None  # noqa: S101 - non-empty roots
    return runners, resolved_applicability


def _build_doc_fidelity_feedback_port(
    layer2_llm_client: verify_types.LlmClient | None = None,
    *,
    change_evidence_provider: Callable[[StoryContext, Path], str | None] | None = None,
) -> closure_types.DocFidelityFeedbackPort:
    """Build the level-4 doc-fidelity feedback seam (FK-38 §38.3.1, non-blocking).

    Runs a REAL level-4 evaluation through the SAME productive
    ``ConformanceService.check_fidelity(level=feedback)`` path the Layer-2
    reviewers use (``role=doc_fidelity``, prompt ``doc-fidelity-feedback.md``,
    ``expected_checks=["feedback_fidelity"]``), evaluating the final diff vs the
    existing project docs (FK-38 §38.3.1). The Layer-2 ``llm_client`` is injected
    here so this seam shares the EXACT transport ``build_verify_system`` resolves
    — when the productive LLM pool lands (AG3-070) both paths get it; until then
    the fail-closed default yields a real FAIL verdict (non-blocking Warning +
    failure-corpus incident candidate), never a silent no-op.

    Args:
        layer2_llm_client: The Layer-2 LLM transport (same one passed to
            ``build_verify_system``). ``None`` => the fail-closed default inside
            the port, so the evaluation still RUNS.
    """
    from agentkit.backend.closure.runtime_ports import ProductiveDocFidelityFeedbackPort

    return ProductiveDocFidelityFeedbackPort(
        llm_client=layer2_llm_client,
        change_evidence_provider=change_evidence_provider,
    )


def _build_vectordb_sync_port() -> closure_types.VectorDbSyncPort:
    """Build the VectorDB sync seam (FK-13 §13.7.1, fire-and-forget, non-blocking).

    Triggers an async ``story_sync``. The VectorDB integration is not yet
    available in the target project; the seam is honest non-blocking — it records
    a human Warning when the sync cannot be triggered (the STEP still runs).
    """
    from agentkit.backend.closure.runtime_ports import ProductiveVectorDbSyncPort

    return ProductiveVectorDbSyncPort()


def _build_guard_deactivation_port(store_dir: Path, *, project_key: str) -> closure_types.GuardDeactivationPort:
    """Build the guard-deactivation seam (FK-29 §29.5, governance top surface).

    Delegates to ``Governance.deactivate_locks`` via a real ``Governance`` wired
    with the state-backend lock/hook/worktree repositories. Closure holds no lock
    logic itself (single delegation step).
    """
    from agentkit.backend.closure.runtime_ports import ProductiveGuardDeactivationPort
    from agentkit.backend.governance import Governance
    from agentkit.backend.state_backend.store.governance_hook_repository import (
        StateBackendHookRegistrationRepository,
    )
    from agentkit.backend.state_backend.store.lock_record_repository import LockRecordRepository

    governance = Governance(
        hook_repo=StateBackendHookRegistrationRepository(store_dir),
        lock_repo=LockRecordRepository(store_dir),
        project_key=project_key,
        project_root=store_dir,
    )
    return ProductiveGuardDeactivationPort(governance)


def build_structural_are_provider(
    are_client: object | None,
    pipeline_config: object,
    *,
    store_dir: Path | None = None,
) -> verify_types.AreGateProvider:
    """Build the REAL Layer-1 ARE provider (FIX-1, FK-27 §27.4.4).

    Wraps the productive :class:`RequirementsCoverage` top-surface (AG3-030,
    FK-40) so the ``are.gate`` stage activates IFF ``features.are == true`` and
    the coverage verdict comes from the real ``check_gate`` dock-point. ARE is
    NEVER silently disabled: when ``features.are`` is true the provider reports
    ``is_enabled == True`` and the gate runs (fail-closed when the verdict is
    unavailable, ``check_are_gate``).

    Args:
        are_client: The configured ``AreClient`` (``None`` when ARE is off).
        pipeline_config: The project's ``PipelineConfig`` (``features.are``).

    Returns:
        An :class:`_RequirementsCoverageAreProvider` over the wired
        ``RequirementsCoverage``.
    """
    from agentkit.backend.config.models import PipelineConfig
    from agentkit.backend.requirements_coverage.are_client import AreClient
    from agentkit.backend.requirements_coverage.top import RequirementsCoverage
    from agentkit.backend.state_backend.store.story_are_link_repository import (
        StateBackendStoryAreLinkRepository,
    )

    if not isinstance(pipeline_config, PipelineConfig):
        msg = f"pipeline_config must be a PipelineConfig; got {type(pipeline_config).__name__}"
        raise TypeError(msg)
    typed_client = are_client if isinstance(are_client, AreClient) else None
    coverage = RequirementsCoverage(
        typed_client,
        pipeline_config,
        link_repository=StateBackendStoryAreLinkRepository(store_dir),
        artifact_manager=build_artifact_manager(store_dir or Path.cwd()),
        audit_root=store_dir,
    )
    return _RequirementsCoverageAreProvider(coverage)


@dataclass(frozen=True)
class _RequirementsCoverageAreProvider:
    """Adapt ``RequirementsCoverage`` to the Layer-1 ``AreGateProvider`` (FIX-1).

    ``is_enabled`` reflects ``features.are`` (ONE activation truth);
    ``coverage_verdict`` delegates to the ``check_gate`` dock-point (FK-40
    §40.5.4). A non-PASS / missing verdict drives the fail-closed ``are.gate``
    finding (FK-27 §27.4.4).

    Attributes:
        coverage: The wired ``RequirementsCoverage`` top-surface.
    """

    coverage: verify_types.RequirementsCoverageProto

    @property
    def are_client(self) -> object | None:
        """Return the injected ARE client for wiring tests."""

        return getattr(self.coverage, "_are_client", None)

    @property
    def is_enabled(self) -> bool:
        """Return whether ``features.are`` is active."""
        return self.coverage.is_enabled

    def coverage_verdict(self, story_id: str, project_key: str) -> verify_types.CoverageVerdict | None:
        """Return the ARE coverage verdict, or ``None`` when ARE is disabled."""
        if not self.coverage.is_enabled:
            return None
        return self.coverage.check_gate(story_id, project_key)


def build_failure_corpus(
    accessor: project_types.ProjectionAccessor,
    project_key: str | None = None,
    store_dir: Path | None = None,
    llm_client: verify_types.LlmClient | None = None,
) -> project_types.FailureCorpus:
    """Create a wired ``FailureCorpus`` top component (AG3-028, AG3-078).

    Composition root for the failure-corpus BC (FK-41 §41.1/§41.4). Wires the
    ``IncidentTriage`` with a default normalizer and IngressCriteria and passes
    the ``ProjectionAccessor`` in both as a narrow ``IncidentWriterPort``
    (``record_fc_incident`` -> ``IncidentId``, FK-41 §41.3.1) and as a
    ``ProjectionReaderPort`` (corpus novelty, FK-41 §41.4.3) (FK-69 §69.9).
    ``failure_corpus`` does NOT know the fc_incidents DB repo adapter
    (CONFLICT-2, AC#6): persistence/reading runs via the ``ProjectionAccessor``.

    AG3-078: When ``project_key`` is provided, also wires the three AG3-078 subs:
    ``PatternPromotion``, ``CheckFactory``, and ``CheckEffectivenessTracker``.
    Without ``project_key`` only ``record_incident`` is functional (existing callers
    that omit project_key retain the AG3-028 behavior).

    The ``CheckFactory`` is wired with an ``AK3StoryCreationAdapter`` and, only
    when ``llm_client`` is supplied, an ``LlmInvariantSharpener``.  The sharpener
    is the step-1 (invariant sharpening) LLM boundary and is the ONLY part of the
    build that needs an LLM transport; it is therefore built lazily.  When
    ``llm_client`` is ``None`` the factory is constructed WITHOUT a sharpener so
    that every non-``derive_check`` command (record_incident, suggest_patterns,
    confirm_pattern, approve_check, report_effectiveness, list_checks) can build
    and run.  ``derive_check`` itself stays FAIL-CLOSED: ``CheckFactory.derive_check``
    raises ``RuntimeError`` if it ever tries to sharpen without a wired sharpener
    (no silent skip).

    Args:
        accessor: The ``ProjectionAccessor`` as the write/read boundary (fulfils
            ``IncidentWriterPort`` and ``ProjectionReaderPort`` by structural typing).
        project_key: Project key for the AG3-078 subs (PatternPromotion,
            CheckFactory, CheckEffectivenessTracker). When ``None`` (default),
            the subs are not wired (backward-compatible with AG3-028 callers).
        store_dir: State-backend base directory. Only relevant for SQLite; passed
            to ``build_projection_repositories`` to obtain the fc_* adapters.
            Defaults to ``Path.cwd()`` when ``project_key`` is given.
        llm_client: LLM transport for invariant sharpening (FK-41 §41.6.2).
            Required when ``project_key`` is provided (FAIL-CLOSED:
            ``LlmInvariantSharpener`` raises if ``None``).  Ignored when
            ``project_key`` is ``None``.

    Returns:
        ``FailureCorpus`` with a functional ``record_incident``; the AG3-078 top
        methods are also functional when ``project_key`` is provided.
    """
    from agentkit.backend.failure_corpus import (
        FailureCorpus as _FailureCorpus,
    )
    from agentkit.backend.failure_corpus import (
        IncidentNormalizer,
        IncidentTriage,
        IngressCriteria,
    )

    triage = IncidentTriage(
        normalizer=IncidentNormalizer(),
        criteria=IngressCriteria(),
        writer=accessor,
        reader=accessor,
    )

    if project_key is None:
        return _FailureCorpus(incident_triage=triage)

    # AG3-078: wire PatternPromotion, CheckFactory, CheckEffectivenessTracker.
    # Repos are obtained from a fresh ProjectionRepositories (the accessor holds
    # them internally but does not expose them via its public surface — we build
    # a parallel repo bundle here to stay within AC#7).
    from agentkit.backend.failure_corpus.check_factory import CheckFactory as _CheckFactory
    from agentkit.backend.failure_corpus.effectiveness import (
        CheckEffectivenessTracker as _CheckEffectivenessTracker,
    )
    from agentkit.backend.failure_corpus.invariant_sharpener import LlmInvariantSharpener as _LlmInvariantSharpener
    from agentkit.backend.failure_corpus.pattern_promotion import PatternPromotion as _PatternPromotion
    from agentkit.backend.failure_corpus.story_creation_adapter import AK3StoryCreationAdapter as _AK3StoryCreationAdapter
    from agentkit.backend.state_backend.store.fc_check_proposal_repository import (
        StateBackendFcCheckProposalRepository,
    )
    from agentkit.backend.state_backend.store.fc_pattern_repository import (
        StateBackendFcPatternRepository,
    )

    _store_dir = store_dir or Path.cwd()
    pattern_repo = StateBackendFcPatternRepository(_store_dir)
    check_repo = StateBackendFcCheckProposalRepository(_store_dir)

    # AG3-078: the LLM invariant sharpener is the ONLY LLM-dependent part of the
    # build and is only needed by derive_check (step 1).  Build it lazily: only
    # when a concrete LLM transport (FK-41 §41.6.2, e.g. HubLlmClient from
    # build_verify_system) is supplied.  Without it the factory is wired WITHOUT
    # a sharpener so the other five top methods (and every non-derive_check CLI
    # subcommand) still build; derive_check stays FAIL-CLOSED via the
    # CheckFactory.derive_check guard (InvariantSharpenerPort is None -> raise).
    _sharpener = _LlmInvariantSharpener(llm_client) if llm_client is not None else None
    _story_creation = _AK3StoryCreationAdapter(project_key)

    pattern_promotion = _PatternPromotion(
        accessor=accessor,
        pattern_repo=pattern_repo,
        project_key=project_key,
    )
    check_factory = _CheckFactory(
        pattern_repo=pattern_repo,
        check_repo=check_repo,
        project_key=project_key,
        invariant_sharpener=_sharpener,
        story_creation=_story_creation,
    )
    effectiveness_tracker = _CheckEffectivenessTracker(
        accessor=accessor,
        check_repo=check_repo,
        pattern_repo=pattern_repo,
        project_key=project_key,
    )
    return _FailureCorpus(
        incident_triage=triage,
        pattern_promotion=pattern_promotion,
        check_factory=check_factory,
        effectiveness_tracker=effectiveness_tracker,
        check_repo=check_repo,
        project_key=project_key,
    )
