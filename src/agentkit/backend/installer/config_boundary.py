"""Byte-exact project-config boundary owned by the installer."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.config.loader import parse_project_config
from agentkit.backend.exceptions import ConfigError, ProjectError
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_CONFIGURATION_INVALID,
    REASON_VECTORDB_REQUIRED,
)
from agentkit.backend.installer.paths import project_config_path

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.config.models import ProjectConfig


@dataclass(frozen=True)
class ConfigBeforeImage:
    """Identity and content observed at the first strict config load."""

    path: Path
    existed: bool
    content: bytes | None
    digest: str
    resolved_target: Path | None


def _config_error_reason(exc: ConfigError) -> str:
    """Classify the one mandatory-VectorDB rejection without masking other faults."""
    cause = exc.__cause__
    if not isinstance(cause, ValidationError):
        return REASON_CONFIGURATION_INVALID
    for error in cause.errors(include_url=False):
        if (
            tuple(error["loc"]) == ("pipeline", "features", "vectordb")
            and error["input"] is False
        ):
            return REASON_VECTORDB_REQUIRED
    return REASON_CONFIGURATION_INVALID


def _read_error_reason(exc: OSError | UnicodeError | ConfigError) -> str:
    if isinstance(exc, ConfigError):
        return _config_error_reason(exc)
    return REASON_CONFIGURATION_INVALID


def capture_config_before_image(
    project_root: Path,
) -> tuple[ConfigBeforeImage, ProjectConfig | None]:
    """Capture and strictly parse the current project.yaml, if present."""
    path = project_config_path(project_root)
    if not path.exists() and not path.is_symlink():
        return (
            ConfigBeforeImage(
                path=path,
                existed=False,
                content=None,
                digest="",
                resolved_target=None,
            ),
            None,
        )
    if not path.is_file():
        raise ProjectError(
            f"Project configuration is not a readable file: {path}",
            detail={
                "reason": REASON_CONFIGURATION_INVALID,
                "config_path": str(path),
            },
        )
    try:
        resolved = path.resolve(strict=True)
        content = path.read_bytes()
        text = content.decode("utf-8")
        model = parse_project_config(text, source=str(path))
    except (OSError, UnicodeError, ConfigError) as exc:
        reason = _read_error_reason(exc)
        raise ProjectError(
            f"Project configuration is invalid: {path}: {exc}",
            detail={"reason": reason, "config_path": str(path)},
        ) from exc
    return (
        ConfigBeforeImage(
            path=path,
            existed=True,
            content=content,
            digest=hashlib.sha256(content).hexdigest(),
            resolved_target=resolved,
        ),
        model,
    )


def verify_config_before_first_effect(
    before: ConfigBeforeImage,
    candidate: ProjectConfig,
) -> None:
    """Re-read strictly and prove identity, bytes and model are unchanged."""
    path = before.path
    present = path.exists() or path.is_symlink()
    if not before.existed:
        if present:
            raise ProjectError(
                f"Project configuration appeared after validation: {path}",
                detail={
                    "reason": "configuration_changed",
                    "config_path": str(path),
                },
            )
        return
    if not path.is_file():
        raise ProjectError(
            f"Project configuration became unreadable after validation: {path}",
            detail={
                "reason": REASON_CONFIGURATION_INVALID,
                "config_path": str(path),
            },
        )
    try:
        resolved = path.resolve(strict=True)
        content = path.read_bytes()
        current = parse_project_config(content.decode("utf-8"), source=str(path))
    except (OSError, UnicodeError, ConfigError) as exc:
        reason = _read_error_reason(exc)
        raise ProjectError(
            f"Project configuration became invalid after validation: {path}: {exc}",
            detail={"reason": reason, "config_path": str(path)},
        ) from exc
    digest = hashlib.sha256(content).hexdigest()
    if (
        resolved != before.resolved_target
        or content != before.content
        or digest != before.digest
        or current != candidate
    ):
        raise ProjectError(
            f"Project configuration changed after validation: {path}",
            detail={"reason": "configuration_changed", "config_path": str(path)},
        )


__all__ = [
    "ConfigBeforeImage",
    "capture_config_before_image",
    "verify_config_before_first_effect",
]
