"""Prompt-audit helpers for QA layers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.phase_state_store import load_flow_execution
from agentkit.prompt_composer import (
    ComposeConfig,
    compose_named_prompt,
    write_rendered_prompt_artifact,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext


def materialize_qa_prompt_audit(
    *,
    layer_name: str,
    template_name: str,
    ctx: StoryContext,
    story_dir: Path,
) -> dict[str, Any]:
    """Materialize a run-scoped rendered prompt artifact when possible."""

    if ctx.project_root is None:
        return {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }

    flow = load_flow_execution(story_dir)
    if flow is None:
        return {
            "status": "skipped",
            "reason": "run_id_unavailable",
        }
    if flow.story_id != ctx.story_id:
        return {
            "status": "skipped",
            "reason": "story_identity_mismatch",
        }
    try:
        story_dir.relative_to(ctx.project_root)
    except ValueError:
        return {
            "status": "skipped",
            "reason": "story_dir_outside_project_root",
        }

    prompt = compose_named_prompt(
        ctx,
        template_name,
        ComposeConfig(
            story_type=ctx.story_type,
            mode=ctx.execution_route,
        ),
        run_id=flow.run_id,
    )
    invocation_id = f"verify-{layer_name}-attempt-{flow.attempt_no:03d}"
    artifact = write_rendered_prompt_artifact(
        prompt,
        ctx.project_root,
        run_id=flow.run_id,
        invocation_id=invocation_id,
        artifact_name=f"{layer_name}-prompt.md",
    )
    return {
        "status": "materialized",
        "run_id": flow.run_id,
        "invocation_id": invocation_id,
        "logical_prompt_id": prompt.logical_prompt_id,
        "prompt_bundle_id": prompt.prompt_bundle_id,
        "prompt_bundle_version": prompt.prompt_bundle_version,
        "artifact_path": artifact.prompt_path.relative_to(
            ctx.project_root,
        ).as_posix(),
        "manifest_path": artifact.manifest_path.relative_to(
            ctx.project_root,
        ).as_posix(),
    }


__all__ = ["materialize_qa_prompt_audit"]
