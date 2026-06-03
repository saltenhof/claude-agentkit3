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


#: The canonical ``sonarqube_gate`` stage definition (FK-33 §33.2.2).
SONARQUBE_GATE_STAGE = SonarStageDefinition(
    stage_id="sonarqube_gate",
    layer=1,
    kind="deterministic",
    applies_to=frozenset({"implementation", "bugfix"}),
    blocking=True,
    trust_class="A",
    producer="qa-sonarqube-gate",
    sequence_after="adversarial",
    execution_policy="ALWAYS",
    override_policy="NON_SKIPPABLE",
)


__all__ = ["SONARQUBE_GATE_STAGE", "SonarStageDefinition"]
