"""Read-only aggregation of Claude transcript hook failures."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_NON_BLOCKING_PREFIX = "Failed with non-blocking status code:"


class TranscriptFormatError(RuntimeError):
    """Raised when a transcript cannot be interpreted without guessing."""


@dataclass(frozen=True)
class HookErrorText:
    """One normalized error text and its occurrence count."""

    count: int
    text: str


@dataclass(frozen=True)
class HookErrorGroup:
    """All non-blocking failures emitted by one exact hook command."""

    hook: str
    total: int
    errors: tuple[HookErrorText, ...]


@dataclass(frozen=True)
class HookErrorReport:
    """Deterministic hook-failure report for one transcript."""

    transcript: Path
    total_errors: int
    hooks: tuple[HookErrorGroup, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable report with stable field names."""
        return {
            "transcript": str(self.transcript),
            "total_errors": self.total_errors,
            "hooks": [
                {
                    "hook": group.hook,
                    "total": group.total,
                    "errors": [
                        {"count": error.count, "text": error.text}
                        for error in group.errors
                    ],
                }
                for group in self.hooks
            ],
        }


def aggregate_hook_errors(
    transcript: Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> HookErrorReport:
    """Group ``hook_non_blocking_error`` attachments by command and error text.

    Args:
        transcript: Claude Code JSONL transcript.
        since: Optional inclusive lower timestamp bound.
        until: Optional inclusive upper timestamp bound.

    Returns:
        A stable report sorted by hook command and then error frequency/text.

    Raises:
        TranscriptFormatError: On unreadable JSONL or incomplete matching
            attachment records.
    """
    if since is not None and until is not None and since > until:
        raise TranscriptFormatError("since must not be later than until")
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total = 0
    try:
        lines = transcript.open(encoding="utf-8")
    except OSError as exc:
        raise TranscriptFormatError(f"Cannot open transcript {transcript}: {exc}") from exc
    with lines:
        for line_number, line in enumerate(lines, start=1):
            record = _parse_record(line, transcript=transcript, line_number=line_number)
            error = _extract_hook_error(
                record,
                since=since,
                until=until,
                transcript=transcript,
                line_number=line_number,
            )
            if error is None:
                continue
            hook, error_text = error
            grouped[hook][error_text] += 1
            total += 1
    hooks = tuple(
        HookErrorGroup(
            hook=hook,
            total=sum(errors.values()),
            errors=tuple(
                HookErrorText(count=count, text=text)
                for text, count in sorted(
                    errors.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
        )
        for hook, errors in sorted(grouped.items())
    )
    return HookErrorReport(
        transcript=transcript.resolve(),
        total_errors=total,
        hooks=hooks,
    )


def _extract_hook_error(
    record: dict[str, object],
    *,
    since: datetime | None,
    until: datetime | None,
    transcript: Path,
    line_number: int,
) -> tuple[str, str] | None:
    """Validate and return one in-window hook error, if the record is one."""
    if record.get("type") != "attachment":
        return None
    attachment = record.get("attachment")
    if not isinstance(attachment, dict):
        raise TranscriptFormatError(
            f"{transcript}:{line_number}: attachment must be an object"
        )
    attachment_type = attachment.get("type")
    if not isinstance(attachment_type, str) or not attachment_type.strip():
        raise TranscriptFormatError(
            f"{transcript}:{line_number}: attachment has no non-empty type"
        )
    if attachment_type != "hook_non_blocking_error":
        return None
    if not _within_bounds(
        record,
        since=since,
        until=until,
        transcript=transcript,
        line_number=line_number,
    ):
        return None
    hook = attachment.get("command")
    if not isinstance(hook, str) or not hook.strip():
        raise TranscriptFormatError(
            f"{transcript}:{line_number}: hook error has no non-empty command"
        )
    return hook, _error_text(attachment)


def parse_timestamp_bound(value: str) -> datetime:
    """Parse an RFC 3339/ISO-8601 CLI timestamp with an explicit offset."""
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TranscriptFormatError(f"Invalid timestamp {value!r}: {exc}") from exc
    if parsed.tzinfo is None:
        raise TranscriptFormatError(
            f"Timestamp {value!r} must include a UTC offset or trailing Z."
        )
    return parsed


def _parse_record(line: str, *, transcript: Path, line_number: int) -> dict[str, object]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise TranscriptFormatError(
            f"{transcript}:{line_number}: invalid JSON: {exc.msg}"
        ) from exc
    if not isinstance(record, dict):
        raise TranscriptFormatError(
            f"{transcript}:{line_number}: transcript record must be an object"
        )
    return record


def _within_bounds(
    record: dict[str, object],
    *,
    since: datetime | None,
    until: datetime | None,
    transcript: Path,
    line_number: int,
) -> bool:
    raw_timestamp = record.get("timestamp")
    if not isinstance(raw_timestamp, str):
        raise TranscriptFormatError(
            f"{transcript}:{line_number}: hook error has no timestamp"
        )
    timestamp = parse_timestamp_bound(raw_timestamp)
    return (since is None or timestamp >= since) and (until is None or timestamp <= until)


def _error_text(attachment: dict[str, object]) -> str:
    raw = attachment.get("stderr")
    if not isinstance(raw, str) or not raw.strip():
        raw = attachment.get("stdout")
    if not isinstance(raw, str) or not raw.strip():
        raise TranscriptFormatError("hook error attachment has no error text")
    normalized = _ANSI_ESCAPE.sub("", raw).replace("\r\n", "\n").replace("\r", "\n").strip()
    if normalized.startswith(_NON_BLOCKING_PREFIX):
        normalized = normalized[len(_NON_BLOCKING_PREFIX) :].lstrip()
    if not normalized:
        raise TranscriptFormatError(
            "hook error attachment has no error text after normalization"
        )
    return normalized


__all__ = [
    "HookErrorGroup",
    "HookErrorReport",
    "HookErrorText",
    "TranscriptFormatError",
    "aggregate_hook_errors",
    "parse_timestamp_bound",
]
