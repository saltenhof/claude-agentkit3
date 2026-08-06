"""Focused proofs for the dedicated AgentKit interpreter and environment."""

from __future__ import annotations

import json
import os
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
    assert resolve_ak3_wrapper("agentkit").parent == interpreter.parent


@pytest.mark.parametrize(
    "entry_kind",
    ["missing", "directory", "symlink", "junction"],
)
def test_wrapper_resolution_rejects_non_regular_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entry_kind: str,
) -> None:
    interpreter = tmp_path / ("python.exe" if sys.platform == "win32" else "python")
    interpreter.write_bytes(b"")
    wrapper = tmp_path / ("agentkit.exe" if sys.platform == "win32" else "agentkit")
    if entry_kind == "directory":
        wrapper.mkdir()
    elif entry_kind == "symlink":
        target = tmp_path / "external-agentkit"
        target.write_bytes(b"")
        try:
            wrapper.symlink_to(target)
        except OSError as exc:
            pytest.skip(f"symlink creation is unavailable: {exc}")
    elif entry_kind == "junction":
        wrapper.write_bytes(b"")
        real_isjunction = os.path.isjunction
        monkeypatch.setattr(
            os.path,
            "isjunction",
            lambda path: Path(path) == wrapper or real_isjunction(path),
        )
    monkeypatch.setattr(
        "agentkit.backend.installer.interpreter.resolve_ak3_interpreter",
        lambda: interpreter,
    )

    with pytest.raises(
        InterpreterResolutionError,
        match="is not a regular file",
    ):
        resolve_ak3_wrapper("agentkit")


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
        '[project]\nname = "gate-fixture"\nrequires-python = ">=3.14"\n'
        "[project.scripts]\n"
        'agentkit-probe = "agentkit.probe:main"\n',
        encoding="utf-8",
    )
    owner = tmp_path / "src/agentkit/backend/installer/interpreter.py"
    owner.parent.mkdir(parents=True)
    owner.write_text(
        "import sys\ndef resolve_ak3_interpreter():\n    return sys.executable\n",
        encoding="utf-8",
    )
    _write_gate_version_policy(tmp_path, "1.0.0")
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
                                    "type": "command",
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
    bundle = tmp_path / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "bundle_id": "fixture-core",
                "bundle_version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    (bundle / "SKILL.md").write_text(
        "```bash\n{{AK3_WRAPPER}} --version\n```\n",
        encoding="utf-8",
    )
    return entrypoint


def _write_gate_version_policy(tmp_path: Path, floor: str) -> None:
    policy = tmp_path / "src/agentkit/backend/skills/version_policy.py"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        "from packaging.version import InvalidVersion, Version\n"
        f'MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS = {{"fixture-core": {floor!r}}}\n'
        "def assess_bundle_version(bundle_id, bundle_version):\n"
        "    minimum = MINIMUM_CONFORM_SKILL_BUNDLE_VERSIONS.get(bundle_id)\n"
        "    if minimum is None:\n"
        "        return None, True, True\n"
        "    try:\n"
        "        candidate = Version(bundle_version)\n"
        "        required = Version(minimum)\n"
        "    except InvalidVersion:\n"
        "        return minimum, False, False\n"
        "    return minimum, True, candidate >= required\n",
        encoding="utf-8",
    )


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


@pytest.mark.parametrize(
    "command",
    ["python", "python3", "py", "py.exe", "python3.14", "python3.14.exe"],
)
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


@pytest.mark.parametrize("command", ["py", "python3.14"])
def test_interpreter_entrypoint_gate_rejects_bare_python_parameter_default(
    tmp_path: Path,
    command: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + f"def launch(command: str = {command!r}):\n    return command\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert (
        f"callable default contains forbidden selector literal {command!r}"
        in completed.stderr
    )


def test_interpreter_entrypoint_gate_does_not_claim_implementation_specific_name(
    tmp_path: Path,
) -> None:
    """PyPy is outside the named CPython/Windows-launcher selector contract."""
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + "import subprocess\nsubprocess.run(['pypy', '-V'])\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 0, completed.stderr


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


@pytest.mark.parametrize("command", ["agentkit", "agentkit-probe"])
def test_interpreter_entrypoint_gate_rejects_wrapper_subprocess(
    tmp_path: Path,
    command: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + f"import subprocess\nsubprocess.run([{command!r}, 'status'])\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert f"subprocess launches bare {command!r} from PATH" in completed.stderr


def test_interpreter_entrypoint_gate_folds_subprocess_selector_constant(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + "import subprocess\n"
        + 'command = "py" + "thon"\n'
        + "subprocess.run([command, '-m', 'agentkit.backend.cli.main'])\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "subprocess launches bare 'python' from PATH" in completed.stderr


def test_interpreter_entrypoint_gate_reports_undecidable_subprocess_selector(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + "import subprocess\n"
        + 'suffix = read_suffix()\ncommand = "agentkit" + suffix\n'
        + "subprocess.run([command, 'status'])\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "undecidable subprocess command expression" in completed.stderr
    assert "raw text: '\"agentkit\" + suffix'" in completed.stderr


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\ndef f(subprocess):\n    subprocess.run(['agentkit', 'status'])\n",
        "from subprocess import run\ndef f(run):\n    run(['python', '-V'])\n",
        "import subprocess\nsubprocess = object()\nsubprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "if enabled:\n"
        "    subprocess = runner_a\n"
        "else:\n"
        "    subprocess = runner_b\n"
        "subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "while True:\n"
        "    subprocess = custom_runner\n"
        "    break\n"
        "subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "for subprocess in runners:\n"
        "    pass\n"
        "subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "with runner_context() as subprocess:\n"
        "    pass\n"
        "subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "try:\n"
        "    risky()\n"
        "except RuntimeError as subprocess:\n"
        "    pass\n"
        "subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "try:\n"
        "    risky()\n"
        "    subprocess = custom_runner\n"
        "except RuntimeError:\n"
        "    pass\n"
        "subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "disabled and (subprocess := custom_runner)\n"
        "subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "[None for item in items if (subprocess := custom_runner)]\n"
        "subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\nimport custom_runner as subprocess\n"
        "subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "def f():\n"
        "    global subprocess\n"
        "    subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "def outer():\n"
        "    subprocess = custom_runner\n"
        "    def inner():\n"
        "        nonlocal subprocess\n"
        "        subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "match mode:\n"
        "    case subprocess:\n"
        "        pass\n"
        "subprocess.run(['agentkit', 'status'])\n",
    ],
)
def test_interpreter_entrypoint_gate_reports_rebound_subprocess_name_as_undecidable(
    tmp_path: Path,
    source: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8") + source,
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "undecidable subprocess call provenance may launch bare" in completed.stderr
    assert "raw call:" in completed.stderr


def test_interpreter_entrypoint_gate_still_rejects_provenance_backed_subprocess_alias(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + "import subprocess as process\n"
        + "process.run(['agentkit', 'status'])\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "subprocess launches bare 'agentkit' from PATH" in completed.stderr


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\n"
        "def configure():\n"
        "    subprocess = custom_runner\n"
        "subprocess.run(['agentkit', 'status'])\n",
        "import subprocess\n"
        "[None for subprocess in runners]\n"
        "subprocess.run(['agentkit', 'status'])\n",
    ],
)
def test_interpreter_entrypoint_gate_isolates_rebindings_outside_the_scope_chain(
    tmp_path: Path,
    source: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8") + source,
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "subprocess launches bare 'agentkit' from PATH" in completed.stderr


def test_interpreter_entrypoint_gate_reports_conditional_selector_assignment(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + "import subprocess\n"
        + "if enabled:\n"
        + '    command = "agentkit"\n'
        + "subprocess.run([command, 'status'])\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "src/agentkit/probe.py:6: undecidable subprocess command binding" in completed.stderr
    assert "raw assignment: 'command = \"agentkit\"'" in completed.stderr


def test_interpreter_entrypoint_gate_ignores_selector_like_assignment_target(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + "import subprocess\n"
        + "if enabled:\n"
        + "    agentkit = resolve_absolute_command()\n"
        + "subprocess.run([agentkit, 'status'])\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 0, completed.stderr


def test_interpreter_entrypoint_gate_reports_multiply_assigned_selector_candidate(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + "import subprocess\n"
        + 'command = "agentkit"\n'
        + 'command = configured_command\n'
        + "subprocess.run([command, 'status'])\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "src/agentkit/probe.py:5: undecidable subprocess command binding" in completed.stderr
    assert "raw assignment: 'command = \"agentkit\"'" in completed.stderr


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


def test_interpreter_entrypoint_gate_requires_module_level_declared_callable(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "class Nested:\n"
        "    def main(self):\n"
        "        resolve_ak3_interpreter()\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "declared entrypoint 'agentkit-probe' has no function main()" in completed.stderr


def test_interpreter_entrypoint_gate_does_not_leak_owner_import_from_helper(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        "def helper():\n"
        "    from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "    resolve_ak3_interpreter()\n"
        "def main():\n"
        "    resolve_ak3_interpreter()\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "function main() does not call an API imported from" in completed.stderr


@pytest.mark.parametrize(
    "source",
    [
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def main(resolve_ak3_interpreter):\n"
        "    resolve_ak3_interpreter()\n",
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def main(value=resolve_ak3_interpreter()):\n"
        "    return value\n",
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def main():\n"
        "    callback = lambda: resolve_ak3_interpreter()\n"
        "    return callback\n",
        "import agentkit.backend.installer.interpreter as owner\n"
        "def main(owner):\n"
        "    owner.resolve_ak3_interpreter()\n",
        "import agentkit.backend.installer.interpreter as owner\n"
        "def main():\n"
        "    owner.resolve_ak3_interpreter()\n"
        "    owner = None\n",
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def main():\n"
        "    def nested(value=resolve_ak3_interpreter()):\n"
        "        return value\n"
        "    return nested\n",
    ],
    ids=[
        "parameter-shadow",
        "default-expression",
        "uninvoked-lambda",
        "module-alias-parameter-shadow",
        "later-local-shadow",
        "nested-default-expression",
    ],
)
def test_interpreter_entrypoint_gate_requires_direct_bound_owner_call(
    tmp_path: Path,
    source: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(source, encoding="utf-8")

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


def test_interpreter_entrypoint_gate_rejects_ruff_python_target_override(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    declaration = tmp_path / "pyproject.toml"
    declaration.write_text(
        declaration.read_text(encoding="utf-8")
        + '[tool.ruff]\ntarget-version = "py314"\n',
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "tool.ruff.target-version duplicates and overrides" in completed.stderr


@pytest.mark.parametrize(
    "selector",
    ["python", "py", "py.exe", "python3.14", "python3.14.exe"],
)
def test_interpreter_entrypoint_gate_rejects_bare_python_in_productive_bundle(
    tmp_path: Path,
    selector: str,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(
        f"```bash\n{selector} -m agentkit.probe\n```\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert (
        f"skill code fence 1 contains forbidden selector word {selector!r}"
        in completed.stderr
    )


@pytest.mark.parametrize(
    ("instruction", "selector"),
    [
        ("Python -m agentkit.probe", "Python"),
        ("PYTHON.EXE -m agentkit.probe", "PYTHON.EXE"),
        ("pYtHoN -V", "pYtHoN"),
        ("AgentKit status", "AgentKit"),
        ("AGENTKIT.EXE status", "AGENTKIT.EXE"),
    ],
)
def test_interpreter_entrypoint_gate_rejects_case_insensitive_inline_skill_command(
    tmp_path: Path,
    instruction: str,
    selector: str,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(
        f"Source A: `{instruction}` performs the operation.\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert (
        "SKILL.md:1: skill inline prose contains command-like forbidden "
        f"selector {selector!r}"
    ) in completed.stderr


@pytest.mark.parametrize(
    "prose",
    [
        "Story persistence remains owned by AgentKit runtime components.\n",
        "Mechanical checks are handled by deterministic Python modules.\n",
    ],
)
def test_interpreter_entrypoint_gate_allows_case_insensitive_product_prose(
    tmp_path: Path,
    prose: str,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(prose, encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("relative_path", "source"),
    [
        (
            "src/agentkit/bundles/target_project/tools/agentkit/projectedge.py",
            "import argparse\n"
            "def main():\n"
            "    argparse.ArgumentParser(prog='python tools/agentkit/projectedge.py')\n",
        ),
        (
            "src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/check.py",
            'HELP = "Run as: python tools/agentkit/concept_toolchain/check.py"\n',
        ),
        (
            "src/agentkit/backend/vectordb/diagnostic.py",
            '"""Run with python -m agentkit.backend.vectordb.diagnostic."""\n'
            "if __name__ == '__main__':\n"
            "    pass\n",
        ),
    ],
)
def test_interpreter_entrypoint_gate_rejects_bare_python_in_productive_cli_text(
    tmp_path: Path,
    relative_path: str,
    source: str,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / relative_path
    cli_source.parent.mkdir(parents=True, exist_ok=True)
    cli_source.write_text(source, encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "productive CLI text publishes bare" in completed.stderr
    assert relative_path in completed.stderr


def test_interpreter_entrypoint_gate_audits_productive_cli_function_docstrings(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / "src/agentkit/diagnostic_cli.py"
    cli_source.write_text(
        "import argparse\n"
        "def main():\n"
        '    \"\"\"Run with python -m agentkit.diagnostic_cli.\"\"\"\n'
        "    return argparse.ArgumentParser()\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert (
        "src/agentkit/diagnostic_cli.py:3: productive CLI text publishes bare "
        "'python -m agentkit.diagnostic_cli' from PATH"
    ) in completed.stderr


def test_interpreter_entrypoint_gate_rejects_python_c_in_productive_cli_text(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / "src/agentkit/diagnostic_cli.py"
    cli_source.write_text(
        "import argparse\n"
        "def main():\n"
        "    return argparse.ArgumentParser(epilog='python -c import_agentkit')\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "productive CLI text publishes bare 'python -c' from PATH" in completed.stderr


def test_interpreter_entrypoint_gate_allows_dynamic_python_concept_prose(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / "src/agentkit/diagnostic_cli.py"
    cli_source.write_text(
        "import argparse\n"
        "def main(version):\n"
        "    return argparse.ArgumentParser(epilog=f'Python runtime version {version}')\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "selector",
    ["py", "py.exe", "python3.14", "python3.14.exe"],
)
def test_interpreter_entrypoint_gate_rejects_dynamic_python_path_command(
    tmp_path: Path,
    selector: str,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / "src/agentkit/diagnostic_cli.py"
    cli_source.write_text(
        "import argparse\n"
        "def main(mode):\n"
        f"    return argparse.ArgumentParser(epilog=f'{selector} {{mode}}')\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert (
        "undecidable productive CLI string expression: dynamic content is "
        f"combined with selector {selector!r}"
    ) in completed.stderr


def test_interpreter_entrypoint_gate_rejects_declared_wrapper_in_productive_cli_text(
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
    hook.write_text(
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def main():\n"
        "    resolve_ak3_interpreter()\n",
        encoding="utf-8",
    )
    cli_source = tmp_path / "src/agentkit/probe_help.py"
    cli_source.write_text(
        "import argparse\n"
        "def main():\n"
        "    argparse.ArgumentParser(epilog='agentkit-hook-new pre probe')\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert (
        "src/agentkit/probe_help.py:3: productive CLI text publishes bare "
        "'agentkit-hook-new pre probe' from PATH"
    ) in completed.stderr


def test_interpreter_entrypoint_gate_resolves_constant_name_in_cli_f_string(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    declaration = tmp_path / "pyproject.toml"
    declaration.write_text(
        declaration.read_text(encoding="utf-8")
        + 'agentkit = "agentkit.probe:main"\n',
        encoding="utf-8",
    )
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + "import argparse\n"
        + "def _dispatch_command(args):\n"
        + "    return {'status': lambda: 0}[args.command]()\n"
        + 'command = "agentkit"\n'
        + 'help_text = f"{command} status"\n'
        + "argparse.ArgumentParser(epilog=help_text)\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "productive CLI text publishes bare 'agentkit status' from PATH" in completed.stderr


def test_interpreter_entrypoint_gate_matches_wrapper_case_insensitively_with_exe(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    declaration = tmp_path / "pyproject.toml"
    declaration.write_text(
        declaration.read_text(encoding="utf-8")
        + 'agentkit-hook-claude = "agentkit.hook:main"\n',
        encoding="utf-8",
    )
    hook = tmp_path / "src/agentkit/hook.py"
    hook.write_text(
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def main():\n"
        "    resolve_ak3_interpreter()\n",
        encoding="utf-8",
    )
    cli_source = tmp_path / "src/agentkit/probe_help.py"
    cli_source.write_text(
        "import argparse\n"
        "HELP = 'AGENTKIT-HOOK-CLAUDE.EXE pre branch_guard'\n"
        "argparse.ArgumentParser(epilog=HELP)\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "'AGENTKIT-HOOK-CLAUDE.EXE pre branch_guard' from PATH" in completed.stderr


def test_interpreter_entrypoint_gate_ignores_wrapper_name_in_prose(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / "src/agentkit/probe_help.py"
    cli_source.write_text(
        "import argparse\n"
        "HELP = 'The agentkit command is unavailable'\n"
        "argparse.ArgumentParser(epilog=HELP)\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 0, completed.stderr


def test_interpreter_entrypoint_gate_matches_dispatched_cli_verb_outside_handler_map(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    declaration = tmp_path / "pyproject.toml"
    declaration.write_text(
        declaration.read_text(encoding="utf-8")
        + 'agentkit = "agentkit.general:main"\n',
        encoding="utf-8",
    )
    general = tmp_path / "src/agentkit/general.py"
    general.write_text(
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def main():\n"
        "    resolve_ak3_interpreter()\n"
        "def _dispatch_command(args):\n"
        "    handlers = {'status': lambda: 0}\n"
        "    if args.command == 'evidence':\n"
        "        return True, 0\n"
        "    return False, 0\n",
        encoding="utf-8",
    )
    cli_source = tmp_path / "src/agentkit/probe_help.py"
    cli_source.write_text(
        "import argparse\n"
        "HELP = 'AGENTKIT.EXE evidence assemble'\n"
        "argparse.ArgumentParser(epilog=HELP)\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "'AGENTKIT.EXE evidence' from PATH" in completed.stderr


@pytest.mark.parametrize(
    ("expression", "expected_line"),
    [
        ('(\n        "python "\n        "-m agentkit.probe"\n    )', 5),
        (
            '"\\n".join((\n'
            '        "Usage:",\n'
            "        (\n"
            '            "python "\n'
            '            "-m agentkit.probe"\n'
            "        ),\n"
            "    ))",
            7,
        ),
    ],
    ids=["implicit-concatenation", "literal-join"],
)
def test_interpreter_entrypoint_gate_rejects_composed_productive_cli_text(
    tmp_path: Path,
    expression: str,
    expected_line: int,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / "src/agentkit/composed_help.py"
    cli_source.write_text(
        "import argparse\n"
        "def main():\n"
        "    mode = 'strict'\n"
        f"    prog = {expression}\n"
        "    argparse.ArgumentParser(prog=prog)\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert (
        f"src/agentkit/composed_help.py:{expected_line}: productive CLI text "
        "publishes bare"
    ) in completed.stderr


@pytest.mark.parametrize(
    ("expression", "expected_line", "selector"),
    [
        ('f"python -m agentkit.probe {mode}"', 4, "python"),
        ('"python -m " + mode', 4, "python"),
        ('"agentkit {}".format(mode)', 4, "agentkit"),
        ('"{} {}".format(mode, "agentkit")', 4, "agentkit"),
        ('"agentkit %s" % mode', 4, "agentkit"),
        ('"{} status" % "agentkit"', 4, "agentkit"),
        ('"%s status" % ("agentkit",)', 4, "agentkit"),
    ],
    ids=[
        "f-string-dynamic-suffix",
        "binary-addition",
        "format-call",
        "format-static-argument",
        "percent-formatting",
        "percent-static-right-operand",
        "percent-nested-right-operand",
    ],
)
def test_interpreter_entrypoint_gate_reports_undecidable_cli_string_expression(
    tmp_path: Path,
    expression: str,
    expected_line: int,
    selector: str,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / "src/agentkit/dynamic_help.py"
    cli_source.write_text(
        "import argparse\n"
        "def main():\n"
        "    mode = read_mode()\n"
        f"    prog = {expression}\n"
        "    argparse.ArgumentParser(prog=prog)\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert (
        f"src/agentkit/dynamic_help.py:{expected_line}: undecidable productive "
        f"CLI string expression: dynamic content is combined with selector {selector!r}"
    ) in completed.stderr


def test_interpreter_entrypoint_gate_ignores_dynamic_non_selector_prefix(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / "src/agentkit/dynamic_prose.py"
    cli_source.write_text(
        "import argparse\n"
        "def main():\n"
        "    mood = 'resting'\n"
        "    help_text = f'The agentkittens are {mood}'\n"
        "    argparse.ArgumentParser(epilog=help_text)\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 0, completed.stderr


def test_interpreter_entrypoint_gate_recognizes_aliased_argument_parser(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / "src/agentkit/aliased_parser.py"
    cli_source.write_text(
        "from argparse import ArgumentParser as Parser\n"
        "Parser(prog='python -m agentkit.probe')\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "src/agentkit/aliased_parser.py:2: productive CLI text publishes bare" in completed.stderr


def test_interpreter_entrypoint_gate_recognizes_function_local_parser_alias(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / "src/agentkit/local_parser.py"
    cli_source.write_text(
        "def main():\n"
        "    from argparse import ArgumentParser as Parser\n"
        "    Parser(prog='python -m agentkit.probe')\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "src/agentkit/local_parser.py:3: productive CLI text publishes bare" in completed.stderr


@pytest.mark.parametrize(
    ("relative_path", "source", "expected_line"),
    [
        (
            "src/agentkit/tool/__main__.py",
            "HELP = 'python -m agentkit.probe'\n",
            1,
        ),
        (
            "src/agentkit/composite_main.py",
            "enabled = True\n"
            "if __name__ == '__main__' and enabled:\n"
            "    HELP = 'python -m agentkit.probe'\n",
            3,
        ),
    ],
    ids=["main-module", "composite-main-guard"],
)
def test_interpreter_entrypoint_gate_recognizes_direct_executable_surface(
    tmp_path: Path,
    relative_path: str,
    source: str,
    expected_line: int,
) -> None:
    _write_gate_repository(tmp_path)
    cli_source = tmp_path / relative_path
    cli_source.parent.mkdir(parents=True, exist_ok=True)
    cli_source.write_text(source, encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert f"{relative_path}:{expected_line}: productive CLI text publishes bare" in completed.stderr


@pytest.mark.parametrize(
    ("fence_text", "selector"),
    [
        ("echo python -m missing", "python"),
        ("PYTHON=python", "python"),
        ("'python'", "python"),
        ('echo "$(python -m missing)"', "python"),
        ("echo AGENTKIT-PROBE.EXE --help", "AGENTKIT-PROBE.EXE"),
        ("echo agentkit --help", "agentkit"),
    ],
    ids=[
        "argument",
        "assignment",
        "quoted",
        "substitution",
        "derived-wrapper",
        "base-wrapper",
    ],
)
def test_interpreter_entrypoint_gate_rejects_selector_word_anywhere_in_fence(
    tmp_path: Path,
    fence_text: str,
    selector: str,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(f"```not-a-shell\n{fence_text}\n```\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert (
        f"skill code fence 1 contains forbidden selector word {selector!r}"
        in completed.stderr
    )


def test_interpreter_entrypoint_gate_allows_placeholders_and_non_selector_words(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(
        "```text\n{{AK3_INTERPRETER}} --version\n"
        "{{AK3_WRAPPER}} --version\nagentkitten\n```\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "skill-fence exceptions: none" in completed.stdout
    assert "skill Markdown file(s)" in completed.stdout
    assert "code fence(s)" in completed.stdout


def test_interpreter_entrypoint_gate_allows_selector_as_module_or_path_component(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(
        "```text\n"
        "agentkit.backend.vectordb.wait_for_weaviate\n"
        "tools/agentkit/concept_toolchain/check.py\n"
        "tools\\agentkit\\concept_toolchain\\semantic_gate.py\n"
        "```\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "skill-fence exceptions: none" in completed.stdout


def test_interpreter_entrypoint_gate_rejects_python_m_agentkit_module_invocation(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text("```text\npython -m agentkit.probe\n```\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "contains forbidden selector word 'python'" in completed.stderr


def test_interpreter_entrypoint_gate_rejects_agentkit_story_invocation(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text("```text\nagentkit story list\n```\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "contains forbidden selector word 'agentkit'" in completed.stderr


def test_interpreter_entrypoint_gate_rejects_hyphenated_wrapper_invocation(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    declaration = tmp_path / "pyproject.toml"
    declaration.write_text(
        declaration.read_text(encoding="utf-8")
        + 'agentkit-hook-claude = "agentkit.hook:main"\n',
        encoding="utf-8",
    )
    hook = tmp_path / "src/agentkit/hook.py"
    hook.write_text(
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def main():\n"
        "    resolve_ak3_interpreter()\n",
        encoding="utf-8",
    )
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(
        "```text\nagentkit-hook-claude pre branch_guard\n```\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert (
        "contains forbidden selector word 'agentkit-hook-claude'"
        in completed.stderr
    )


@pytest.mark.parametrize(
    "command",
    ["./agentkit", r".\agentkit.exe"],
    ids=["posix-relative", "windows-relative"],
)
def test_interpreter_entrypoint_gate_rejects_relative_agentkit_executable_invocation(
    tmp_path: Path,
    command: str,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(f"```text\n{command}\n```\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    expected_selector = "agentkit.exe" if command.endswith(".exe") else "agentkit"
    assert (
        f"contains forbidden selector word {expected_selector!r}"
        in completed.stderr
    )


def test_interpreter_entrypoint_gate_audits_untagged_fence_and_textual_module_target(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text("```\npython -m\nmissing.module\n```\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "skill code fence 1 contains forbidden selector word 'python'" in completed.stderr
    assert "productive python -m target 'missing.module'" in completed.stderr


def test_interpreter_entrypoint_gate_audits_unclosed_fence_to_end_of_file(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text("```text\necho python\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "skill code fence 1 contains forbidden selector word 'python'" in completed.stderr


def test_interpreter_entrypoint_gate_rejects_missing_productive_module_target(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(
        "```bash\n{{AK3_INTERPRETER}} -m agentkit.missing\n```\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "productive python -m target 'agentkit.missing'" in completed.stderr
    assert "has no module file or package __main__.py" in completed.stderr


def test_interpreter_entrypoint_gate_ignores_bundle_below_productive_floor(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    _write_gate_version_policy(tmp_path, "1.1.0")
    bundle = tmp_path / "src/agentkit/bundles/skill_bundles/fixture-core/1.1.0"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"bundle_id": "fixture-core", "bundle_version": "1.1.0"}),
        encoding="utf-8",
    )
    (bundle / "SKILL.md").write_text(
        "```bash\n{{AK3_WRAPPER}} --version\n```\n",
        encoding="utf-8",
    )
    old = tmp_path / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    old.write_text("```bash\npython -m agentkit.missing\n```\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "2 shipped immutable bundle version(s)" in completed.stdout
    assert "1 productive skill bundle version(s)" in completed.stdout


def test_interpreter_entrypoint_gate_rejects_floor_without_productive_bundle(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    _write_gate_version_policy(tmp_path, "9.0.0")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "no valid productive bundle version satisfies minimum 9.0.0" in completed.stderr


def test_interpreter_entrypoint_gate_rejects_numeric_concept_floor_authority(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    concept = (
        tmp_path
        / "concept/_meta/decisions/future-floor-owner.md"
    )
    concept.parent.mkdir(parents=True)
    concept.write_text(
        "`execute-userstory-core` ist ab `7.8.9` produktiv bindbar und liegt "
        "damit ueber der Mindest-Konformversion.\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "numeric skill-bundle floor authority is duplicated" in completed.stderr
    assert "7.8.9" in completed.stderr


def _declare_fixture_claude_hook(tmp_path: Path) -> None:
    declaration = tmp_path / "pyproject.toml"
    declaration.write_text(
        declaration.read_text(encoding="utf-8")
        + 'agentkit-hook-claude = "agentkit.claude_hook:main"\n',
        encoding="utf-8",
    )
    hook = tmp_path / "src/agentkit/claude_hook.py"
    hook.write_text(
        "from agentkit.backend.installer.interpreter import resolve_ak3_interpreter\n"
        "def main():\n"
        "    resolve_ak3_interpreter()\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "raw_command",
    [
        'py"thon" -m agentkit.probe',
        'agent"kit-hook-claude" pre branch_guard',
    ],
    ids=["python", "wrapper"],
)
def test_interpreter_entrypoint_gate_normalizes_shell_quotes_in_skill_fences(
    tmp_path: Path,
    raw_command: str,
) -> None:
    _write_gate_repository(tmp_path)
    _declare_fixture_claude_hook(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(f"```sh\n{raw_command}\n```\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "skill code fence 1 contains forbidden selector word" in completed.stderr
    assert f"raw text: {raw_command!r}" in completed.stderr


@pytest.mark.parametrize(
    "raw_command",
    [
        'py"thon" -m agentkit.probe',
        'agent"kit-hook-claude" pre branch_guard',
    ],
    ids=["python", "wrapper"],
)
def test_interpreter_entrypoint_gate_normalizes_shell_quotes_in_inline_prose(
    tmp_path: Path,
    raw_command: str,
) -> None:
    _write_gate_repository(tmp_path)
    _declare_fixture_claude_hook(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(f"Run `{raw_command}` now.\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "skill inline prose contains command-like forbidden selector" in completed.stderr
    assert f"raw text: 'Run `{raw_command}` now.'" in completed.stderr


@pytest.mark.parametrize(
    "raw_command",
    [
        'py"thon" -m agentkit.probe',
        'agent"kit-hook-claude" pre branch_guard',
    ],
    ids=["python", "wrapper"],
)
def test_interpreter_entrypoint_gate_normalizes_shell_quotes_in_cli_text(
    tmp_path: Path,
    raw_command: str,
) -> None:
    _write_gate_repository(tmp_path)
    _declare_fixture_claude_hook(tmp_path)
    cli_source = tmp_path / "src/agentkit/quote_split_help.py"
    cli_source.write_text(
        "import argparse\n"
        f"HELP = {raw_command!r}\n"
        "argparse.ArgumentParser(epilog=HELP)\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "productive CLI text publishes bare" in completed.stderr
    assert f"raw text: {raw_command!r}" in completed.stderr


def test_interpreter_entrypoint_gate_follows_process_callable_attribute_alias(
    tmp_path: Path,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + "import subprocess\n"
        + "runner = subprocess.run\n"
        + "runner(['python', '-m', 'agentkit.backend.cli.main'])\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "subprocess launches bare 'python' from PATH" in completed.stderr


@pytest.mark.parametrize(
    ("function_name", "argument"),
    [
        ("Popen", "['python', '-V']"),
        ("call", "['python', '-V']"),
        ("check_call", "['python', '-V']"),
        ("check_output", "['python', '-V']"),
        ("run", "['python', '-V']"),
        ("getoutput", "'python -V'"),
        ("getstatusoutput", "'python -V'"),
    ],
)
def test_interpreter_entrypoint_gate_inventories_every_subprocess_starter(
    tmp_path: Path,
    function_name: str,
    argument: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + f"import subprocess\nsubprocess.{function_name}({argument})\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "subprocess launches bare 'python' from PATH" in completed.stderr


@pytest.mark.parametrize(
    "source",
    [
        "import asyncio\nasyncio.create_subprocess_exec('python', '-V')\n",
        "import asyncio\nasyncio.create_subprocess_shell('python -V')\n",
        "from asyncio.subprocess import create_subprocess_exec\n"
        "create_subprocess_exec('python', '-V')\n",
        "from asyncio.subprocess import create_subprocess_shell\n"
        "create_subprocess_shell('python -V')\n",
        "import os\nos.execvp('python', ['python', '-V'])\n",
        "import os\nos.system('python -V')\n",
        "import os\nos.popen('python -V')\n",
        "import os\nos.spawnvp(os.P_WAIT, 'python', ['python', '-V'])\n",
        "import os\nos.posix_spawnp('python', ['python', '-V'], {})\n",
        "import os\nos.startfile('python')\n",
        "import pty\npty.spawn(['python', '-V'])\n",
        "import multiprocessing\nmultiprocessing.set_executable('python')\n",
        "context.set_executable('python')\n",
        "loop.subprocess_exec(factory, 'python', '-V')\n",
        "loop.subprocess_shell(factory, 'python -V')\n",
    ],
    ids=[
        "asyncio-exec",
        "asyncio-shell",
        "asyncio-submodule-exec",
        "asyncio-submodule-shell",
        "os-exec",
        "os-system",
        "os-popen",
        "os-spawn",
        "os-posix-spawn",
        "os-startfile",
        "pty-spawn",
        "multiprocessing-executable",
        "multiprocessing-context-executable",
        "event-loop-exec",
        "event-loop-shell",
    ],
)
def test_interpreter_entrypoint_gate_audits_stdlib_process_api_families(
    tmp_path: Path,
    source: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8") + source,
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "bare 'python' from PATH" in completed.stderr


@pytest.mark.parametrize(
    ("function_name", "argument_prefix"),
    [
        ("execl", ""),
        ("execle", ""),
        ("execlp", ""),
        ("execlpe", ""),
        ("execv", ""),
        ("execve", ""),
        ("execvp", ""),
        ("execvpe", ""),
        ("spawnl", "os.P_WAIT, "),
        ("spawnle", "os.P_WAIT, "),
        ("spawnlp", "os.P_WAIT, "),
        ("spawnlpe", "os.P_WAIT, "),
        ("spawnv", "os.P_WAIT, "),
        ("spawnve", "os.P_WAIT, "),
        ("spawnvp", "os.P_WAIT, "),
        ("spawnvpe", "os.P_WAIT, "),
    ],
)
def test_interpreter_entrypoint_gate_inventories_every_os_exec_and_spawn_variant(
    tmp_path: Path,
    function_name: str,
    argument_prefix: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + f"import os\nos.{function_name}({argument_prefix}'python', 'python')\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "os launches bare 'python' from PATH" in completed.stderr


def test_mcp_conformance_rejects_cwd_and_path_command_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentkit.backend.installer.mcp_conformance.process import resolve_command

    foreign = tmp_path / "agentkit-are-mcp"
    foreign.write_bytes(b"foreign executable")
    monkeypatch.setenv("PATH", str(tmp_path))

    assert resolve_command("agentkit-are-mcp", cwd=tmp_path) is None
    assert resolve_command(str(foreign.resolve()), cwd=tmp_path) == str(
        foreign.resolve()
    )


def test_interpreter_entrypoint_gate_audits_every_bundled_hook_command(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    settings_path = (
        tmp_path / "src/agentkit/bundles/target_project/.claude/settings.json"
    )
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload["hooks"]["PreToolUse"][0]["hooks"].append(
        {
            "type": "command",
            "command": "python .agentkit/hooks/other.py",
        }
    )
    settings_path.write_text(json.dumps(payload), encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "bundled PreToolUse hook command contains forbidden selector 'python'" in (
        completed.stderr
    )
    assert "raw text: 'python .agentkit/hooks/other.py'" in completed.stderr


def test_interpreter_entrypoint_gate_rejects_unknown_bundled_hook_type(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    settings_path = (
        tmp_path / "src/agentkit/bundles/target_project/.claude/settings.json"
    )
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload["hooks"]["PreToolUse"][0]["hooks"].append(
        {
            "type": "future-handler",
            "payload": "python -m agentkit.probe",
        }
    )
    settings_path.write_text(json.dumps(payload), encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "cannot audit bundled hook PreToolUse[0].hooks[1] of unknown type" in (
        completed.stderr
    )


def test_interpreter_entrypoint_gate_rejects_missing_bundled_hook_type(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    settings_path = (
        tmp_path / "src/agentkit/bundles/target_project/.claude/settings.json"
    )
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    del payload["hooks"]["PreToolUse"][0]["hooks"][0]["type"]
    settings_path.write_text(json.dumps(payload), encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "cannot audit bundled hook PreToolUse[0].hooks[0] of unknown type None" in (
        completed.stderr
    )


@pytest.mark.parametrize(
    ("raw_command", "expected_message"),
    [
        (r"py\thon -m agentkit.probe", "forbidden selector word 'python'"),
        (
            r"agentkit\-hook-claude pre branch_guard",
            "forbidden selector word 'agentkit-hook-claude'",
        ),
        ("py\\\nthon -m agentkit.probe", "forbidden selector word 'python'"),
        (
            "py`printf t`hon -m agentkit.probe",
            "is undecidable: shell evaluation marker '`'",
        ),
        (
            "py`unterminated",
            "is undecidable: shell evaluation marker '`'",
        ),
        (
            r"$'py\x74hon' -m agentkit.probe",
            "is undecidable: shell evaluation",
        ),
        (
            "$'python' -m agentkit.probe",
            "is undecidable: shell evaluation marker \"$'\"",
        ),
        (
            "py$(printf t)hon -m agentkit.probe",
            "is undecidable: shell evaluation marker '$('",
        ),
        (
            "py$(unterminated",
            "is undecidable: shell evaluation marker '$('",
        ),
        (
            "py$(printf %s $(printf t))hon -m agentkit.probe",
            "is undecidable: shell evaluation marker '$('",
        ),
    ],
    ids=[
        "backslash-python",
        "backslash-wrapper",
        "continuation-python",
        "backtick-substitution",
        "unbalanced-backtick-marker",
        "ansi-c-escape",
        "ansi-c-marker-without-escape",
        "dollar-substitution",
        "unbalanced-dollar-marker",
        "nested-dollar-substitution",
    ],
)
def test_interpreter_entrypoint_gate_normalizes_or_rejects_shell_escapes(
    tmp_path: Path,
    raw_command: str,
    expected_message: str,
) -> None:
    _write_gate_repository(tmp_path)
    _declare_fixture_claude_hook(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text(f"```sh\n{raw_command}\n```\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert expected_message in completed.stderr
    assert "raw text:" in completed.stderr


def test_interpreter_entrypoint_gate_rejects_shell_marker_without_selector(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    _declare_fixture_claude_hook(tmp_path)
    skill = (
        tmp_path
        / "src/agentkit/bundles/skill_bundles/fixture-core/1.0.0/SKILL.md"
    )
    skill.write_text("```sh\nvalue=$(date)\n```\n", encoding="utf-8")

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "is undecidable: shell evaluation marker '$('" in completed.stderr
    assert "raw text: 'value=$(date)'" in completed.stderr


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\ndef launch(r=subprocess.run): r(['python'])\nlaunch()\n",
        "import subprocess\nrunners = {'go': subprocess.run}\nrunners['go'](['python'])\n",
        "import subprocess\nclass Runner: go = subprocess.run\nRunner.go(['python'])\n",
        "import subprocess\nclass Child(subprocess.Popen): pass\nChild(['python'])\n",
        "import shutil, subprocess\ncommand = shutil.which('python')\nsubprocess.run([command])\n",
        "import anyio\nanyio.run_process(['python'])\n",
        "from asyncio import subprocess as asp\nasp.create_subprocess_exec('python')\n",
    ],
    ids=[
        "default-argument-callable",
        "container-callable",
        "class-attribute-callable",
        "subprocess-subclass",
        "lookup-data-flow",
        "foreign-process-api",
        "asyncio-submodule-alias",
    ],
)
def test_interpreter_entrypoint_gate_rejects_selector_literals_for_any_callable(
    tmp_path: Path,
    source: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8") + source,
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "call argument contains forbidden selector literal 'python'" in (
        completed.stderr
    )


@pytest.mark.parametrize(
    "selector",
    ["python3", "python.exe", "python3.exe", "agentkit-probe"],
)
def test_interpreter_entrypoint_gate_argument_rule_covers_every_selector_variant(
    tmp_path: Path,
    selector: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + f"def foreign_api(value): return value\nforeign_api([{selector!r}])\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert f"call argument contains forbidden selector literal {selector!r}" in (
        completed.stderr
    )


@pytest.mark.parametrize(
    "literal",
    ["python -V", b"python"],
    ids=["selector-word-inside-string", "bytes-selector"],
)
def test_interpreter_entrypoint_gate_argument_rule_audits_selector_words_and_bytes(
    tmp_path: Path,
    literal: str | bytes,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + f"def launch(value): return value\nlaunch({literal!r})\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "call argument contains forbidden selector literal 'python'" in (
        completed.stderr
    )


@pytest.mark.parametrize("suffix", [".module", "/child", r"\child"])
def test_interpreter_entrypoint_gate_argument_rule_relieves_path_segments(
    tmp_path: Path,
    suffix: str,
) -> None:
    entrypoint = _write_gate_repository(tmp_path)
    entrypoint.write_text(
        entrypoint.read_text(encoding="utf-8")
        + f"def foreign_api(value): return value\nforeign_api({f'python{suffix}'!r})\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 0


def test_interpreter_entrypoint_gate_rejects_selector_callable_default(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    executable_module = tmp_path / "src/agentkit/backend/vectordb/engine.py"
    executable_module.parent.mkdir(parents=True)
    executable_module.write_text(
        "def compose_runtime(command='python'):\n"
        "    return command\n"
        "def main():\n"
        "    return compose_runtime()\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "callable default contains forbidden selector literal 'python'" in (
        completed.stderr
    )


def test_interpreter_entrypoint_gate_resolves_one_module_constant_for_default(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    executable_module = tmp_path / "src/agentkit/backend/vectordb/engine.py"
    executable_module.parent.mkdir(parents=True)
    executable_module.write_text(
        'DEFAULT_COMMAND = "python"\n'
        "def compose_runtime(command=DEFAULT_COMMAND):\n"
        "    return command\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "callable default contains forbidden selector literal 'python'" in (
        completed.stderr
    )


def test_interpreter_entrypoint_gate_does_not_follow_constant_name_chain(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    executable_module = tmp_path / "src/agentkit/backend/vectordb/engine.py"
    executable_module.parent.mkdir(parents=True)
    executable_module.write_text(
        'SELECTOR = "python"\n'
        "DEFAULT_COMMAND = SELECTOR\n"
        "def compose_runtime(command=DEFAULT_COMMAND):\n"
        "    return command\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "undecidable callable default name 'DEFAULT_COMMAND'" in completed.stderr
    assert "raw text: 'DEFAULT_COMMAND'" in completed.stderr


def test_interpreter_entrypoint_gate_rejects_empty_project_scripts(
    tmp_path: Path,
) -> None:
    _write_gate_repository(tmp_path)
    declaration = tmp_path / "pyproject.toml"
    declaration.write_text(
        '[project]\nname = "gate-fixture"\nrequires-python = ">=3.14"\n'
        "[project.scripts]\n",
        encoding="utf-8",
    )

    completed = _run_entrypoint_gate(tmp_path)

    assert completed.returncode == 1
    assert "project.scripts must declare at least one entrypoint" in completed.stderr
