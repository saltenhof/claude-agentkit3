"""Concrete prompt materializer for Layer-2 evaluations (FK-44 §44.4.2).

:class:`PromptRuntimeMaterializer` is the production adapter behind the
``_PromptMaterializer`` port consumed by
:class:`~agentkit.verify_system.llm_evaluator.structured_evaluator.StructuredEvaluator`.
It resolves the role prompt **exclusively** via
``PromptRuntime.materialize_prompt`` (FK-44 §44.4.2 -- never a direct resource
read), then reads back the materialized prompt bytes and the verified
``template_sha256`` from the returned :class:`PromptInstance`.

The run correlation (run_id / attempt) is resolved through the injected
:class:`~agentkit.verify_system.protocols.StoryContextQueryPort` (AG3-035
BC-topology) so ``verify_system`` does not import ``state_backend.store``.

This adapter is wired by the composition root together with the concrete
``LlmClient`` adapter (the latter is a follow-up story, story.md §2.2). Until
then ``VerifySystem.layer2_runner`` stays ``None`` and Layer 2 runs the
deterministic reviewers (fail-closed, no silent skip).

Source:
  - FK-44 §44.4.2 / §44.6 -- materialize_prompt + audit
  - FK-34 -- StructuredEvaluator prompt source
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.exceptions import ProjectError
from agentkit.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    template_name_for_role,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.artifacts import ArtifactManager
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.verify_system.llm_evaluator.structured_evaluator import ReviewerRole
    from agentkit.verify_system.protocols import StoryContextQueryPort


@dataclass(frozen=True)
class PromptRuntimeMaterializer:
    """Resolve role prompts via ``PromptRuntime.materialize_prompt`` (FK-44 §44.4.2).

    Attributes:
        ctx: The story context for the run under verification (carries
            ``project_root`` / ``story_id`` / type / route).
        story_dir: Story working directory (used to resolve the run scope).
        artifact_manager: ArtifactManager for the prompt-audit persistence.
        story_context_port: Port resolving the authoritative run correlation.
    """

    ctx: StoryContext
    story_dir: Path
    artifact_manager: ArtifactManager
    story_context_port: StoryContextQueryPort

    def context_for(self, bundle: ReviewBundle) -> tuple[StoryContext, str]:
        """Return the resolved ``(story_context, story_id)`` for ``bundle``.

        Args:
            bundle: The review bundle (its ``story_id`` must match the
                materializer's story context, fail-closed).

        Returns:
            ``(ctx, story_id)``.

        Raises:
            LlmClientError: If the bundle story_id does not match the resolved
                story context (identity mismatch, fail-closed).
        """
        if bundle.story_id != self.ctx.story_id:
            msg = (
                "ReviewBundle.story_id "
                f"{bundle.story_id!r} != materializer story_id "
                f"{self.ctx.story_id!r} (fail-closed identity check)."
            )
            raise LlmClientError(msg)
        return self.ctx, self.ctx.story_id

    def render(
        self,
        role: ReviewerRole,
        ctx: StoryContext,
        story_id: str,
        template_override: str | None = None,
    ) -> tuple[str, str]:
        """Materialize the role prompt and return ``(prompt_text, template_sha256)``.

        Resolution is exclusively through ``PromptRuntime.materialize_prompt``
        (FK-44 §44.4.2). The returned instance carries the verified
        ``template_sha256`` and the run-scoped ``prompt_path`` whose bytes are
        the materialized prompt text.

        Args:
            role: The reviewer role (used to select the template when
                ``template_override`` is ``None``).
            ctx: The story context (carries ``project_root``).
            story_id: Story display-ID (must match the run scope, fail-closed).
            template_override: When set, use this logical template name instead
                of the role's default (FK-32 conformance levels use level-specific
                templates over the DOC_FIDELITY role; ``None`` => role default).

        Returns:
            ``(prompt_text, template_sha256)``.

        Raises:
            LlmClientError: If the project root or run correlation cannot be
                resolved, or materialization fails (fail-closed -- the LLM
                evaluation cannot proceed without a materialized prompt).
        """
        if ctx.project_root is None:
            raise LlmClientError(
                "Cannot materialize Layer-2 prompt: ctx.project_root is None "
                "(FK-44 §44.4.2 fail-closed)."
            )
        run_scope = self.story_context_port.resolve_run_scope(self.story_dir)
        if run_scope is None or not run_scope.run_id:
            raise LlmClientError(
                "Cannot materialize Layer-2 prompt: run correlation unresolved "
                "(FK-44 §44.4.2 fail-closed)."
            )
        if run_scope.story_id != story_id:
            raise LlmClientError(
                f"Run-scope story_id {run_scope.story_id!r} != {story_id!r} "
                "(fail-closed identity check)."
            )
        # Local import to break the import cycle prompt_runtime -> ... ->
        # verify_system.system -> ... -> prompt_materializer: ``ComposeConfig``/
        # ``PromptRuntime`` are only needed at call time, so resolving them here
        # keeps module load order independent of prompt_runtime init order.
        from agentkit.prompt_runtime import ComposeConfig, PromptRuntime

        runtime = PromptRuntime(ctx.project_root, self.artifact_manager)
        template_name = template_override if template_override is not None else template_name_for_role(role)
        try:
            runtime.ensure_run_pin(run_scope.run_id)
            instance = runtime.materialize_prompt(
                ctx,
                template_name,
                ComposeConfig(
                    story_type=ctx.story_type,
                    execution_route=ctx.execution_route,
                ),
                run_id=run_scope.run_id,
                invocation_id=f"verify-layer2-{role.value}-attempt-{run_scope.attempt:03d}",
                render_mode="rendered",
                attempt=run_scope.attempt,
            )
        except ProjectError as exc:
            raise LlmClientError(
                f"Layer-2 prompt materialization failed for role={role.value!r} "
                f"(FK-44 §44.4.2 fail-closed): {exc}"
            ) from exc
        prompt_text = instance.prompt_path.read_text(encoding="utf-8")
        return prompt_text, instance.audit_hash.template_sha256


__all__ = ["PromptRuntimeMaterializer"]
