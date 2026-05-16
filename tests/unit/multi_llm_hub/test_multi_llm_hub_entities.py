from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.multi_llm_hub.entities import (
    HubBackendMetric,
    HubHealth,
    HubHolder,
    HubSession,
)


def test_hub_session_accepts_known_backend() -> None:
    session = HubSession(
        session_id="s-1",
        owner="owner",
        description="Test session",
        llms=["chatgpt", "kimi"],
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_activity=datetime(2026, 1, 1, tzinfo=UTC),
        resumable=False,
    )

    assert session.llms == ["chatgpt", "kimi"]


def test_hub_session_rejects_unknown_backend() -> None:
    with pytest.raises(ValidationError):
        HubSession(
            session_id="s-1",
            owner="owner",
            description="Test session",
            llms=["unknown"],  # intentionally invalid
            status="active",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            last_activity=datetime(2026, 1, 1, tzinfo=UTC),
            resumable=False,
        )


def test_backend_metric_rejects_negative_slots() -> None:
    with pytest.raises(ValidationError):
        HubBackendMetric(
            name="chatgpt",
            label="ChatGPT",
            status="healthy",
            slots_total=-1,
            slots_in_use=0,
            sends=0,
            responses=0,
            errors=0,
            avg_response_ms=None,
            holders=[],
        )


def test_hub_health_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        HubHealth.model_validate(
            {
                "status": "ok",
                "version": "0.3.0",
                "backends": {"chatgpt": "ok"},
                "persistence": "ok",
                "uptime_ms": 100,
                "extra": "forbidden",
            },
        )


def test_holder_model_is_strict() -> None:
    holder = HubHolder(session_id="s-1", owner="owner", description="Held session")

    assert holder.session_id == "s-1"
