"""Telemetry query/export operator recovery command handlers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from datetime import datetime


from ._operator_recovery_config import (
    _ConfigResolutionError as _ConfigResolutionError,
)
from ._operator_recovery_config import _parse_since_cutoff as _parse_since_cutoff
from ._operator_recovery_config import _resolve_project_key as _resolve_project_key


def _validate_event_type(event_type_raw: str) -> int:
    """Validate ``--event`` value against :class:`~agentkit.backend.telemetry.events.EventType`.

    ERROR 4 fix: unknown event type must fail-closed (non-zero + stderr) rather
    than silently dropping the filter or querying all events.

    Args:
        event_type_raw: The raw ``--event`` string from the CLI.

    Returns:
        0 when valid, 1 when the value is not a known :class:`EventType`.
    """
    from agentkit.backend.telemetry.events import EventType

    try:
        EventType(event_type_raw)
        return 0
    except ValueError:
        valid = sorted(e.value for e in EventType)
        detail = f"--event {event_type_raw!r} is not a known EventType; use one of the listed values."
        print(
            json.dumps(
                {
                    "finding": "InvalidEventType",
                    "value": event_type_raw,
                    "valid_values": valid,
                    "detail": detail,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


def _pick_event_time(event: object) -> object:
    """Return the first non-``None`` time value from an event object.

    Priority order: ``occurred_at`` → ``occurred`` → ``timestamp``.
    This is the single source of truth for "the event's time" — used by
    both ``_apply_since_filter`` (for comparison) and the output serializer
    (for display), so the two always agree on which field carries the time.

    Args:
        event: Any event object that may have time fields as attributes.

    Returns:
        The raw time value (str or datetime) from the first populated field,
        or ``None`` when no recognisable time field is present.
    """
    for field in ("occurred_at", "occurred", "timestamp"):
        val = getattr(event, field, None)
        if val is not None:
            return val
    return None


def _coerce_to_aware_datetime(value: object) -> datetime | None:
    """Coerce a raw event time value to a timezone-aware :class:`datetime`.

    Accepts an ISO-8601 string or a :class:`datetime`; naive values are
    treated as UTC.  Returns ``None`` when the value is missing, not a
    recognised type, or an unparseable string (fail-closed: such an event
    has no comparable timestamp).

    Args:
        value: A raw time value from :func:`_pick_event_time` (str, datetime,
            or ``None``).

    Returns:
        A timezone-aware :class:`datetime`, or ``None`` when not coercible.
    """
    from datetime import UTC, datetime

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return None


def _apply_since_filter(events: list[object], since_cutoff: datetime) -> list[object]:
    """Filter ``events`` to those whose timestamp is >= ``since_cutoff``.

    MAJOR 5 fix: filters by parsed datetime (not raw string comparison) so
    window-form cutoffs (``7d``, ``24h``) work correctly.

    MAJOR 2 fix: reads the event timestamp from whichever field is present —
    ``occurred_at``, ``occurred``, or ``timestamp`` — so that story-scoped
    ``Event`` objects (which use ``.timestamp``) are not silently dropped.
    The first non-``None`` value found in that priority order is used.
    Delegates field selection to :func:`_pick_event_time` (single source of
    truth shared with the output serializer).

    Args:
        events: Iterable of event objects whose timestamp may live in
            ``occurred_at``, ``occurred``, or ``timestamp`` attributes.
        since_cutoff: A timezone-aware :class:`datetime` lower bound.

    Returns:
        Subset of ``events`` that fall at or after ``since_cutoff``.
    """
    result = []
    for e in events:
        occ_dt = _coerce_to_aware_datetime(_pick_event_time(e))
        # ``None`` means no recognisable/parseable time field — skip rather than
        # silently retain; the event has no timestamp to compare.
        if occ_dt is not None and occ_dt >= since_cutoff:
            result.append(e)
    return result


def _cmd_query_telemetry_story_form(
    story_id: str,
    project_root: Path,
    event_type_raw: str | None,
    since_cutoff: datetime | None,
) -> int:
    """Inner handler for the story-scoped ``query-telemetry`` form.

    Delegates to :class:`~agentkit.backend.telemetry.storage.StateBackendEmitter.query`
    (story §2.1.7 / §2.3 anchor: telemetry/storage.py:89).

    Args:
        story_id: Story display ID.
        project_root: Project root path.
        event_type_raw: Optional validated event-type string.
        since_cutoff: Optional timezone-aware :class:`datetime` lower bound.

    Returns:
        0 on success, 1 on backend error.
    """
    from agentkit.backend.telemetry.events import EventType
    from agentkit.backend.telemetry.storage import StateBackendEmitter

    story_dir = project_root / "stories" / story_id
    event_type_filter: EventType | None = EventType(event_type_raw) if event_type_raw else None

    try:
        emitter = StateBackendEmitter(story_dir)
        events: list[object] = list(emitter.query(story_id, event_type_filter))
    except Exception as exc:  # noqa: BLE001
        print(f"query-telemetry failed: {exc}", file=sys.stderr)
        return 1

    if since_cutoff is not None:
        events = _apply_since_filter(events, since_cutoff)

    events_out = [
        {
            "event_id": str(getattr(e, "event_id", "")),
            "event_type": str(getattr(e, "event_type", "")),
            # Use _pick_event_time for the same priority order as _apply_since_filter
            # (occurred_at -> occurred -> timestamp) so the displayed time matches
            # whichever field the event actually uses (MINOR 2 fix).
            "occurred_at": str(_pick_event_time(e) or ""),
            "story_id": str(getattr(e, "story_id", "")),
        }
        for e in events
    ]
    print(json.dumps({"story_id": story_id, "events": events_out}, sort_keys=True))
    return 0


def _cmd_query_telemetry(args: argparse.Namespace) -> int:
    """Handle ``agentkit query-telemetry`` (AG3-076, FK-68).

    Requires at least one of --story, --run, or --event.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on error.
    """
    story_id: str | None = getattr(args, "story", None)
    run_id: str | None = getattr(args, "run", None)
    event_type_raw: str | None = getattr(args, "event", None)
    since_raw: str | None = getattr(args, "since", None)

    if not story_id and not run_id and not event_type_raw:
        print(
            "query-telemetry failed [MissingFilter]: at least one of --story, --run, or --event is required.",
            file=sys.stderr,
        )
        return 1

    # ERROR 4 fix: validate --event fail-closed before any query.
    if event_type_raw is not None and _validate_event_type(event_type_raw) != 0:
        return 1

    # MAJOR 5 fix: parse --since into a timezone-aware datetime (fail-closed).
    since_cutoff: datetime | None = None
    if since_raw is not None:
        try:
            since_cutoff = _parse_since_cutoff(since_raw)
        except ValueError as exc:
            print(
                json.dumps(
                    {"finding": "InvalidSinceValue", "value": since_raw, "detail": str(exc)},
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1

    # ERROR 1 fix: when --config is explicitly provided, validate it BEFORE branching
    # on story_id.  A broken --config must fail-closed (non-zero + structured stderr
    # finding) regardless of which query form is used (story or non-story).
    # When --config is absent, the story form proceeds without requiring a project_key.
    config_path_raw = getattr(args, "config", None)
    if config_path_raw is not None:
        try:
            _resolve_project_key(args)
        except _ConfigResolutionError as exc:
            print(f"query-telemetry failed [ConfigResolutionError]: {exc}", file=sys.stderr)
            return 1

    if story_id:
        project_root = Path(getattr(args, "project_root", "."))
        return _cmd_query_telemetry_story_form(story_id, project_root, event_type_raw, since_cutoff)

    # run-scoped or event-type global form: needs project_key (handled in helper).
    return _cmd_query_telemetry_global_form(args, run_id, event_type_raw, since_cutoff)


def _cmd_query_telemetry_global_form(
    args: argparse.Namespace,
    run_id: str | None,
    event_type_raw: str | None,
    since_cutoff: datetime | None,
) -> int:
    """Inner handler for the project-global ``query-telemetry`` forms (--run / --event).

    Resolves the project key fail-closed, reads project-global execution events
    via the composition-root wrapper, and applies adapter-side run/event/since
    filters (story §2.1.7).

    Args:
        args: Parsed CLI arguments (for project-key resolution).
        run_id: Optional run-ID filter.
        event_type_raw: Optional validated event-type filter.
        since_cutoff: Optional timezone-aware :class:`datetime` lower bound.

    Returns:
        0 on success, 1 on error.
    """
    # ERROR 2 fix: --config provided but broken -> fail-closed, not env fallback.
    # When --config is present the caller already validated it; resolving again
    # here keeps the resolution logic in one canonical place.
    try:
        project_key = _resolve_project_key(args)
    except _ConfigResolutionError as exc:
        print(f"query-telemetry failed [ConfigResolutionError]: {exc}", file=sys.stderr)
        return 1
    if not project_key:
        print(
            "query-telemetry failed [MissingProjectKey]: --project, --config-derived key, "
            "or AGENTKIT_PROJECT_KEY is required for run-scoped or event-type queries.",
            file=sys.stderr,
        )
        return 1

    from agentkit.backend.bootstrap.composition_root import cli_load_execution_events_for_project_global

    try:
        all_records = cli_load_execution_events_for_project_global(project_key)
    except Exception as exc:  # noqa: BLE001
        print(f"query-telemetry failed: {exc}", file=sys.stderr)
        return 1

    filtered: list[object] = list(all_records)
    if run_id:
        filtered = [r for r in filtered if str(getattr(r, "run_id", "")) == run_id]
    if event_type_raw:
        filtered = [r for r in filtered if str(getattr(r, "event_type", "")) == event_type_raw]
    if since_cutoff is not None:
        filtered = _apply_since_filter(filtered, since_cutoff)

    events_out = [
        {
            "event_id": str(getattr(r, "event_id", "")),
            "event_type": str(getattr(r, "event_type", "")),
            "story_id": str(getattr(r, "story_id", "")),
            "run_id": str(getattr(r, "run_id", "")),
            "occurred_at": str(getattr(r, "occurred_at", "")),
        }
        for r in filtered
    ]
    print(json.dumps({"project_key": project_key, "events": events_out}, sort_keys=True))
    return 0


def _build_weekly_review_frame() -> dict[str, object]:
    """Build the structured weekly-review frame with inline service-gap findings.

    The renderer frame itself (Class A) always succeeds. Data sections backed
    by ``FailureCorpus`` are Class C (service gaps reported inline).

    Returns:
        Dict suitable for JSON serialisation.
    """
    return {
        "pattern_candidates": {
            "status": "service_gap",
            "finding": "[ServiceGap] FailureCorpus.suggest_patterns not implemented (owner: AG3-078)",
        },
        "check_proposals": {
            "status": "service_gap",
            "finding": "[ServiceGap] FailureCorpus.derive_check not implemented (owner: AG3-078)",
        },
        "effectiveness_alerts": {
            "status": "service_gap",
            "finding": "[ServiceGap] FailureCorpus.report_effectiveness not implemented (owner: AG3-078)",
        },
    }


def _cmd_weekly_review(args: argparse.Namespace) -> int:
    """Handle ``agentkit weekly-review`` (AG3-076).

    Renders the operator weekly-review frame.  All sections are Class C
    (Failure-Corpus service gap) — their substantive content is absent until
    AG3-078 delivers the producers.  Per §2.1 preamble, Class-C parts emit a
    machine-readable finding to STDERR and return non-zero.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Always 1 — all data sections are Class-C service gaps (non-zero exit
        per §2.1 preamble); the machine-readable findings go to stderr.
    """
    _ = args
    frame = _build_weekly_review_frame()
    # Class-C: machine-readable service-gap findings -> stderr (§2.1 preamble)
    print(json.dumps({"weekly_review": frame}, sort_keys=True, indent=2), file=sys.stderr)
    return 1


def _cmd_export_telemetry(args: argparse.Namespace) -> int:
    """Handle ``agentkit export-telemetry`` (AG3-076, FK-68 §68.3.6).

    Exports a completed story run as a JSONL audit bundle via
    :class:`~agentkit.backend.telemetry.audit_bundle.AuditBundleExporter`.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on error.
    """
    output_dir = Path(args.output_dir)

    if args.dry_run:
        # Check output_dir reachability/writability only — NO filesystem mutation.
        # Story §2.1.10: checks reachability/writability only, no writes,
        # no export call (ERROR 4 fix).
        import os

        # Walk up to the nearest existing ancestor to check writability.
        check_target = output_dir
        while not check_target.exists() and check_target != check_target.parent:
            check_target = check_target.parent

        if not check_target.exists():
            print(
                f"export-telemetry dry-run failed [OutputDirNotWritable]: no existing ancestor found for {output_dir}",
                file=sys.stderr,
            )
            return 1

        if not os.access(check_target, os.W_OK):
            print(
                f"export-telemetry dry-run failed [OutputDirNotWritable]: {check_target} is not writable",
                file=sys.stderr,
            )
            return 1

        print(json.dumps({"dry_run": True, "output_dir": str(output_dir), "writable": True}, sort_keys=True))
        return 0

    from agentkit.backend.bootstrap.composition_root import build_projection_accessor
    from agentkit.backend.telemetry.audit_bundle import AuditBundleExporter, AuditBundleExportError
    from agentkit.backend.telemetry.storage import StateBackendEmitter

    project_root = Path(getattr(args, "project_root", "."))
    story_dir = project_root / "stories" / args.story

    try:
        accessor = build_projection_accessor(story_dir)
        event_store = StateBackendEmitter(story_dir)
        exporter = AuditBundleExporter(
            projection_accessor=accessor,
            event_store=event_store,
        )
        bundle = exporter.export(args.story, args.run, output_dir)
    except AuditBundleExportError as exc:
        print(f"export-telemetry failed [AuditBundleExportError]: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"export-telemetry failed: {exc}", file=sys.stderr)
        return 1

    file_info = [{"name": f.name, "path": str(f.path), "sha256": f.sha256, "size_bytes": f.size_bytes} for f in bundle.files]
    print(
        json.dumps(
            {
                "story_id": bundle.story_id,
                "run_id": bundle.run_id,
                "output_dir": str(bundle.output_dir),
                "manifest_path": str(bundle.manifest_path),
                "files": file_info,
            },
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "_apply_since_filter",
    "_build_weekly_review_frame",
    "_cmd_export_telemetry",
    "_cmd_query_telemetry",
    "_cmd_query_telemetry_global_form",
    "_cmd_query_telemetry_story_form",
    "_cmd_weekly_review",
    "_coerce_to_aware_datetime",
    "_pick_event_time",
    "_validate_event_type",
]
