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
PROJECT_LOCK_RELPATH = Path(".agentkit") / "config" / "prompt-bundle.lock.json"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _binding_lock_path(project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    candidate = project_root / PROJECT_LOCK_RELPATH
    if candidate.is_file():
        return candidate
    return None


def _load_binding_lock(project_root: Path | None) -> dict[str, object] | None:
    lock_path = _binding_lock_path(project_root)
    if lock_path is None:
        return None
    return json.loads(lock_path.read_text(encoding="utf-8"))


def _validated_binding_lock(
    project_root: Path | None,
) -> dict[str, object] | None:
    lock = _load_binding_lock(project_root)
    if lock is None or project_root is None:
        return None

    manifest_file = lock.get("manifest_file")
    manifest_sha256 = lock.get("manifest_sha256")
    bundle_root = lock.get("bundle_root")
    if (
        not isinstance(manifest_file, str)
        or not isinstance(manifest_sha256, str)
        or not isinstance(bundle_root, str)
    ):
        raise ProjectError(
            "Prompt bundle lock is malformed",
            detail={"path": str(project_root / PROJECT_LOCK_RELPATH)},
        )

    manifest_path = Path(bundle_root) / Path(manifest_file)
    if not manifest_path.is_file():
        raise ProjectError(
            f"Prompt bundle lock points to missing manifest: {manifest_path}",
            detail={
                "path": str(project_root / PROJECT_LOCK_RELPATH),
                "manifest_path": str(manifest_path),
            },
        )

    actual_sha256 = _sha256_text(manifest_path.read_text(encoding="utf-8"))
    if actual_sha256 != manifest_sha256:
        raise ProjectError(
            "Prompt bundle lock manifest digest mismatch",
            detail={
                "path": str(project_root / PROJECT_LOCK_RELPATH),
                "manifest_path": str(manifest_path),
                "expected_sha256": manifest_sha256,
                "actual_sha256": actual_sha256,
            },
        )
    return lock


def prompt_manifest_sha256(project_root: Path | None = None) -> str:
    """Return the digest of the resolved prompt manifest."""

    manifest_path = _manifest_path(project_root)
    return _sha256_text(manifest_path.read_text(encoding="utf-8"))


def _manifest_path(project_root: Path | None = None) -> Path:
    lock = _validated_binding_lock(project_root)
    if lock is not None:
        bundle_root = lock.get("bundle_root")
        manifest_file = lock.get("manifest_file")
        if isinstance(bundle_root, str) and isinstance(manifest_file, str):
            candidate = Path(bundle_root) / Path(manifest_file)
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

    lock = _validated_binding_lock(project_root)
    manifest_path = _manifest_path(project_root)
    bundle_id = (
        lock.get("bundle_id")
        if lock is not None
        else _load_manifest(project_root).get("bundle_id")
    )
    if not isinstance(bundle_id, str) or not bundle_id:
        raise ProjectError(
            "Prompt manifest is missing bundle_id",
            detail={"path": str(manifest_path)},
        )
    return bundle_id


def prompt_bundle_version(project_root: Path | None = None) -> str:
    """Return the version of the currently resolved prompt bundle."""

    lock = _validated_binding_lock(project_root)
    manifest_path = _manifest_path(project_root)
    bundle_version = (
        lock.get("bundle_version")
        if lock is not None
        else _load_manifest(project_root).get("bundle_version")
    )
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
    lock = _validated_binding_lock(project_root)
    if lock is not None:
        bundle_root = lock.get("bundle_root")
        if isinstance(bundle_root, str):
            path = Path(bundle_root) / Path(relpath).name
        else:
            path = RESOURCE_DIR.parent.parent / Path(relpath)
    else:
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
    "PROJECT_LOCK_RELPATH",
    "RESOURCE_DIR",
    "load_prompt_template",
    "prompt_bundle_id",
    "prompt_manifest_sha256",
    "prompt_bundle_version",
    "prompt_template_path",
    "prompt_template_relpath",
    "prompt_template_sha256",
]
