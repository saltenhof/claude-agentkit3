"""Governance, setup, skill, and Sonar composition builders."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from agentkit.backend.artifacts import EnvelopeValidator
from agentkit.backend.bootstrap.composition_artifacts import build_artifact_manager, build_producer_registry
from agentkit.backend.bootstrap.composition_config import _project_config_present
from agentkit.backend.bootstrap.composition_state import build_phase_state_residue_probe, build_projection_accessor

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.bootstrap import composition_project_types as project_types
    from agentkit.backend.bootstrap import composition_verify_types as verify_types
    from agentkit.backend.governance.ccag.permission_service import PermissionService


def build_sonar_gate_port(
    config: object,
    *,
    client: object,
    fast: bool,
    story_type: object,
    ledger: object,
    bound_analysis: object,
    main_head_revision: str,
) -> verify_types.SonarGateInputPort:
    """Build the productive ``sonarqube_gate`` port (FK-33 §33.6, AG3-052).

    When ``sonarqube.available == false`` the gate is deliberately absent
    (not-applicable) and the absent default port is returned — never the
    fail-closed adapter (FK-33 §33.6.5 "absent != broken"). Otherwise the
    :class:`ConfiguredSonarGateInputPort` is wired with the per-run
    collaborators; it fails closed on any unreachable/unreadable input.

    The per-run coordinates (the commit-bound analysis, the loaded ledger,
    main HEAD, the fast axis/story type) are resolved by the caller (pipeline
    engine) and passed in; this keeps ``build_verify_system`` free of
    per-story knowledge. The objects are typed loosely here to avoid
    importing the capability submodules at module top-level; they are
    validated by the adapter.

    Args:
        config: The resolved ``SonarQubeConfig``.
        client: A connected ``integrations.sonar`` ``SonarClient``.
        fast: Whether the run is in ``fast`` mode (FK-24 §24.3.3) — the
            SEPARATE fast/standard axis (``story_context.mode is
            WireStoryMode.FAST``), NOT ``execution_route``.
        story_type: Resolved ``StoryType``.
        ledger: The loaded ``AcceptedExceptionLedger``.
        bound_analysis: The commit-bound ``BoundAnalysis`` coordinates.
        main_head_revision: Authoritative current main HEAD revision.

    Returns:
        A productive ``SonarGateInputPort`` (or the absent default port
        when ``available == false``).
    """
    from agentkit.backend.config.models import SonarQubeConfig
    from agentkit.backend.story_context_manager.types import StoryType
    from agentkit.backend.verify_system.sonarqube_gate.adapter import (
        BoundAnalysis,
        ConfiguredSonarGateInputPort,
    )
    from agentkit.backend.verify_system.sonarqube_gate.ledger import AcceptedExceptionLedger
    from agentkit.backend.verify_system.sonarqube_gate.port import (
        ABSENT_SONAR_GATE_PORT,
    )
    from agentkit.integration_clients.sonar import SonarClient

    if not isinstance(config, SonarQubeConfig):
        msg = f"config must be a SonarQubeConfig; got {type(config).__name__}"
        raise TypeError(msg)
    if not config.available:
        # Deliberately absent Sonar => not-applicable skip; never fail-closed.
        return ABSENT_SONAR_GATE_PORT
    if not isinstance(client, SonarClient):
        msg = f"client must be a SonarClient; got {type(client).__name__}"
        raise TypeError(msg)
    if not isinstance(ledger, AcceptedExceptionLedger):
        msg = f"ledger must be an AcceptedExceptionLedger; got {type(ledger).__name__}"
        raise TypeError(msg)
    if not isinstance(bound_analysis, BoundAnalysis):
        msg = f"bound_analysis must be a BoundAnalysis; got {type(bound_analysis).__name__}"
        raise TypeError(msg)
    if not isinstance(story_type, StoryType):
        msg = f"story_type must be a StoryType; got {type(story_type).__name__}"
        raise TypeError(msg)
    return ConfiguredSonarGateInputPort(
        config=config,
        client=client,
        fast=bool(fast),
        story_type=story_type,
        ledger=ledger,
        bound_analysis=bound_analysis,
        main_head_revision=main_head_revision,
    )


def build_skills(
    store_dir: Path,
    *,
    bundle_store_root: Path | None = None,
) -> project_types.Skills:
    """Create a fully wired ``Skills`` top-surface (AG3-048).

    Composition root for the agent-skills BC (FK-43, bc-cut-decisions.md §BC 11
    + §BC 12), analogous to ``build_artifact_manager``: binds the system-wide
    ``SkillBundleStore`` and the productive
    ``StateBackendSkillBindingRepository`` into a ``Skills`` instance. Callers
    (installer, runtime, tests) receive ``Skills`` via DI and do not know the
    repository implementation.

    Architecture conformance: ``agentkit.backend.skills`` does NOT import from
    ``state_backend.store``; the wiring of the state-backend persistence
    happens exclusively here in the composition root.

    Args:
        store_dir: Base directory of the state backend (SQLite stores under
            ``store_dir/.agentkit/...``; Postgres ignores the path).
        bundle_store_root: Optional override for the system-wide
            skill-bundle store. ``None`` -> platform default (FK-43 §43.5.2).

    Returns:
        ``Skills`` with ``SkillBundleStore`` + ``StateBackendSkillBindingRepository``.
    """
    from agentkit.backend.skills import Skills as _Skills
    from agentkit.backend.skills.bundle_store import SkillBundleStore as _SkillBundleStore
    from agentkit.backend.state_backend.store.skill_binding_repository import (
        StateBackendSkillBindingRepository,
    )

    bundle_store = _SkillBundleStore(store_root=bundle_store_root)
    repository = StateBackendSkillBindingRepository(store_dir)
    projection_accessor = build_projection_accessor(store_dir)
    return _Skills(
        bundle_store=bundle_store,
        binding_repo=repository,
        projection_accessor=projection_accessor,
    )


def build_integrity_gate(store_dir: Path | None = None) -> verify_types.IntegrityGate:
    """Create a fully wired ``IntegrityGate``.

    Composition root for the closure phase (AG3-031 Pass-5 Fix E9):
    instantiates ``StateBackendIntegrityGateStateAdapter`` as ``state_port``.

    AG3-034 (Finding E / Remediation E-F): additionally wires the
    ``EnvelopeValidator`` so the required-artifact pre-stage runs the
    envelope required-field check (FK-71 §71.2) for **every** required QA
    artifact (Structural Dim 1 + Decision Dim 4) (``ENVELOPE_VIOLATION`` on a
    violation).  The dimensions read the canonical QA envelopes themselves via
    the ``state_port`` (FK-35 §35.2.4 producer/status/depth).

    Dimension 9 (SONARQUBE_GREEN, R2-C/A2): wires the productive
    ``ProductiveSonarDimensionPort``, which CONSUMES the AG3-052 capability
    (``build_sonar_gate_port_for_run`` + ``evaluate_sonarqube_gate``) — no
    own attestation mechanic, no None-stub loader.  The capability resolves the
    applicability from ``sonarqube.available`` + story ``mode`` + story type
    (``available == false`` / fast / non-code => not-applicable, Dim 9
    is omitted).  For an APPLICABLE impl/bugfix run
    ``build_sonar_gate_port_for_run`` reads the commit-bound scan artifact; if
    it is absent (the integrated pre-merge scan FK-29 §29.1a is OOS), the
    capability yields a fail-closed APPLICABLE port (``attestation = None``) and
    ``evaluate_sonarqube_gate`` a ``failed`` outcome -> Dim 9 **fail-closed**
    (``SONAR_NOT_GREEN``/ESCALATED), NEVER a skip.

    Args:
        store_dir: Base directory of the state backend (SQLite); Postgres
            ignores the path.  ``None`` => the repository's default store.

    Returns:
        ``IntegrityGate`` with state port + envelope validation + Dim-9 port.
    """
    from agentkit.backend.governance.integrity_gate import IntegrityGate as _IntegrityGate
    from agentkit.backend.state_backend.store.integrity_gate_repository import (
        StateBackendIntegrityGateStateAdapter,
    )

    validator = EnvelopeValidator(build_producer_registry())
    sonar_port = _build_dim9_sonar_port(store_dir)
    return _IntegrityGate(
        state_port=StateBackendIntegrityGateStateAdapter(),
        envelope_validator=validator,
        sonar_port=sonar_port,
    )


def _build_dim9_sonar_port(store_dir: Path | None) -> verify_types.SonarDimensionPort:
    """Build the productive Dim-9 ``SonarDimensionPort`` (FK-35 §35.2.4a, R2-C/A2).

    Wires the :class:`ProductiveSonarDimensionPort`, which CONSUMES the AG3-052
    capability (``build_sonar_gate_port_for_run`` + ``evaluate_sonarqube_gate``)
    for the resolution AND the verdict — no hand-rolled attestation loader, no
    second gate mechanic.  The two injected loaders are the truth-boundary reads
    the composition root owns (``governance`` may not read the StoryContext /
    project config directly): one resolves the run's :class:`StoryContext`, the
    other the project :class:`SonarQubeConfig`.  The capability then resolves
    applicability + the commit-bound inputs and produces the canonical outcome.
    """
    from agentkit.backend.governance.integrity_gate.dim9_port import (
        ProductiveSonarDimensionPort,
    )

    _ = store_dir  # the facade resolves the active backend itself.
    return ProductiveSonarDimensionPort(
        _load_sonar_config,  # type: ignore[arg-type]
        _load_story_context_for_gate,  # type: ignore[arg-type]
    )


def _load_story_context_for_gate(gate_ctx: object) -> object | None:
    """Resolve the run's ``StoryContext`` for the Dim-9 port (truth-boundary read).

    Owned by the composition root: ``governance`` may not read the StoryContext
    directly.  An unreadable/absent context returns ``None`` -> the port treats a
    code story as APPLICABLE-but-unresolvable -> Dim 9 fails closed.
    """
    from agentkit.backend.governance.integrity_gate import IntegrityGateContext
    from agentkit.backend.state_backend.story_lifecycle_store import load_story_context

    assert isinstance(gate_ctx, IntegrityGateContext)  # noqa: S101 - DI guard
    try:
        return load_story_context(gate_ctx.story_dir)
    except Exception:  # noqa: BLE001 -- unreadable context -> fail-closed downstream
        return None


def _load_sonar_config(gate_ctx: object) -> object | None:
    """Resolve the project ``SonarQubeConfig`` for the Dim-9 port (truth boundary).

    Returns the project's ``sonarqube`` config stanza, or ``None`` ONLY for a
    legitimate, deliberate absence: no resolvable project root, or a successfully
    loaded config that simply omits the ``sonarqube`` stanza (a non-code-producing
    project — ``build_sonar_gate_port_for_run`` then resolves a declared skip,
    FK-33 §33.6.5 "absent != broken").

    FAIL-CLOSED (R3-C/A2, analog AG3-052
    ``test_anchor_propagates_config_error_no_silent_skip``): a BROKEN or unreadable
    project config (``ConfigError``/``OSError`` from ``load_project_config``,
    including the E6 hard-fail on an omitted stanza for a code-producing project)
    is NOT a declared absence.  It MUST NOT be swallowed into ``None`` (which would
    route through the absent-port branch => silent Dim-9 skip).  It PROPAGATES so
    the Dim-9 port fails closed (``SONAR_NOT_GREEN``/escalation), never an inert
    skip (FAIL-CLOSED, ZERO DEBT).  ``governance`` never reads the project config
    directly; this composition-root helper owns the read.

    Equally fail-closed (R4-C/A2): an absent/unresolvable ``project_root`` is a
    declared absence ONLY for a NON-code-producing story (the gate never applies
    to it; ``None`` -> deliberate skip).  For a CODE-PRODUCING story
    (implementation/bugfix) an unresolvable ``project_root`` is a BROKEN
    precondition — the config cannot be loaded, so applicability cannot be
    proven absent.  It MUST raise ``ConfigError`` (fail-closed) rather than
    return ``None``, which would otherwise route through the absent-port branch
    into a silent Dim-9 skip = fail-open.  The code-producing axis is the
    AG3-052 SSOT (``is_code_producing_story``), not a re-derived flag.

    Raises:
        ConfigError: When the project config cannot be loaded/validated for a run
            with a resolvable project root (propagated fail-closed), OR when a
            code-producing story has no resolvable ``project_root`` (broken
            precondition => never a silent skip).
        OSError: When the config files cannot be read (propagated fail-closed).
    """
    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.exceptions import ConfigError
    from agentkit.backend.governance.integrity_gate import IntegrityGateContext
    from agentkit.backend.installer.paths import project_root_for_story_dir
    from agentkit.backend.verify_system.sonarqube_gate import is_code_producing_story

    assert isinstance(gate_ctx, IntegrityGateContext)  # noqa: S101 - DI guard
    # AG3-123: the project-config root is derived structurally from the canonical
    # ``<project_root>/stories/<story_id>`` story_dir layout -- the SAME anchor the
    # Backend ``StoryWorkspaceLocator`` yields -- NOT from a re-loaded, dev-supplied
    # ``ctx.project_root``. The Dim-9 fail-closed semantics are preserved: an
    # off-layout / unresolvable root for a code-producing story is a broken
    # precondition (never a silent skip; FK-33 §33.6.5, R4-C/A2).
    project_root = project_root_for_story_dir(gate_ctx.story_dir)
    if project_root is None or not _project_config_present(project_root):
        if is_code_producing_story(gate_ctx.story_type):
            # Code-producing story whose project config cannot be located (the
            # story_dir is off-layout, or the project declares no AK3 config): the
            # config is unloadable, so a deliberate absence cannot be proven. Fail
            # closed (never a silent Dim-9 skip; FK-33 §33.6.5, R4-C/A2).
            msg = (
                "cannot resolve a project config root for code-producing story "
                f"{gate_ctx.story_type.value!r}: project config unloadable -> "
                "Dim 9 fail-closed (no silent skip)"
            )
            raise ConfigError(msg)
        # Non-code-producing story (concept/research): a missing config is a
        # legitimate declared absence -> None (the gate never applies to it).
        return None
    # NO try/except ConfigError/OSError -> None here: a PRESENT-but-broken config
    # is a fail-closed condition, NOT a declared absence (R3-C/A2).
    project_config = load_project_config(project_root)
    pipeline = getattr(project_config, "pipeline", None)
    return getattr(pipeline, "sonarqube", None) if pipeline is not None else None


def build_setup_preflight_gate() -> verify_types.SetupContextRepository:
    """Create a wired ``SetupContextRepository`` adapter.

    Composition root for the setup phase (AG3-031 Pass-5 Fix E9):
    instantiates ``StateBackendSetupContextAdapter`` and returns it as a
    ``SetupContextRepository``.  Callers pass it in via
    ``SetupPhaseHandler(config, context_repository=...)``.

    Returns:
        ``StateBackendSetupContextAdapter`` as a ``SetupContextRepository``.
    """
    from agentkit.backend.state_backend.store.setup_context_repository import (
        StateBackendSetupContextAdapter,
    )

    return StateBackendSetupContextAdapter()


def build_are_client_from_project_config(project_config: object) -> object | None:
    """Construct the ARE client from the single ProjectConfig ARE truth."""

    from agentkit.backend.config.models import ProjectConfig
    from agentkit.backend.requirements_coverage.are_client import AreClient

    if not isinstance(project_config, ProjectConfig):
        msg = f"project_config must be a ProjectConfig; got {type(project_config).__name__}"
        raise TypeError(msg)
    if not project_config.pipeline.features.are:
        return None
    if project_config.are is None or not project_config.are.rest_base_url:
        return None
    return AreClient(
        project_config.are.rest_base_url,
        project_config.are.auth_token,
    )


def build_setup_fence_scope_binder() -> Callable[..., contextlib.AbstractContextManager[None]]:
    """Build the REAL ownership-fence-scope binder for ``SetupPhaseHandler``.

    AG3-144 (Codex round-3, architecture-conformance fix): ``setup_preflight_gate.phase``
    must have ZERO ownership-fence store imports -- module-level OR lazy
    (``tests/unit/governance/test_architecture_conformance_imports.py``). This
    composition-root helper owns the ``resolve_ownership_fence_snapshot`` +
    ``bind_ownership_fence_scope`` calls and is injected into ``SetupPhaseHandler`` as a plain
    callable DI seam -- mirrors ``build_phase_state_residue_probe`` (TB003:
    governance may not call the state-backend loader directly).

    Returns:
        ``binder(*, project_key, story_id, run_id) -> ContextManager[None]``:
        on the narrow SQLite unit-test path (``resolve_ownership_fence_snapshot``
        returns ``None``) this yields ``contextlib.nullcontext()`` (no fence
        mirroring there, K5 Postgres-only); on Postgres it resolves the active
        ``run_ownership_records`` snapshot and binds it for the caller's
        mutating call.
    """
    from agentkit.backend.state_backend.governance_runtime_store import (
        bind_ownership_fence_scope,
        resolve_ownership_fence_snapshot,
    )

    def _bind(
        *,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> contextlib.AbstractContextManager[None]:
        snapshot = resolve_ownership_fence_snapshot(project_key, story_id)
        if snapshot is None:
            return contextlib.nullcontext()
        owner_session_id, expected_ownership_epoch = snapshot
        return bind_ownership_fence_scope(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            owner_session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
        )

    return _bind


def build_setup_edge_provisioning_coordinator(
    project_root: Path,
) -> verify_types.EdgeProvisioningCoordinator:
    """Build the productive edge-provisioning coordinator (AG3-145 Teilschritt C).

    Delegates to the ``bootstrap.edge_provisioning_adapter`` module which owns the
    concrete Postgres-backed :class:`SetupEdgeProvisioningCoordinator` (commission
    + read of ``preflight_probe`` / ``provision_worktree`` commands, ownership /
    takeover / ``ls-remote`` decision context). Kept here as the canonical setup
    wiring entry point (FK-10 §10.2.4a, FK-91 §91.1b).
    """
    from agentkit.backend.bootstrap.edge_provisioning_adapter import (
        build_setup_edge_provisioning_coordinator as _build,
    )

    return _build(project_root)


def build_setup_phase_handler(
    config: object,
    *,
    store_dir: Path | None = None,
    dependency_repository: object | None = None,
    green_main_port: object | None = None,
) -> verify_types.SetupPhaseHandler:
    """Wire a fully-collaborated ``SetupPhaseHandler`` (AG3-034 canonical point).

    Assembles the Setup-phase collaborators the truth-boundary-protected
    handler may not build itself: the context repository, the run-aware
    residue probe (Check 6, Finding B), the project ``ModeLockRepository``
    read path (Check 10) and the optional green-main capability port (FK-22
    §22.4c).  Callers that build a bare ``SetupPhaseHandler(config, repo)``
    miss the residue/mode-lock wiring and the residue check fails closed.

    Args:
        config: The ``SetupConfig``.
        store_dir: State-backend base dir for the residue probe + mode-lock
            repository (SQLite); ``None`` => the config's ``project_root``.
        dependency_repository: Optional ``StoryDependencyRepository`` (Check 4).
        green_main_port: Optional ``MainGreenPort`` (FK-22 §22.4c); ``None`` is
            the absent-Sonar default (green-main SKIPs unless APPLICABLE).

    Returns:
        A wired ``SetupPhaseHandler``.
    """
    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.governance.setup_preflight_gate.phase import (
        SetupConfig,
        SetupPhaseHandler,
    )
    from agentkit.backend.requirements_coverage.top import RequirementsCoverage
    from agentkit.backend.state_backend.store.mode_lock_repository import ModeLockRepository
    from agentkit.backend.state_backend.store.story_are_link_repository import (
        StateBackendStoryAreLinkRepository,
    )

    if not isinstance(config, SetupConfig):
        msg = f"config must be a SetupConfig; got {type(config).__name__}"
        raise TypeError(msg)
    project_config = load_project_config(config.project_root)
    are_client = build_are_client_from_project_config(project_config)
    are_bundle_loader = RequirementsCoverage(
        are_client,  # type: ignore[arg-type]
        project_config.pipeline,
        link_repository=StateBackendStoryAreLinkRepository(config.project_root),
        artifact_manager=build_artifact_manager(config.project_root),
        audit_root=config.project_root,
    )
    return SetupPhaseHandler(
        config,
        build_setup_preflight_gate(),
        dependency_repository=dependency_repository,  # type: ignore[arg-type]
        mode_lock_repository=ModeLockRepository(config.project_root),
        green_main_port=green_main_port,  # type: ignore[arg-type]
        are_bundle_loader=are_bundle_loader,
        residue_probe=build_phase_state_residue_probe(store_dir or config.project_root),
        fence_scope_binder=build_setup_fence_scope_binder(),
        edge_provisioning_coordinator=build_setup_edge_provisioning_coordinator(config.project_root),
    )

def _story_is_github_backed(ctx: project_types.StoryContext) -> bool:
    """Whether the run's story type is GitHub-backed (code-producing; E5).

    SSOT criterion: a GitHub-backed story is a CODE-PRODUCING story
    (implementation/bugfix). Per the canonical ``StoryTypeProfile`` those are the
    types with ``uses_worktree`` / ``uses_merge`` true -- the only ones that
    create a ``story/{story_id}`` branch + worktree and merge to ``main`` against
    a real GitHub repo (FK-12 §12.7.1 "GitHub-Operationen in der Pipeline":
    Setup/Worker/Closure contact GitHub only for these). CONCEPT/RESEARCH are
    INTERNAL stories (``uses_worktree=False``, ``uses_merge=False``): they
    create no worktree/merge. The axis is read from the authoritative
    ``is_code_producing_story`` SSOT, never a re-derived flag.

    Args:
        ctx: The run's story context.

    Returns:
        ``True`` iff the story type is GitHub-backed (implementation/bugfix).
    """
    from agentkit.backend.verify_system.sonarqube_gate import is_code_producing_story

    return is_code_producing_story(ctx.story_type)


def build_setup_config_for_run(ctx: project_types.StoryContext, *, project_root: Path) -> object:
    """Build the run's authoritative ``SetupConfig`` (AG3-123 / E5).

    AK3 owns the user story via ``story_id`` (branch-safe ``story/{story_id}``);
    GitHub is exclusively the code backend (FK-12 §12.1.1, FK-91 §91.2 rule 9).
    The setup config therefore carries only the run's ``project_root`` and the
    worktree decision — the authoritative story identity is ``story_id`` (always
    present and branch-safe on the ``StoryContext``), resolved against the AK3
    Story-Service record by the setup handler.

    AG3-123: the ``project_root`` (run store / worktree anchor) is the
    Backend-resolved :class:`~agentkit.backend.control_plane.workspace_locator.StoryWorkspace`
    anchor — NOT ``ctx.project_root``. The locator is the SINGLE source for the
    workspace location (FIX THE MODEL); this builder consumes the resolved anchor
    rather than re-reading a dev-supplied path. An unresolvable workspace already
    failed the dispatch closed at the locator (FK-10 §10.6), so a valid anchor is
    always supplied here.

    For an INTERNAL story (CONCEPT/RESEARCH; not code-producing) the setup
    handler never creates a worktree or merges, so ``create_worktree`` is off.

    Args:
        ctx: The run's story context (story type drives the worktree decision).
        project_root: The Backend-resolved run store / worktree filesystem anchor.

    Returns:
        A ``SetupConfig`` for the run (with ``create_worktree`` off for a
        non-code-producing story).
    """
    from agentkit.backend.governance.setup_preflight_gate.phase import SetupConfig

    return SetupConfig(
        project_root=project_root,
        create_worktree=_story_is_github_backed(ctx),
    )
def build_permission_service() -> PermissionService:
    """Build the governance owner with canonical Postgres adapters."""
    from agentkit.backend.governance.ccag.permission_service import PermissionService
    from agentkit.backend.state_backend.store.permission_lease_repository import (
        StateBackendPermissionLeaseRepository,
    )
    from agentkit.backend.state_backend.store.permission_request_repository import (
        StateBackendPermissionRequestRepository,
    )

    return PermissionService(
        StateBackendPermissionRequestRepository(),
        StateBackendPermissionLeaseRepository(),
    )
