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

from agentkit.backend.core_types.qa_artifact_names import STRUCTURAL_PRODUCER
from agentkit.backend.verify_system.protocols import TrustClass
from agentkit.backend.verify_system.stage_registry.check_origins import (
    NATIVE_CHECK_ORIGIN_REFS,
)
from agentkit.backend.verify_system.stage_registry.data import ALL_STAGES
from agentkit.backend.verify_system.stage_registry.stages import StageOverridePolicy

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentkit.backend.story_context_manager.types import ImplementationContract, StoryType
    from agentkit.backend.verify_system.protocols import LayerResult
    from agentkit.backend.verify_system.stage_registry.stages import StageDefinition

__all__ = ["StageRegistry", "is_integration_stabilization_stage"]

#: Stage-id prefix that marks a stage as integration-stabilization-only
#: (AG3-069). Stages whose id starts with this prefix are excluded from
#: standard-contract stage plans.
_IS_STAGE_PREFIX: str = "integration."

#: The dedicated stability_gate stage id (Layer-4, IS contract only).
_STABILITY_GATE_ID: str = "stability_gate"


def _build_stage_result_catalog(
    stages: tuple[StageDefinition, ...],
) -> tuple[dict[str, str], dict[str, str]]:
    """Build result mappings only after every stage claim is unambiguous."""
    result_claims: dict[str, list[StageDefinition]] = {}
    for stage in stages:
        result_claims.setdefault(stage.result_name, []).append(stage)
    ambiguous = {
        result_name: [stage.stage_id for stage in candidates]
        for result_name, candidates in result_claims.items()
        if len(candidates) > 1
    }
    if ambiguous:
        msg = f"ambiguous LayerResult names claimed by stage definitions: {ambiguous!r}"
        raise ValueError(msg)
    return (
        {result_name: candidates[0].stage_id for result_name, candidates in result_claims.items()},
        {result_name: candidates[0].producer for result_name, candidates in result_claims.items()},
    )


#: Result identities that aggregate several registered stages instead of
#: corresponding to one ``StageDefinition``. They are explicit registry input,
#: never an invitation to accept an unknown result name as canonical.
DEFAULT_AGGREGATE_RESULT_STAGE_IDS: Mapping[str, str] = {
    "structural": "structural",
}

#: Producer identities for aggregate results that can be materialized into the
#: FK-69 stage/finding projections.
DEFAULT_AGGREGATE_RESULT_PRODUCERS: Mapping[str, str] = {
    "structural": STRUCTURAL_PRODUCER,
}

DEFAULT_STAGE_RESULT_STAGE_IDS, DEFAULT_STAGE_RESULT_PRODUCERS = _build_stage_result_catalog(ALL_STAGES)

#: Additional stage coverage that a non-aggregate result may prove through its
#: complete executed-check protocol. The stability gate actually executes the
#: target-matrix stage; merely naming that stage in producer metadata is never
#: sufficient.
DEFAULT_RESULT_ADDITIONAL_STAGE_COVERAGE: Mapping[str, frozenset[str]] = {
    "stability_gate": frozenset(("integration.integration_target_matrix_passed",)),
}


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
            (:data:`agentkit.backend.verify_system.stage_registry.data.ALL_STAGES`),
            which is a superset of the standard stages. Tests and project
            overrides may inject a different tuple.
    """

    stages: tuple[StageDefinition, ...] = field(default=ALL_STAGES)
    stage_overrides: Mapping[str, bool] = field(default_factory=dict)
    native_check_origin_refs: Mapping[str, str | None] = field(default=NATIVE_CHECK_ORIGIN_REFS)
    stage_result_stage_ids: Mapping[str, str] | None = None
    stage_result_producers: Mapping[str, str] | None = None
    aggregate_result_stage_ids: Mapping[str, str] = field(default_factory=lambda: DEFAULT_AGGREGATE_RESULT_STAGE_IDS)
    aggregate_result_producers: Mapping[str, str] = field(default_factory=lambda: DEFAULT_AGGREGATE_RESULT_PRODUCERS)
    aggregate_result_stage_coverage: Mapping[str, frozenset[str]] | None = None
    result_additional_stage_coverage: Mapping[str, frozenset[str]] | None = None

    @classmethod
    def result_catalog_only(cls) -> StageRegistry:
        """Return an unplanned registry that still knows every result identity."""
        return cls(
            stages=(),
            stage_result_stage_ids=DEFAULT_STAGE_RESULT_STAGE_IDS,
            stage_result_producers=DEFAULT_STAGE_RESULT_PRODUCERS,
        )

    def __post_init__(self) -> None:
        """Apply project overrides and validate fail-closed invariants."""
        by_id: dict[str, StageDefinition] = {}
        for stage in self.stages:
            if not stage.stage_id.strip():
                msg = "stage id must not be empty or whitespace-only"
                raise ValueError(msg)
            if stage.layer_result_name is not None and not stage.layer_result_name.strip():
                msg = f"layer result name for stage {stage.stage_id!r} must not be empty or whitespace-only"
                raise ValueError(msg)
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
                    msg = f"stage {stage.stage_id!r} does not allow blocking overrides"
                    raise ValueError(msg)
                stage = replace(stage, _blocking_override=self.stage_overrides[stage.stage_id])
            if stage.trust_class is TrustClass.WORKER_ASSERTION and stage.effective_blocking:
                msg = f"stage {stage.stage_id!r} has trust class C and is blocking; Trust-C stages must never block"
                raise ValueError(msg)
            stages.append(stage)
        object.__setattr__(self, "stages", tuple(stages))

        derived_stage_result_stage_ids, derived_stage_result_producers = _build_stage_result_catalog(self.stages)

        stage_result_stage_ids = (
            dict(self.stage_result_stage_ids) if self.stage_result_stage_ids is not None else derived_stage_result_stage_ids
        )
        stage_result_producers = (
            dict(self.stage_result_producers) if self.stage_result_producers is not None else derived_stage_result_producers
        )
        self._validate_result_catalog_names(
            stage_result_stage_ids=stage_result_stage_ids,
            aggregate_result_stage_ids=self.aggregate_result_stage_ids,
        )
        unknown_stage_result_producers = set(stage_result_producers) - set(stage_result_stage_ids)
        if unknown_stage_result_producers:
            msg = f"stage result producer(s) have no registered result identity: {sorted(unknown_stage_result_producers)!r}"
            raise ValueError(msg)
        object.__setattr__(self, "stage_result_stage_ids", stage_result_stage_ids)
        object.__setattr__(self, "stage_result_producers", stage_result_producers)

        unknown_aggregate_producers = set(self.aggregate_result_producers) - set(self.aggregate_result_stage_ids)
        if unknown_aggregate_producers:
            msg = f"aggregate result producer(s) have no registered result identity: {sorted(unknown_aggregate_producers)!r}"
            raise ValueError(msg)

        result_claims: dict[str, list[str]] = {}
        for result_name, stage_id in stage_result_stage_ids.items():
            result_claims.setdefault(result_name, []).append(stage_id)
        for result_name, stage_id in self.aggregate_result_stage_ids.items():
            result_claims.setdefault(result_name, []).append(stage_id)
        ambiguous = {name: claims for name, claims in result_claims.items() if len(claims) != 1}
        if ambiguous:
            msg = f"ambiguous LayerResult names in stage registry: {ambiguous!r}"
            raise ValueError(msg)

        self._configure_result_coverage(stage_result_stage_ids)

    def _configure_result_coverage(
        self,
        stage_result_stage_ids: Mapping[str, str],
    ) -> None:
        """Derive and validate registry-owned result coverage."""
        registered_result_names = set(stage_result_stage_ids) | set(self.aggregate_result_stage_ids)
        registered_stage_ids = {stage.stage_id for stage in self.stages}
        registered_stage_ids.update(stage_result_stage_ids.values())
        registered_stage_ids.update(self.aggregate_result_stage_ids.values())
        if self.aggregate_result_stage_coverage is None:
            aggregate_coverage = (
                {
                    "structural": frozenset(
                        stage.stage_id for stage in self.stages if stage.layer == 1 and stage.stage_id != "sonarqube_gate"
                    )
                }
                if "structural" in self.aggregate_result_stage_ids
                else {}
            )
        else:
            aggregate_coverage = dict(self.aggregate_result_stage_coverage)
        if self.result_additional_stage_coverage is None:
            additional_coverage = {
                result_name: coverage
                for result_name, coverage in DEFAULT_RESULT_ADDITIONAL_STAGE_COVERAGE.items()
                if result_name in registered_result_names and coverage.issubset(registered_stage_ids)
            }
        else:
            additional_coverage = dict(self.result_additional_stage_coverage)
        object.__setattr__(self, "aggregate_result_stage_coverage", aggregate_coverage)
        object.__setattr__(self, "result_additional_stage_coverage", additional_coverage)

        unknown_aggregates = set(aggregate_coverage) - set(self.aggregate_result_stage_ids)
        if unknown_aggregates:
            raise ValueError(f"aggregate coverage has no registered result identity: {sorted(unknown_aggregates)!r}")
        unknown_additional = set(additional_coverage) - registered_result_names
        if unknown_additional:
            raise ValueError(f"additional coverage has no registered result identity: {sorted(unknown_additional)!r}")
        coverage_stage_ids = {
            stage_id for coverage in (*aggregate_coverage.values(), *additional_coverage.values()) for stage_id in coverage
        }
        unknown_stage_ids = coverage_stage_ids - registered_stage_ids
        if unknown_stage_ids:
            raise ValueError(f"result coverage references unknown stage id(s): {sorted(unknown_stage_ids)!r}")

    @staticmethod
    def _validate_result_catalog_names(
        *,
        stage_result_stage_ids: Mapping[str, str],
        aggregate_result_stage_ids: Mapping[str, str],
    ) -> None:
        """Reject blank result names and canonical stage identities."""
        for result_name, stage_id in (
            *stage_result_stage_ids.items(),
            *aggregate_result_stage_ids.items(),
        ):
            if not result_name.strip():
                raise ValueError("layer result name must not be empty or whitespace-only")
            if not stage_id.strip():
                raise ValueError(f"canonical stage id for result {result_name!r} must not be empty or whitespace-only")

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
        from agentkit.backend.story_context_manager.types import ImplementationContract

        is_contract = implementation_contract is ImplementationContract.INTEGRATION_STABILIZATION
        return [
            s
            for s in self.stages
            if story_type in s.applies_to and (is_contract or not is_integration_stabilization_stage(s.stage_id))
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
        from agentkit.backend.story_context_manager.types import ImplementationContract

        is_contract = implementation_contract is ImplementationContract.INTEGRATION_STABILIZATION
        if not is_contract and is_integration_stabilization_stage(stage_id):
            return None
        return next((s for s in self.stages if s.stage_id == stage_id), None)

    def canonical_stage_id_for_result_name(self, result_name: str) -> str:
        """Resolve a ``LayerResult.layer`` name to its canonical stage ID.

        Stage result names are owned by :class:`StageDefinition`; aggregate
        result names are owned by ``aggregate_result_stage_ids``. Any other
        value is rejected instead of being passed through as a purportedly
        canonical stage identity.

        Args:
            result_name: The ``LayerResult.layer`` value to resolve.

        Returns:
            The canonical stage ID for persistence and policy projections.

        Raises:
            ValueError: If the result name is unknown or ambiguous.
        """
        matches: list[str] = []
        if self.stage_result_stage_ids is not None:
            stage_id = self.stage_result_stage_ids.get(result_name)
            if stage_id is not None:
                matches.append(stage_id)
        aggregate_stage_id = self.aggregate_result_stage_ids.get(result_name)
        if aggregate_stage_id is not None:
            matches.append(aggregate_stage_id)
        if len(matches) > 1:
            msg = f"ambiguous LayerResult name {result_name!r} in stage registry: {matches!r}"
            raise ValueError(msg)
        if not matches:
            msg = f"unknown LayerResult name {result_name!r} in stage registry"
            raise ValueError(msg)
        return matches[0]

    def producer_for_result_name(self, result_name: str) -> str:
        """Return the registered producer for a projectable result name."""
        aggregate_producer = self.aggregate_result_producers.get(result_name)
        if aggregate_producer is not None:
            return aggregate_producer
        self.canonical_stage_id_for_result_name(result_name)
        if self.stage_result_producers is not None:
            stage_producer = self.stage_result_producers.get(result_name)
            if stage_producer is not None:
                return stage_producer
        msg = f"LayerResult name {result_name!r} has no projectable producer"
        raise ValueError(msg)

    def result_names_for_layer(self, layer: int) -> frozenset[str]:
        """Return the registry-owned result identities for one QA layer."""
        return frozenset(stage.result_name for stage in self.stages if stage.layer == layer)

    def produced_stage_ids(
        self,
        layer_results: tuple[LayerResult, ...],
        *,
        expected_stage_ids: frozenset[str],
    ) -> set[str]:
        """Resolve produced stage IDs from registry coverage and the active plan.

        Producer ``metadata['stage_ids']`` is not an authority source. When
        present, it must exactly mirror the coverage derived here; a result
        cannot claim a known stage owned by another result type.
        """
        registered_stage_ids = {stage.stage_id for stage in self.stages}
        if self.stage_result_stage_ids is not None:
            registered_stage_ids.update(self.stage_result_stage_ids.values())
        registered_stage_ids.update(self.aggregate_result_stage_ids.values())
        unknown_expected = set(expected_stage_ids) - registered_stage_ids
        if unknown_expected:
            msg = f"execution plan references unknown stage id(s): {sorted(unknown_expected)!r}"
            raise ValueError(msg)
        produced: set[str] = set()
        aggregate_coverage_by_result = self.aggregate_result_stage_coverage
        if aggregate_coverage_by_result is None:
            raise RuntimeError("registry aggregate result coverage was not configured")
        additional_coverage_by_result = self.result_additional_stage_coverage
        if additional_coverage_by_result is None:
            raise RuntimeError("registry additional result coverage was not configured")
        for layer_result in layer_results:
            canonical_stage_id = self.canonical_stage_id_for_result_name(layer_result.layer)
            executed_check_ids = self._executed_check_ids_for_coverage(layer_result)
            if layer_result.layer in self.aggregate_result_stage_ids:
                allowed_coverage = aggregate_coverage_by_result.get(
                    layer_result.layer,
                    frozenset((canonical_stage_id,)),
                )
                result_coverage = set(allowed_coverage & expected_stage_ids)
            else:
                result_coverage = {canonical_stage_id} & expected_stage_ids
                additional = additional_coverage_by_result.get(
                    layer_result.layer,
                    frozenset(),
                )
                result_coverage.update(additional & executed_check_ids & expected_stage_ids)

            metadata_stage_ids = layer_result.metadata.get("stage_ids")
            if metadata_stage_ids is not None:
                if not isinstance(metadata_stage_ids, (list, tuple, set, frozenset)) or any(
                    not isinstance(stage_id, str) for stage_id in metadata_stage_ids
                ):
                    msg = "LayerResult metadata['stage_ids'] must be a string sequence"
                    raise ValueError(msg)
                claimed_stage_ids = set(metadata_stage_ids)
                if claimed_stage_ids != result_coverage:
                    msg = (
                        f"LayerResult {layer_result.layer!r} metadata stage coverage "
                        f"does not match registry and execution plan: claimed="
                        f"{sorted(claimed_stage_ids)!r}, expected={sorted(result_coverage)!r}"
                    )
                    raise ValueError(msg)
            produced.update(result_coverage)
        return produced

    @staticmethod
    def _executed_check_ids_for_coverage(layer_result: LayerResult) -> frozenset[str]:
        """Return well-formed executed IDs used for registry-owned coverage."""
        raw_executed = layer_result.metadata.get("executed_check_ids", ())
        if not isinstance(raw_executed, (list, tuple)) or any(not isinstance(check_id, str) for check_id in raw_executed):
            msg = "LayerResult metadata['executed_check_ids'] must be a string list or tuple"
            raise ValueError(msg)
        return frozenset(raw_executed)

    def resolve_check_origin_refs(
        self,
        executed_check_ids: tuple[str, ...] | list[str],
        *,
        adversarial_target_sources: Mapping[str, str] | None = None,
    ) -> dict[str, str | None]:
        """Resolve only registry-proven provenance for executed checks.

        Stage IDs resolve through their typed definitions. Built-in sub-checks
        resolve through the explicit native table. Adversarial target IDs use
        the registered source layer plus the source check's exact provenance.
        Unknown IDs are omitted so the outcome emitter detects registry or
        wiring drift instead of classifying them as native.

        Args:
            executed_check_ids: Check IDs reported by one completed layer.

        Returns:
            Proven ``check_id -> CHK-NNNN | None`` entries. Unknown IDs are
            absent.
        """
        check_origins: dict[str, str | None] = dict(self.native_check_origin_refs)
        check_origins.update({stage.stage_id: stage.origin_check_ref for stage in self.stages})
        target_sources = adversarial_target_sources or {}
        resolved: dict[str, str | None] = {}
        for check_id in executed_check_ids:
            if check_id in check_origins:
                resolved[check_id] = check_origins[check_id]
                continue
            source_check_id = target_sources.get(check_id)
            if source_check_id is not None and source_check_id in check_origins:
                resolved[check_id] = check_origins[source_check_id]
        return resolved

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
            for s in self.stages_for(story_type, implementation_contract=implementation_contract)
            if s.layer == 1 and s.stage_id != "sonarqube_gate" and (are_enabled or not s.feature_gated_are)
        ]
