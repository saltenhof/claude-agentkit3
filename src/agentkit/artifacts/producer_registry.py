"""ProducerRegistry — Register der erlaubten Artefakt-Producer.

Registriert pro `ArtifactClass` die erlaubten Producer-Namen und deren
Typen. Beinhaltet das LLM-Status-Mapping nach FK-71 §71.2.

Init-Mechanik (AG3-022 §2.1.5.1):
- Der Konstruktor seeded alle `ArtifactClass`-Werte mit leerem
  Producer-Dict (Klassen-Seed; aktuell neun Werte inkl. ``prompt_audit``,
  AG3-015).
- Keine konkreten Producer sind in AG3-022 registriert; dies erfolgt
  in AG3-023 durch BC-spezifische Init-Hooks.
- `validate(envelope)` ist fail-closed: unbekannte Producer-Namen
  werfen `ProducerNotRegisteredError`.

LLM-Status-Mapping (FK-71 §71.2, Z. 145-161):
- ``"PASS"``              -> ``EnvelopeStatus.PASS``
- ``"PASS_WITH_CONCERNS"``-> ``EnvelopeStatus.WARN`` (nur LLM-Wire-String)
- ``"FAIL"``              -> ``EnvelopeStatus.FAIL``
- ``"ERROR"``             -> ``EnvelopeStatus.ERROR``
- ``"TIMEOUT"``           -> ``EnvelopeStatus.ERROR``
- Unbekannte Strings      -> ``LlmStatusMappingError`` (fail-closed)

`PASS_WITH_CONCERNS` ist ausschliesslich LLM-Check-Wire-String.
Er wird hier zu `EnvelopeStatus.WARN` gemappt — keine Wiedereinfuehrung
in PolicyVerdict oder Policy-Engine (AG3-021 §2.1.1.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from agentkit.artifacts.errors import (
    LlmStatusMappingError,
    ProducerNotRegisteredError,
    ProducerTypeMismatchError,
)
from agentkit.core_types import ArtifactClass, EnvelopeStatus

if TYPE_CHECKING:
    from agentkit.artifacts.envelope import ArtifactEnvelope
    from agentkit.artifacts.producer import ProducerType

# ---------------------------------------------------------------------------
# LLM-Status-Mapping als Klassen-Konstante (FK-71 §71.2 Z. 145-161)
# ---------------------------------------------------------------------------

_LLM_STATUS_MAPPING: Final[dict[str, EnvelopeStatus]] = {
    "PASS": EnvelopeStatus.PASS,
    "PASS_WITH_CONCERNS": EnvelopeStatus.WARN,
    "FAIL": EnvelopeStatus.FAIL,
    "ERROR": EnvelopeStatus.ERROR,
    "TIMEOUT": EnvelopeStatus.ERROR,
}


class ProducerRegistry:
    """Registry der erlaubten Artefakt-Producer pro ArtifactClass.

    Wird zur App-Initialisierung mit `register(...)` befuellt und danach
    read-only verwendet (kein Thread-Safety-Overhead noetig).

    Beispiel::

        registry = ProducerRegistry()
        registry.register(ArtifactClass.QA, "qa-structural", ProducerType.DETERMINISTIC)
        registry.validate(envelope)  # wirft ProducerNotRegisteredError wenn unbekannt
    """

    def __init__(self) -> None:
        # Klassen-Seed: alle ArtifactClass-Werte als Keys, jeweils mit leerem
        # Producer-Dict (AG3-022 §2.1.5.1). Iteriert ueber das Enum, bleibt
        # damit automatisch in Sync mit Enum-Erweiterungen (z. B. AG3-015
        # ``prompt_audit``).
        self._producers: dict[ArtifactClass, dict[str, ProducerType]] = {
            ac: {} for ac in ArtifactClass
        }

    def register(
        self,
        artifact_class: ArtifactClass,
        producer_name: str,
        producer_type: ProducerType,
    ) -> None:
        """Registriert einen Producer fuer eine ArtifactClass.

        Args:
            artifact_class: Artefaktklasse, fuer die dieser Producer gilt.
            producer_name: Kanonischer Producer-Name (z.B. ``qa-structural``).
            producer_type: Typ des Producers (WORKER / LLM_REVIEWER / DETERMINISTIC).
        """
        self._producers[artifact_class][producer_name] = producer_type

    def validate(self, envelope: ArtifactEnvelope) -> None:
        """Prueft, ob der Producer im Envelope registriert ist (fail-closed).

        Es werden BEIDE Aspekte gegen die Registry geprueft:
        1. Der Producer-Name muss fuer die gegebene ``ArtifactClass``
           registriert sein.
        2. Der ``ProducerType`` im Envelope muss mit dem registrierten
           Typ uebereinstimmen — sonst kann ein Producer-Name still
           seinen Typ drehen (Defense in depth gegen Drift).

        Args:
            envelope: Das zu pruefende ArtifactEnvelope.

        Raises:
            ProducerNotRegisteredError: Wenn der Producer-Name fuer die
                gegebene ArtifactClass nicht registriert ist.
            ProducerTypeMismatchError: Wenn der Producer-Name registriert
                ist, aber sein im Envelope angegebener Typ vom
                registrierten Typ abweicht.
        """
        allowed = self._producers[envelope.artifact_class]
        registered_type = allowed.get(envelope.producer.name)
        if registered_type is None:
            msg = (
                f"Producer '{envelope.producer.name}' ist fuer "
                f"ArtifactClass '{envelope.artifact_class}' nicht registriert. "
                f"Bekannte Producer: {set(allowed.keys()) or '{}'}"
            )
            raise ProducerNotRegisteredError(msg)
        if registered_type is not envelope.producer.type:
            msg = (
                f"Producer '{envelope.producer.name}' ist fuer ArtifactClass "
                f"'{envelope.artifact_class}' als '{registered_type.value}' "
                f"registriert, Envelope behauptet aber "
                f"'{envelope.producer.type.value}' (Typ-Drift)."
            )
            raise ProducerTypeMismatchError(msg)

    def map_llm_status_to_envelope_status(self, llm_status: str) -> EnvelopeStatus:
        """Mappt einen LLM-Check-Status auf `EnvelopeStatus` (FK-71 §71.2).

        Args:
            llm_status: LLM-Wire-String (z.B. ``"PASS_WITH_CONCERNS"``).

        Returns:
            Entsprechender `EnvelopeStatus`.

        Raises:
            LlmStatusMappingError: Bei unbekanntem LLM-Status (fail-closed).
        """
        try:
            return _LLM_STATUS_MAPPING[llm_status]
        except KeyError:
            known = list(_LLM_STATUS_MAPPING.keys())
            msg = f"Unbekannter LLM-Check-Status '{llm_status}'. Bekannte Werte: {known}"
            raise LlmStatusMappingError(msg) from None

    def known_producers(self, artifact_class: ArtifactClass) -> set[str]:
        """Gibt alle registrierten Producer-Namen fuer eine ArtifactClass zurueck.

        Args:
            artifact_class: Artefaktklasse, fuer die Producer abgefragt werden.

        Returns:
            Menge der registrierten Producer-Namen (leer wenn keine registriert).
        """
        return set(self._producers[artifact_class].keys())
