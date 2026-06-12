"""Create-scope prompt materializer for the conflict assessment (FK-44 §44.4.2).

This is the create-time counterpart to
:class:`~agentkit.verify_system.llm_evaluator.prompt_materializer.PromptRuntimeMaterializer`.
It resolves the ``vectordb-conflict`` prompt template for the FK-21 §21.4.1
Schritt 3 conflict assessment WITHOUT a live ``StoryContext`` / ``run_id`` /
run-pin / story working directory -- none of which exist before the story is
created (story.md §1.1).

It still resolves the template through the pinned/bootstrap prompt bundle
(FK-44 §44.4.2: the SAME bundle source the execution-scoped path uses, never a
direct loose-file read) and verifies the manifest digest, so the create-scope
path inherits the bundle's byte-faithfulness and the ARE/ARCH-55 prompt
conventions. It deliberately does NOT materialize a run-scoped prompt instance
file (that requires a run-pin + story dir); the conflict assessment is a single
gating call, not a run-pinned agent invocation.

The ``story_id`` placeholder substitution mirrors the single substitution the
execution-scoped renderer performs for ``story_id`` (composer
``_build_placeholder_map``), using the bundle's draft display-id (the search
scope) -- not a persisted story id.

This adapter intentionally satisfies the ``_PromptMaterializer`` *surface*
consumed by :class:`StructuredEvaluator` (``context_for`` + ``render``) but
returns ``None`` for the story-context slot: the evaluator treats that value as
an opaque pass-through token (it hands it straight back into ``render`` and
never inspects it), so no ``StoryContext`` is needed. The execution-scoped
materializer is left completely untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.exceptions import ProjectError
from agentkit.prompt_runtime.resources import (
    load_prompt_template,
    prompt_template_sha256,
)
from agentkit.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.verify_system.llm_evaluator.structured_evaluator import (
    template_name_for_role,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.verify_system.llm_evaluator.roles import ReviewerRole


class CreateScopePromptMaterializer:
    """Resolve the conflict-assessment prompt with NO story context / run-pin.

    Attributes:
        _project_root: Optional project root used ONLY to resolve the
            project-pinned prompt-bundle binding (FK-44 §44.3). ``None`` -> the
            internal bootstrap bundle (non-project / pre-story contexts). No
            ``StoryContext`` and no run-pin are derived from it.
    """

    def __init__(self, *, project_root: Path | None = None) -> None:
        """Initialise the create-scope materializer.

        Args:
            project_root: Optional target-project root for the project-pinned
                prompt bundle binding. ``None`` uses the internal bootstrap
                bundle.
        """
        self._project_root = project_root

    def context_for(self, bundle: ReviewBundle) -> tuple[None, str]:
        """Return ``(None, story_id)`` for the create-scope evaluation.

        There is no ``StoryContext`` at create time. The evaluator only uses the
        first element as an opaque token it passes back into :meth:`render`, so
        ``None`` is returned for it. The second element is the bundle's draft
        display-id (the search scope), used for the ``story_id`` placeholder.

        Args:
            bundle: The review bundle carrying the draft display-id.

        Returns:
            ``(None, bundle.story_id)``.
        """
        return None, bundle.story_id

    def render(
        self,
        role: ReviewerRole,
        ctx: None,
        story_id: str,
        template_override: str | None = None,
    ) -> tuple[str, str]:
        """Resolve ``(prompt_text, template_sha256)`` from the pinned bundle.

        The template is loaded and digest-verified through the prompt-bundle
        binding (FK-44 §44.4.2) -- never a direct loose-file read. The single
        ``{story_id}`` placeholder is substituted with ``story_id`` to mirror the
        execution-scoped renderer's behaviour for that placeholder; the template
        carries no other dynamic placeholders.

        Args:
            role: The reviewer role; selects the template when
                ``template_override`` is ``None`` (here: ``vectordb-conflict``).
            ctx: Always ``None`` in create scope (the opaque pass-through token).
            story_id: The draft display-id used for the ``{story_id}`` placeholder.
            template_override: Optional explicit template name (unused on the
                create-scope path; kept for surface fidelity).

        Returns:
            ``(prompt_text, template_sha256)``.

        Raises:
            LlmClientError: When the prompt bundle / template cannot be resolved
                (fail-closed: the assessment cannot proceed without a verified
                prompt). Raised as ``LlmClientError`` so the adjudicator maps it
                to the truthful create-time fail-closed error, distinguishable
                from a VectorDB outage.
        """
        del ctx  # No story context at create time (opaque pass-through token).
        template_name = (
            template_override
            if template_override is not None
            else template_name_for_role(role)
        )
        try:
            # ``project_root=None`` resolves the internal bootstrap bundle
            # (FK-44 §44.4.2, non-project / pre-story context); a project root
            # resolves the project-pinned binding. Both paths read through the
            # bundle resolver + verify the manifest digest -- never a loose read.
            template_text = load_prompt_template(
                template_name, project_root=self._project_root
            )
            template_sha256 = prompt_template_sha256(
                template_name, project_root=self._project_root
            )
        except ProjectError as exc:
            raise LlmClientError(
                "create-scope prompt resolution failed for template "
                f"{template_name!r} (FK-44 §44.4.2 fail-closed): {exc}"
            ) from exc
        prompt_text = template_text.replace("{story_id}", story_id)
        # The sha256 stays the digest of the canonical (un-substituted) template
        # bytes (FK-44 §44.6: the template digest is over the bundle file, not
        # the rendered instance) -- matches the execution-scoped audit hash.
        return prompt_text, template_sha256


__all__ = ["CreateScopePromptMaterializer"]
