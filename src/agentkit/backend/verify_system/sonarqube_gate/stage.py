"""``sonarqube_gate`` stage definition (FK-33 §33.2.2 / §33.8.3).

The stage is classified Layer 1 deterministic (Trust-Class A, blocking)
but the StageExecutionPlan sequences it AFTER the Layer-3 adversarial
stage (``sequence_after = "adversarial"``), because every prior
remediation changes production code and may introduce new violations
(FK-33 §33.6.3 / §33.8.3). Field set matches the formal entity
``formal.deterministic-checks.entities.sonarqube-gate-stage``.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentkit.backend.verify_system.stage_registry import StageRegistry


@dataclass(frozen=True)
class SonarStageDefinition:
    """Typed profile of the ``sonarqube_gate`` stage.

    Attributes:
        stage_id: Stable stage id (``sonarqube_gate``).
        layer: Classificatory layer (1 = deterministic).
        kind: Check kind (``deterministic``).
        applies_to: Story types the stage applies to.
        blocking: Whether a FAIL blocks (Trust A => blocking allowed).
        trust_class: Trust class (``A`` -- authoritative external system).
        producer: Allowed producer name.
        sequence_after: Stage id this stage is sequenced AFTER in the plan.
        execution_policy: DSL execution policy of the stage invocation.
        override_policy: Normative override frame for the stage.
    """

    stage_id: str
    layer: int
    kind: str
    applies_to: frozenset[str]
    blocking: bool
    trust_class: str
    producer: str
    sequence_after: str
    execution_policy: str
    override_policy: str


_REGISTRY_STAGE = StageRegistry().stage_for_id("sonarqube_gate")
if _REGISTRY_STAGE is None:  # pragma: no cover - canonical registry invariant
    msg = "sonarqube_gate missing from StageRegistry"
    raise RuntimeError(msg)

#: Compatibility view of the canonical registry-owned ``sonarqube_gate`` stage.
SONARQUBE_GATE_STAGE = SonarStageDefinition(
    stage_id=_REGISTRY_STAGE.stage_id,
    layer=_REGISTRY_STAGE.layer,
    kind=_REGISTRY_STAGE.kind.value,
    applies_to=frozenset(story_type.value for story_type in _REGISTRY_STAGE.applies_to),
    blocking=_REGISTRY_STAGE.effective_blocking,
    trust_class=(
        _REGISTRY_STAGE.trust_class.value
        if _REGISTRY_STAGE.trust_class is not None
        else ""
    ),
    producer=_REGISTRY_STAGE.producer,
    sequence_after="adversarial",
    execution_policy=_REGISTRY_STAGE.execution_policy.value,
    override_policy=_REGISTRY_STAGE.override_policy.value,
)


__all__ = ["SONARQUBE_GATE_STAGE", "SonarStageDefinition"]
