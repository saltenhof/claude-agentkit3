"""StageRegistry -- typed planner of QA-subflow stages (FK-33 §33.2).

The registry holds the typed :class:`StageDefinition` profiles and answers
"which stages apply to this story type" (FK-33 §33.2.4 ``stages_for``). It
is a pure planner: it never runs check code (FK-33 §33.2.5
Verantwortungstrennung -- "die Registry plant, der GateRunner fuehrt aus,
die PolicyEngine aggregiert"). The Layer-1 ``StructuralChecker`` consumes
``stages_for(story_type)`` filtered to ``layer == 1`` to drive its checks;
the ``PolicyEngine`` consumes the same registry to know which blocking
Layer-1 stages MUST have produced a result (fail-closed, FK-33 §33.7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.verify_system.stage_registry.data import LAYER_1_STAGES

if TYPE_CHECKING:
    from agentkit.story_context_manager.types import StoryType
    from agentkit.verify_system.stage_registry.stages import StageDefinition

__all__ = ["StageRegistry"]


@dataclass(frozen=True)
class StageRegistry:
    """Typed registry of QA-subflow stage definitions (FK-33 §33.2).

    Args:
        stages: The full ordered tuple of stage definitions. Defaults to the
            canonical FK-27 §27.4 / FK-33 Layer-1 catalogue
            (:data:`agentkit.verify_system.stage_registry.data.LAYER_1_STAGES`).
            Tests and project overrides may inject a different tuple; the
            default is the production single source of truth.
    """

    stages: tuple[StageDefinition, ...] = field(default=LAYER_1_STAGES)

    def stages_for(self, story_type: StoryType) -> list[StageDefinition]:
        """Return the stages that apply to ``story_type`` (FK-33 §33.2.4).

        Only stages whose ``applies_to`` contains ``story_type`` are returned,
        in registry (execution) order. Concept/research stories therefore get
        an empty Layer-1 list (FK-33 §33.2.4 / §33.9).

        Args:
            story_type: The story type to plan stages for.

        Returns:
            The applicable stage definitions in execution order.
        """
        return [s for s in self.stages if story_type in s.applies_to]

    def layer1_stages_for(
        self,
        story_type: StoryType,
        *,
        are_enabled: bool,
    ) -> list[StageDefinition]:
        """Return the applicable Layer-1 stages for ``story_type``.

        Filters :meth:`stages_for` to ``layer == 1`` and drops the
        feature-gated ARE stage(s) unless ``are_enabled`` (FK-27 §27.4.4:
        the ARE-Gate runs only when ``features.are == true``).

        Args:
            story_type: The story type to plan Layer-1 stages for.
            are_enabled: Whether ``features.are`` is active for this run
                (``RequirementsCoverage.is_enabled``, AG3-030).

        Returns:
            The applicable Layer-1 stage definitions in execution order.
        """
        return [
            s
            for s in self.stages_for(story_type)
            if s.layer == 1 and (are_enabled or not s.feature_gated_are)
        ]
