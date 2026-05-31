"""Shared prompt-audit dependency carrier for QA layers (AG3-015).

QA layers materialize and audit their prompts exclusively via
``PromptRuntime.materialize_prompt`` + ``ArtifactManager`` (FK-44 §44.4.2 /
§44.6). They need two injected dependencies for that: the ``ArtifactManager``
(audit persistence) and the ``StoryContextQueryPort`` (run-correlation
resolution without a direct ``state_backend.store`` import).

This mixin holds those dependencies and exposes a single helper so the four
QA layers (three Layer-2 reviewers + the Layer-3 challenger) do not duplicate
the wiring. When the dependencies are absent (e.g. a unit test constructing a
layer directly without the composition root), the prompt audit is skipped
fail-soft -- the audit is diagnostic metadata, never a gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.verify_system.prompt_audit import materialize_qa_prompt_audit

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.artifacts import ArtifactManager
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.protocols import StoryContextQueryPort


class PromptAuditMixin:
    """Carries the injected prompt-audit dependencies for a QA layer."""

    def __init__(
        self,
        *,
        artifact_manager: ArtifactManager | None = None,
        story_context_port: StoryContextQueryPort | None = None,
    ) -> None:
        self._prompt_artifact_manager = artifact_manager
        self._prompt_story_context_port = story_context_port

    def _materialize_prompt_audit(
        self,
        *,
        layer_name: str,
        template_name: str,
        ctx: StoryContext,
        story_dir: Path,
    ) -> dict[str, Any]:
        """Materialize and audit the layer prompt via the top surface.

        Returns a ``skipped`` status when the prompt-audit dependencies were
        not injected (no composition-root wiring) -- the audit never blocks
        QA execution.
        """
        if self._prompt_story_context_port is None:
            return {"status": "skipped", "reason": "story_context_port_unavailable"}
        return materialize_qa_prompt_audit(
            layer_name=layer_name,
            template_name=template_name,
            ctx=ctx,
            story_dir=story_dir,
            artifact_manager=self._prompt_artifact_manager,
            story_context_port=self._prompt_story_context_port,
        )


__all__ = ["PromptAuditMixin"]
