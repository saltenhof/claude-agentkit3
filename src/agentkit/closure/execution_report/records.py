"""Closure execution-report records: summary of a completed story execution."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ("ExecutionReport",)


@dataclass(frozen=True)
class ExecutionReport:
    """Summary of a completed story execution."""

    story_id: str
    story_type: str
    status: str
    phases_executed: tuple[str, ...]
    started_at: str | None = None
    completed_at: str | None = None
    issue_closed: bool = False
    warnings: tuple[str, ...] = ()
    metrics: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize to the canonical export shape."""

        payload: dict[str, object] = {
            "story_id": self.story_id,
            "story_type": self.story_type,
            "status": self.status,
            "phases_executed": list(self.phases_executed),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "issue_closed": self.issue_closed,
            "warnings": list(self.warnings),
        }
        if self.metrics is not None:
            payload["metrics"] = self.metrics
        return payload
