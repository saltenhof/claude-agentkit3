"""Unit tests for agentkit.backend.config.loader."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentkit.backend.config.loader import find_project_root, load_project_config
from agentkit.backend.config.models import ProjectConfig
from agentkit.backend.exceptions import ConfigError


class TestFindProjectRoot:
    """Tests for find_project_root."""

    def test_finds_agentkit_dir(self, tmp_path: Path) -> None:
        agentkit_dir = tmp_path / ".agentkit"
        agentkit_dir.mkdir()
        result = find_project_root(tmp_path)
        assert result == tmp_path.resolve()

    def test_finds_in_parent(self, tmp_path: Path) -> None:
        agentkit_dir = tmp_path / ".agentkit"
        agentkit_dir.mkdir()
        child = tmp_path / "sub" / "deep"
        child.mkdir(parents=True)
        result = find_project_root(child)
        assert result == tmp_path.resolve()

    def test_raises_when_not_found(self) -> None:
        with (
            tempfile.TemporaryDirectory() as td,
            pytest.raises(ConfigError, match="No .agentkit/ directory found"),
        ):
            find_project_root(Path(td))

    def test_raises_config_error_type(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with pytest.raises(ConfigError) as exc_info:
                find_project_root(Path(td))
            assert "start_path" in exc_info.value.detail

    def test_uses_cwd_when_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agentkit_dir = tmp_path / ".agentkit"
        agentkit_dir.mkdir()
        monkeypatch.chdir(tmp_path)
        result = find_project_root(None)
        assert result == tmp_path.resolve()


class TestLoadProjectConfig:
    """Tests for load_project_config."""

    @staticmethod
    def _write_config(project_root: Path, data: dict[str, Any]) -> Path:
        config_dir = project_root / ".agentkit" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "project.yaml"
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        return config_file

    def test_loads_valid_config(self, tmp_path: Path) -> None:
        data = {
            "project_key": "test-project",
            "project_name": "test-project",
            "repositories": [
                {"name": "backend", "path": "/opt/backend"},
            ],
            # AG3-052 E6 / AG3-056: code-producing default story_types must
            # declare the sonarqube + ci stanzas explicitly (here: opt-outs).
            # config_version is mandatory (FK-03 §3.2.1); multi_llm=False for
            # this single-LLM test fixture.
            "pipeline": {
                "config_version": "3.0",
                "features": {"multi_llm": False},
                "sonarqube": {"available": False, "enabled": False},
                "ci": {"available": False, "enabled": False},
            },
        }
        self._write_config(tmp_path, data)
        config = load_project_config(tmp_path)
        assert isinstance(config, ProjectConfig)
        assert config.project_key == "test-project"
        assert config.project_name == "test-project"
        assert len(config.repositories) == 1
        assert config.repositories[0].name == "backend"

    def test_loads_top_level_policy_stage_overrides(self, tmp_path: Path) -> None:
        data = {
            "project_key": "test-project",
            "project_name": "test-project",
            "repositories": [{"name": "backend", "path": "/opt/backend"}],
            "pipeline": {
                "config_version": "3.0",
                "features": {"multi_llm": False},
                "sonarqube": {"available": False, "enabled": False},
                "ci": {"available": False, "enabled": False},
            },
            "policy": {"stage_overrides": {"adversarial": {"blocking": False}}},
        }
        self._write_config(tmp_path, data)
        config = load_project_config(tmp_path)
        assert config.policy.stage_overrides["adversarial"].blocking is False

    def test_unknown_stage_override_fails_closed(self, tmp_path: Path) -> None:
        data = {
            "project_key": "test-project",
            "project_name": "test-project",
            "repositories": [{"name": "backend", "path": "/opt/backend"}],
            "pipeline": {
                "config_version": "3.0",
                "features": {"multi_llm": False},
                "sonarqube": {"available": False, "enabled": False},
                "ci": {"available": False, "enabled": False},
            },
            "policy": {"stage_overrides": {"unknown.stage": {"blocking": False}}},
        }
        self._write_config(tmp_path, data)
        with pytest.raises(ConfigError, match="unknown stage"):
            load_project_config(tmp_path)

    def test_forbidden_stage_override_field_fails_closed(self, tmp_path: Path) -> None:
        data = {
            "project_key": "test-project",
            "project_name": "test-project",
            "repositories": [{"name": "backend", "path": "/opt/backend"}],
            "pipeline": {
                "config_version": "3.0",
                "features": {"multi_llm": False},
                "sonarqube": {"available": False, "enabled": False},
                "ci": {"available": False, "enabled": False},
            },
            "policy": {
                "stage_overrides": {
                    "adversarial": {"blocking": False, "producer": "other"}
                }
            },
        }
        self._write_config(tmp_path, data)
        with pytest.raises(ConfigError, match="Extra inputs"):
            load_project_config(tmp_path)

    def test_loads_full_config(self, tmp_path: Path) -> None:
        data = {
            "project_key": "full",
            "project_name": "full",
            "repositories": [
                {
                    "name": "api",
                    "path": "/opt/api",
                    "language": "python",
                    "test_command": "pytest",
                    "build_command": "pip install -e .",
                },
            ],
            "pipeline": {
                "config_version": "3.0",
                "features": {"multi_llm": False},
                "max_feedback_rounds": 5,
                "max_remediation_rounds": 1,
                "exploration_mode": False,
                "verify_layers": ["structural", "policy"],
                # AG3-052 E6 / AG3-056: bugfix is code-producing => declare
                # both gate stanzas explicitly.
                "sonarqube": {"available": False, "enabled": False},
                "ci": {"available": False, "enabled": False},
            },
            "story_types": ["bugfix"],
            "github_owner": "acme",
            "github_repo": "backend",
        }
        self._write_config(tmp_path, data)
        config = load_project_config(tmp_path)
        assert config.project_key == "full"
        assert config.pipeline.max_feedback_rounds == 5
        assert config.github_owner == "acme"
        assert config.story_types == ["bugfix"]

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="Configuration file not found"):
            load_project_config(tmp_path)

    def test_raises_on_invalid_yaml(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".agentkit" / "config"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "project.yaml"
        config_file.write_text("{{invalid yaml: [}", encoding="utf-8")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_project_config(tmp_path)

    def test_raises_on_non_dict_yaml(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".agentkit" / "config"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "project.yaml"
        config_file.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="YAML mapping"):
            load_project_config(tmp_path)

    def test_raises_on_validation_error(self, tmp_path: Path) -> None:
        data = {"not_a_valid_field": True}
        self._write_config(tmp_path, data)
        with pytest.raises(ConfigError, match="validation failed"):
            load_project_config(tmp_path)

    def test_error_detail_contains_path(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError) as exc_info:
            load_project_config(tmp_path)
        assert "config_path" in exc_info.value.detail
