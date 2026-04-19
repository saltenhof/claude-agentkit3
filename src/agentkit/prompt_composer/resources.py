"""Resource access for bundled prompt templates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agentkit.exceptions import ProjectError

RESOURCE_DIR = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "internal"
    / "prompts"
)
MANIFEST_PATH = RESOURCE_DIR / "manifest.json"


def _manifest_path(project_root: Path | None = None) -> Path:
    if project_root is not None:
        candidate = project_root / "prompts" / "manifest.json"
        if candidate.is_file():
            return candidate
    return MANIFEST_PATH


def _load_manifest(project_root: Path | None = None) -> dict[str, object]:
    manifest_path = _manifest_path(project_root)
    if not manifest_path.is_file():
        raise ProjectError(
            f"Prompt manifest not found: {manifest_path}",
            detail={"path": str(manifest_path)},
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _manifest_entry(name: str, project_root: Path | None = None) -> dict[str, str]:
    manifest = _load_manifest(project_root)
    manifest_path = _manifest_path(project_root)
    templates = manifest.get("templates")
    if not isinstance(templates, dict):
        raise ProjectError(
            "Prompt manifest is missing a templates mapping",
            detail={"path": str(manifest_path)},
        )
    entry = templates.get(name)
    if not isinstance(entry, dict):
        raise ProjectError(
            f"Prompt template is not declared in manifest: {name}",
            detail={"template_name": name, "path": str(manifest_path)},
        )
    relpath = entry.get("relpath")
    sha256 = entry.get("sha256")
    if not isinstance(relpath, str) or not isinstance(sha256, str):
        raise ProjectError(
            f"Prompt manifest entry is malformed for template: {name}",
            detail={"template_name": name, "path": str(manifest_path)},
        )
    return {"relpath": relpath, "sha256": sha256}


def prompt_bundle_id(project_root: Path | None = None) -> str:
    """Return the identifier of the currently resolved prompt bundle."""

    manifest = _load_manifest(project_root)
    manifest_path = _manifest_path(project_root)
    bundle_id = manifest.get("bundle_id")
    if not isinstance(bundle_id, str) or not bundle_id:
        raise ProjectError(
            "Prompt manifest is missing bundle_id",
            detail={"path": str(manifest_path)},
        )
    return bundle_id


def prompt_bundle_version(project_root: Path | None = None) -> str:
    """Return the version of the currently resolved prompt bundle."""

    manifest = _load_manifest(project_root)
    manifest_path = _manifest_path(project_root)
    bundle_version = manifest.get("bundle_version")
    if not isinstance(bundle_version, str) or not bundle_version:
        raise ProjectError(
            "Prompt manifest is missing bundle_version",
            detail={"path": str(manifest_path)},
        )
    return bundle_version


def prompt_template_path(
    name: str,
    *,
    project_root: Path | None = None,
) -> Path:
    """Return the absolute filesystem path of a bundled prompt template."""

    relpath = _manifest_entry(name, project_root)["relpath"]
    manifest_path = _manifest_path(project_root)
    path = manifest_path.parent / Path(relpath).name
    if not path.is_file():
        path = RESOURCE_DIR.parent.parent / Path(relpath)
    if not path.is_file():
        raise ProjectError(
            f"Prompt template resource not found: {path}",
            detail={"template_name": name, "path": str(path)},
        )
    return path


def prompt_template_relpath(
    name: str,
    *,
    project_root: Path | None = None,
) -> str:
    """Return the bundle-relative path of a prompt template."""

    return _manifest_entry(name, project_root)["relpath"]


def load_prompt_template(
    name: str,
    *,
    project_root: Path | None = None,
) -> str:
    """Load a bundled prompt template as UTF-8 text."""

    return prompt_template_path(name, project_root=project_root).read_text(
        encoding="utf-8",
    )


def prompt_template_sha256(
    name: str,
    *,
    project_root: Path | None = None,
) -> str:
    """Return a stable SHA-256 digest of the template bytes."""

    content = load_prompt_template(name, project_root=project_root).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    expected = _manifest_entry(name, project_root)["sha256"]
    if digest != expected:
        raise ProjectError(
            f"Prompt template digest mismatch for {name}",
            detail={
                "template_name": name,
                "expected_sha256": expected,
                "actual_sha256": digest,
            },
        )
    return digest


__all__ = [
    "MANIFEST_PATH",
    "RESOURCE_DIR",
    "load_prompt_template",
    "prompt_bundle_id",
    "prompt_bundle_version",
    "prompt_template_path",
    "prompt_template_relpath",
    "prompt_template_sha256",
]
