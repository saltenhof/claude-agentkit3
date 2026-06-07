"""Adversarial QA layer -- edge-case testing and multi-LLM sparring.

Defines the contract. Actual LLM implementation comes later.
``AdversarialChallenger`` is a passthrough that always passes (for
pipeline testing until the real multi-LLM integration is available).

AG3-044 (FK-27 §27.6 / FK-48 §48.2): the Layer-3 call now uses the
:class:`AdversarialSpawner` to derive the mandatory adversarial targets from the
Layer-2 findings. ``derive_adversarial_targets`` is the seam the QA-subflow
drives to turn BLOCKING Layer-2 findings into mandatory targets before spawning
the adversarial worker; the spawn itself (sandbox + ``agents_to_spawn``) is owned
by :class:`AdversarialSpawner`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.verify_system.prompt_audit_support import PromptAuditMixin
from agentkit.verify_system.protocols import LayerResult

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.artifacts import ArtifactManager
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.adversarial_orchestrator.spawn import (
        AdversarialSpawner,
        AdversarialTarget,
    )
    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput
    from agentkit.verify_system.protocols import Finding, StoryContextQueryPort


class AdversarialChallenger(PromptAuditMixin):
    """Layer 3: Adversarial edge-case testing.

    Currently a passthrough that always passes. Real implementation
    will generate edge-case tests, run them, and perform multi-LLM
    sparring over weaknesses (code stories only).

    AG3-044: when constructed with an :class:`AdversarialSpawner` the Layer-3
    call derives the mandatory adversarial targets from the Layer-2 findings via
    :meth:`derive_adversarial_targets` (FK-48 §48.2).

    Satisfies the :class:`~agentkit.verify_system.protocols.QALayer` protocol.
    """

    def __init__(
        self,
        *,
        artifact_manager: ArtifactManager | None = None,
        story_context_port: StoryContextQueryPort | None = None,
        spawner: AdversarialSpawner | None = None,
    ) -> None:
        """Initialise the challenger, optionally wiring the spawner.

        Args:
            artifact_manager: Prompt-audit persistence (forwarded to the
                :class:`PromptAuditMixin`).
            story_context_port: Run-correlation port (forwarded to the mixin).
            spawner: The :class:`AdversarialSpawner` used to derive mandatory
                targets from Layer-2 findings (FK-48 §48.2). ``None`` keeps the
                pure passthrough behaviour (no target derivation wired).
        """
        super().__init__(
            artifact_manager=artifact_manager,
            story_context_port=story_context_port,
        )
        self._spawner = spawner

    def derive_adversarial_targets(
        self,
        layer2_findings: list[Finding],
    ) -> list[AdversarialTarget]:
        """Derive mandatory adversarial targets from Layer-2 findings (FK-48 §48.2).

        Delegates to the wired :class:`AdversarialSpawner`. Returns an empty list
        when no spawner is wired (pure passthrough) or no BLOCKING finding exists.

        Args:
            layer2_findings: The Layer-2 findings of the current round.

        Returns:
            The mandatory adversarial targets (one per BLOCKING finding).
        """
        if self._spawner is None:
            return []
        return self._spawner.derive_targets(layer2_findings)

    @property
    def name(self) -> str:
        """Return the layer name.

        Returns:
            ``"adversarial"``.
        """
        return "adversarial"

    def evaluate(
        self,
        ctx: StoryContext,
        story_dir: Path,
        *,
        review_input: Layer2ReviewInput | None = None,
    ) -> LayerResult:
        """Evaluate adversarial quality -- currently a passthrough.

        ``review_input`` is accepted but ignored by Layer 3 (Adversarial);
        it is only used by Layer-2 reviewers.

        Args:
            ctx: Story context (unused in passthrough).
            story_dir: Directory containing story artifacts (unused).
            review_input: Ignored by Layer 3. Accepted for protocol
                compatibility with ``QALayer``.

        Returns:
            LayerResult with ``passed=True`` and no findings.
        """
        del review_input  # Layer 3 does not use review_input.
        return LayerResult(
            layer=self.name,
            passed=True,
            metadata={
                "prompt_audit": self._materialize_prompt_audit(
                    layer_name=self.name,
                    template_name="qa-adversarial-review",
                    ctx=ctx,
                    story_dir=story_dir,
                ),
            },
        )
