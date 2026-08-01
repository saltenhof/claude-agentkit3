"""Strict field readers and canonical timestamp rendering for stored records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def positive_int(raw: object, *, field_name: str) -> int:
    """Read a positive integer strictly, without bool-as-int coercion."""
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise VectorDbUnavailableError(f"persisted record has a non-numeric {field_name!r} ({raw!r}); fail-closed (N08/N16).")
    try:
        value = int(raw)
    except ValueError as exc:
        raise VectorDbUnavailableError(
            f"persisted record has a non-numeric {field_name!r} ({raw!r}); fail-closed (N08/N16)."
        ) from exc
    if value < 1:
        raise VectorDbUnavailableError(f"persisted record has a non-positive {field_name!r} ({value}); fail-closed (N08/N16).")
    return value


def required_strings(props: Mapping[str, object], names: Sequence[str], *, context: str) -> dict[str, str]:
    """Read mandatory string fields strictly, without ``str()`` coercion."""
    values: dict[str, str] = {}
    for field_name in names:
        raw = props.get(field_name)
        if not isinstance(raw, str) or not raw:
            raise VectorDbUnavailableError(
                f"persisted {context} has a missing/non-string {field_name!r} ({raw!r}); fail-closed (N08)."
            )
        values[field_name] = raw
    return values


def utc_clock() -> datetime:
    """Return the current UTC instant."""
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    """Render a UTC instant as an ISO-8601 string with a ``Z`` suffix."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["iso", "positive_int", "required_strings", "utc_clock"]
