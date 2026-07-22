"""AG3-176 AC2/R1: strict config boundary BEFORE installer effects."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from pydantic import ValidationError

from agentkit.backend.config.loader import load_project_config
from agentkit.backend.config.models import Features
from agentkit.backend.config.strict_yaml import StrictYamlError, strict_load_yaml
from agentkit.backend.exceptions import ConfigError, InstallationError
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    run_checkpoint_install,
)
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.paths import project_config_path
from agentkit.backend.installer.runner import InstallConfig

if TYPE_CHECKING:
    from pathlib import Path


def _write_project(tmp_path: Path, pipeline_features: object, *, vectordb: bool = True) -> Path:
    data: dict[str, object] = {
        "project_key": "p1",
        "project_name": "P1",
        "repositories": [{"name": "app", "path": "."}],
        "story_types": ["concept"],
        "pipeline": {
            "config_version": "3.0",
            "features": pipeline_features,
            "sonarqube": {"available": False, "enabled": False},
            "ci": {"available": False, "enabled": False},
        },
        "concepts_dir": "concepts",
        "wiki_stories_dir": "stories",
    }
    if vectordb:
        pipe = data["pipeline"]
        assert isinstance(pipe, dict)
        pipe["vectordb"] = {
            "host": "weaviate.test.local",
            "port": 19903,
            "grpc_port": 50051,
        }
    cfg_dir = tmp_path / ".agentkit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "project.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return tmp_path


def test_missing_vectordb_flag_means_active(tmp_path: Path) -> None:
    root = _write_project(tmp_path, {"multi_llm": False})
    cfg = load_project_config(root)
    assert cfg.pipeline.features.vectordb is True


def test_true_accepted(tmp_path: Path) -> None:
    root = _write_project(tmp_path, {"multi_llm": False, "vectordb": True})
    cfg = load_project_config(root)
    assert cfg.pipeline.features.vectordb is True


def test_false_hard_error(tmp_path: Path) -> None:
    root = _write_project(tmp_path, {"multi_llm": False, "vectordb": False}, vectordb=False)
    with pytest.raises(ConfigError) as ei:
        load_project_config(root)
    assert "vectordb" in str(ei.value).lower() or "configuration" in str(ei.value).lower()


def test_string_coercion_rejected() -> None:
    with pytest.raises(ValidationError):
        Features(vectordb="true")  # type: ignore[arg-type]


def test_null_rejected() -> None:
    with pytest.raises(ValidationError):
        Features.model_validate({"vectordb": None})


def test_number_rejected() -> None:
    with pytest.raises(ValidationError):
        Features.model_validate({"vectordb": 1})


def test_duplicate_keys_fail_closed() -> None:
    text = "a: 1\na: 2\n"
    with pytest.raises(StrictYamlError, match="duplicate"):
        strict_load_yaml(text)


def test_extreme_depth_fail_closed() -> None:
    depth = 80
    text = "x: " + ("{y: " * depth) + "1" + ("}" * depth) + "\n"
    with pytest.raises(StrictYamlError, match="nesting"):
        strict_load_yaml(text)


def test_utf8_decode_error_is_configuration_invalid(tmp_path: Path) -> None:
    """R13: file-loader maps UTF-8 decode to ConfigError(configuration_invalid)."""
    cfg_dir = tmp_path / ".agentkit" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "project.yaml").write_bytes(b"\xff\xfe not utf-8 \xff")
    with pytest.raises(ConfigError) as ei:
        load_project_config(tmp_path)
    detail = getattr(ei.value, "detail", {}) or {}
    assert detail.get("error_code") == "configuration_invalid" or "utf-8" in str(
        ei.value
    ).lower()


def test_model_allows_missing_vectordb_stanza_but_installer_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scope fix: ProjectConfig without vectordb stanza loads; install fails closed."""
    from agentkit.backend.config.models import require_installer_vectordb_endpoint

    root = _write_project(tmp_path, {"multi_llm": False}, vectordb=False)
    # features.vectordb defaults active; no pipeline.vectordb stanza.
    cfg = load_project_config(root)
    assert cfg.pipeline.features.vectordb is True
    assert cfg.pipeline.vectordb is None
    with pytest.raises(ValueError, match="installer requires pipeline.vectordb"):
        require_installer_vectordb_endpoint(cfg)

    effects: list[str] = []

    def boom_scaffold(*a, **k):  # type: ignore[no-untyped-def]
        effects.append("scaffold")
        raise AssertionError("scaffold must not run")

    monkeypatch.setattr(
        "agentkit.backend.installer.runner.scaffold_project_structure",
        boom_scaffold,
    )
    monkeypatch.setattr(
        "agentkit.backend.installer.runner._resolve_mandatory_skill_bundles",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("preflight")),
    )
    config = InstallConfig(
        project_key="p1",
        project_name="P1",
        project_root=root,
        weaviate_host="weaviate.test.local",
        weaviate_http_port=19903,
        weaviate_grpc_port=50051,
    )
    cfg_bytes = project_config_path(root).read_bytes()
    with pytest.raises(InstallationError) as ei:
        run_checkpoint_install(config, mode=ExecutionMode.REGISTER)
    assert "configuration_invalid" in str(ei.value).lower() or (
        isinstance(ei.value.detail, dict)
        and ei.value.detail.get("error_code") == "configuration_invalid"
    )
    assert effects == []
    assert project_config_path(root).read_bytes() == cfg_bytes


def test_no_installer_effect_before_config_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1: real run_checkpoint_install aborts before FS/preflight/registration effects."""
    root = _write_project(tmp_path, {"multi_llm": False, "vectordb": False}, vectordb=False)

    # Observe seams: if any of these run, the test fails.
    effects: list[str] = []

    def boom_scaffold(*a, **k):  # type: ignore[no-untyped-def]
        effects.append("scaffold")
        raise AssertionError("scaffold must not run")

    def boom_preflight(*a, **k):  # type: ignore[no-untyped-def]
        effects.append("preflight")
        raise AssertionError("preflight must not run")

    def boom_dual(*a, **k):  # type: ignore[no-untyped-def]
        effects.append("dual_write")
        raise AssertionError("dual write must not run")

    def boom_hooks(*a, **k):  # type: ignore[no-untyped-def]
        effects.append("hooks")
        raise AssertionError("hooks must not run")

    monkeypatch.setattr(
        "agentkit.backend.installer.runner.scaffold_project_structure",
        boom_scaffold,
    )
    monkeypatch.setattr(
        "agentkit.backend.installer.runner._resolve_mandatory_skill_bundles",
        boom_preflight,
    )
    monkeypatch.setattr(
        "agentkit.backend.installer.mcp_registration.dual_write.apply_dual_registration_writes",
        boom_dual,
        raising=False,
    )
    monkeypatch.setattr(
        "agentkit.backend.vectordb.git_hooks.materialize_concept_git_hooks",
        boom_hooks,
        raising=False,
    )

    config = InstallConfig(
        project_key="p1",
        project_name="P1",
        project_root=root,
        weaviate_host="weaviate.test.local",
        weaviate_http_port=19903,
        weaviate_grpc_port=50051,
    )

    # Snapshot FS markers that must not appear
    hooks_pre = root / "tools" / "hooks" / "pre-commit"
    mcp = root / ".mcp.json"
    assert not hooks_pre.exists()
    assert not mcp.exists()
    cfg_bytes = project_config_path(root).read_bytes()

    with pytest.raises(InstallationError) as ei:
        run_checkpoint_install(config, mode=ExecutionMode.REGISTER)
    assert "configuration_invalid" in str(ei.value).lower() or (
        isinstance(ei.value.detail, dict)
        and ei.value.detail.get("error_code") == "configuration_invalid"
    )
    assert effects == []
    assert project_config_path(root).read_bytes() == cfg_bytes
    assert not hooks_pre.exists()
    assert not mcp.exists()
