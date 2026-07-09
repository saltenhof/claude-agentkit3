"""Shared helpers for persistence row mappers."""

from __future__ import annotations

import logging
from datetime import datetime

from agentkit.backend.state_backend.persistence_json_codec import (
    cast_json_record as cast_json_record,
)
from agentkit.backend.state_backend.persistence_json_codec import (
    dump_json as dump_json,
)
from agentkit.backend.state_backend.persistence_json_codec import (
    load_json as load_json,
)

_log = logging.getLogger(__name__)

_OptionalString = str | None



def _optional_int(value: object) -> int | None:
    """Coerce a nullable integer column value to ``int | None``."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(str(value))



def _optional_iso_datetime(value: object) -> datetime | None:
    """Parse a nullable ISO-8601 TEXT instant column to ``datetime | None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))



def _parse_aware_claimed_at(claimed_at_raw: object) -> datetime | None:
    """Normalize a stored ``claimed_at`` to an aware-UTC datetime (AG3-054 #4).

    ``claimed_at`` is a pure AUDIT instant (AG3-139: no code path compares it
    against a wall clock to decide a claim has "expired" -- ownership never ends
    by wall clock, FK-91 §91.1a Rule 16). It IS still consulted verbatim by the
    ownership-scoped finalize/release CAS (WARNING-4) and as the ``since`` bound
    for the AG3-138 admin-abort partial-write probe, both of which require an
    aware UTC value. A NAIVE (tz-unaware) ``claimed_at`` is therefore normalized
    to aware UTC at THIS mapper boundary: a value already aware is converted to
    UTC; a NAIVE value is assumed UTC (the productive writer always stamps aware
    UTC via ``isoformat``, so a naive value is a legacy/foreign write and the
    only safe, fail-closed reading is UTC).

    A ``None`` value (a terminal row, or a claim with no audit instant) maps to
    ``None``. An UNPARSEABLE / malformed value also maps to ``None`` (fail-closed:
    no audit instant) instead of crashing.

    Args:
        claimed_at_raw: The raw ``claimed_at`` column value (TEXT / ``datetime`` /
            ``None``).

    Returns:
        The aware-UTC claim instant, or ``None`` when absent or malformed.
    """
    from datetime import UTC, datetime

    if claimed_at_raw is None:
        return None
    parsed: datetime
    if isinstance(claimed_at_raw, datetime):
        parsed = claimed_at_raw
    else:
        try:
            parsed = datetime.fromisoformat(str(claimed_at_raw))
        except ValueError:
            # Malformed claim instant: fail-closed to "no audit instant" rather
            # than crashing.
            _log.warning(
                "control_plane_operations.claimed_at is unparseable (%r); "
                "treating it as absent (no audit instant, AG3-054 #4)",
                claimed_at_raw,
            )
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)



def _optional_str(value: object) -> str | None:
    """Coerce a nullable TEXT column value to ``str | None``."""
    if value is None:
        return None
    return str(value)
