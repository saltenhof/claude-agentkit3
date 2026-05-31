"""Minimal AgentKit installer for target projects."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agentkit.config.defaults import (
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    DEFAULT_MAX_REMEDIATION_ROUNDS,
    DEFAULT_STORY_TYPES,
    DEFAULT_VERIFY_LAYERS,
)
from agentkit.exceptions import ProjectError
from agentkit.installer.codex_settings import write_codex_settings
from agentkit.installer.file_ops import (
    atomic_write_text,
    atomic_write_yaml,
    copy_file,
    create_or_replace_hardlink,
)
from agentkit.installer.paths import (
    AGENTKIT_DIR,
    AGENTKIT_TOOLS_DIR,
    CLAUDE_DIR,
    CODEX_DIR,
    STATIC_PROMPTS_DIR,
    STORIES_DIR,
    claude_settings_path,
    codex_config_path,
    config_dir,
    control_plane_config_path,
    manifests_dir,
    project_config_path,
    prompt_bundle_lock_path,
    prompt_bundle_store_dir,
    runtime_prompts_dir,
    static_prompts_dir,
    stories_dir,
)

PROMPT_MANIFEST_FILENAME = "manifest.json"
MISSING_TEMPLATES_MESSAGE = "Prompt bundle manifest is missing templates"
MALFORMED_TEMPLATE_ENTRY_MESSAGE = "Prompt bundle manifest template entry is malformed"
MISSING_TEMPLATE_RELPATH_MESSAGE = (
    "Prompt bundle manifest template entry is missing relpath"
)


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
    project_key: str
    project_name: str
    project_root: Path
    repositories: list[dict[str, str]] | None = None
    github_owner: str | None = None
    github_repo: str | None = None
    prompt_bundle_root: Path | None = None


@dataclass(frozen=True)
class InstallResult:
    success: bool
    project_root: Path
    created_files: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class UninstallResult:
    success: bool
    project_root: Path
    removed_files: tuple[str, ...] = ()
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
        "project_key": config.project_key,
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


def _resolve_prompt_source_dir(config: InstallConfig) -> Path:
    prompt_source_dir = (
        config.prompt_bundle_root
        if config.prompt_bundle_root is not None
        else _resources_internal_prompt_dir()
    )
    if not prompt_source_dir.is_dir():
        raise ProjectError(
            f"Prompt bundle root does not exist: {prompt_source_dir}",
            detail={"prompt_bundle_root": str(prompt_source_dir)},
        )
    manifest_path = prompt_source_dir / PROMPT_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ProjectError(
            "Prompt bundle root is missing "
            f"{PROMPT_MANIFEST_FILENAME}: {prompt_source_dir}",
            detail={"prompt_bundle_root": str(prompt_source_dir)},
        )
    return prompt_source_dir


def _load_prompt_bundle_manifest(
    prompt_source_dir: Path,
) -> tuple[dict[str, object], str]:
    manifest_path = prompt_source_dir / PROMPT_MANIFEST_FILENAME
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    bundle_id = manifest.get("bundle_id")
    bundle_version = manifest.get("bundle_version")
    templates = manifest.get("templates")
    if not isinstance(bundle_id, str) or not bundle_id:
        raise ProjectError(
            "Prompt bundle manifest is missing bundle_id",
            detail={"path": str(manifest_path)},
        )
    if not isinstance(bundle_version, str) or not bundle_version:
        raise ProjectError(
            "Prompt bundle manifest is missing bundle_version",
            detail={"path": str(manifest_path)},
        )
    if not isinstance(templates, dict):
        raise ProjectError(
            MISSING_TEMPLATES_MESSAGE,
            detail={"path": str(manifest_path)},
        )
    return manifest, manifest_text


def _ensure_prompt_bundle_store_entry(
    prompt_source_dir: Path,
) -> tuple[Path, dict[str, object], str]:
    manifest, manifest_text = _load_prompt_bundle_manifest(prompt_source_dir)
    bundle_id = str(manifest["bundle_id"])
    bundle_version = str(manifest["bundle_version"])
    canonical_root = prompt_bundle_store_dir(
        bundle_id,
        bundle_version,
    )
    canonical_manifest_path = canonical_root / PROMPT_MANIFEST_FILENAME
    source_digest = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()

    if canonical_manifest_path.is_file():
        existing_text = canonical_manifest_path.read_text(encoding="utf-8")
        existing_digest = hashlib.sha256(existing_text.encode("utf-8")).hexdigest()
        if existing_digest != source_digest:
            raise ProjectError(
                "Canonical prompt bundle store collision",
                detail={
                    "bundle_id": bundle_id,
                    "bundle_version": bundle_version,
                    "canonical_root": str(canonical_root),
                    "expected_manifest_sha256": source_digest,
                    "actual_manifest_sha256": existing_digest,
                },
            )
        return canonical_root, manifest, manifest_text

    canonical_root.mkdir(parents=True, exist_ok=True)
    templates = manifest["templates"]
    if not isinstance(templates, dict):  # pragma: no cover
        raise ProjectError(
            MISSING_TEMPLATES_MESSAGE,
            detail={"path": str(prompt_source_dir / PROMPT_MANIFEST_FILENAME)},
        )
    for entry in templates.values():
        if not isinstance(entry, dict):  # pragma: no cover
            raise ProjectError(
                MALFORMED_TEMPLATE_ENTRY_MESSAGE,
                detail={"path": str(prompt_source_dir / PROMPT_MANIFEST_FILENAME)},
            )
        relpath = entry.get("relpath")
        if not isinstance(relpath, str):  # pragma: no cover
            raise ProjectError(
                MISSING_TEMPLATE_RELPATH_MESSAGE,
                detail={"path": str(prompt_source_dir / PROMPT_MANIFEST_FILENAME)},
            )
        source = prompt_source_dir / Path(relpath).name
        copy_file(source, canonical_root / Path(relpath))
    copy_file(prompt_source_dir / PROMPT_MANIFEST_FILENAME, canonical_manifest_path)
    return canonical_root, manifest, manifest_text


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


def _deploy_static_resource_files(
    resources_dir: Path,
    target_root: Path,
) -> list[str]:
    created: list[str] = []

    for item in sorted(resources_dir.rglob("*")):
        rel = item.relative_to(resources_dir)
        if rel.parts[0] == "templates" or item.is_dir():
            continue

        target = target_root / rel
        if _copy_file_if_changed(item, target):
            created.append(str(rel))

    return created


def _deploy_prompt_bindings(target_root: Path, prompt_source_dir: Path) -> list[str]:
    created: list[str] = []
    prompt_target_dir = static_prompts_dir(target_root)
    manifest_path = prompt_source_dir / PROMPT_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    templates = manifest.get("templates")
    if not isinstance(templates, dict):
        raise ProjectError(
            MISSING_TEMPLATES_MESSAGE,
            detail={"path": str(manifest_path)},
        )

    manifest_target = prompt_target_dir / PROMPT_MANIFEST_FILENAME
    if not _file_contents_match(manifest_path, manifest_target):
        create_or_replace_hardlink(manifest_path, manifest_target)
        created.append(str(manifest_target.relative_to(target_root)))

    for entry in templates.values():
        if not isinstance(entry, dict):
            raise ProjectError(
                MALFORMED_TEMPLATE_ENTRY_MESSAGE,
                detail={"path": str(manifest_path)},
            )
        relpath = entry.get("relpath")
        if not isinstance(relpath, str):
            raise ProjectError(
                MISSING_TEMPLATE_RELPATH_MESSAGE,
                detail={"path": str(manifest_path)},
            )
        source = prompt_source_dir / Path(relpath)
        target = prompt_target_dir / Path(relpath).name
        if not _file_contents_match(source, target):
            create_or_replace_hardlink(source, target)
            created.append(str(target.relative_to(target_root)))

    return created


def _write_prompt_bundle_lock(
    target_root: Path,
    *,
    manifest: dict[str, object],
    manifest_text: str,
) -> str | None:
    """Update the project prompt-bundle binding (FK-50 §50.5).

    Delegates the actual binding update to the prompt-runtime top-surface
    ``PromptRuntime.update_binding`` (Owner-BC principle). Idempotence for
    ``created_files`` reporting is preserved by composing the would-be lock
    content via the shared ``build_prompt_bundle_lock_content`` and only
    delegating when it differs from the on-disk lock. The fail-closed path
    is not weakened: ``update_binding`` re-resolves the manifest from the
    installer-managed central store and raises on any inconsistency.

    Imported lazily to avoid an import cycle (``prompt_runtime`` imports
    ``installer.paths``; the installer package eagerly imports this runner).
    """
    from agentkit.prompt_runtime.runtime import (
        PromptRuntime,
        build_prompt_bundle_lock_content,
    )

    bundle_id = str(manifest["bundle_id"])
    bundle_version = str(manifest["bundle_version"])
    desired_content = build_prompt_bundle_lock_content(
        bundle_id=bundle_id,
        bundle_version=bundle_version,
        manifest_file=PROMPT_MANIFEST_FILENAME,
        manifest_text=manifest_text,
    )
    lock_path = prompt_bundle_lock_path(target_root)
    if lock_path.is_file() and (
        lock_path.read_text(encoding="utf-8") == desired_content
    ):
        return None
    PromptRuntime(target_root).update_binding(bundle_id, bundle_version)
    return str(lock_path.relative_to(target_root))


def _write_control_plane_config(target_root: Path) -> str | None:
    config_path = control_plane_config_path(target_root)
    content = (
        json.dumps(
            {
                "base_url": "https://127.0.0.1:9080",
                "ca_file": None,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if not _write_text_if_changed(
        config_path,
        content,
    ):
        return None
    return str(config_path.relative_to(target_root))


def _file_contents_match(source: Path, target: Path) -> bool:
    if not target.is_file():
        return False
    return source.read_bytes() == target.read_bytes()


def _copy_file_if_changed(source: Path, target: Path) -> bool:
    if _file_contents_match(source, target):
        return False
    copy_file(source, target)
    return True


def _write_text_if_changed(path: Path, content: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    atomic_write_text(path, content)
    return True


def _write_yaml_if_changed(path: Path, data: dict[str, object]) -> bool:
    if path.is_file():
        existing = yaml.safe_load(path.read_text(encoding="utf-8"))
        if existing == data:
            return False
    atomic_write_yaml(path, data)
    return True


def install_agentkit(config: InstallConfig) -> InstallResult:
    root = config.project_root

    if not root.is_dir():
        raise ProjectError(
            f"Project root does not exist: {root}",
            detail={"project_root": str(root)},
        )

    resources_dir = _resources_target_project_dir()
    prompt_source_dir = _resolve_prompt_source_dir(config)
    canonical_prompt_bundle_root, manifest, manifest_text = (
        _ensure_prompt_bundle_store_entry(prompt_source_dir)
    )
    created = _deploy_directory_structure(resources_dir, root)
    created.extend(_deploy_static_resource_files(resources_dir, root))
    created.extend(_deploy_prompt_bindings(root, canonical_prompt_bundle_root))

    # Runtime working directories that are intentionally empty right after a
    # fresh install. Git cannot track empty directories, so they are absent
    # from the resources/target_project scaffold and the scaffold-mirroring
    # deploy step never creates them. The installer therefore guarantees them
    # explicitly. This set is the mirror image of what ``uninstall_agentkit``
    # removes (keep both in sync):
    #   .agentkit/config    -- also receives files below; created here too
    #   .agentkit/prompts   -- FK-44 prompt-materialization root (prompt_instance_dir)
    #   .agentkit/manifests -- prompt-pin manifests
    #   stories             -- story working tree
    #   .claude/context     -- harness context dir (Claude Code)
    #   .claude/skills      -- harness skill bind point (FK-50 §50.5)
    for runtime_dir in (
        config_dir(root),
        runtime_prompts_dir(root),
        manifests_dir(root),
        stories_dir(root),
        root / CLAUDE_DIR / "context",
        root / CLAUDE_DIR / "skills",
    ):
        runtime_dir.mkdir(parents=True, exist_ok=True)

    prompt_lock = _write_prompt_bundle_lock(
        root,
        manifest=manifest,
        manifest_text=manifest_text,
    )
    if prompt_lock is not None:
        created.append(prompt_lock)
    control_plane_config = _write_control_plane_config(root)
    if control_plane_config is not None:
        created.append(control_plane_config)
    codex_settings = write_codex_settings(root)
    if codex_settings is not None and codex_settings not in created:
        created.append(codex_settings)

    yaml_path = project_config_path(root)
    yaml_data = _build_project_yaml(config)
    if _write_yaml_if_changed(yaml_path, yaml_data):
        created.append(str(yaml_path.relative_to(root)))

    return InstallResult(
        success=True,
        project_root=root,
        created_files=tuple(created),
    )


def _remove_file(path: Path, project_root: Path) -> list[str]:
    if not path.exists():
        return []
    path.unlink()
    return [str(path.relative_to(project_root))]


def _remove_tree(path: Path, project_root: Path) -> list[str]:
    if not path.exists():
        return []
    shutil.rmtree(path)
    return [str(path.relative_to(project_root))]


def _remove_empty_dir(path: Path, project_root: Path) -> list[str]:
    if not path.is_dir() or any(path.iterdir()):
        return []
    path.rmdir()
    return [str(path.relative_to(project_root))]


def uninstall_agentkit(project_root: Path) -> UninstallResult:
    """Remove AgentKit-managed install artifacts from a target project."""

    if not project_root.is_dir():
        raise ProjectError(
            f"Project root does not exist: {project_root}",
            detail={"project_root": str(project_root)},
        )

    removed: list[str] = []
    removed.extend(_remove_file(codex_config_path(project_root), project_root))
    removed.extend(_remove_empty_dir(project_root / CODEX_DIR, project_root))
    removed.extend(_remove_file(claude_settings_path(project_root), project_root))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR / "context", project_root))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR / "skills", project_root))
    removed.extend(_remove_empty_dir(project_root / CLAUDE_DIR, project_root))
    removed.extend(_remove_tree(project_root / AGENTKIT_DIR, project_root))
    removed.extend(_remove_tree(project_root / AGENTKIT_TOOLS_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / "tools", project_root))
    removed.extend(_remove_tree(project_root / STATIC_PROMPTS_DIR, project_root))
    removed.extend(_remove_empty_dir(project_root / STORIES_DIR, project_root))

    return UninstallResult(
        success=True,
        project_root=project_root,
        removed_files=tuple(removed),
    )


__all__ = [
    "InstallConfig",
    "InstallResult",
    "UninstallResult",
    "install_agentkit",
    "uninstall_agentkit",
]
