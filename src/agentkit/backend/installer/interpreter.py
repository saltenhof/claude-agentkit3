"""Single owner of the interpreter used by every AgentKit entrypoint."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path


class InterpreterResolutionError(RuntimeError):
    """Raised when the running process is not bound to an isolated interpreter."""


class NotVirtualEnvironmentError(InterpreterResolutionError):
    """Raised when AgentKit was invoked by a global interpreter."""


def _venv_configuration(environment_root: Path) -> dict[str, str]:
    """Read the standard ``pyvenv.cfg`` as normalized key/value pairs."""
    configuration_path = environment_root / "pyvenv.cfg"
    if not configuration_path.is_file():
        raise InterpreterResolutionError(
            "AgentKit requires its dedicated virtual environment, but "
            f"{configuration_path} is missing. Global installations are refused "
            "to avoid contaminating the host with AgentKit and its dependencies."
        )
    configuration: dict[str, str] = {}
    for raw_line in configuration_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = raw_line.partition("=")
        if separator:
            configuration[key.strip().lower()] = value.strip().lower()
    return configuration


def resolve_ak3_interpreter() -> Path:
    """Return the absolute interpreter path of AgentKit's isolated runtime.

    This function is the sole production read of :data:`sys.executable` for
    AgentKit entrypoint dispatch. It also proves that the interpreter belongs to
    a virtual environment that cannot see system site-packages.

    Returns:
        Absolute path to the running virtual-environment interpreter.

    Raises:
        InterpreterResolutionError: If the process is global, the interpreter
            is missing, or the environment exposes system site-packages.
    """
    raw_interpreter = sys.executable
    if not raw_interpreter or not raw_interpreter.strip():
        raise InterpreterResolutionError(
            "Cannot resolve the AgentKit interpreter because sys.executable is empty."
        )
    if sys.prefix == sys.base_prefix:
        raise NotVirtualEnvironmentError(
            "AgentKit is running outside a virtual environment. Global execution "
            "is refused because AgentKit and its third-party dependencies must not "
            "contaminate the host installation; the shared AK2 package name adds a "
            "second, immediate collision risk. Install and run AgentKit in its "
            "dedicated virtual environment."
        )
    environment_root = Path(sys.prefix).absolute()
    configuration = _venv_configuration(environment_root)
    if configuration.get("include-system-site-packages") != "false":
        actual = configuration.get("include-system-site-packages", "missing")
        raise InterpreterResolutionError(
            "AgentKit's virtual environment is not isolated: "
            f"include-system-site-packages={actual!r} in "
            f"{environment_root / 'pyvenv.cfg'}. Refusing to use or repair it."
        )
    interpreter = Path(raw_interpreter).absolute()
    if not interpreter.is_file():
        raise InterpreterResolutionError(
            f"Cannot resolve the AgentKit interpreter: {interpreter} is not a file."
        )
    return interpreter


def ak3_python_command(module: str, *arguments: str) -> tuple[str, ...]:
    """Return an argv tuple bound to the single AgentKit interpreter owner."""
    if not module or any(character.isspace() for character in module):
        raise ValueError("module must be a non-empty Python module name")
    return (str(resolve_ak3_interpreter()), "-m", module, *arguments)


def ak3_interpreter_command(*arguments: str) -> tuple[str, ...]:
    """Return argv for a script or interpreter option without a PATH lookup."""
    return (str(resolve_ak3_interpreter()), *arguments)


def resolve_ak3_wrapper(wrapper_name: str) -> Path:
    """Return an installed console-script wrapper beside the AK3 interpreter.

    Args:
        wrapper_name: Distribution entry-point name without a platform suffix.

    Returns:
        Absolute path to the installed wrapper.

    Raises:
        ValueError: If ``wrapper_name`` is not a plain executable name.
    """
    if (
        not wrapper_name
        or Path(wrapper_name).name != wrapper_name
        or any(character.isspace() for character in wrapper_name)
    ):
        raise ValueError("wrapper_name must be a plain non-empty executable name")
    interpreter = resolve_ak3_interpreter()
    suffix = ".exe" if sys.platform == "win32" else ""
    return interpreter.parent / f"{wrapper_name}{suffix}"


def ak3_wrapper_command(wrapper_name: str, *arguments: str) -> tuple[str, ...]:
    """Return argv bound to an installed AgentKit console-script wrapper."""
    return (str(resolve_ak3_wrapper(wrapper_name)), *arguments)


def render_ak3_interpreter_command(*arguments: str) -> str:
    """Render a shell command bound to the isolated AgentKit interpreter."""
    command = ak3_interpreter_command(*arguments)
    if sys.platform == "win32":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def render_ak3_python_command(module: str, *arguments: str) -> str:
    """Render a ``python -m`` command bound to the AgentKit interpreter."""
    command = ak3_python_command(module, *arguments)
    if sys.platform == "win32":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def render_ak3_wrapper_command(wrapper_name: str, *arguments: str) -> str:
    """Render an installed AgentKit wrapper command without a PATH lookup."""
    command = ak3_wrapper_command(wrapper_name, *arguments)
    if sys.platform == "win32":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


__all__ = [
    "InterpreterResolutionError",
    "NotVirtualEnvironmentError",
    "ak3_interpreter_command",
    "ak3_python_command",
    "ak3_wrapper_command",
    "render_ak3_interpreter_command",
    "render_ak3_python_command",
    "render_ak3_wrapper_command",
    "resolve_ak3_interpreter",
    "resolve_ak3_wrapper",
]
