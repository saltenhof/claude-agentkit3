"""Secret redaction at the third-party service boundary."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

_AUTH_HEADER = re.compile(r"(?i)\b(?:basic|bearer)\s+[A-Za-z0-9+/=_\-.]+")
_AUTH_ASSIGNMENT = re.compile(
    r"(?i)(authorization|token|password|secret)\s*[:=]\s*[^\s,;]+"
)
_REDACTED = "[REDACTED]"


def redact_detail(value: object, secrets: Iterable[str] = ()) -> str:
    """Return a safe diagnostic string with credentials removed."""
    redacted = _AUTH_HEADER.sub(_REDACTED, str(value))
    for secret in sorted({item for item in secrets if item}, key=len, reverse=True):
        redacted = redacted.replace(secret, _REDACTED)
    return _AUTH_ASSIGNMENT.sub(lambda match: f"{match.group(1)}={_REDACTED}", redacted)


__all__ = ["redact_detail"]
