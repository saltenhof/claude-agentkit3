"""Minimal AgentKit installer for target projects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentkit.config.defaults import (
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    DEFAULT_MAX_REMEDIATION_ROUNDS,
    DEFAULT_STORY_TYPES,
    DEFAULT_VERIFY_LAYERS,
)
from agentkit.exceptions import ProjectError
from agentkit.installer.file_ops import atomic_write_yaml, create_or_replace_hardlink
from agentkit.installer.paths import config_dir, project_config_path, static_prompts_dir


def _resources_target_project_dir() -> Path:
    package_dir = Path(__file__).resolve().parent.parent
    resources_dir = package_dir / "resources" / "target_project"
    if not resources_dir.is_dir():
        raise ProjectError(
            f"Resources directory not found: {resources_dir}",
            detail={"resources_dir": str(resources_dir)},
        )
    return resources_dir


def _resources_internal_prompt_dir() -> Path:
    package_dir = Path(__file__).resolve().parent.parent
    resources_dir = package_dir / "resources" / "internal" / "prompts"
    if not resources_dir.is_dir():
        raise ProjectError(
            f"Internal prompt resources directory not found: {resources_dir}",
            detail={"resources_dir": str(resources_dir)},
        )
    return resources_dir


@dataclass
class InstallConfig:
    project_name: str
    project_root: Path
    repositories: list[dict[str, str]] | None = None
    github_owner: str | None = None
    github_repo: str | None = None


@dataclass(frozen=True)
class InstallResult:
    success: bool
    project_root: Path
    created_files: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)


def _build_project_yaml(config: InstallConfig) -> dict[str, object]:
    if config.repositories:
        repos: list[dict[str, str]] = []
        for repo in config.repositories:
            entry: dict[str, str] = {
                "name": repo["name"],
                "path": repo["path"],
            }
            if "language" in repo:
                entry["language"] = repo["language"]
            if "test_command" in repo:
                entry["test_command"] = repo["test_command"]
            if "build_command" in repo:
                entry["build_command"] = repo["build_command"]
            repos.append(entry)
    else:
        repos = [{"name": "app", "path": "."}]

    data: dict[str, object] = {
        "project_name": config.project_name,
        "repositories": repos,
        "story_types": list(DEFAULT_STORY_TYPES),
        "pipeline": {
            "max_feedback_rounds": DEFAULT_MAX_FEEDBACK_ROUNDS,
            "max_remediation_rounds": DEFAULT_MAX_REMEDIATION_ROUNDS,
            "exploration_mode": True,
            "verify_layers": list(DEFAULT_VERIFY_LAYERS),
        },
    }

    if config.github_owner is not None:
        data["github_owner"] = config.github_owner
    if config.github_repo is not None:
        data["github_repo"] = config.github_repo

    return data


def _deploy_directory_structure(
    resources_dir: Path,
    target_root: Path,
) -> list[str]:
    created: list[str] = []

    for item in sorted(resources_dir.rglob("*")):
        rel = item.relative_to(resources_dir)
        if rel.parts[0] == "templates":
            continue

        target = target_root / rel
        if item.is_dir() and not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            created.append(str(rel))

    return created


def _deploy_prompt_bindings(target_root: Path) -> list[str]:
    created: list[str] = []
    prompt_source_dir = _resources_internal_prompt_dir()
    prompt_target_dir = static_prompts_dir(target_root)

    for item in sorted(prompt_source_dir.iterdir()):
        if not item.is_file():
            continue
        target = prompt_target_dir / item.name
        create_or_replace_hardlink(item, target)
        created.append(str(target.relative_to(target_root)))

    return created


def install_agentkit(config: InstallConfig) -> InstallResult:
    root = config.project_root

    if not root.is_dir():
        raise ProjectError(
            f"Project root does not exist: {root}",
            detail={"project_root": str(root)},
        )

    ak_dir = root / ".agentkit"
    if ak_dir.exists():
        raise ProjectError(
            f"AgentKit is already installed in {root} "
            f"(.agentkit/ directory exists)",
            detail={"project_root": str(root), "agentkit_dir": str(ak_dir)},
        )

    resources_dir = _resources_target_project_dir()
    created = _deploy_directory_structure(resources_dir, root)
    created.extend(_deploy_prompt_bindings(root))

    cfg_dir = config_dir(root)
    if not cfg_dir.exists():
        cfg_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = project_config_path(root)
    yaml_data = _build_project_yaml(config)
    atomic_write_yaml(yaml_path, yaml_data)
    created.append(str(yaml_path.relative_to(root)))

    return InstallResult(
        success=True,
        project_root=root,
        created_files=tuple(created),
    )

__all__ = [
    "InstallConfig",
    "InstallResult",
    "install_agentkit",
]
