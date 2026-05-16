"""Producer-Typen fuer das Artefakt-BC (agentkit.artifacts).

Definitionen:
- `ProducerType` — StrEnum mit WORKER / LLM_REVIEWER / DETERMINISTIC
- `ProducerId` — NewType fuer typsichere Instanz-IDs
- `Producer` — Pydantic-Modell mit Pflichtfeldern

Quelle: bc-cut-decisions.md §BC 8, FK-71 §71.2.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType

from pydantic import BaseModel, ConfigDict


class ProducerType(StrEnum):
    """Erzeuger-Kategorie eines Artefakt-Producers.

    Attributes:
        WORKER: Worker-Agent (Implementierung, Entwurf, Handover).
        LLM_REVIEWER: LLM-basierter Gutachter (QA-Semantik, Guard-Review).
        DETERMINISTIC: Deterministischer Pruefschritt (Structural, Policy).
    """

    WORKER = "WORKER"
    LLM_REVIEWER = "LLM_REVIEWER"
    DETERMINISTIC = "DETERMINISTIC"


#: Typsichere Instanz-ID eines Producers (z.B. "worker-impl-run-42").
ProducerId = NewType("ProducerId", str)


class Producer(BaseModel):
    """Getypter Producer eines Artefakts (bc-cut-decisions.md §BC 8).

    Attributes:
        type: Kategorie des Producers (WORKER / LLM_REVIEWER / DETERMINISTIC).
        name: Kanonischer Name (z.B. ``qa-semantic-reviewer``).
        id: Eindeutige Instanz-ID dieser Producer-Instanz.
        version: Optionale Tool- oder Bundle-Version.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ProducerType
    name: str
    id: ProducerId
    version: str | None = None
