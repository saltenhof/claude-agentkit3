"""Init hook: registers the four QA-layer producers of the verify-system.

Called **once** by the composition root (app bootstrap),
before any pipeline run starts. Consistent with the AK3 cut
"no operative code in ``__init__.py``" — the registration lives in
this dedicated init-hook module, not in the package init.

Sources:
- ``concept/_meta/bc-cut-decisions.md §BC 8 artifacts`` — lines 715-770
  (producer registry; AG3-022 §2.1.5.1 init strategy: empty registry
  + init hooks per BC)
- ``stories/AG3-023-artifact-manager-migration/story.md §2.1.6.1`` —
  variant choice: dedicated ``register.py``
- Concept mapping of the four layers:
    - ``FK-27 §27.4`` — Layer 1 Structural (deterministic)
    - ``FK-27 §27.5`` — Layer 2 LLM reviews
    - ``FK-27 §27.6`` — Layer 3 Adversarial
    - ``FK-27 §27.7`` — Layer 4 Policy (deterministic)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentkit.backend.artifacts import ProducerType
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.core_types.qa_artifact_names import (
    ADVERSARIAL_PRODUCER,
    CONTEXT_SUFFICIENCY_PRODUCER,
    DOC_FIDELITY_PRODUCER,
    QA_REVIEW_PRODUCER,
    SEMANTIC_REVIEW_PRODUCER,
    SONARQUBE_GATE_PRODUCER,
    STABILITY_GATE_PRODUCER,
    STRUCTURAL_PRODUCER,
    VERIFY_DECISION_PRODUCER,
)

if TYPE_CHECKING:
    from agentkit.backend.artifacts import ProducerRegistry

#: Canonical producer name stamped on adversarial-sandbox envelopes (AG3-044,
#: FK-48 §48.1). The Layer-3 adversarial spawn writes its sandbox under
#: ``_temp/adversarial/{story_id}/{epoch}/`` as ``ADVERSARIAL_TEST_SANDBOX``.
ADVERSARIAL_SANDBOX_PRODUCER: Final[str] = "qa-adversarial-sandbox"

#: Stage id of the adversarial-sandbox artifact (envelope ``stage`` field).
ADVERSARIAL_SANDBOX_STAGE: Final[str] = "qa-adversarial"

# (ArtifactClass, producer name, ProducerType) — Single Source of Truth
# for the verify-system producers. A change to this list is
# a concept change and must be reflected in FK-27.
#
# AG3-026 §AK7 requires three separate QA artifacts for Layer 2
# (qa_review.json, semantic_review.json, doc_fidelity.json); hence
# three separate Layer-2 producers with distinguishable names.
# ``verify-system.layer-2-llm`` (legacy from AG3-023) stays registered for
# backward compatibility with existing code (write_layer_artifacts in
# verify_system.artifacts).
# Producer names reference the cross-cutting SSOT
# ``core_types.qa_artifact_names`` (no second naming truth, AG3-034 R2-H); the
# legacy ``verify-system.layer-2-llm`` producer is not a QA-layer SSOT member and
# stays literal here.
#
# AG3-065 (remediation 3): Layer-2 prompt-audit and dialogue-audit records are
# persisted via the concept-owned ``prompt-runtime.materialization`` producer
# (registered in ``prompt_runtime.register``) — no separate verify-system
# PROMPT_AUDIT producers needed. Role-unique DB keys are achieved via
# role-specific stage ids (e.g. ``layer2-prompt-audit-qa-review``).
_VERIFY_PRODUCERS: Final[tuple[tuple[ArtifactClass, str, ProducerType], ...]] = (
    (ArtifactClass.QA, STRUCTURAL_PRODUCER, ProducerType.DETERMINISTIC),
    # Layer 2 -- AG3-026 §AK7: three FK-27 §27.7 artifacts
    (ArtifactClass.QA, QA_REVIEW_PRODUCER, ProducerType.LLM_REVIEWER),
    (ArtifactClass.QA, SEMANTIC_REVIEW_PRODUCER, ProducerType.LLM_REVIEWER),
    (ArtifactClass.QA, DOC_FIDELITY_PRODUCER, ProducerType.LLM_REVIEWER),
    (
        ArtifactClass.QA,
        CONTEXT_SUFFICIENCY_PRODUCER,
        ProducerType.DETERMINISTIC,
    ),
    # Layer 2 (legacy AG3-023, write_layer_artifacts/_decision path)
    (ArtifactClass.QA, "verify-system.layer-2-llm", ProducerType.LLM_REVIEWER),
    (ArtifactClass.QA, ADVERSARIAL_PRODUCER, ProducerType.LLM_REVIEWER),
    # SonarQube-Green-Gate (FK-33 §33.6 / §33.2.2, AG3-052): Layer-1
    # deterministic stage sequenced after Layer 3.
    (ArtifactClass.QA, SONARQUBE_GATE_PRODUCER, ProducerType.DETERMINISTIC),
    (ArtifactClass.QA, VERIFY_DECISION_PRODUCER, ProducerType.DETERMINISTIC),
    # AG3-069 (FK-05 §5.10/§5.14, FK-37 §37.1.3): stability_gate Verify-Stage
    # producer for integration_stabilization contract enforcement.
    (ArtifactClass.QA, STABILITY_GATE_PRODUCER, ProducerType.DETERMINISTIC),
    # Layer 3 adversarial sandbox (AG3-044, FK-48 §48.1): the spawned
    # adversarial worker writes sandbox tests under the protected
    # ``_temp/adversarial/{story_id}/{epoch}/`` path.
    (
        ArtifactClass.ADVERSARIAL_TEST_SANDBOX,
        ADVERSARIAL_SANDBOX_PRODUCER,
        ProducerType.WORKER,
    ),
)


def register_verify_producers(registry: ProducerRegistry) -> None:
    """Register the four QA-layer producers of the verify-system.

    Idempotent: a re-run with the same registry overwrites the
    entries with the same values (see AG3-022 §2.1.5.1
    init strategy). The call belongs in the composition root.

    Args:
        registry: Fresh or already-populated ``ProducerRegistry``.
            The function mutates the registry state.
    """
    for artifact_class, name, producer_type in _VERIFY_PRODUCERS:
        registry.register(artifact_class, name, producer_type)


__all__ = [
    "ADVERSARIAL_SANDBOX_PRODUCER",
    "ADVERSARIAL_SANDBOX_STAGE",
    "register_verify_producers",
]
