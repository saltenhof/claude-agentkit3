"""Pure time utilities shared across all boundary and domain layers."""

from __future__ import annotations

from datetime import UTC, datetime


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""

    return datetime.now(tz=UTC).isoformat()
