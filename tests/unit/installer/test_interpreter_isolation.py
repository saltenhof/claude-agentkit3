"""Focused proofs for the dedicated AgentKit interpreter and environment."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
    REASON_RUNTIME_NOT_ISOLATED,
)
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    run_checkpoint_install,
)
from agentkit.backend.installer.interpreter import (
    InterpreterResolutionError,
    NotVirtualEnvironmentError,
    ak3_python_command,
    resolve_ak3_interpreter,
    resolve_ak3_wrapper,
)
from agentkit.backend.installer.runtime_environment import (
    RuntimeEnvironmentError,
    declared_minimum_python,
    ensure_runtime_environment,
)


def test_running_ak3_interpreter_is_absolute_and_isolated() -> None:
    interpreter = resolve_ak3_interpreter()

    assert interpreter.is_absolute()
    assert interpreter.is_file()
    assert ak3_python_command("agentkit.backend.cli.main") == (
        str(interpreter),
        "-m",
        "agentkit.backend.cli.main",
    )
    assert resolve_ak3_wrapper("agentkit-hook-claude").parent == interpreter.parent
    assert resolve_ak3_wrapper("agentkit-hook-codex").parent == interpreter.parent


def test_global_interpreter_is_rejected_with_both_isolation_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)

    with pytest.raises(NotVirtualEnvironmentError) as captured:
        resolve_ak3_interpreter()

    message = str(captured.value)
    assert "outside a virtual environment" in message
    assert "third-party dependencies" in message
    assert "AK2" in message


def test_missing_environment_is_created_and_reused_without_replacement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agentkit-runtime"

    created = ensure_runtime_environment(root)
    marker = root / "owner-marker"
    marker.write_text("preserve", encoding="utf-8")
    reused = ensure_runtime_environment(root)

    assert created.created is True
    assert reused.created is False
    assert reused.interpreter == created.interpreter
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_existing_nonisolated_environment_is_rejected_without_repair(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agentkit-runtime"
    root.mkdir()
    configuration = root / "pyvenv.cfg"
    configuration.write_text(
        "include-system-site-packages = true\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeEnvironmentError, match="include-system-site-packages='true'"):
        ensure_runtime_environment(root)

    assert configuration.read_text(encoding="utf-8") == (
        "include-system-site-packages = true\n"
    )
    assert not (root / "Scripts" / "python.exe").exists()
    assert not (root / "bin" / "python").exists()


def test_runtime_minimum_is_derived_from_requires_python(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=9.8"\n',
        encoding="utf-8",
    )

    assert declared_minimum_python(tmp_path) == (9, 8)


def test_runtime_minimum_rejects_non_ascii_digits(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=١.٢"\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeEnvironmentError, match="unambiguous major/minor"):
        declared_minimum_python(tmp_path)


def test_runtime_minimum_preserves_unicode_whitespace_support(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=\u00a09.8"\n',
        encoding="utf-8",
    )

    assert declared_minimum_python(tmp_path) == (9, 8)


def test_canonical_installer_funnel_rejects_isolation_before_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    config = make_config(
        project_root,
        bundle_store_root=tmp_path / "bundles",
        registration_repo=InMemoryRegistrationRepo(),
    )

    def _not_isolated() -> Path:
        raise InterpreterResolutionError("funnel isolation proof")

    def _dependencies_must_not_run() -> object:
        raise AssertionError("dependency preflight ran before isolation")

    monkeypatch.setattr(
        "agentkit.backend.installer.interpreter.resolve_ak3_interpreter",
        _not_isolated,
    )
    monkeypatch.setattr(
        "agentkit.backend.installer.dependency_preflight.check_runtime_dependencies",
        _dependencies_must_not_run,
    )

    result = run_checkpoint_install(config)

    assert result.success is False
    assert len(result.checkpoint_results) == 1
    assert result.checkpoint_results[0].reason == REASON_RUNTIME_NOT_ISOLATED
    assert "funnel isolation proof" in (result.checkpoint_results[0].detail or "")


def _write_gate_repository(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "gate-fixture"\n[project.scripts]\n'
        'agentkit-probe = "agentkit.probe:main"\n',
        encoding="utf-8",
    )
    owner = tmp_path / "src/agentkit/backend/installer/interpreter.py"
    owner.parent.mkdir(parents=True)
    owner.write_text(
        "import sys\ndef resolve_ak3_interpreter():\n    return sys.executable\n",
        encoding="utf-8",
    )
    package = tmp_path / "src/agentkit/__init__.py"
    package.write_text(
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def _enforce_installed_runtime_isolation():\n"
        "    resolve_ak3_interpreter()\n",
        encoding="utf-8",
    )
    entrypoint = tmp_path / "src/agentkit/probe.py"
    entrypoint.write_text(
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def main():\n"
        "    resolve_ak3_interpreter()\n",
        encoding="utf-8",
    )
    settings = tmp_path / "src/agentkit/bundles/target_project/.claude/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "command": (
                                        "__AK3_INTERPRETER__ "
                                        ".agentkit/hooks/pre_tool_use.py"
                                    )
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return entrypoint


def _run_entrypoint_gate(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    repository_root = Path(__file__).parents[3]
    gate = repository_root / "scripts" / "ci" / "check_interpreter_entrypoints.py"
    return subprocess.run(
        [sys.executable, str(gate), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_interpreter_entrypoint_gate_rejects_direct_sys_executable(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + "import sys\nselected = sys.executable\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "src/agentkit/probe.py:5: direct sys.executable read" in completed.stderr


@pytest.mark.parametrize("command", ["python", "python3"])
def test_interpreter_entrypoint_gate_rejects_bare_python_subprocess(
    tmp_path: Path,
    command: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + f"import subprocess\nsubprocess.run([{command!r}, '-V'])\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert f"subprocess launches bare {command!r} from PATH" in completed.stderr


def test_interpreter_entrypoint_gate_follows_bare_python_assignment(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + "import subprocess\ncommand = ['python', '-V']\nsubprocess.run(command)\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "subprocess launches bare 'python' from PATH" in completed.stderr


def test_interpreter_entrypoint_gate_rejects_name_match_without_owner_import(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        "def resolve_ak3_interpreter():\n    return None\n"
        "def main():\n    resolve_ak3_interpreter()\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "does not call an API imported from" in completed.stderr


def test_interpreter_entrypoint_gate_rejects_owner_call_outside_entrypoint(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def unrelated_helper():\n    resolve_ak3_interpreter()\n"
        "def main():\n    return 0\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "function main() does not call an API imported from" in completed.stderr


def test_interpreter_entrypoint_gate_derives_new_hook_from_pyproject(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    declaration = tmp_path / "pyproject.toml"
    declaration.write_text(
        declaration.read_text(encoding="utf-8")
        + 'agentkit-hook-new = "agentkit.new_hook:main"\n',
        encoding="utf-8",
    )
    hook = tmp_path / "src/agentkit/new_hook.py"
    hook.write_text("def main():\n    return 0\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert (
        "entrypoint 'agentkit-hook-new' function main() does not call an API imported from"
        in completed.stderr
    )
