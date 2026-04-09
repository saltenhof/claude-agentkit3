"""Pydantic models for story data.

Defines the durable story context, runtime phase state, and phase
snapshot models used throughout the AgentKit pipeline.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from agentkit.story.types import StoryMode, StoryType


class PhaseStatus(StrEnum):
    """Status of a pipeline phase.

    Attributes:
        PENDING: Phase has not started yet.
        IN_PROGRESS: Phase is currently executing.
        PAUSED: Phase execution paused (e.g. awaiting external input).
        COMPLETED: Phase finished successfully.
        FAILED: Phase finished with errors.
        ESCALATED: Phase failed beyond retry limits, escalated for review.
        BLOCKED: Phase cannot proceed due to unresolved dependency.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    BLOCKED = "blocked"


class StoryContext(BaseModel):
    """Durable story context -- persisted in context.json.

    This is the authoritative source for story semantics.
    Survives phase-state resets, recovery, and rehydration.

    Args:
        story_id: Unique identifier, e.g. "AG3-001".
        story_type: The type of story (implementation, bugfix, etc.).
        mode: Execution mode (execution, exploration, not_applicable).
        issue_nr: GitHub issue number, if linked.
        title: Human-readable story title.
        project_root: Root path of the target project.
        worktree_path: Path to the git worktree, if applicable.
        participating_repos: List of repository identifiers involved.
        labels: GitHub labels attached to the issue.
        created_at: Timestamp when the story was created.
    """

    story_id: str
    story_type: StoryType
    mode: StoryMode
    issue_nr: int | None = None

    @field_validator("story_id")
    @classmethod
    def _validate_story_id_branch_safe(cls, v: str) -> str:
        """Ensure story_id is safe to embed in a git branch name.

        A ``story/{story_id}`` branch is created for implementation and bugfix
        stories.  The story_id must therefore consist only of characters that
        are legal in git ref names.

        Raises:
            ValueError: If *v* contains characters that are invalid in a git
                branch name component.
        """
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$", v):
            raise ValueError(
                f"story_id {v!r} must start with an alphanumeric character and "
                "contain only alphanumeric characters, dots, hyphens, or underscores"
            )
        return v
    title: str = ""
    project_root: Path | None = None
    worktree_path: Path | None = None
    participating_repos: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    created_at: datetime | None = None

    model_config = {"frozen": True}


class PhaseState(BaseModel):
    """Runtime phase state -- persisted in phase-state.json.

    Current execution state only. NOT the source of truth for
    story semantics (that's ``StoryContext``).

    Args:
        story_id: Identifier of the story this state belongs to.
        phase: Current phase name (e.g. "setup", "verify").
        status: Current status of the phase.
        paused_reason: Human-readable reason if status is PAUSED.
        review_round: Current review/remediation round (0 = initial).
        errors: List of error messages accumulated during execution.
        attempt_id: Unique identifier for attempt-based tracking.
    """

    story_id: str
    phase: str
    status: PhaseStatus
    paused_reason: str | None = None
    review_round: int = 0
    errors: list[str] = Field(default_factory=list)
    attempt_id: str | None = None


class PhaseSnapshot(BaseModel):
    """Authoritative record of a completed phase.

    Persisted as ``phase-state-{phase}.json``. Provides an immutable
    record of what happened during a phase, including produced artifacts
    and evidence of completion.

    Args:
        story_id: Identifier of the story this snapshot belongs to.
        phase: Name of the completed phase.
        status: Final status (should be COMPLETED for successful phases).
        completed_at: Timestamp when the phase finished.
        artifacts: Paths to produced artifacts.
        evidence: Structured proof of completion (e.g. test results).
    """

    story_id: str
    phase: str
    status: PhaseStatus
    completed_at: datetime
    artifacts: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}
