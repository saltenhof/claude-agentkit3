"""Installer checkpoint orchestrator — the engine-driven install entry point.

This is what the thin ``install_agentkit`` façade delegates to (story AC1). It
builds the :class:`CheckpointContext`, constructs the :class:`CheckpointEngine`
over the installer :class:`FlowDefinition`, runs the flow in the requested mode
and maps the collected :class:`CheckpointResult` list onto an
:class:`InstallResult`. NO imperative checkpoint ordering lives here — the order
is the flow contract; this module only wires and runs the engine.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from agentkit.backend.exceptions import ProjectError
from agentkit.backend.installer.bootstrap_checkpoints.registry import (
    build_branch_predicate_registry,
    build_handler_registry,
)
from agentkit.backend.installer.checkpoint_engine.context import (
    CheckpointContext,
    CheckpointRunState,
    ScopeInteractionMode,
)
from agentkit.backend.installer.checkpoint_engine.engine import CheckpointEngine
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.flow import build_installer_flow
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from agentkit.backend.installer.registration import CheckpointResult
    from agentkit.backend.installer.runner import InstallConfig, InstallResult


def _resolve_features(config: InstallConfig) -> tuple[bool, bool, bool]:
    """Resolve ``(vectordb, are, sonarqube)`` flags consumed by the branches.

    Consumes (never defines) the feature decision carried on the install config:
    ``features_vectordb`` / ``features_are`` (FK-03 §3.1 ``features.*``) and
    ``sonarqube_available`` (CP 10d applicability axis). ``features.are`` also
    implies the ``are`` runtime profile when the operator did not pin one.
    """
    return (
        bool(config.features_vectordb),
        bool(config.features_are),
        bool(config.sonarqube_available),
    )


def build_checkpoint_context(
    config: InstallConfig,
    mode: ExecutionMode,
    *,
    scope_interaction_mode: str = ScopeInteractionMode.AGENTIC,
) -> CheckpointContext:
    """Build the immutable per-run :class:`CheckpointContext`."""
    vectordb, are, sonarqube = _resolve_features(config)
    return CheckpointContext(
        config=config,
        mode=mode,
        project_root=config.project_root,
        vectordb_enabled=vectordb,
        are_enabled=are,
        sonarqube_enabled=sonarqube,
        scope_interaction_mode=scope_interaction_mode,
        run_state=CheckpointRunState(),
    )


def build_checkpoint_engine() -> CheckpointEngine[CheckpointContext]:
    """Build the :class:`CheckpointEngine` over the installer flow + registries."""
    return CheckpointEngine(
        flow=build_installer_flow(),
        handlers=build_handler_registry(),
        branch_predicates=build_branch_predicate_registry(),
    )


def run_checkpoint_install(
    config: InstallConfig,
    *,
    mode: ExecutionMode = ExecutionMode.REGISTER,
    scope_interaction_mode: str = ScopeInteractionMode.AGENTIC,
) -> InstallResult:
    """Run the installer checkpoint flow and return an :class:`InstallResult`.

    Args:
        config: The install configuration.
        mode: The execution mode (register / dry_run / verify).
        scope_interaction_mode: CP 10c interaction mode (agentic / interactive).

    Returns:
        The install result. ``success`` is ``False`` iff any checkpoint FAILED
        (register aborts on the first FAILED; read-only modes collect all and
        report ``success=False`` when any FAILED is present).

    Raises:
        ProjectError: When the project root does not exist (fail-closed; no
            checkpoint can run against a missing root).
    """
    from agentkit.backend.installer.runner import InstallResult

    # AG3-123 (single canonical resolution point): canonicalize the install
    # boundary to an ABSOLUTE backend anchor HERE -- the single funnel every
    # install path (CLI ``agentkit install --project-root .`` and a direct
    # ``install_agentkit(InstallConfig(...))`` call) flows through. The CLI passes
    # a possibly RELATIVE ``--project-root`` (e.g. ``.``); resolving it once at
    # this entry makes the whole checkpoint flow -- and the CP 7
    # ``ProjectRegistration`` it persists -- operate on the same absolute root,
    # so the model-floor ``_validate_project_root_absolute`` is satisfied without
    # relaxing it. ``resolve()`` on an existing dir keeps pointing at the same
    # project; the dir-existence check below still fails closed on a missing root.
    # This is the ONLY normalization point -- no shadow/duplicate path resolution
    # downstream (FIX-THE-MODEL / SINGLE SOURCE OF TRUTH).
    root = config.project_root.resolve()
    if not root.is_dir():
        raise ProjectError(
            f"Project root does not exist: {root}",
            detail={"project_root": str(root)},
        )
    if root != config.project_root:
        config = replace(config, project_root=root)

    # PREFLIGHT (FK-50 §50.5, Codex-r7 FINDING — behaviour preserved): resolve
    # the mandatory skill bundles BEFORE the engine writes anything in register
    # mode. The common install failure is a missing bundle; failing here (no
    # project writes yet) guarantees ``register`` never leaves a half-scaffolded
    # project on ``BundleNotFound``. This is engine WIRING, not checkpoint
    # ordering (CP 8 re-resolves + binds the same bundles, self-atomically). A
    # partial skill injection is likewise rejected fail-closed here.
    if mode is ExecutionMode.REGISTER:
        from agentkit.backend.installer.runner import _resolve_mandatory_skill_bundles

        _resolve_mandatory_skill_bundles(config, root)

    context = build_checkpoint_context(
        config, mode, scope_interaction_mode=scope_interaction_mode
    )
    engine = build_checkpoint_engine()
    results: tuple[CheckpointResult, ...] = engine.run(context)

    # AG3-056 CI (Jenkins) precondition — the engine OWNS this orthogonal
    # precondition (AG3-088 AC1: the ``install_agentkit`` façade carries NO
    # checkpoint orchestration of its own). It is not one of the FK-50 §50.3
    # twelve CP nodes, but it IS a fail-closed install precondition (the closure
    # pre-merge barrier must never be promised an unverified Jenkins, ZERO DEBT).
    # It runs ONLY in the mutating REGISTER mode after the 12 CPs succeeded, and
    # ONLY when no CP FAILED (a FAILED register run already aborts). Read-only
    # modes (dry_run/verify) do not hit the live Jenkins boundary (FK-50 §50.2).
    results = _append_ci_preflight(config, context, results)

    failed = [r for r in results if r.status is CheckpointStatus.FAILED]
    errors = tuple(
        (r.detail or r.reason or f"{r.checkpoint} failed.") for r in failed
    )
    return InstallResult(
        success=not failed,
        project_root=root,
        created_files=tuple(context.run_state.created_files),
        errors=errors,
        checkpoint_results=tuple(results),
    )


def _append_ci_preflight(
    config: InstallConfig,
    context: CheckpointContext,
    results: tuple[CheckpointResult, ...],
) -> tuple[CheckpointResult, ...]:
    """Append the AG3-056 CI (Jenkins) preflight result in REGISTER mode.

    Engine-owned orthogonal precondition (AG3-088 AC1): kept out of the FK-50
    §50.3 CP spine but enforced by the engine path so the façade delegates only.
    It runs after a clean 12-CP register run; a FAILED CI preflight raises and
    aborts (the productive install keeps its fail-closed CI precondition). The
    project.yaml is read from the run-state CP 5 published (single source — no
    re-derivation), with a deterministic rebuild fallback only if CP 5 did not
    publish it. Read-only modes never touch the live Jenkins boundary.
    """
    if not context.mode.mutations_allowed:
        return results
    if any(r.status is CheckpointStatus.FAILED for r in results):
        return results
    from agentkit.backend.installer.runner import (
        _build_project_yaml,
        run_ci_preflight_checkpoint_result,
    )

    yaml_data = context.run_state.project_yaml or _build_project_yaml(config)
    ci_result = run_ci_preflight_checkpoint_result(config, yaml_data)
    return (*results, ci_result)


def _checkpoint_ids(results: tuple[CheckpointResult, ...]) -> tuple[str, ...]:
    """Return the ordered checkpoint ids of a result tuple (test/debug aid)."""
    return tuple(r.checkpoint for r in results)


__all__ = [
    "build_checkpoint_context",
    "build_checkpoint_engine",
    "run_checkpoint_install",
]
