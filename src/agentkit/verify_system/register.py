"""Init-Hook: Registriert die vier QA-Layer-Producer des verify-systems.

Wird vom Composition-Root (App-Bootstrap) **einmalig** aufgerufen,
bevor irgendein Pipeline-Run startet. Konsistent mit dem AK3-Schnitt
"kein operativer Code in ``__init__.py``" — die Registrierung lebt in
diesem dedizierten Init-Hook-Modul, nicht im Paket-Init.

Quellen:
- ``concept/_meta/bc-cut-decisions.md §BC 8 artifacts`` — Z. 715-770
  (Producer-Registry; AG3-022 §2.1.5.1 Init-Strategie: leere Registry
  + Init-Hooks pro BC)
- ``stories/AG3-023-artifact-manager-migration/story.md §2.1.6.1`` —
  Variantenwahl: dedizierte ``register.py``
- Konzeptzuordnung der vier Layer:
    - ``FK-27 §27.4`` — Layer 1 Structural (deterministisch)
    - ``FK-27 §27.5`` — Layer 2 LLM-Reviews
    - ``FK-27 §27.6`` — Layer 3 Adversarial
    - ``FK-27 §27.7`` — Layer 4 Policy (deterministisch)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentkit.artifacts import ProducerType
from agentkit.core_types import ArtifactClass

if TYPE_CHECKING:
    from agentkit.artifacts import ProducerRegistry

# (ArtifactClass, Producer-Name, ProducerType) — Single Source of Truth
# fuer die verify-system-Producer. Eine Aenderung dieser Liste ist
# eine Konzept-Aenderung und muss in FK-27 nachgezogen werden.
#
# AG3-026 §AK7 verlangt fuer Layer 2 drei separate QA-Artefakte
# (qa_review.json, semantic_review.json, doc_fidelity.json); deshalb
# drei separate Layer-2-Producer mit unterscheidbaren Namen.
# ``verify-system.layer-2-llm`` (Bestand aus AG3-023) bleibt fuer
# Backward-Compatibility mit Bestandscode (write_layer_artifacts in
# verify_system.artifacts) registriert.
_VERIFY_PRODUCERS: Final[tuple[tuple[ArtifactClass, str, ProducerType], ...]] = (
    (ArtifactClass.QA, "verify-system.layer-1-structural", ProducerType.DETERMINISTIC),
    # Layer 2 -- AG3-026 §AK7: drei FK-27 §27.7-Artefakte
    (ArtifactClass.QA, "verify-system.layer-2-qa-review", ProducerType.LLM_REVIEWER),
    (ArtifactClass.QA, "verify-system.layer-2-semantic-review", ProducerType.LLM_REVIEWER),
    (ArtifactClass.QA, "verify-system.layer-2-doc-fidelity", ProducerType.LLM_REVIEWER),
    # Layer 2 (Bestand AG3-023, write_layer_artifacts/_decision-Pfad)
    (ArtifactClass.QA, "verify-system.layer-2-llm", ProducerType.LLM_REVIEWER),
    (ArtifactClass.QA, "verify-system.layer-3-adversarial", ProducerType.LLM_REVIEWER),
    # SonarQube-Green-Gate (FK-33 §33.6 / §33.2.2, AG3-052): Layer-1
    # deterministic stage sequenced after Layer 3, producer ``qa-sonarqube-gate``.
    (ArtifactClass.QA, "qa-sonarqube-gate", ProducerType.DETERMINISTIC),
    (ArtifactClass.QA, "verify-system.layer-4-policy", ProducerType.DETERMINISTIC),
)


def register_verify_producers(registry: ProducerRegistry) -> None:
    """Registriert die vier QA-Layer-Producer des verify-systems.

    Idempotent: Re-Run mit derselben Registry ueberschreibt die
    Eintraege mit denselben Werten (siehe AG3-022 §2.1.5.1
    Init-Strategie). Der Aufruf gehoert in den Composition-Root.

    Args:
        registry: Frische oder bereits befuellte ``ProducerRegistry``.
            Die Funktion mutiert den Registry-Zustand.
    """
    for artifact_class, name, producer_type in _VERIFY_PRODUCERS:
        registry.register(artifact_class, name, producer_type)


__all__ = ["register_verify_producers"]
