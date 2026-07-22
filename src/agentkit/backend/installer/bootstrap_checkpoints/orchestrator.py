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
    """Resolve ``(vectordb, are, sonarqube)`` flags consumed by the flow.

    VectorDB is **mandatory** infrastructure (Decision Record 2026-07-21 Rand 1,
    AG3-176 AC6): ``vectordb`` is always ``True`` here. ARE remains optional
    via ``features_are``. Sonar/CI/ARE drive the third-party branch for CP 10d.
    """
    third_party_enabled = bool(
        config.sonarqube_available or config.ci_available or config.features_are
    )
    return (
        True,  # VectorDB mandatory — optional branch removed (AG3-176 AC6)
        bool(config.features_are),
        third_party_enabled,
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

    # AG3-176 R1: strict config boundary BEFORE any installer effect (scaffold,
    # registration, preflight, hooks). Existing project.yaml is fail-closed
    # via load_project_config (no yaml.safe_load migration/overwrite).
    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.exceptions import ConfigError, InstallationError
    from agentkit.backend.installer.paths import project_config_path

    existing_config_path = project_config_path(root)
    entry_project_config = None
    if existing_config_path.is_file():
        try:
            entry_project_config = load_project_config(root)
        except ConfigError as exc:
            raise InstallationError(
                f"configuration_invalid: refusing install before any effect: {exc}",
                detail={
                    "error_code": "configuration_invalid",
                    "reason": "configuration_invalid",
                    "config_path": str(existing_config_path),
                    "error": str(exc),
                },
            ) from exc
        # AG3-176 R1 / AC1/AC2/AC6: VectorDB endpoint duty is the INSTALLER
        # activation boundary, not a global ProjectConfig model rule. Active
        # (default/true) without a valid pipeline.vectordb stanza fails closed
        # here — before scaffold, registration, preflight, or hooks.
        from agentkit.backend.config.models import require_installer_vectordb_endpoint

        try:
            require_installer_vectordb_endpoint(entry_project_config)
        except ValueError as exc:
            raise InstallationError(
                f"configuration_invalid: refusing install before any effect: {exc}",
                detail={
                    "error_code": "configuration_invalid",
                    "reason": "configuration_invalid",
                    "config_path": str(existing_config_path),
                    "error": str(exc),
                },
            ) from exc
    # Fresh install (no project.yaml yet): CP5 materialises the endpoint from
    # InstallConfig; CP10 preflight remains the live readiness gate. Do not
    # invent defaults here; incomplete InstallConfig fails at CP5/CP10.

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
    if entry_project_config is not None:
        context.run_state.project_config = entry_project_config
        # Seed project_yaml from the ON-DISK mapping (not model_dump expansion)
        # so CP7 config_digest stays byte-stable across idempotent re-runs
        # (Pydantic defaults would otherwise change the digest without a real
        # operator change).
        from agentkit.backend.config.strict_yaml import strict_load_yaml

        try:
            raw = strict_load_yaml(
                existing_config_path.read_text(encoding="utf-8")
            )
        except Exception:  # noqa: BLE001 -- fall back only if re-read fails
            raw = entry_project_config.model_dump(mode="json")
        if isinstance(raw, dict):
            context.run_state.project_yaml = raw
        else:
            context.run_state.project_yaml = entry_project_config.model_dump(
                mode="json"
            )
    engine = build_checkpoint_engine()
    results: tuple[CheckpointResult, ...] = engine.run(context)

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


def _checkpoint_ids(results: tuple[CheckpointResult, ...]) -> tuple[str, ...]:
    """Return the ordered checkpoint ids of a result tuple (test/debug aid)."""
    return tuple(r.checkpoint for r in results)


__all__ = [
    "build_checkpoint_context",
    "build_checkpoint_engine",
    "run_checkpoint_install",
]
