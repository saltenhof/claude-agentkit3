"""Atomic read/write operations for pipeline state persistence.

Provides crash-safe JSON persistence for ``PhaseState``, ``StoryContext``,
``PhaseSnapshot``, and ``AttemptRecord``. All writes use atomic
temp-file-plus-replace to guarantee no corrupt state on crash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, cast

from agentkit.story.models import PhaseSnapshot, PhaseState, PhaseStatus, StoryContext

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class AttemptRecord:
    """Immutable record of a single phase execution attempt.

    Persisted as ``phase-runs/<phase>/attempt-NNN.json``.

    Args:
        attempt_id: Unique attempt identifier (e.g. ``"exploration-002"``).
        phase: Name of the phase this attempt belongs to.
        entered_at: Timestamp when the attempt started.
        exit_status: Final status, or ``None`` if still running.
        guard_evaluations: Guard evaluation results captured during the attempt.
        artifacts_produced: Paths to artifacts produced during the attempt.
        outcome: Outcome description (e.g. ``"completed"``, ``"yielded"``).
        yield_status: Yield reason if the phase was paused.
        resume_trigger: Resume trigger if the phase was resumed.
    """

    attempt_id: str
    phase: str
    entered_at: datetime
    exit_status: PhaseStatus | None = None
    guard_evaluations: tuple[dict[str, object], ...] = ()
    artifacts_produced: tuple[str, ...] = ()
    outcome: str | None = None
    yield_status: str | None = None
    resume_trigger: str | None = None


def atomic_write_json(path: Path, data: dict[str, object]) -> None:
    """Write JSON atomically via ``atomic_write_text``.

    Delegates to :func:`agentkit.project_ops.shared.file_ops.atomic_write_text`
    for crash-safe temp-file-plus-replace semantics.

    Args:
        path: Target file path. Parent directories are created if missing.
        data: Dictionary to serialize as JSON.
    """
    from agentkit.project_ops.shared.file_ops import atomic_write_text

    content = json.dumps(data, indent=2, sort_keys=True, default=str)
    atomic_write_text(path, content)


def load_json_safe(path: Path) -> dict[str, object] | None:
    """Load JSON from a file, returning ``None`` if missing or corrupt.

    Args:
        path: File path to read.

    Returns:
        Parsed dictionary, or ``None`` if the file is missing,
        contains invalid JSON, or is not a JSON object.
    """
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return cast("dict[str, object]", data)
    except (json.JSONDecodeError, OSError):
        return None


def save_phase_state(story_dir: Path, state: PhaseState) -> None:
    """Persist current phase state atomically.

    Args:
        story_dir: Root directory for this story's artifacts.
        state: The ``PhaseState`` to persist.
    """
    atomic_write_json(
        story_dir / "phase-state.json",
        state.model_dump(mode="json"),
    )


def load_phase_state(story_dir: Path) -> PhaseState | None:
    """Load current phase state from disk.

    Args:
        story_dir: Root directory for this story's artifacts.

    Returns:
        The deserialized ``PhaseState``, or ``None`` if missing/corrupt.
    """
    data = load_json_safe(story_dir / "phase-state.json")
    if data is None:
        return None
    try:
        return PhaseState.model_validate(data)
    except Exception:  # noqa: BLE001 — intentionally broad to handle any validation error
        return None


def save_story_context(story_dir: Path, ctx: StoryContext) -> None:
    """Persist story context atomically.

    Args:
        story_dir: Root directory for this story's artifacts.
        ctx: The ``StoryContext`` to persist.
    """
    atomic_write_json(
        story_dir / "context.json",
        ctx.model_dump(mode="json"),
    )


def load_story_context(story_dir: Path) -> StoryContext | None:
    """Load story context from disk.

    Args:
        story_dir: Root directory for this story's artifacts.

    Returns:
        The deserialized ``StoryContext``, or ``None`` if missing/corrupt.
    """
    data = load_json_safe(story_dir / "context.json")
    if data is None:
        return None
    try:
        return StoryContext.model_validate(data)
    except Exception:  # noqa: BLE001 — intentionally broad to handle any validation error
        return None


def save_attempt(story_dir: Path, attempt: AttemptRecord) -> None:
    """Save an attempt record to ``phase-runs/<phase>/attempt-NNN.json``.

    The attempt number is auto-incremented based on existing files
    in the phase's attempt directory.

    Args:
        story_dir: Root directory for this story's artifacts.
        attempt: The ``AttemptRecord`` to persist.
    """
    attempts_dir = story_dir / "phase-runs" / attempt.phase
    attempts_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(attempts_dir.glob("attempt-*.json"))
    next_num = len(existing) + 1
    path = attempts_dir / f"attempt-{next_num:03d}.json"
    data: dict[str, object] = {
        "attempt_id": attempt.attempt_id,
        "phase": attempt.phase,
        "entered_at": attempt.entered_at.isoformat(),
        "exit_status": attempt.exit_status.value if attempt.exit_status else None,
        "guard_evaluations": list(attempt.guard_evaluations),
        "artifacts_produced": list(attempt.artifacts_produced),
        "outcome": attempt.outcome,
        "yield_status": attempt.yield_status,
        "resume_trigger": attempt.resume_trigger,
    }
    atomic_write_json(path, data)


def load_attempts(story_dir: Path, phase: str) -> list[AttemptRecord]:
    """Load all attempt records for a phase, ordered by attempt number.

    Corrupt attempt files are silently skipped; valid attempts
    are returned in order.

    Args:
        story_dir: Root directory for this story's artifacts.
        phase: The phase name to load attempts for.

    Returns:
        List of ``AttemptRecord`` objects in order.
    """
    attempts_dir = story_dir / "phase-runs" / phase
    if not attempts_dir.exists():
        return []
    records: list[AttemptRecord] = []
    for path in sorted(attempts_dir.glob("attempt-*.json")):
        data = load_json_safe(path)
        if data is not None:
            try:
                records.append(AttemptRecord(
                    attempt_id=str(data.get("attempt_id", "")),
                    phase=str(data.get("phase", phase)),
                    entered_at=datetime.fromisoformat(
                        str(data.get("entered_at", "")),
                    ),
                    exit_status=(
                        PhaseStatus(str(data["exit_status"]))
                        if data.get("exit_status")
                        else None
                    ),
                    guard_evaluations=tuple(
                        cast(
                            "list[dict[str, object]]",
                            data.get("guard_evaluations", []),
                        ),
                    ),
                    artifacts_produced=tuple(
                        str(x) for x in cast(
                            "list[object]",
                            data.get("artifacts_produced", []),
                        )
                    ),
                    outcome=(
                        str(data["outcome"]) if data.get("outcome") else None
                    ),
                    yield_status=(
                        str(data["yield_status"])
                        if data.get("yield_status")
                        else None
                    ),
                    resume_trigger=(
                        str(data["resume_trigger"])
                        if data.get("resume_trigger")
                        else None
                    ),
                ))
            except (ValueError, KeyError, TypeError):
                continue
    return records


def save_phase_snapshot(story_dir: Path, snapshot: PhaseSnapshot) -> None:
    """Persist a phase snapshot (completed phase record).

    Saved as ``phase-state-{phase}.json`` in the story directory.

    Args:
        story_dir: Root directory for this story's artifacts.
        snapshot: The ``PhaseSnapshot`` to persist.
    """
    atomic_write_json(
        story_dir / f"phase-state-{snapshot.phase}.json",
        snapshot.model_dump(mode="json"),
    )


def load_phase_snapshot(story_dir: Path, phase: str) -> PhaseSnapshot | None:
    """Load a phase snapshot from disk.

    Args:
        story_dir: Root directory for this story's artifacts.
        phase: The phase name to load the snapshot for.

    Returns:
        The deserialized ``PhaseSnapshot``, or ``None`` if missing/corrupt.
    """
    data = load_json_safe(story_dir / f"phase-state-{phase}.json")
    if data is None:
        return None
    try:
        return PhaseSnapshot.model_validate(data)
    except Exception:  # noqa: BLE001 — intentionally broad to handle any validation error
        return None
