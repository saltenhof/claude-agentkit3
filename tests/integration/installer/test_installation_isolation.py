"""Real package-install proofs for AgentKit's dedicated environment."""

from __future__ import annotations

import json
import os
import site
import subprocess
import sys
from pathlib import Path

import pytest


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
    if editable:
        command.append("--editable")
    command.append(str(repository_root))
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
