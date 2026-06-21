"""Regression test for ``_pg_row_to_envelope`` timezone normalization.

A Postgres server running in a non-UTC session timezone (e.g. Europe/Berlin)
returns TIMESTAMPTZ values as tz-aware datetimes with a non-zero offset. FK-71
§71.2 requires UTC offset 0, so the deserializer must convert such values to
UTC. The previous implementation only handled naive datetimes, so reads against
a localized Postgres raised ``ValidationError`` (offset 2:00:00). This was
masked locally because the ephemeral test container ran in UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from agentkit.backend.artifacts.producer import ProducerType
from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus
from agentkit.backend.state_backend.store.artifact_repository import _pg_row_to_envelope


def _row(started_at: datetime, finished_at: datetime) -> dict[str, object]:
    return {
        "story_id": "AG3-023",
        "run_id": "run-tz-1",
        "stage": "impl",
        "attempt": 1,
        "producer_type": ProducerType.DETERMINISTIC.value,
        "producer_name": "verify-system.layer-1-structural",
        "producer_id": "inst-tz-1",
        "producer_version": None,
        "status": EnvelopeStatus.PASS.value,
        "artifact_class": ArtifactClass.QA.value,
        "payload_json": None,
        "started_at": started_at,
        "finished_at": finished_at,
    }


def test_pg_row_to_envelope_normalizes_berlin_tz_to_utc() -> None:
    """tz-aware (Europe/Berlin, +02:00) timestamps must become UTC offset 0."""
    berlin = datetime(2026, 5, 31, 19, 37, 36, tzinfo=ZoneInfo("Europe/Berlin"))

    env = _pg_row_to_envelope(_row(berlin, berlin))

    assert env.started_at.utcoffset() == timedelta(0)
    assert env.finished_at.utcoffset() == timedelta(0)
    # The instant is preserved (19:37 Berlin == 17:37 UTC).
    assert env.started_at == berlin
    assert env.started_at.hour == 17


def test_pg_row_to_envelope_treats_naive_as_utc() -> None:
    """Naive datetimes (no tzinfo) are interpreted as already-UTC."""
    naive = datetime(2026, 5, 31, 17, 37, 36)  # noqa: DTZ001 - intentional naive input

    env = _pg_row_to_envelope(_row(naive, naive))

    assert env.started_at == datetime(2026, 5, 31, 17, 37, 36, tzinfo=UTC)
    assert env.finished_at.utcoffset() == timedelta(0)
