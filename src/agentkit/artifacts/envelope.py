"""ArtifactEnvelope — typed artifact-envelope model.

Distinction of the schema versions
-----------------------------------
- ``ENVELOPE_SCHEMA_VERSION = "3.0"`` — wire-schema version of this
  envelope format (FK-71 §71.2). This constant belongs to the
  ``agentkit.artifacts`` BC and is immutable to external
  storage-schema migrations.

- ``agentkit.state_backend.config.SCHEMA_VERSION`` (e.g. ``"3.3.0"``) —
  storage-schema version of the Postgres/SQLite persistence layer (FK-18
  §18.9a). The two versions are deliberately separate; a drift of the
  storage version does not change the envelope wire string.

Required fields and validators (FK-71 §71.2, AG3-022 §2.1.2):

- ``schema_version`` — ``Literal["3.0"]`` (no drift with state_backend)
- ``story_id`` — story display id, pattern ``^[A-Z][A-Z0-9]+-\\d+$``
- ``run_id`` — run correlation
- ``stage`` — stage id (string; StageRegistry binding in THEME-009)
- ``attempt`` — attempt counter (>= 1)
- ``producer`` — typed producer
- ``started_at`` / ``finished_at`` — UTC timestamps; ``finished_at >= started_at``
- ``status`` — ``EnvelopeStatus`` from ``core_types``
- ``artifact_class`` — ``ArtifactClass`` from ``core_types``
- ``payload`` — optional payload data
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentkit.artifacts.producer import Producer
from agentkit.core_types import ArtifactClass, EnvelopeStatus

#: Wire-schema version of the ArtifactEnvelope format (FK-71 §71.2).
#: Not to be confused with ``agentkit.state_backend.config.SCHEMA_VERSION``
#: (storage-schema version).
ENVELOPE_SCHEMA_VERSION: Final[str] = "3.0"

#: Story-Display-ID-Pattern (``{PREFIX}-{NNN}``, FK-02 §2.3.1). SINGLE SOURCE OF
#: TRUTH for the wire story-id format: the ``ArtifactEnvelope`` validator uses
#: it just like the change-frame artifact embedded in the envelope
#: (``agentkit.exploration.change_frame``), so a frame ``story_id`` and the
#: enclosing envelope ``story_id`` can never drift apart. Anchored with
#: ``\A``/``\Z`` (not ``^``/``$``) so the multiline-tolerant ``$``/``^`` does
#: NOT accept a trailing/embedded newline; all call sites match it with
#: ``fullmatch`` (fail-closed, ZERO DEBT): values carrying a trailing or
#: embedded newline, control characters or surrounding whitespace are rejected.
STORY_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Z][A-Z0-9]+-\d+\Z")
_STORY_ID_PATTERN: re.Pattern[str] = STORY_ID_PATTERN
#: Stage-id pattern: lowercase start, alphanumeric with ``-``/``_``
#: (kebab/snake), 1-64 characters. Binding to the StageRegistry happens in
#: THEME-009; until then at least this structural pattern applies.
_STAGE_ID_PATTERN: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ArtifactEnvelope(BaseModel):
    """Pydantic-v2 model for a typed artifact envelope.

    All instances are immutable (``frozen=True``) and allow no unknown
    fields (``extra="forbid"``).

    Attributes:
        schema_version: Wire-schema version; always ``"3.0"``.
        story_id: Story display id (e.g. ``AG3-042``).
        run_id: Run correlation id.
        stage: Stage id (free string; StageRegistry binding follows).
        attempt: Attempt counter, must be >= 1.
        producer: Typed producer record.
        started_at: Start time (UTC).
        finished_at: End time (UTC); must be >= ``started_at``.
        status: Envelope status from ``EnvelopeStatus``.
        artifact_class: Producer class from ``ArtifactClass``.
        payload: Optional payload data (any JSON-serializable data).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["3.0"]
    story_id: str
    run_id: str = Field(min_length=1)
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
        if _STORY_ID_PATTERN.fullmatch(v) is None:
            msg = (
                f"story_id '{v}' does not match pattern "
                r"'\A[A-Z][A-Z0-9]+-\d+\Z' (e.g. 'AG3-042')"
            )
            raise ValueError(msg)
        return v

    @field_validator("stage")
    @classmethod
    def _validate_stage(cls, v: str) -> str:
        if not _STAGE_ID_PATTERN.match(v):
            msg = (
                f"stage '{v}' does not match pattern "
                r"'^[a-z][a-z0-9_-]{0,63}$' "
                "(lowercase, kebab/snake, 1-64 characters)"
            )
            raise ValueError(msg)
        return v

    @field_validator("attempt")
    @classmethod
    def _validate_attempt(cls, v: int) -> int:
        if v < 1:
            msg = f"attempt must be >= 1, received: {v}"
            raise ValueError(msg)
        return v

    @field_validator("started_at", "finished_at")
    @classmethod
    def _validate_utc(cls, v: datetime) -> datetime:
        """Enforce tz-aware datetimes with a UTC offset.

        FK-71 §71.2 requires ISO-8601 timestamps with a timezone; AG3-022
        story §2.1.2 specifies UTC. Naive datetimes or non-UTC offsets are
        fail-closed forbidden so that audit and reproducibility checks do
        not fail on timezone drift.
        """
        if v.tzinfo is None:
            msg = (
                f"timestamp must be tz-aware, naive datetime not "
                f"allowed: {v!r}"
            )
            raise ValueError(msg)
        offset = v.utcoffset()
        if offset is None or offset != timedelta(0):
            msg = (
                f"timestamp must have UTC offset 0 (FK-71 §71.2), "
                f"received: {v!r} with offset {offset}"
            )
            raise ValueError(msg)
        return v

    @field_validator("payload")
    @classmethod
    def _validate_payload_json_serialisable(
        cls, v: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Enforce JSON-serializability of the payload.

        Pydantic v2 does not automatically reject dict contents with
        arbitrary Python objects. This validator check attempts a
        canonical JSON serialization and fails closed as soon as a value
        is not JSON-convertible — matching the wire requirement from
        AG3-022 §2.1.2 ("Pydantic-conformant serialization").
        """
        if v is None:
            return v
        try:
            json.dumps(v, sort_keys=True, default=None)
        except TypeError as exc:
            msg = f"payload is not JSON-serializable: {exc}. Only values that json.dumps can process are allowed."
            raise ValueError(msg) from exc
        return v

    @model_validator(mode="after")
    def _validate_finished_at(self) -> ArtifactEnvelope:
        if self.finished_at < self.started_at:
            msg = (
                f"finished_at ({self.finished_at}) must be >= started_at "
                f"({self.started_at})"
            )
            raise ValueError(msg)
        return self
