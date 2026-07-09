"""State inspection operator recovery command handlers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

from ._operator_recovery_telemetry import _build_weekly_review_frame


def _cmd_status(args: argparse.Namespace) -> int:
    """Handle ``agentkit status`` (AG3-076, FK-29).

    With ``--story``: reads the phase state via the state backend and renders a
    weekly-review frame inline.  Without ``--story``: renders the weekly-review
    frame only.

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on error.
    """
    from agentkit.backend.bootstrap.composition_root import cli_read_phase_state_record

    project_root = Path(getattr(args, "project_root", "."))
    story_id: str | None = getattr(args, "story", None)

    phase_state_payload: object = None
    if story_id:
        story_dir = project_root / "stories" / story_id
        try:
            phase_state_payload = cli_read_phase_state_record(story_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"status failed [PhaseStateReadError]: {exc}", file=sys.stderr)
            return 1

        # ERROR 3 fix (NEW): None phase-state for a named story is fail-closed.
        # Story §2.3 anchor: an unresolvable story -> non-zero + stderr finding.
        if phase_state_payload is None:
            print(
                json.dumps(
                    {
                        "finding": "PhaseStateNotFound",
                        "story_id": story_id,
                        "detail": "no phase-state record found for the specified story",
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1

    weekly_frame = _build_weekly_review_frame()

    # Class-A overview goes to stdout (exit 0 on success).
    # The FC review-block sections are Class-C service gaps: they go to stderr as
    # explicit machine-readable findings (§2.1.5 "no silent empty report"),
    # while the status exit code reflects Class-A success.
    # Distinction vs. weekly-review (§2.1.8 / §2.1.5 rationale):
    #   - weekly-review: all content is Class-C → stderr + non-zero
    #   - status: Class-A overview (run/pool/phase-state) → stdout + exit 0;
    #             FC service-gap markers → stderr (explicit, never silent/empty)
    print(json.dumps({"weekly_review_service_gaps": weekly_frame}, sort_keys=True, indent=2), file=sys.stderr)

    output: dict[str, object] = {}
    if story_id is not None:
        output["story_id"] = story_id
        if phase_state_payload is not None and hasattr(phase_state_payload, "model_dump"):
            output["phase_state"] = phase_state_payload.model_dump()

    print(json.dumps(output, sort_keys=True, default=str))
    return 0


def _cmd_query_state(args: argparse.Namespace) -> int:
    """Handle ``agentkit query-state`` (AG3-076).

    Without ``--locks``: reads and outputs the phase state record (Class A).
    With ``--locks``: reports a service gap (Class C).

    Args:
        args: Parsed CLI arguments.

    Returns:
        0 on success, 1 on error or service gap.
    """
    if args.locks:
        print(
            "[ServiceGap] no lock-listing read repository — reported as service gap "
            "(owner: Lock-State-Backend/PO-assignment-required)",
            file=sys.stderr,
        )
        return 1

    from agentkit.backend.bootstrap.composition_root import cli_read_phase_state_record

    story_id: str | None = getattr(args, "story", None)
    if not story_id:
        print(
            "query-state failed [MissingStoryId]: --story is required for phase-state queries",
            file=sys.stderr,
        )
        return 1

    project_root = Path(getattr(args, "project_root", "."))
    story_dir = project_root / "stories" / story_id

    try:
        record = cli_read_phase_state_record(story_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"query-state failed [PhaseStateReadError]: {exc}", file=sys.stderr)
        return 1

    # ERROR 3 fix (NEW): None record means the story/phase-state is not found.
    # Story §2.3: an unresolvable story is fail-closed (non-zero + stderr finding).
    if record is None:
        print(
            json.dumps(
                {
                    "finding": "PhaseStateNotFound",
                    "story_id": story_id,
                    "detail": "no phase-state record found for the specified story",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    payload = record.model_dump() if hasattr(record, "model_dump") else None

    print(json.dumps({"story_id": story_id, "phase_state": payload}, sort_keys=True, default=str))
    return 0


__all__ = ["_cmd_query_state", "_cmd_status"]
