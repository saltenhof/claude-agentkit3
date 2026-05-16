"""Test fuer verify_system.register (AG3-023 §2.1.6.1).

Registriert die vier QA-Layer-Producer und verifiziert Anzahl, Namen
und Typen gegen die in der Story verbindlich gesetzte Tabelle.
"""

from __future__ import annotations

from agentkit.artifacts import ProducerRegistry, ProducerType
from agentkit.core_types import ArtifactClass
from agentkit.verify_system.register import register_verify_producers


def test_register_verify_producers_adds_four_qa_producers() -> None:
    registry = ProducerRegistry()
    register_verify_producers(registry)
    known = registry.known_producers(ArtifactClass.QA)
    assert known == {
        "verify-system.layer-1-structural",
        "verify-system.layer-2-llm",
        "verify-system.layer-3-adversarial",
        "verify-system.layer-4-policy",
    }


def test_register_verify_producers_is_idempotent() -> None:
    registry = ProducerRegistry()
    register_verify_producers(registry)
    register_verify_producers(registry)  # zweiter Aufruf darf nicht failen
    assert len(registry.known_producers(ArtifactClass.QA)) == 4


def test_layer_1_and_4_are_deterministic() -> None:
    registry = ProducerRegistry()
    register_verify_producers(registry)
    # Hole interne Map ueber den Validator-Pfad: registrierten Typ
    # spiegeln wir ueber map_llm_status_to_envelope_status nicht direkt;
    # stattdessen pruefen wir per validate-Flow ueber ein Test-Envelope.
    # Hier reicht uns: register hat genau die richtigen Typen verwendet
    # (semantischer Beleg via Konstanten-Tabelle in register.py).
    from agentkit.verify_system.register import _VERIFY_PRODUCERS

    types_by_name = {name: ptype for _, name, ptype in _VERIFY_PRODUCERS}
    assert types_by_name["verify-system.layer-1-structural"] is ProducerType.DETERMINISTIC
    assert types_by_name["verify-system.layer-2-llm"] is ProducerType.LLM_REVIEWER
    assert types_by_name["verify-system.layer-3-adversarial"] is ProducerType.LLM_REVIEWER
    assert types_by_name["verify-system.layer-4-policy"] is ProducerType.DETERMINISTIC
