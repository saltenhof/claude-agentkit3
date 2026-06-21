"""Contract-Tests fuer ArtifactEnvelope Wire-Schema (AG3-022 §2.1.7, §2.1.8).

Prueft:
- ``ENVELOPE_SCHEMA_VERSION == "3.0"``
- Alle neun ``ArtifactClass``-Werte sind im Registry-Default geseeded
  (AG3-015: inkl. ``prompt_audit``, FK-44 §44.6)
- LLM-Status-Mapping ist exakt das aus FK-71 §71.2

Diese Tests pinnen das Wire-Verhalten fest; jede Abweichung ist ein
Konzeptbruch und muss explizit behoben werden.
"""

from __future__ import annotations

from typing import Final

from agentkit.backend.artifacts import ENVELOPE_SCHEMA_VERSION, ProducerRegistry
from agentkit.backend.artifacts.producer_registry import _LLM_STATUS_MAPPING
from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus

# ---------------------------------------------------------------------------
# Erwartete Wire-Werte (autoritativ aus FK-71 §71.2 + AG3-022 §2.1.5)
# ---------------------------------------------------------------------------

_EXPECTED_LLM_MAPPING: Final[dict[str, EnvelopeStatus]] = {
    "PASS": EnvelopeStatus.PASS,
    "PASS_WITH_CONCERNS": EnvelopeStatus.WARN,
    "FAIL": EnvelopeStatus.FAIL,
    "ERROR": EnvelopeStatus.ERROR,
    "TIMEOUT": EnvelopeStatus.ERROR,
}

_EXPECTED_ARTIFACT_CLASSES: Final[frozenset[ArtifactClass]] = frozenset(ArtifactClass)


def test_envelope_schema_version_is_3_0() -> None:
    """AK9, AK12: ENVELOPE_SCHEMA_VERSION muss exakt '3.0' sein."""
    assert ENVELOPE_SCHEMA_VERSION == "3.0", (
        f"ENVELOPE_SCHEMA_VERSION drift: erwartet '3.0', erhalten '{ENVELOPE_SCHEMA_VERSION}'"
    )


def test_all_nine_artifact_classes_seeded() -> None:
    """AK12 + AG3-015: Alle neun ArtifactClass-Werte sind im Registry-Default als Keys vorhanden."""
    registry = ProducerRegistry()
    for ac in ArtifactClass:
        # known_producers darf nicht werfen; leer ist OK
        known = registry.known_producers(ac)
        assert isinstance(known, set), (
            f"known_producers({ac}) hat unerwarteten Typ: {type(known)}"
        )

    assert len(list(ArtifactClass)) == 9, (
        f"Erwartet 9 ArtifactClass-Werte, gefunden: {len(list(ArtifactClass))}"
    )


def test_llm_status_mapping_exact_fk71() -> None:
    """AK12: LLM-Status-Mapping ist exakt FK-71 §71.2 (Z. 145-161)."""
    assert dict(_LLM_STATUS_MAPPING) == _EXPECTED_LLM_MAPPING, (
        f"LLM-Status-Mapping drift.\n"
        f"Erwartet: {_EXPECTED_LLM_MAPPING}\n"
        f"Tatsaechlich: {dict(_LLM_STATUS_MAPPING)}"
    )


def test_llm_mapping_count() -> None:
    """AK12: Genau fuenf LLM-Status-Eintraege (PASS, PASS_WITH_CONCERNS, FAIL, ERROR, TIMEOUT)."""
    assert len(_LLM_STATUS_MAPPING) == 5, (
        f"Erwartet 5 LLM-Status-Eintraege, gefunden: {len(_LLM_STATUS_MAPPING)}"
    )


def test_registry_via_api_matches_mapping() -> None:
    """AK7, AK12: Registry-API liefert dieselben Mappings wie die Konstante."""
    registry = ProducerRegistry()
    for llm_status, expected_status in _EXPECTED_LLM_MAPPING.items():
        actual = registry.map_llm_status_to_envelope_status(llm_status)
        assert actual == expected_status, (
            f"map_llm_status_to_envelope_status('{llm_status}') "
            f"liefert '{actual}', erwartet '{expected_status}'"
        )


def test_pass_with_concerns_is_not_envelope_status() -> None:
    """AK12: PASS_WITH_CONCERNS ist kein EnvelopeStatus (nur LLM-Wire-String)."""
    import pytest

    with pytest.raises(ValueError):
        EnvelopeStatus("PASS_WITH_CONCERNS")


def test_envelope_schema_version_in_instance() -> None:
    """AK3: Jede ArtifactEnvelope-Instanz hat schema_version='3.0'."""
    from datetime import UTC, datetime

    from agentkit.backend.artifacts import ArtifactEnvelope
    from agentkit.backend.artifacts.producer import Producer, ProducerId, ProducerType

    start = datetime.now(tz=UTC)
    env = ArtifactEnvelope(
        schema_version="3.0",
        story_id="AG3-022",
        run_id="r1",
        stage="impl",
        attempt=1,
        producer=Producer(
            type=ProducerType.DETERMINISTIC,
            name="contract-test-producer",
            id=ProducerId("ct-001"),
        ),
        started_at=start,
        finished_at=start,
        status=EnvelopeStatus.PASS,
        artifact_class=ArtifactClass.QA,
    )
    assert env.schema_version == "3.0"
    assert env.schema_version == ENVELOPE_SCHEMA_VERSION
