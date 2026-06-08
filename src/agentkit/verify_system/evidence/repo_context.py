"""Repository context for multi-repo evidence assembly."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RepoContext(BaseModel):
    """Runtime metadata for one participating repository.

    Attributes:
        repo_id: Stable repository identifier inside the assembly.
        repo_path: Repository root or worktree path.
        git_base_branch: Base branch used by the external change-evidence port.
        role: Domain role of the repository, such as ``app`` or ``docs``.
        affected: Whether this repository participates in the story change.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_id: str = Field(min_length=1)
    repo_path: Path
    git_base_branch: str = Field(default="main", min_length=1)
    role: str = Field(default="app", min_length=1)
    affected: bool = True

    @field_validator("repo_path")
    @classmethod
    def _normalize_repo_path(cls, value: Path) -> Path:
        """Normalize the repository path without requiring it to exist yet."""
        return value.expanduser()


__all__ = ["RepoContext"]
