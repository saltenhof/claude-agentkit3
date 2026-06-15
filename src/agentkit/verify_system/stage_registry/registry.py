"""StageRegistry -- typed planner of QA-subflow stages (FK-33 §33.2).

The registry holds the typed :class:`StageDefinition` profiles and answers
"which stages apply to this story type" (FK-33 §33.2.4 ``stages_for``). It
is a pure planner: it never runs check code (FK-33 §33.2.5
Verantwortungstrennung -- "die Registry plant, der GateRunner fuehrt aus,
die PolicyEngine aggregiert"). The Layer-1 ``StructuralChecker`` consumes
``stages_for(story_type)`` filtered to ``layer == 1`` to drive its checks;
the ``PolicyEngine`` consumes the same registry to know which blocking
Layer-1 stages MUST have produced a result (fail-closed, FK-33 §33.7).

AG3-069 (FK-05 §5.10/§5.14): the registry is contract-aware. Stages whose
``stage_id`` starts with ``"integration."`` or equals ``"stability_gate"``
are only active for the ``integration_stabilization`` contract. The
``layer1_stages_for`` and ``stages_for`` methods accept an optional
``implementation_contract`` parameter to filter accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from agentkit.verify_system.protocols import TrustClass
from agentkit.verify_system.stage_registry.data import ALL_STAGES
from agentkit.verify_system.stage_registry.stages import StageOverridePolicy

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentkit.story_context_manager.types import ImplementationContract, StoryType
    from agentkit.verify_system.stage_registry.stages import StageDefinition

__all__ = ["StageRegistry", "is_integration_stabilization_stage"]

#: Stage-id prefix that marks a stage as integration-stabilization-only
#: (AG3-069). Stages whose id starts with this prefix are excluded from
#: standard-contract stage plans.
_IS_STAGE_PREFIX: str = "integration."

#: The dedicated stability_gate stage id (Layer-4, IS contract only).
_STABILITY_GATE_ID: str = "stability_gate"


def is_integration_stabilization_stage(stage_id: str) -> bool:
    """Return True iff ``stage_id`` is an integration-stabilization-only stage.

    Integration-stabilization stages have ids starting with ``"integration."``
    or are the dedicated ``"stability_gate"`` stage (AG3-069, FK-05 §5.10).

    Args:
        stage_id: The stage identifier to test.

    Returns:
        True iff this stage is only active for the integration_stabilization
        contract.
    """
    return stage_id.startswith(_IS_STAGE_PREFIX) or stage_id == _STABILITY_GATE_ID


@dataclass(frozen=True)
class StageRegistry:
    """Typed registry of QA-subflow stage definitions (FK-33 §33.2).

    The default ``stages`` tuple is the ONE canonical catalogue
    (:data:`ALL_STAGES`) including both the standard stages and the
    integration-stabilization stages. There is NO parallel registry; the
    contract-aware query methods (:meth:`stages_for`, :meth:`layer1_stages_for`,
    :meth:`stage_for_id`) filter to the appropriate subset based on the caller's
    ``implementation_contract`` parameter.

    Standard-contract stories see only the standard stages; only
    integration-stabilization stories see the IS stages (AG3-069,
    FK-05 §5.10/§5.14).

    Args:
        stages: The full ordered tuple of stage definitions. Defaults to the
            canonical full catalogue
            (:data:`agentkit.verify_system.stage_registry.data.ALL_STAGES`),
            which is a superset of the standard stages. Tests and project
            overrides may inject a different tuple.
    """

    stages: tuple[StageDefinition, ...] = field(default=ALL_STAGES)
    stage_overrides: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Apply project overrides and validate fail-closed invariants."""
        by_id: dict[str, StageDefinition] = {}
        for stage in self.stages:
            if stage.stage_id in by_id:
                msg = f"duplicate stage id in registry: {stage.stage_id!r}"
                raise ValueError(msg)
            by_id[stage.stage_id] = stage

        unknown = set(self.stage_overrides) - set(by_id)
        if unknown:
            msg = f"unknown stage override(s): {sorted(unknown)!r}"
            raise ValueError(msg)

        stages: list[StageDefinition] = []
        for stage in self.stages:
            if stage.stage_id in self.stage_overrides:
                if stage.override_policy is StageOverridePolicy.NONE:
                    msg = (
                        f"stage {stage.stage_id!r} does not allow blocking "
                        "overrides"
                    )
                    raise ValueError(msg)
                stage = replace(
                    stage, _blocking_override=self.stage_overrides[stage.stage_id]
                )
            if (
                stage.trust_class is TrustClass.WORKER_ASSERTION
                and stage.effective_blocking
            ):
                msg = (
                    f"stage {stage.stage_id!r} has trust class C and is "
                    "blocking; Trust-C stages must never block"
                )
                raise ValueError(msg)
            stages.append(stage)
        object.__setattr__(self, "stages", tuple(stages))

    def stages_for(
        self,
        story_type: StoryType,
        *,
        implementation_contract: ImplementationContract | None = None,
    ) -> list[StageDefinition]:
        """Return the stages that apply to ``story_type`` (FK-33 §33.2.4).

        Only stages whose ``applies_to`` contains ``story_type`` are returned,
        in registry (execution) order. Concept/research stories receive their
        aggregate registry stages (FK-33 §33.2.4 / §33.9).

        AG3-069: integration-stabilization-only stages (ids starting with
        ``"integration."`` or equal to ``"stability_gate"``) are excluded for
        the standard contract and included for the integration_stabilization
        contract. When ``implementation_contract`` is ``None``, IS stages are
        excluded (standard behaviour).

        Args:
            story_type: The story type to plan stages for.
            implementation_contract: The active implementation contract.
                ``None`` or ``STANDARD`` excludes IS-only stages.

        Returns:
            The applicable stage definitions in execution order.
        """
        from agentkit.story_context_manager.types import ImplementationContract

        is_contract = (
            implementation_contract is ImplementationContract.INTEGRATION_STABILIZATION
        )
        return [
            s
            for s in self.stages
            if story_type in s.applies_to
            and (is_contract or not is_integration_stabilization_stage(s.stage_id))
        ]

    def stage_for_id(
        self,
        stage_id: str,
        *,
        implementation_contract: ImplementationContract | None = None,
    ) -> StageDefinition | None:
        """Return the registered stage for ``stage_id``, if visible for the contract.

        AG3-069 (MAJOR H, no-regression): integration-stabilization stages
        (``integration.*`` / ``stability_gate``) are visible ONLY for the
        ``integration_stabilization`` contract. For ``None``/``STANDARD`` they
        are invisible — a lookup for an IS stage id returns ``None`` so the
        shared-surface behaviour for standard stories is unchanged (the IS
        stages must never leak into the standard plan).

        Args:
            stage_id: The stage identifier to look up.
            implementation_contract: The active implementation contract.
                ``None`` or ``STANDARD`` hides IS-only stages.

        Returns:
            The matching :class:`StageDefinition`, or ``None`` when absent or
            when the stage is IS-only and the contract is not IS.
        """
        from agentkit.story_context_manager.types import ImplementationContract

        is_contract = (
            implementation_contract is ImplementationContract.INTEGRATION_STABILIZATION
        )
        if not is_contract and is_integration_stabilization_stage(stage_id):
            return None
        return next((s for s in self.stages if s.stage_id == stage_id), None)

    def layer1_stages_for(
        self,
        story_type: StoryType,
        *,
        are_enabled: bool,
        implementation_contract: ImplementationContract | None = None,
    ) -> list[StageDefinition]:
        """Return the applicable Layer-1 stages for ``story_type``.

        Filters :meth:`stages_for` to ``layer == 1`` and drops the
        feature-gated ARE stage(s) unless ``are_enabled`` (FK-27 §27.4.4:
        the ARE-Gate runs only when ``features.are == true``).

        AG3-069: integration-stabilization-only stages are only included when
        ``implementation_contract == INTEGRATION_STABILIZATION``.

        Args:
            story_type: The story type to plan Layer-1 stages for.
            are_enabled: Whether ``features.are`` is active for this run
                (``RequirementsCoverage.is_enabled``, AG3-030).
            implementation_contract: The active implementation contract.
                ``None`` or ``STANDARD`` excludes IS-only stages.

        Returns:
            The applicable Layer-1 stage definitions in execution order.
        """
        return [
            s
            for s in self.stages_for(
                story_type, implementation_contract=implementation_contract
            )
            if s.layer == 1
            and s.stage_id != "sonarqube_gate"
            and (are_enabled or not s.feature_gated_are)
        ]
