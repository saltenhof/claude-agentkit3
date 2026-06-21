"""Test fuer verify_system.register (AG3-023 §2.1.6.1 + AG3-026 Re-Review §AK7).

Registriert die QA-Layer-Producer und verifiziert Anzahl, Namen
und Typen gegen die in der Story verbindlich gesetzte Tabelle.

AG3-026 Re-Review (2026-05-19): Layer 2 zerfaellt in drei Producer
(qa-review, semantic-review, doc-fidelity) gemaess FK-27 §27.7;
``verify-system.layer-2-llm`` bleibt fuer Backward-Compatibility
mit dem AG3-023-Bestandspfad registriert.
"""

from __future__ import annotations

from pathlib import Path

from agentkit.backend.artifacts import ProducerRegistry, ProducerType
from agentkit.backend.core_types import ArtifactClass
from agentkit.backend.core_types.qa_artifact_names import (
    CONTEXT_SUFFICIENCY_PRODUCER,
    SONARQUBE_GATE_PRODUCER,
    STABILITY_GATE_PRODUCER,
)
from agentkit.backend.verify_system.register import register_verify_producers

#: Erwartete Producer-Liste nach AG3-026 Re-Review (+ AG3-069 IS stability-gate).
EXPECTED_QA_PRODUCERS: frozenset[str] = frozenset(
    {
        "verify-system.layer-1-structural",
        "verify-system.layer-2-qa-review",
        "verify-system.layer-2-semantic-review",
        "verify-system.layer-2-doc-fidelity",
        CONTEXT_SUFFICIENCY_PRODUCER,
        "verify-system.layer-2-llm",  # AG3-023-Bestand
        "verify-system.layer-3-adversarial",
        SONARQUBE_GATE_PRODUCER,
        "verify-system.layer-4-policy",
        STABILITY_GATE_PRODUCER,  # AG3-069: IS stability-gate producer
    }
)
_OLD_SONAR_LITERAL = "qa-" + "sonarqube-gate"


def test_register_verify_producers_adds_expected_qa_producers() -> None:
    registry = ProducerRegistry()
    register_verify_producers(registry)
    known = registry.known_producers(ArtifactClass.QA)
    assert known == set(EXPECTED_QA_PRODUCERS)


def test_register_verify_producers_is_idempotent() -> None:
    registry = ProducerRegistry()
    register_verify_producers(registry)
    register_verify_producers(registry)  # zweiter Aufruf darf nicht failen
    assert registry.known_producers(ArtifactClass.QA) == set(EXPECTED_QA_PRODUCERS)


def test_layer_1_and_4_are_deterministic() -> None:
    registry = ProducerRegistry()
    register_verify_producers(registry)
    from agentkit.backend.verify_system.register import _VERIFY_PRODUCERS

    types_by_name = {name: ptype for _, name, ptype in _VERIFY_PRODUCERS}
    assert types_by_name["verify-system.layer-1-structural"] is ProducerType.DETERMINISTIC
    assert types_by_name["verify-system.layer-2-llm"] is ProducerType.LLM_REVIEWER
    assert types_by_name["verify-system.layer-2-qa-review"] is ProducerType.LLM_REVIEWER
    assert types_by_name["verify-system.layer-2-semantic-review"] is ProducerType.LLM_REVIEWER
    assert types_by_name["verify-system.layer-2-doc-fidelity"] is ProducerType.LLM_REVIEWER
    assert types_by_name[CONTEXT_SUFFICIENCY_PRODUCER] is ProducerType.DETERMINISTIC
    assert types_by_name["verify-system.layer-3-adversarial"] is ProducerType.LLM_REVIEWER
    assert types_by_name["verify-system.layer-4-policy"] is ProducerType.DETERMINISTIC
    assert types_by_name[STABILITY_GATE_PRODUCER] is ProducerType.DETERMINISTIC


def test_sonarqube_producer_literal_only_lives_in_ssot() -> None:
    root = Path(__file__).parents[3]
    offenders = []
    for path in (root / "src").rglob("*.py"):
        if path.name == "qa_artifact_names.py":
            continue
        if _OLD_SONAR_LITERAL in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(root).as_posix())
    assert offenders == []
