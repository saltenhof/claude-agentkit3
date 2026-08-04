"""Creation and validation of AgentKit's dedicated machine environment."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_PROBE_TIMEOUT_SECONDS = 30.0
_INSTALL_TIMEOUT_SECONDS = 900.0
_RUNTIME_CONFIG_KEY = "agentkit.runtime-venv"
_SOURCE_ROOT = Path(__file__).resolve().parents[4]
_MINIMUM_PYTHON_PATTERN = re.compile(
    r">=\s*(?P<major>(?a:\d+))\.(?P<minor>(?a:\d+))",
)


class RuntimeEnvironmentError(RuntimeError):
    """Raised when the dedicated environment cannot be created or trusted."""


@dataclass(frozen=True, slots=True)
class RuntimeEnvironment:
    """Validated dedicated environment and its interpreter."""

    root: Path
    interpreter: Path
    created: bool


def declared_minimum_python(source_root: Path = _SOURCE_ROOT) -> tuple[int, int]:
    """Read the runtime minimum from the package's ``requires-python`` field.

    The installer deliberately supports one declaration shape so a broadened
    specifier cannot silently acquire ambiguous minimum-version semantics.
    ``pyproject.toml`` remains the sole numeric source of truth.
    """
    declaration_path = source_root / "pyproject.toml"
    try:
        payload = tomllib.loads(declaration_path.read_text(encoding="utf-8"))
        project = payload["project"]
        if not isinstance(project, dict):
            raise TypeError("project must be a table")
        requires_python = project["requires-python"]
        if not isinstance(requires_python, str):
            raise TypeError("project.requires-python must be a string")
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeEnvironmentError(
            f"cannot read the Python runtime declaration from {declaration_path}: {exc}"
        ) from exc
    match = _MINIMUM_PYTHON_PATTERN.fullmatch(requires_python.strip())
    if match is None:
        raise RuntimeEnvironmentError(
            "project.requires-python must be one unambiguous major/minor lower "
            f"bound in the form '>=MAJOR.MINOR', got {requires_python!r}"
        )
    return int(match["major"]), int(match["minor"])


def default_runtime_environment_root() -> Path:
    """Return the platform-specific machine-local AgentKit environment root."""
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "AgentKit" / "runtime"
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / "agentkit" / "runtime"


def runtime_root_from_config(
    config_settings: Mapping[str, object] | None,
) -> Path:
    """Resolve the explicit PEP-517 test/operator override or the machine default."""
    if not config_settings or _RUNTIME_CONFIG_KEY not in config_settings:
        return default_runtime_environment_root()
    raw = config_settings[_RUNTIME_CONFIG_KEY]
    if isinstance(raw, list):
        if len(raw) != 1:
            raise RuntimeEnvironmentError(
                f"{_RUNTIME_CONFIG_KEY} must be specified exactly once"
            )
        raw = raw[0]
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeEnvironmentError(
            f"{_RUNTIME_CONFIG_KEY} must name a non-empty absolute path"
        )
    root = Path(raw)
    if not root.is_absolute():
        raise RuntimeEnvironmentError(
            f"{_RUNTIME_CONFIG_KEY} must be absolute, got {raw!r}"
        )
    return root


def environment_interpreter(environment_root: Path) -> Path:
    """Return the standard interpreter path for ``environment_root``."""
    if os.name == "nt":
        return environment_root / "Scripts" / "python.exe"
    return environment_root / "bin" / "python"


def _read_configuration(environment_root: Path) -> dict[str, str]:
    path = environment_root / "pyvenv.cfg"
    if not path.is_file():
        raise RuntimeEnvironmentError(
            f"existing runtime {environment_root} is unusable: pyvenv.cfg is missing; "
            "refusing to repair or replace it"
        )
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = raw_line.partition("=")
        if separator:
            values[key.strip().lower()] = value.strip().lower()
    if values.get("include-system-site-packages") != "false":
        actual = values.get("include-system-site-packages", "missing")
        raise RuntimeEnvironmentError(
            f"existing runtime {environment_root} is unusable: "
            f"include-system-site-packages={actual!r}; refusing to repair or replace it"
        )
    return values


def _probe_environment(
    environment_root: Path,
    *,
    minimum_python: tuple[int, int],
) -> Path:
    _read_configuration(environment_root)
    interpreter = environment_interpreter(environment_root)
    if not interpreter.is_file():
        raise RuntimeEnvironmentError(
            f"existing runtime {environment_root} is unusable: interpreter "
            f"{interpreter} is missing; refusing to repair or replace it"
        )
    source = (
        "import json,sys; "
        "print(json.dumps({'prefix': sys.prefix, 'base_prefix': sys.base_prefix, "
        "'version': list(sys.version_info[:2])}))"
    )
    try:
        completed = subprocess.run(
            [str(interpreter), "-I", "-c", source],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeEnvironmentError(
            f"existing runtime {environment_root} is unusable: interpreter probe "
            f"failed ({exc}); refusing to repair or replace it"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeEnvironmentError(
            f"existing runtime {environment_root} is unusable: interpreter probe "
            f"exited {completed.returncode}: {detail}; refusing to repair or replace it"
        )
    try:
        payload = json.loads(completed.stdout)
        prefix = Path(str(payload["prefix"])).resolve()
        base_prefix = Path(str(payload["base_prefix"])).resolve()
        version = tuple(int(part) for part in payload["version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeEnvironmentError(
            f"existing runtime {environment_root} is unusable: interpreter probe "
            f"returned invalid data; refusing to repair or replace it"
        ) from exc
    if prefix != environment_root.resolve() or prefix == base_prefix:
        raise RuntimeEnvironmentError(
            f"existing runtime {environment_root} is unusable: interpreter reports "
            f"prefix={prefix} and base_prefix={base_prefix}; refusing to repair or replace it"
        )
    if version < minimum_python:
        raise RuntimeEnvironmentError(
            f"existing runtime {environment_root} is unusable: Python "
            f"{version[0]}.{version[1]} is below "
            f"{minimum_python[0]}.{minimum_python[1]}; "
            "refusing to repair or replace it"
        )
    pip_probe = subprocess.run(
        [str(interpreter), "-I", "-m", "pip", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=_PROBE_TIMEOUT_SECONDS,
    )
    if pip_probe.returncode != 0:
        detail = (pip_probe.stderr or pip_probe.stdout).strip()
        raise RuntimeEnvironmentError(
            f"existing runtime {environment_root} is unusable: pip is unavailable "
            f"({detail}); refusing to repair or replace it"
        )
    return interpreter


def ensure_runtime_environment(environment_root: Path) -> RuntimeEnvironment:
    """Create a missing environment or validate an existing one without repair."""
    minimum_python = declared_minimum_python()
    if environment_root.exists():
        if not environment_root.is_dir():
            raise RuntimeEnvironmentError(
                f"runtime path {environment_root} exists but is not a directory; "
                "refusing to replace it"
            )
        return RuntimeEnvironment(
            root=environment_root,
            interpreter=_probe_environment(
                environment_root,
                minimum_python=minimum_python,
            ),
            created=False,
        )
    try:
        venv.EnvBuilder(with_pip=True, clear=False, symlinks=os.name != "nt").create(
            environment_root
        )
        interpreter = _probe_environment(
            environment_root,
            minimum_python=minimum_python,
        )
    except (OSError, subprocess.SubprocessError, RuntimeEnvironmentError) as exc:
        raise RuntimeEnvironmentError(
            f"could not create an isolated AgentKit runtime at {environment_root}: {exc}"
        ) from exc
    return RuntimeEnvironment(
        root=environment_root,
        interpreter=interpreter,
        created=True,
    )


def install_source_into_environment(
    environment: RuntimeEnvironment,
    source_root: Path,
    *,
    editable: bool,
) -> None:
    """Install AgentKit and its declared dependencies into ``environment``."""
    command = [str(environment.interpreter), "-I", "-m", "pip", "install"]
    if editable:
        command.append("--editable")
    command.append(str(source_root))
    child_environment = dict(os.environ)
    for inherited_key in ("PIP_BUILD_TRACKER", "PYTHONPATH", "VIRTUAL_ENV"):
        child_environment.pop(inherited_key, None)
    completed = subprocess.run(
        command,
        cwd=source_root,
        env=child_environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=_INSTALL_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeEnvironmentError(
            f"installation into dedicated runtime {environment.root} failed "
            f"with exit {completed.returncode}: {detail}"
        )


__all__ = [
    "RuntimeEnvironment",
    "RuntimeEnvironmentError",
    "declared_minimum_python",
    "default_runtime_environment_root",
    "ensure_runtime_environment",
    "environment_interpreter",
    "install_source_into_environment",
    "runtime_root_from_config",
]
