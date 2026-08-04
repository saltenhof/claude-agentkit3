"""CLI surface for read-only transcript hook-failure visibility."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.harness_client.harness_adapters.hook_error_report import (
    TranscriptFormatError,
    aggregate_hook_errors,
    parse_timestamp_bound,
)

if TYPE_CHECKING:
    import argparse


def add_hook_error_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the ``hook-errors`` read-only diagnostic verb."""
    parser = subparsers.add_parser(
        "hook-errors",
        help="Aggregate hook_non_blocking_error attachments from a Claude transcript.",
    )
    parser.add_argument("transcript", help="Path to one Claude Code JSONL transcript.")
    parser.add_argument(
        "--since",
        help="Inclusive RFC 3339 lower timestamp bound.",
    )
    parser.add_argument(
        "--until",
        help="Inclusive RFC 3339 upper timestamp bound.",
    )


def cmd_hook_errors(args: argparse.Namespace) -> int:
    """Render the grouped, deduplicated hook-error report as JSON."""
    try:
        since = parse_timestamp_bound(args.since) if args.since else None
        until = parse_timestamp_bound(args.until) if args.until else None
        report = aggregate_hook_errors(
            Path(args.transcript),
            since=since,
            until=until,
        )
    except TranscriptFormatError as exc:
        print(f"hook-errors failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return 0


__all__ = ["add_hook_error_parser", "cmd_hook_errors"]
