"""Real package-install proofs for AgentKit's dedicated environment."""

from __future__ import annotations

import json
import os
import site
import subprocess
import sys
from pathlib import Path

import pytest

from agentkit.backend.installer.interpreter import (
    render_ak3_interpreter_command,
    resolve_ak3_interpreter,
)
from agentkit.backend.installer.project_structure import _resources_target_project_dir
from agentkit.backend.installer.runner import _deploy_static_resource_files


@pytest.mark.integration
@pytest.mark.parametrize(
    "relative_script",
    [
        Path("tools/agentkit/projectedge.py"),
        Path("tools/agentkit/concept_toolchain/check.py"),
        Path("tools/agentkit/concept_toolchain/semantic_gate.py"),
    ],
)
def test_materialized_target_project_cli_help_uses_isolated_interpreter(
    tmp_path: Path,
    relative_script: Path,
) -> None:
    """A foreign project receives help text bound to the actual AK3 runtime."""
    _deploy_static_resource_files(_resources_target_project_dir(), tmp_path)
    completed = subprocess.run(
        [str(resolve_ak3_interpreter()), str(tmp_path / relative_script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    expected = render_ak3_interpreter_command(relative_script.as_posix())
    assert f"usage: {expected}" in completed.stdout
    assert "usage: python " not in completed.stdout.lower()


def _base_interpreter() -> Path:
    """Return the throwaway non-venv interpreter this test may install into.

    **Never falls back to ``sys.base_prefix``.** This test drives a real ``pip
    install`` against whatever it returns. Falling back to the machine's own
    base interpreter would mean that a regression in the isolation logic --
    exactly the failure this test exists to catch -- installs AK3 globally. On
    a developer machine that overwrites AK2, which shares the ``agentkit``
    package name, and takes its Claude Code hooks with it.

    A test that damages the machine when it finds its bug is worse than no
    test. Without an explicitly nominated throwaway interpreter the test skips
    and says so.
    """
    explicit = os.environ.get("AGENTKIT_TEST_NON_VENV_INTERPRETER")
    if not explicit:
        pytest.skip(
            "AGENTKIT_TEST_NON_VENV_INTERPRETER is unset. This test performs a "
            "real pip install against a non-venv interpreter and must never "
            "target the machine's own base interpreter -- an isolation "
            "regression would install AK3 globally and overwrite AK2. Point "
            "the variable at a disposable interpreter (see "
            "var/ag3-189-reality-*/ for how one is built)."
        )
    interpreter = Path(explicit)
    if not interpreter.is_absolute() or not interpreter.is_file():
        raise RuntimeError(
            "AGENTKIT_TEST_NON_VENV_INTERPRETER must name an existing "
            "absolute interpreter path"
        )
    if interpreter == Path(sys.base_prefix) / ("python.exe" if os.name == "nt" else "bin/python"):
        raise RuntimeError(
            "AGENTKIT_TEST_NON_VENV_INTERPRETER points at this machine's own "
            "base interpreter; nominate a disposable one instead"
        )
    return interpreter


def _agentkit_artifacts(directory: Path) -> dict[str, tuple[int, int]]:
    if not directory.is_dir():
        return {}
    return {
        entry.name: (entry.stat().st_size, entry.stat().st_mtime_ns)
        for entry in directory.iterdir()
        if "agentkit" in entry.name.lower()
    }


def _base_purelib(base_interpreter: Path) -> Path:
    completed = subprocess.run(
        [
            str(base_interpreter),
            "-I",
            "-c",
            "import json,sysconfig; print(json.dumps(sysconfig.get_path('purelib')))",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return Path(json.loads(completed.stdout))


def _install_attempt(
    base_interpreter: Path,
    repository_root: Path,
    runtime_root: Path,
    temporary_root: Path,
    *,
    editable: bool,
    no_build_isolation: bool = False,
    pythonpath: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    temporary_root.mkdir(parents=True, exist_ok=True)
    command = [
        str(base_interpreter),
        "-m",
        "pip",
        "install",
        "--config-settings",
        f"agentkit.runtime-venv={runtime_root}",
    ]
    if no_build_isolation:
        command.append("--no-build-isolation")
    if editable:
        command.append("--editable")
    command.append(str(repository_root))
    environment = _pip_environment(temporary_root)
    if pythonpath is not None:
        environment["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(
        command,
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=900,
    )


def _pip_environment(temporary_root: Path) -> dict[str, str]:
    """Return an isolated pip environment without inherited warning controls."""
    environment = dict(os.environ)
    environment.update(
        {
            "PIP_CACHE_DIR": str(temporary_root / "pip-cache"),
            "TEMP": str(temporary_root),
            "TMP": str(temporary_root),
            "TMPDIR": str(temporary_root),
        }
    )
    environment.pop("VIRTUAL_ENV", None)
    environment.pop("PYTHONPATH", None)
    # pip and its vendored libraries still contain platform-default text reads.
    # The parent pytest process keeps both EncodingWarning guards enabled; only
    # this foreign package-manager subprocess drops them so pip can reach AK3's
    # build backend instead of failing inside its own cache implementation.
    environment.pop("PYTHONWARNDEFAULTENCODING", None)
    environment.pop("PYTHONWARNINGS", None)
    return environment


def _build_agentkit_wheel(
    repository_root: Path,
    wheel_directory: Path,
    temporary_root: Path,
) -> Path:
    wheel_directory.mkdir()
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheel_directory),
            str(repository_root),
        ],
        cwd=repository_root,
        env=_pip_environment(temporary_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=900,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    wheels = tuple(wheel_directory.glob("agentkit-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def _install_wheel_into_disposable_base(
    base_interpreter: Path,
    wheel: Path,
    temporary_root: Path,
) -> None:
    installed = subprocess.run(
        [
            str(base_interpreter),
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-deps",
            str(wheel),
        ],
        env=_pip_environment(temporary_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=900,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr


def _install_hatchling_target(
    base_interpreter: Path,
    target: Path,
    temporary_root: Path,
) -> None:
    installed = subprocess.run(
        [
            str(base_interpreter),
            "-m",
            "pip",
            "install",
            "--target",
            str(target),
            "hatchling",
        ],
        env=_pip_environment(temporary_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=900,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr


@pytest.mark.integration
def test_global_regular_and_editable_installs_redirect_to_one_dedicated_venv(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[3]
    base_interpreter = _base_interpreter()
    runtime_root = tmp_path / "agentkit-runtime"
    user_site = Path(site.getusersitepackages())
    base_purelib = _base_purelib(base_interpreter)
    before = {
        user_site: _agentkit_artifacts(user_site),
        base_purelib: _agentkit_artifacts(base_purelib),
    }

    regular = _install_attempt(
        base_interpreter,
        repository_root,
        runtime_root,
        tmp_path / "regular-temp",
        editable=False,
    )
    marker = runtime_root / "reuse-marker"
    marker.write_text("must survive", encoding="utf-8")
    editable = _install_attempt(
        base_interpreter,
        repository_root,
        runtime_root,
        tmp_path / "editable-temp",
        editable=True,
    )

    for attempt in (regular, editable):
        output = attempt.stdout + attempt.stderr
        assert attempt.returncode != 0
        assert "Refused the global AgentKit installation" in output
        assert "third-party dependency set" in output
        assert "AK2" in output
    assert marker.read_text(encoding="utf-8") == "must survive"
    runtime_interpreter = runtime_root / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    import_probe = subprocess.run(
        [
            str(runtime_interpreter),
            "-I",
            "-c",
            "import agentkit,mcp,pydantic,tomlkit,weaviate; print(agentkit.__version__)",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert import_probe.returncode == 0, import_probe.stderr
    assert import_probe.stdout.strip() == "0.1.0"
    after = {
        user_site: _agentkit_artifacts(user_site),
        base_purelib: _agentkit_artifacts(base_purelib),
    }
    assert after == before


@pytest.mark.integration
def test_unusable_existing_runtime_is_rejected_without_install_or_repair(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[3]
    runtime_root = tmp_path / "agentkit-runtime"
    runtime_root.mkdir()
    configuration = runtime_root / "pyvenv.cfg"
    configuration.write_text(
        "include-system-site-packages = true\n",
        encoding="utf-8",
    )

    attempt = _install_attempt(
        _base_interpreter(),
        repository_root,
        runtime_root,
        tmp_path / "rejected-temp",
        editable=False,
    )

    output = attempt.stdout + attempt.stderr
    assert attempt.returncode != 0
    assert "include-system-site-packages='true'" in output
    assert "refusing to repair or replace it" in output
    assert configuration.read_text(encoding="utf-8") == (
        "include-system-site-packages = true\n"
    )
    assert not (runtime_root / "Scripts" / "agentkit.exe").exists()
    assert not (runtime_root / "bin" / "agentkit").exists()


@pytest.mark.integration
def test_wheel_installed_for_non_venv_interpreter_is_not_usable(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[3]
    wheel = _build_agentkit_wheel(
        repository_root,
        tmp_path / "wheelhouse",
        tmp_path / "wheel-build",
    )

    target = tmp_path / "non-venv-wheel-target"
    installed = subprocess.run(
        [
            str(_base_interpreter()),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(target),
            str(wheel),
        ],
        env=_pip_environment(tmp_path / "wheel-install"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=900,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    source = f"import sys; sys.path.insert(0, {str(target)!r}); import agentkit"
    probe = subprocess.run(
        [str(_base_interpreter()), "-c", source],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert probe.returncode != 0
    assert "outside a virtual environment" in probe.stderr
    assert "third-party dependencies" in probe.stderr
    assert "dedicated virtual environment" in probe.stderr


@pytest.mark.integration
def test_system_site_packages_venv_rejects_import_and_module_entrypoint(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[3]
    base_interpreter = _base_interpreter()
    wheel = _build_agentkit_wheel(
        repository_root,
        tmp_path / "wheelhouse",
        tmp_path / "wheel-build",
    )
    _install_wheel_into_disposable_base(
        base_interpreter,
        wheel,
        tmp_path / "base-install",
    )
    environment_root = tmp_path / "system-site-venv"
    created = subprocess.run(
        [
            str(base_interpreter),
            "-m",
            "venv",
            "--system-site-packages",
            str(environment_root),
        ],
        env=_pip_environment(tmp_path / "venv-create"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    interpreter = environment_root / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )

    probes = (
        [str(interpreter), "-c", "import agentkit"],
        [str(interpreter), "-m", "agentkit.backend.cli.main", "--help"],
    )
    for command in probes:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert completed.returncode != 0
        assert "include-system-site-packages='true'" in completed.stderr


@pytest.mark.integration
def test_same_name_distribution_does_not_block_no_build_isolation_bootstrap(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[3]
    base_interpreter = _base_interpreter()
    wheel = _build_agentkit_wheel(
        repository_root,
        tmp_path / "wheelhouse",
        tmp_path / "wheel-build",
    )
    _install_wheel_into_disposable_base(
        base_interpreter,
        wheel,
        tmp_path / "base-install",
    )
    build_support = tmp_path / "build-support"
    _install_hatchling_target(
        base_interpreter,
        build_support,
        tmp_path / "build-support-install",
    )
    runtime_root = tmp_path / "agentkit-runtime"

    regular = _install_attempt(
        base_interpreter,
        repository_root,
        runtime_root,
        tmp_path / "regular-temp",
        editable=False,
        no_build_isolation=True,
        pythonpath=build_support,
    )
    editable = _install_attempt(
        base_interpreter,
        repository_root,
        runtime_root,
        tmp_path / "editable-temp",
        editable=True,
        no_build_isolation=True,
        pythonpath=build_support,
    )

    for attempt in (regular, editable):
        output = attempt.stdout + attempt.stderr
        assert attempt.returncode != 0
        assert "Refused the global AgentKit installation" in output
        assert "The isolated CLI is" in output
        assert "include-system-site-packages" not in output
    runtime_interpreter = runtime_root / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    probe = subprocess.run(
        [str(runtime_interpreter), "-I", "-c", "import agentkit; print(agentkit.__version__)"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "0.1.0"
