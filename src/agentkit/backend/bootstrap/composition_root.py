"""Public composition-root import surface without import-time side effects."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentkit.backend.bootstrap.composition_implementation_evidence import build_fast_test_runner as build_fast_test_runner
    from agentkit.backend.bootstrap.composition_pipeline import build_pipeline_engine as build_pipeline_engine
    from agentkit.backend.bootstrap.composition_project import (
        build_dashboard_service as build_dashboard_service,
    )
    from agentkit.backend.bootstrap.composition_project import (
        build_project_read_model_routes as build_project_read_model_routes,
    )
    from agentkit.backend.bootstrap.composition_project import (
        build_project_repository as build_project_repository,
    )
    from agentkit.backend.bootstrap.composition_project import (
        build_story_read_service as build_story_read_service,
    )
    from agentkit.backend.bootstrap.composition_project import (
        build_task_management_routes as build_task_management_routes,
    )

_EXPORT_MODULE_NAMES = {
    "agentkit.backend.bootstrap.composition_artifacts": (
        "build_artifact_manager", "build_producer_registry",
    ),
    "agentkit.backend.bootstrap.composition_closure": (
        "ClosureConfigUnavailableError", "_build_doc_fidelity_feedback_port", "_build_guard_counter_flush_port",
        "_build_guard_deactivation_port", "_build_mode_lock_release_port", "_build_per_repo_runners",
        "_build_pre_merge_runners", "_build_telemetry_evidence_port",
        "_build_vectordb_sync_port", "_RequirementsCoverageAreProvider",
        "_resolve_pre_merge_configs", "build_closure_phase_handler", "build_failure_corpus",
        "build_structural_are_provider",
    ),
    "agentkit.backend.bootstrap.composition_implementation_evidence": (
        "_CiBuildTestEvidenceAdapter", "build_fast_test_runner", "build_structural_build_test_port",
    ),
    "agentkit.backend.bootstrap.composition_config": ("_project_config_present",),
    "agentkit.backend.bootstrap.composition_exploration": (
        "_build_exploration_drafting", "_StateBackendDeclaredImpactReader", "_UnavailableFineDesignEvaluator",
        "build_exploration_drafting", "build_exploration_phase_handler", "build_exploration_review",
        "build_hub_fine_design_evaluator",
    ),
    "agentkit.backend.bootstrap.composition_governance": (
        "_build_dim9_sonar_port", "_load_sonar_config", "_load_story_context_for_gate", "_story_is_github_backed",
        "build_are_client_from_project_config", "build_integrity_gate", "build_setup_config_for_run",
        "build_setup_edge_provisioning_coordinator", "build_setup_fence_scope_binder", "build_setup_phase_handler",
        "build_setup_preflight_gate", "build_skills", "build_sonar_gate_port",
    ),
    "agentkit.backend.bootstrap.composition_pipeline": (
        "_UnresolvedSetupCoordinatesHandler", "build_pipeline_engine", "build_pipeline_handler_registry",
    ),
    "agentkit.backend.bootstrap.composition_project": (
        "_default_split_source_state_loader", "build_compat_window_reader", "build_dashboard_service",
        "build_kpi_analytics", "build_kpi_analytics_read_facade", "build_project_read_model_routes",
        "build_project_repository", "build_project_telemetry_event_source", "build_story_exit_service",
        "build_story_read_service", "build_story_reset_service", "build_story_split_service",
        "build_task_management_routes", "cli_load_story_context", "cli_read_phase_state_record",
    ),
    "agentkit.backend.bootstrap.composition_state": (
        "build_phase_envelope_store", "build_phase_state_residue_probe", "build_planning_projection_accessor",
        "build_planning_story_dependency_repository", "build_projection_accessor", "build_runtime_execution_purge_port",
        "build_runtime_execution_residue_probe",
    ),
    "agentkit.backend.bootstrap.composition_verify": (
        "_BarrierPushVerification", "_build_repo_code_backend_port", "_ControlPlaneQaCyclePushBarrierGate",
        "_derive_actual_impact", "_StateBackedQaCycleFingerprintSource", "_StateBackendTelemetryEventCountPort",
        "_SubprocessGitChangeEvidenceProvider", "_TelemetryArtifactInvalidationSink", "_TelemetryReviewCompletionSink",
        "build_artifact_invalidation_sink", "build_control_plane_runtime_service",
        "build_github_code_backend_port", "build_push_barrier_evidence",
        "build_push_verification_port", "build_qa_cycle_push_barrier_gate", "build_review_completion_sink",
        "build_verify_system",
    ),
}
_EXPORT_MODULE_BY_NAME = {name: module for module, names in _EXPORT_MODULE_NAMES.items() for name in names}

_PUBLIC_NAMES = (
    "ClosureConfigUnavailableError", "build_compat_window_reader", "build_artifact_invalidation_sink",
    "build_review_completion_sink", "build_artifact_manager", "build_closure_phase_handler",
    "build_exploration_drafting", "build_exploration_phase_handler", "build_exploration_review",
    "build_failure_corpus", "build_control_plane_runtime_service", "build_github_code_backend_port", "build_integrity_gate",
    "build_phase_state_residue_probe", "build_pipeline_engine", "build_pipeline_handler_registry",
    "build_planning_projection_accessor", "build_planning_story_dependency_repository", "build_producer_registry",
    "build_projection_accessor", "build_push_barrier_evidence", "build_runtime_execution_purge_port",
    "build_runtime_execution_residue_probe", "build_setup_config_for_run", "build_setup_phase_handler",
    "build_setup_preflight_gate", "build_skills", "build_sonar_gate_port", "build_structural_are_provider",
    "build_structural_build_test_port", "build_verify_system", "cli_load_story_context",
    "cli_load_execution_events_for_project_global", "cli_read_phase_state_record",
)
__all__ = list(_PUBLIC_NAMES)


def __getattr__(name: str) -> Any:
    """Load composition-root compatibility attributes lazily."""
    module_name = _EXPORT_MODULE_BY_NAME.get(name)
    if module_name is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy compatibility attributes to inspection."""
    return sorted({*globals(), *_EXPORT_MODULE_BY_NAME})


def cli_load_execution_events_for_project_global(
    project_key: str,
    *,
    limit: int | None = None,
) -> list[object]:
    """Load all execution events for a project for the CLI."""
    from agentkit.backend.state_backend.telemetry_event_store import (
        load_execution_events_for_project_global,
    )

    return load_execution_events_for_project_global(project_key, limit=limit)  # type: ignore[return-value]
