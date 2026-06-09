"""Schema-bound sub-agent back-channel filter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class BackChannelStatus(StrEnum):
    """Allowed sub-agent back-channel statuses."""

    OK = "ok"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class BackChannelMessage:
    """Typed allow-schema for sub-agent output to the orchestrator."""

    status: BackChannelStatus | None = None
    error_class: str | None = None
    next_step: str | None = None
    artifact_refs: tuple[str, ...] = ()
    reason: Mapping[str, str] | None = None


_MAX_SHORT = 120
_MAX_REFS = 20
_MAX_REASON_KEYS = 5
_CONTENT_KEYS = frozenset(
    {
        "diff",
        "raw_diff",
        "content",
        "contents",
        "context_json",
        "are_bundle_json",
        "prompt",
        "prompts",
        "bundle",
        "bundles",
        "artifact_content",
        "full_artifact",
    }
)


def filter_back_channel(payload: Mapping[str, object]) -> BackChannelMessage:
    """Return the bounded allow-schema projection of ``payload``.

    Unknown fields and known content-bearing fields are default-denied by being
    omitted from the returned typed message.
    """
    status = _status(payload.get("status"))
    error_class = _short(payload.get("error_class"))
    next_step = _short(payload.get("next_step"))
    artifact_refs = _artifact_refs(payload.get("artifact_refs"))
    reason = _reason(payload.get("reason"))
    return BackChannelMessage(
        status=status,
        error_class=error_class,
        next_step=next_step,
        artifact_refs=artifact_refs,
        reason=reason,
    )


def rejected_content_keys(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Return content-bearing keys rejected by the filter."""
    return tuple(key for key in payload if key in _CONTENT_KEYS)


def _status(value: object) -> BackChannelStatus | None:
    if not isinstance(value, str):
        return None
    try:
        return BackChannelStatus(value)
    except ValueError:
        return None


def _short(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > _MAX_SHORT or "\n" in stripped:
        return None
    return stripped


def _artifact_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    refs: list[str] = []
    for item in value[:_MAX_REFS]:
        ref = _short(item)
        if ref is not None and not _looks_like_content(ref):
            refs.append(ref)
    return tuple(refs)


def _reason(value: object) -> Mapping[str, str] | None:
    if not isinstance(value, dict):
        return None
    clean: dict[str, str] = {}
    for key, raw in list(value.items())[:_MAX_REASON_KEYS]:
        key_str = _short(key)
        value_str = _short(raw)
        if key_str is not None and value_str is not None:
            clean[key_str] = value_str
    return clean or None


def _looks_like_content(value: str) -> bool:
    return value.startswith(("diff --git", "{", "[")) or "\n" in value


__all__ = [
    "BackChannelMessage",
    "BackChannelStatus",
    "filter_back_channel",
    "rejected_content_keys",
]
