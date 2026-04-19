"""Minimal AgentKit installer for target projects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from agentkit.config.defaults import (
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    DEFAULT_MAX_REMEDIATION_ROUNDS,
    DEFAULT_STORY_TYPES,
    DEFAULT_VERIFY_LAYERS,
)
from agentkit.exceptions import ProjectError
from agentkit.installer.file_ops import (
    atomic_write_text,
    atomic_write_yaml,
    copy_file,
    create_or_replace_hardlink,
)
from agentkit.installer.paths import (
    config_dir,
    project_config_path,
    prompt_bundle_lock_path,
    prompt_bundle_store_dir,
    static_prompts_dir,
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
    manifest_path = prompt_source_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ProjectError(
            f"Prompt bundle root is missing manifest.json: {prompt_source_dir}",
            detail={"prompt_bundle_root": str(prompt_source_dir)},
        )
    return prompt_source_dir


def _load_prompt_bundle_manifest(
    prompt_source_dir: Path,
) -> tuple[dict[str, object], str]:
    manifest_path = prompt_source_dir / "manifest.json"
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
            "Prompt bundle manifest is missing templates",
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
    canonical_manifest_path = canonical_root / "manifest.json"
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
            "Prompt bundle manifest is missing templates",
            detail={"path": str(prompt_source_dir / "manifest.json")},
        )
    for entry in templates.values():
        if not isinstance(entry, dict):  # pragma: no cover
            raise ProjectError(
                "Prompt bundle manifest template entry is malformed",
                detail={"path": str(prompt_source_dir / "manifest.json")},
            )
        relpath = entry.get("relpath")
        if not isinstance(relpath, str):  # pragma: no cover
            raise ProjectError(
                "Prompt bundle manifest template entry is missing relpath",
                detail={"path": str(prompt_source_dir / "manifest.json")},
            )
        source = prompt_source_dir / Path(relpath).name
        copy_file(source, canonical_root / Path(relpath))
    copy_file(prompt_source_dir / "manifest.json", canonical_manifest_path)
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


def _deploy_prompt_bindings(target_root: Path, prompt_source_dir: Path) -> list[str]:
    created: list[str] = []
    prompt_target_dir = static_prompts_dir(target_root)
    manifest_path = prompt_source_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    templates = manifest.get("templates")
    if not isinstance(templates, dict):
        raise ProjectError(
            "Prompt bundle manifest is missing templates",
            detail={"path": str(manifest_path)},
        )

    manifest_target = prompt_target_dir / "manifest.json"
    create_or_replace_hardlink(manifest_path, manifest_target)
    created.append(str(manifest_target.relative_to(target_root)))

    for entry in templates.values():
        if not isinstance(entry, dict):
            raise ProjectError(
                "Prompt bundle manifest template entry is malformed",
                detail={"path": str(manifest_path)},
            )
        relpath = entry.get("relpath")
        if not isinstance(relpath, str):
            raise ProjectError(
                "Prompt bundle manifest template entry is missing relpath",
                detail={"path": str(manifest_path)},
            )
        source = prompt_source_dir / Path(relpath)
        target = prompt_target_dir / Path(relpath).name
        create_or_replace_hardlink(source, target)
        created.append(str(target.relative_to(target_root)))

    return created


def _write_prompt_bundle_lock(
    target_root: Path,
    *,
    canonical_bundle_root: Path,
    manifest: dict[str, object],
    manifest_text: str,
) -> str:
    manifest_sha256 = hashlib.sha256(
        manifest_text.encode("utf-8"),
    ).hexdigest()
    lock_data = {
        "bundle_id": manifest["bundle_id"],
        "bundle_version": manifest["bundle_version"],
        "binding_root": "prompts",
        "manifest_file": "manifest.json",
        "manifest_sha256": manifest_sha256,
        "templates": manifest["templates"],
    }
    lock_path = prompt_bundle_lock_path(target_root)
    atomic_write_text(
        lock_path,
        json.dumps(lock_data, indent=2, sort_keys=True) + "\n",
    )
    return str(lock_path.relative_to(target_root))


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
    prompt_source_dir = _resolve_prompt_source_dir(config)
    canonical_prompt_bundle_root, manifest, manifest_text = (
        _ensure_prompt_bundle_store_entry(prompt_source_dir)
    )
    created = _deploy_directory_structure(resources_dir, root)
    created.extend(_deploy_prompt_bindings(root, canonical_prompt_bundle_root))

    cfg_dir = config_dir(root)
    if not cfg_dir.exists():
        cfg_dir.mkdir(parents=True, exist_ok=True)

    created.append(
        _write_prompt_bundle_lock(
            root,
            canonical_bundle_root=canonical_prompt_bundle_root,
            manifest=manifest,
            manifest_text=manifest_text,
        ),
    )

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
