"""Artifact envelope row mappers shared by state-backend repositories."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from agentkit.backend.artifacts.envelope import ArtifactEnvelope
from agentkit.backend.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus


def sqlite_artifact_envelope_row_to_record(row: dict[str, Any]) -> ArtifactEnvelope:
    """Deserialize a SQLite artifact_envelopes row."""
    payload: dict[str, Any] | None = None
    raw_payload = row.get("payload_json")
    if raw_payload is not None:
        payload = json.loads(str(raw_payload))

    started_at = datetime.fromisoformat(str(row["started_at"]))
    finished_at = datetime.fromisoformat(str(row["finished_at"]))
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=UTC)

    return ArtifactEnvelope(
        schema_version="3.0",
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        stage=str(row["stage"]),
        attempt=int(row["attempt"]),
        producer=Producer(
            type=ProducerType(str(row["producer_type"])),
            name=str(row["producer_name"]),
            id=ProducerId(str(row["producer_id"])),
            version=str(row["producer_version"])
            if row.get("producer_version") is not None
            else None,
        ),
        started_at=started_at,
        finished_at=finished_at,
        status=EnvelopeStatus(str(row["status"])),
        artifact_class=ArtifactClass(str(row["artifact_class"])),
        payload=payload,
    )


def postgres_artifact_envelope_row_to_record(row: dict[str, Any]) -> ArtifactEnvelope:
    """Deserialize a PostgreSQL artifact_envelopes row."""
    payload: dict[str, Any] | None = None
    raw_payload = row.get("payload_json")
    if raw_payload is not None:
        payload = raw_payload if isinstance(raw_payload, dict) else json.loads(str(raw_payload))

    started_at = row["started_at"]
    finished_at = row["finished_at"]
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at)
    if isinstance(finished_at, str):
        finished_at = datetime.fromisoformat(finished_at)

    started_at = (
        started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at.astimezone(UTC)
    )
    finished_at = (
        finished_at.replace(tzinfo=UTC) if finished_at.tzinfo is None else finished_at.astimezone(UTC)
    )

    return ArtifactEnvelope(
        schema_version="3.0",
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        stage=str(row["stage"]),
        attempt=int(row["attempt"]),
        producer=Producer(
            type=ProducerType(str(row["producer_type"])),
            name=str(row["producer_name"]),
            id=ProducerId(str(row["producer_id"])),
            version=str(row["producer_version"])
            if row.get("producer_version") is not None
            else None,
        ),
        started_at=started_at,
        finished_at=finished_at,
        status=EnvelopeStatus(str(row["status"])),
        artifact_class=ArtifactClass(str(row["artifact_class"])),
        payload=payload,
    )


__all__ = [
    "postgres_artifact_envelope_row_to_record",
    "sqlite_artifact_envelope_row_to_record",
]
