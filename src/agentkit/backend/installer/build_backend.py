"""PEP-517 backend that redirects non-venv installs into AgentKit's runtime."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hatchling import build as _hatchling

from agentkit.backend.installer.interpreter import (
    NotVirtualEnvironmentError,
    resolve_ak3_interpreter,
)
from agentkit.backend.installer.runtime_environment import (
    RuntimeEnvironmentError,
    ensure_runtime_environment,
    install_source_into_environment,
    runtime_root_from_config,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_SOURCE_ROOT = Path(__file__).resolve().parents[4]


def _redirect_global_install(
    config_settings: Mapping[str, object] | None,
    *,
    editable: bool,
) -> None:
    try:
        resolve_ak3_interpreter()
    except NotVirtualEnvironmentError:
        runtime_root = runtime_root_from_config(config_settings)
        environment = ensure_runtime_environment(runtime_root)
        install_source_into_environment(
            environment,
            _SOURCE_ROOT,
            editable=editable,
        )
        executable = environment.root / (
            "Scripts/agentkit.exe"
            if environment.interpreter.suffix == ".exe"
            else "bin/agentkit"
        )
        raise RuntimeEnvironmentError(
            "Refused the global AgentKit installation after installing AgentKit "
            f"and its declared dependencies into the dedicated runtime {environment.root}. "
            "Isolation is permanent: it protects the host from AgentKit's "
            "third-party dependency set, while the shared AK2 package name is an "
            f"additional collision risk. The isolated CLI is {executable}."
        ) from None


def get_requires_for_build_wheel(
    config_settings: dict[str, Any] | None = None,
) -> list[str]:
    """Return wheel build requirements after enforcing installation isolation."""
    _redirect_global_install(config_settings, editable=False)
    return _hatchling.get_requires_for_build_wheel(config_settings)


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    """Build a wheel only from AgentKit's isolated runtime."""
    _redirect_global_install(config_settings, editable=False)
    return _hatchling.build_wheel(
        wheel_directory,
        config_settings,
        metadata_directory,
    )


def get_requires_for_build_editable(
    config_settings: dict[str, Any] | None = None,
) -> list[str]:
    """Return editable requirements after enforcing installation isolation."""
    _redirect_global_install(config_settings, editable=True)
    return _hatchling.get_requires_for_build_editable(config_settings)


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    """Build an editable wheel only from AgentKit's isolated runtime."""
    _redirect_global_install(config_settings, editable=True)
    return _hatchling.build_editable(
        wheel_directory,
        config_settings,
        metadata_directory,
    )


build_sdist = _hatchling.build_sdist
get_requires_for_build_sdist = _hatchling.get_requires_for_build_sdist

__all__ = [
    "build_editable",
    "build_sdist",
    "build_wheel",
    "get_requires_for_build_editable",
    "get_requires_for_build_sdist",
    "get_requires_for_build_wheel",
]
