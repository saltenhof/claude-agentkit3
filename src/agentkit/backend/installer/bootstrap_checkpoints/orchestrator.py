"""Installer checkpoint orchestrator — the engine-driven install entry point.

This is what the thin ``install_agentkit`` façade delegates to (story AC1). It
builds the :class:`CheckpointContext`, constructs the :class:`CheckpointEngine`
over the installer :class:`FlowDefinition`, runs the flow in the requested mode
and maps the collected :class:`CheckpointResult` list onto an
:class:`InstallResult`. NO imperative checkpoint ordering lives here — the order
is the flow contract; this module only wires and runs the engine.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.config.models import ProjectConfig
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
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_CONFIGURATION_INVALID,
    REASON_VECTORDB_REQUIRED,
)
from agentkit.backend.installer.config_boundary import (
    ConfigBeforeImage,
    capture_config_before_image,
)
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.installer.vectordb_preflight import HttpVectorDbPreflight

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.installer.dependency_preflight import (
        DependencyPreflightReport,
    )
    from agentkit.backend.installer.registration import CheckpointResult
    from agentkit.backend.installer.runner import InstallConfig, InstallResult


def _resolve_features(config: InstallConfig) -> tuple[bool, bool, bool]:
    """Resolve ``(vectordb, are, sonarqube)`` flags consumed by the branches.

    VectorDB has no feature decision: the strict candidate boundary already
    proved that it is mandatory. ``features_are`` and ``sonarqube_available``
    remain independent applicability axes.
    """
    third_party_enabled = bool(config.sonarqube_available or config.ci_available or config.features_are)
    return (
        True,
        bool(config.features_are),
        third_party_enabled,
    )


def build_checkpoint_context(
    config: InstallConfig,
    mode: ExecutionMode,
    *,
    project_config: ProjectConfig | None = None,
    project_yaml: dict[str, object] | None = None,
    config_before_image: ConfigBeforeImage | None = None,
    dependency_preflight: DependencyPreflightReport | None = None,
    scope_interaction_mode: str = ScopeInteractionMode.AGENTIC,
) -> CheckpointContext:
    """Build the immutable per-run :class:`CheckpointContext`."""
    if config.features_vectordb is not True:
        reason = (
            REASON_VECTORDB_REQUIRED
            if config.features_vectordb is False
            else REASON_CONFIGURATION_INVALID
        )
        raise ProjectError(
            "features.vectordb must be true; VectorDB is mandatory",
            detail={"reason": reason},
        )
    if config_before_image is None:
        config_before_image, existing_config = capture_config_before_image(
            config.project_root,
        )
    else:
        existing_config = None
    if project_config is None or project_yaml is None:
        from agentkit.backend.installer.runner import _build_project_yaml

        if existing_config is None:
            project_yaml = _build_project_yaml(config)
            project_config = ProjectConfig.model_validate(project_yaml)
        else:
            project_config = existing_config
            project_yaml = existing_config.model_dump(mode="json", exclude_none=True)
    vectordb, are, sonarqube = _resolve_features(config)
    run_state = CheckpointRunState(
        project_config=project_config,
        project_yaml=project_yaml,
        config_before_image=config_before_image,
        dependency_preflight=dependency_preflight,
    )
    return CheckpointContext(
        config=config,
        mode=mode,
        project_root=config.project_root,
        vectordb_enabled=vectordb,
        are_enabled=are,
        sonarqube_enabled=sonarqube,
        scope_interaction_mode=scope_interaction_mode,
        run_state=run_state,
    )


def _candidate_config(
    config: InstallConfig,
    root: Path,
) -> tuple[ProjectConfig, dict[str, object], ConfigBeforeImage]:
    """Resolve and validate the sole config candidate before installer effects."""
    from agentkit.backend.installer.runner import _build_project_yaml

    if config.features_vectordb is not True:
        reason = (
            REASON_VECTORDB_REQUIRED
            if config.features_vectordb is False
            else REASON_CONFIGURATION_INVALID
        )
        raise ProjectError(
            "features.vectordb must be true; VectorDB is mandatory",
            detail={"reason": reason},
        )
    before, existing_config = capture_config_before_image(root)
    if existing_config is not None:
        candidate = existing_config
        raw = candidate.model_dump(mode="json", exclude_none=True)
    else:
        raw = _build_project_yaml(config)
        try:
            candidate = ProjectConfig.model_validate(raw)
        except ValidationError as exc:
            raise ProjectError(
                f"Candidate project configuration is invalid: {exc}",
                detail={
                    "reason": REASON_CONFIGURATION_INVALID,
                    "error": str(exc),
                },
            ) from exc
        raw = candidate.model_dump(mode="json", exclude_none=True)
    vectordb = candidate.pipeline.vectordb
    if vectordb is None or vectordb.weaviate_http_endpoint is None or vectordb.weaviate_grpc_endpoint is None:
        raise ProjectError(
            "Mandatory VectorDB endpoints are missing from the validated candidate configuration",
            detail={"reason": REASON_CONFIGURATION_INVALID},
        )
    return candidate, raw, before


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
    from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
        dependency_preflight_checkpoint,
        runtime_isolation_checkpoint,
    )
    from agentkit.backend.installer.dependency_preflight import (
        DependencyDeclarationError,
        check_runtime_dependencies,
    )
    from agentkit.backend.installer.interpreter import (
        InterpreterResolutionError,
        resolve_ak3_interpreter,
    )
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

    isolation_start = time.monotonic()
    try:
        resolve_ak3_interpreter()
    except InterpreterResolutionError as exc:
        isolation_result = runtime_isolation_checkpoint(
            detail=str(exc),
            start=isolation_start,
        )
        return InstallResult(
            success=False,
            project_root=root,
            created_files=(),
            errors=(isolation_result.detail or "AgentKit runtime is not isolated.",),
            checkpoint_results=(isolation_result,),
        )

    # AG3-206: collect the declaration-owned environment result before the
    # VectorDB probe, bundle resolution or any installer mutation. A failed
    # report returns the real CP 1 result immediately; no later checkpoint runs.
    declaration_error: str | None
    try:
        checked_dependencies = check_runtime_dependencies()
    except DependencyDeclarationError as exc:
        dependency_preflight = None
        declaration_error = str(exc)
        dependency_preflight_duration_ms = exc.duration_ms
    else:
        dependency_preflight = checked_dependencies
        declaration_error = None
        dependency_preflight_duration_ms = checked_dependencies.duration_ms
    if dependency_preflight is None or not dependency_preflight.passed:
        dependency_result = dependency_preflight_checkpoint(
            report=dependency_preflight,
            declaration_error=declaration_error,
            preflight_duration_ms=dependency_preflight_duration_ms,
        )
        return InstallResult(
            success=False,
            project_root=root,
            created_files=(),
            errors=(dependency_result.detail or "Runtime dependency preflight failed.",),
            checkpoint_results=(dependency_result,),
        )

    # AC1/AC2: resolve one strict candidate and prove the mandatory external
    # dependency BEFORE bundle resolution, context construction or any checkpoint
    # effect. All downstream endpoint consumers use this typed candidate.
    project_config, project_yaml, config_before_image = _candidate_config(
        config,
        root,
    )
    preflight = config.vectordb_preflight or HttpVectorDbPreflight()
    preflight.check(project_config)

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
        config,
        mode,
        project_config=project_config,
        project_yaml=project_yaml,
        config_before_image=config_before_image,
        dependency_preflight=dependency_preflight,
        scope_interaction_mode=scope_interaction_mode,
    )
    engine = build_checkpoint_engine()
    results: tuple[CheckpointResult, ...] = engine.run(context)

    failed = [r for r in results if r.status is CheckpointStatus.FAILED]
    errors = tuple((r.detail or r.reason or f"{r.checkpoint} failed.") for r in failed)
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
