"""Prompt-audit helpers for QA layers.

FK-44 §44.4.2: evaluator/QA prompts MUST be resolved exclusively via the
prompt-runtime top surface ``PromptRuntime.materialize_prompt`` and audited
via ``artifacts.ArtifactManager`` -- never by reaching into the prompt-runtime
sub-modules (``compose_named_prompt`` / ``initialize_prompt_run_pin`` /
``write_rendered_prompt_artifact``) or by writing loose ``rendered-manifest``
JSON. The run correlation is resolved through the injected
``StoryContextQueryPort`` (AG3-035 BC-topology), so ``verify_system`` does not
import ``state_backend.store`` directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.exceptions import ProjectError
from agentkit.prompt_runtime import ComposeConfig, PromptRuntime

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.artifacts import ArtifactManager
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.protocols import RunScope, StoryContextQueryPort


def materialize_qa_prompt_audit(
    *,
    layer_name: str,
    template_name: str,
    ctx: StoryContext,
    story_dir: Path,
    artifact_manager: ArtifactManager | None,
    story_context_port: StoryContextQueryPort,
) -> dict[str, Any]:
    """Materialize and audit a run-scoped QA prompt via the top surface.

    Resolution happens exclusively through ``PromptRuntime.materialize_prompt``
    (FK-44 §44.4.2); the audit record is persisted via the injected
    ``ArtifactManager`` (FK-44 §44.6). The run correlation is resolved through
    the injected ``StoryContextQueryPort`` -- no direct ``state_backend.store``
    import.

    Args:
        layer_name: QA layer name (used to derive a stable invocation id).
        template_name: Logical prompt template name.
        ctx: Story context (carries ``project_root``/``story_id``).
        story_dir: Story working directory (used to resolve the run scope).
        artifact_manager: ArtifactManager for audit persistence; ``None`` when
            the verify-system was built without one (audit is then skipped).
        story_context_port: Port resolving the authoritative run correlation.

    Returns:
        A status dict: ``materialized`` with audit coordinates, or ``skipped``
        with a machine-readable reason.
    """
    if ctx.project_root is None:
        return {"status": "skipped", "reason": "project_root_unavailable"}
    if artifact_manager is None:
        return {"status": "skipped", "reason": "artifact_manager_unavailable"}

    run_scope: RunScope | None = story_context_port.resolve_run_scope(story_dir)
    if run_scope is None or not run_scope.run_id:
        return {"status": "skipped", "reason": "run_id_unavailable"}
    if run_scope.story_id != ctx.story_id:
        return {"status": "skipped", "reason": "story_identity_mismatch"}
    try:
        story_dir.relative_to(ctx.project_root)
    except ValueError:
        return {"status": "skipped", "reason": "story_dir_outside_project_root"}

    invocation_id = f"verify-{layer_name}-attempt-{run_scope.attempt:03d}"
    runtime = PromptRuntime(ctx.project_root, artifact_manager)
    runtime.create_run_pin(run_scope.run_id)
    try:
        instance = runtime.materialize_prompt(
            ctx,
            template_name,
            ComposeConfig(
                story_type=ctx.story_type,
                execution_route=ctx.execution_route,
            ),
            run_id=run_scope.run_id,
            invocation_id=invocation_id,
            render_mode="rendered",
            attempt=run_scope.attempt,
        )
    except ProjectError as exc:
        return {"status": "skipped", "reason": "materialization_failed", "detail": str(exc)}

    return {
        "status": "materialized",
        "run_id": run_scope.run_id,
        "invocation_id": invocation_id,
        "render_mode": instance.render_mode,
        "artifact_path": instance.prompt_path.relative_to(
            ctx.project_root,
        ).as_posix(),
        "audit_record_key": instance.audit_reference.record_key,
        "output_sha256": instance.audit_hash.output_sha256,
    }


__all__ = ["materialize_qa_prompt_audit"]
