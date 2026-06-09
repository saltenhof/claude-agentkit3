"""Tests for worker-health configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.config.models import ProjectConfig
from agentkit.config.worker_health import WorkerHealthConfig


def test_worker_health_config_defaults_cover_all_fk49_fields() -> None:
    config = WorkerHealthConfig()

    assert config.scoring.thresholds.warning == 50
    assert config.scoring.runtime.M == (60, 90, 120)
    assert config.scoring.repetition.window_size == 15
    assert config.scoring.hook_conflict.same_reason_threshold == 2
    assert config.scoring.stagnation.max_points == 20
    assert config.scoring.tool_calls.hard_limit == 120
    assert config.llm_assessment.timeout_seconds == 45
    assert config.sidecar.poll_interval_seconds == 60
    assert config.tool_call_log.max_entries == 500


def test_worker_health_monitor_has_no_disable_path() -> None:
    with pytest.raises(ValidationError):
        WorkerHealthConfig.model_validate({"enabled": False})


def test_project_config_accepts_top_level_worker_health() -> None:
    project = ProjectConfig.model_validate(
        {
            "project_key": "p",
            "project_name": "P",
            "repositories": [{"name": "repo", "path": "."}],
            "story_types": ["concept"],
            "pipeline": {
                "config_version": "3.0",
                "features": {"multi_llm": False},
            },
            "worker_health": {
                "tool_call_log": {"max_entries": 200},
            },
        }
    )

    assert project.worker_health.tool_call_log.max_entries == 200
