"""Post-merge-finalization records: closure-time operational metrics."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ("StoryMetricsRecord",)


@dataclass(frozen=True)
class StoryMetricsRecord:
    """Closure-time operational metrics for one completed story run."""

    project_key: str
    story_id: str
    run_id: str
    story_type: str
    story_size: str
    mode: str
    processing_time_min: float
    qa_rounds: int
    increments: int
    final_status: str
    completed_at: str
    adversarial_findings: int | None = None
    adversarial_tests_created: int | None = None
    files_changed: int | None = None
    agentkit_version: str | None = None
    agentkit_commit: str | None = None
    config_version: str | None = None
    llm_roles: tuple[str, ...] = ()

    def to_metrics_payload(self) -> dict[str, object]:
        """Serialize the closure metrics payload for projections."""

        payload: dict[str, object] = {
            "story_size": self.story_size,
            "mode": self.mode,
            "processing_time_min": self.processing_time_min,
            "qa_rounds": self.qa_rounds,
            "increments": self.increments,
            "final_status": self.final_status,
            "completed_at": self.completed_at,
        }
        if self.adversarial_findings is not None:
            payload["adversarial_findings"] = self.adversarial_findings
        if self.adversarial_tests_created is not None:
            payload["adversarial_tests_created"] = self.adversarial_tests_created
        if self.files_changed is not None:
            payload["files_changed"] = self.files_changed
        if self.agentkit_version is not None:
            payload["agentkit_version"] = self.agentkit_version
        if self.agentkit_commit is not None:
            payload["agentkit_commit"] = self.agentkit_commit
        if self.config_version is not None:
            payload["config_version"] = self.config_version
        if self.llm_roles:
            payload["llm_roles"] = list(self.llm_roles)
        return payload
