"""ArtifactEnvelope — typisiertes Artefakt-Envelope-Modell.

Abgrenzung der Schema-Versionen
--------------------------------
- ``ENVELOPE_SCHEMA_VERSION = "3.0"`` — Wire-Schema-Version dieses
  Envelope-Formats (FK-71 §71.2). Diese Konstante gehoert dem
  ``agentkit.artifacts``-BC und ist unveraenderlich durch externe
  Storage-Schema-Migrationen.

- ``agentkit.state_backend.config.SCHEMA_VERSION`` (z.B. ``"3.3.0"``) —
  Storage-Schema-Version der Postgres-/SQLite-Persistenzschicht (FK-18
  §18.9a). Die beiden Versionen sind bewusst getrennt; ein Drift der
  Storage-Version aendert nicht den Envelope-Wire-String.

Pflichtfelder und Validatoren (FK-71 §71.2, AG3-022 §2.1.2):

- ``schema_version`` — ``Literal["3.0"]`` (kein Drift mit state_backend)
- ``story_id`` — Story-Display-ID, Pattern ``^[A-Z][A-Z0-9]+-\\d+$``
- ``run_id`` — Run-Korrelation
- ``stage`` — Stage-ID (String; StageRegistry-Bindung in THEME-009)
- ``attempt`` — Versuchszaehler (>= 1)
- ``producer`` — typisierter Producer
- ``started_at`` / ``finished_at`` — UTC-Timestamps; ``finished_at >= started_at``
- ``status`` — ``EnvelopeStatus`` aus ``core_types``
- ``artifact_class`` — ``ArtifactClass`` aus ``core_types``
- ``payload`` — optionale Nutzdaten
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from agentkit.artifacts.producer import Producer
from agentkit.core_types import ArtifactClass, EnvelopeStatus

#: Wire-Schema-Version des ArtifactEnvelope-Formats (FK-71 §71.2).
#: Nicht verwechseln mit ``agentkit.state_backend.config.SCHEMA_VERSION``
#: (Storage-Schema-Version).
ENVELOPE_SCHEMA_VERSION: Final[str] = "3.0"

_STORY_ID_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


class ArtifactEnvelope(BaseModel):
    """Pydantic-v2-Modell fuer ein typisiertes Artefakt-Envelope.

    Alle Instanzen sind immutabel (``frozen=True``) und lassen keine
    unbekannten Felder zu (``extra="forbid"``).

    Attributes:
        schema_version: Wire-Schema-Version; immer ``"3.0"``.
        story_id: Story-Display-ID (z.B. ``AG3-042``).
        run_id: Run-Korrelations-ID.
        stage: Stage-ID (freier String; StageRegistry-Bindung folgt).
        attempt: Versuchszaehler, muss >= 1 sein.
        producer: Getypter Producer-Record.
        started_at: Startzeitpunkt (UTC).
        finished_at: Endzeitpunkt (UTC); muss >= ``started_at`` sein.
        status: Envelope-Status aus ``EnvelopeStatus``.
        artifact_class: Erzeugerklasse aus ``ArtifactClass``.
        payload: Optionale Nutzdaten (beliebige JSON-serialisierbare Daten).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["3.0"]
    story_id: str
    run_id: str
    stage: str
    attempt: int
    producer: Producer
    started_at: datetime
    finished_at: datetime
    status: EnvelopeStatus
    artifact_class: ArtifactClass
    payload: dict[str, Any] | None = None

    @field_validator("story_id")
    @classmethod
    def _validate_story_id(cls, v: str) -> str:
        if not _STORY_ID_PATTERN.match(v):
            msg = (
                f"story_id '{v}' entspricht nicht dem Pattern "
                r"'^[A-Z][A-Z0-9]+-\d+$' (z.B. 'AG3-042')"
            )
            raise ValueError(msg)
        return v

    @field_validator("attempt")
    @classmethod
    def _validate_attempt(cls, v: int) -> int:
        if v < 1:
            msg = f"attempt muss >= 1 sein, erhalten: {v}"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def _validate_finished_at(self) -> ArtifactEnvelope:
        if self.finished_at < self.started_at:
            msg = (
                f"finished_at ({self.finished_at}) muss >= started_at "
                f"({self.started_at}) sein"
            )
            raise ValueError(msg)
        return self
