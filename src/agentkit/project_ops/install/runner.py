"""Minimal AgentKit installer for target projects.

Creates the ``.agentkit/`` directory structure in a target project
and generates a ``project.yaml`` that is loadable by
:func:`agentkit.config.load_project_config`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.config.defaults import (
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    DEFAULT_MAX_REMEDIATION_ROUNDS,
    DEFAULT_STORY_TYPES,
    DEFAULT_VERIFY_LAYERS,
)
from agentkit.exceptions import ProjectError
from agentkit.project_ops.shared.file_ops import atomic_write_yaml, ensure_dir
from agentkit.project_ops.shared.paths import (
    HOOKS_DIR,
    PROMPTS_DIR,
    agentkit_dir,
    config_dir,
    project_config_path,
    stories_dir,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class InstallConfig:
    """Configuration for installing AgentKit into a target project.

    Attributes:
        project_name: Display name for the project.
        project_root: Filesystem path to the target project root.
        repositories: Optional list of repository descriptors.  Each
            entry is a dict with keys ``name``, ``path``, and optionally
            ``language``, ``test_command``, ``build_command``.
        github_owner: GitHub organisation or user owning the repo.
        github_repo: GitHub repository name.
    """

    project_name: str
    project_root: Path
    repositories: list[dict[str, str]] | None = None
    github_owner: str | None = None
    github_repo: str | None = None


@dataclass(frozen=True)
class InstallResult:
    """Result of an AgentKit installation.

    Attributes:
        success: Whether the installation completed without errors.
        project_root: Root directory of the installed project.
        created_files: Tuple of relative paths to all created files
            and directories.
        errors: Tuple of error messages (empty on success).
    """

    success: bool
    project_root: Path
    created_files: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)


def _build_project_yaml(config: InstallConfig) -> dict[str, object]:
    """Build the project.yaml data structure from install config.

    The resulting dict is directly serialisable to YAML and loadable
    by :func:`agentkit.config.load_project_config`.

    Args:
        config: Installation configuration.

    Returns:
        Dictionary matching the :class:`~agentkit.config.ProjectConfig`
        schema.
    """
    # Build repositories list -- default to single repo at "."
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


def install_agentkit(config: InstallConfig) -> InstallResult:
    """Install AgentKit into a target project.

    Creates the ``.agentkit/`` directory structure with:

    - ``.agentkit/config/project.yaml``
    - ``.agentkit/prompts/`` (empty directory)
    - ``.agentkit/hooks/`` (empty directory)
    - ``stories/`` (empty directory)

    Args:
        config: Installation configuration.

    Returns:
        :class:`InstallResult` with success status and list of
        created files/directories.

    Raises:
        ProjectError: If ``project_root`` does not exist or
            ``.agentkit/`` already exists (double-install guard).
    """
    root = config.project_root

    # 1. Validate project_root exists
    if not root.is_dir():
        raise ProjectError(
            f"Project root does not exist: {root}",
            detail={"project_root": str(root)},
        )

    # 2. Check .agentkit/ doesn't already exist
    ak_dir = agentkit_dir(root)
    if ak_dir.exists():
        raise ProjectError(
            f"AgentKit is already installed in {root} "
            f"(.agentkit/ directory exists)",
            detail={"project_root": str(root), "agentkit_dir": str(ak_dir)},
        )

    # 3. Create directory structure
    created: list[str] = []

    ensure_dir(config_dir(root))
    created.append(str(config_dir(root).relative_to(root)))

    prompts_path = root / PROMPTS_DIR
    ensure_dir(prompts_path)
    created.append(str(prompts_path.relative_to(root)))

    hooks_path = root / HOOKS_DIR
    ensure_dir(hooks_path)
    created.append(str(hooks_path.relative_to(root)))

    stories_path = stories_dir(root)
    ensure_dir(stories_path)
    created.append(str(stories_path.relative_to(root)))

    # 4. Generate project.yaml
    yaml_path = project_config_path(root)
    yaml_data = _build_project_yaml(config)
    atomic_write_yaml(yaml_path, yaml_data)
    created.append(str(yaml_path.relative_to(root)))

    return InstallResult(
        success=True,
        project_root=root,
        created_files=tuple(created),
    )
