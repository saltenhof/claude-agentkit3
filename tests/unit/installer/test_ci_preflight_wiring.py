"""Installer configuration pins for backend-owned Jenkins validation."""

from __future__ import annotations

from pathlib import Path

from agentkit.backend.installer.runner import InstallConfig, _build_project_yaml


def _config(**kwargs: object) -> InstallConfig:
    return InstallConfig(
        project_key="acme",
        project_name="Acme",
        project_root=Path("/tmp"),
        **kwargs,  # type: ignore[arg-type]
    )


def test_built_yaml_has_explicit_secret_reference_only_ci_stanza() -> None:
    """The target config names the backend secret reference, never its value."""
    data = _build_project_yaml(_config())
    pipeline = data["pipeline"]
    assert isinstance(pipeline, dict)
    ci = pipeline["ci"]
    assert isinstance(ci, dict)
    assert ci == {
        "available": True,
        "enabled": True,
        "base_url": "http://localhost:8080",
        "token_env": "JENKINS_TOKEN",
        "pipeline": "ak3-pre-merge",
    }


def test_built_yaml_conscious_ci_optout_is_explicit() -> None:
    data = _build_project_yaml(_config(ci_available=False))
    pipeline = data["pipeline"]
    assert isinstance(pipeline, dict)
    ci = pipeline["ci"]
    assert ci == {"available": False, "enabled": False}
