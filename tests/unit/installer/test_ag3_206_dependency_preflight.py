"""AG3-206 dependency declaration and earliest-abort proofs."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest
from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.cli.main import _is_installer_invocation
from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
    cp01_package_check,
)
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
    run_checkpoint_install,
)
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_RUNTIME_DEPENDENCY_UNAVAILABLE,
)
from agentkit.backend.installer.dependency_preflight import (
    DependencyDeclarationError,
    DependencyFailure,
    DependencyPreflightReport,
    check_runtime_dependencies,
    declared_runtime_requirements,
)
from agentkit.backend.installer.registration import CheckpointStatus


def _run_isolated_script(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed current-interpreter invocation
        [sys.executable, "-c", textwrap.dedent(source)],
        check=False,
        capture_output=True,
        text=True,
        # Explicit: `text=True` alone decodes with the locale encoding, which
        # CI rejects (PYTHONWARNDEFAULTENCODING=1 + -W error::EncodingWarning).
        encoding="utf-8",
    )

def test_installed_artifact_dependencies_are_importable() -> None:
    """The current interpreter satisfies the installed artifact declaration."""
    report = check_runtime_dependencies()

    assert report.passed
    assert report.declared_count == len(declared_runtime_requirements())
    assert report.declared_count > 0


def test_public_installer_export_preflights_before_top_level_dependency_import() -> None:
    """B1: the public export diagnoses pydantic before loading the orchestrator."""
    result = _run_isolated_script(
        """
        import importlib.abc
        import sys

        class BlockPydantic(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "pydantic" or fullname.startswith("pydantic."):
                    raise ModuleNotFoundError("No module named 'pydantic'")
                return None

        sys.meta_path.insert(0, BlockPydantic())
        try:
            from agentkit.backend.installer import run_checkpoint_install
        except RuntimeError as exc:
            print(type(exc).__name__)
            print(exc)
        else:
            raise AssertionError(run_checkpoint_install)
        """
    )

    assert result.returncode == 0, result.stderr
    assert "RuntimeDependencyError" in result.stdout
    assert "pydantic" in result.stdout
    assert f"{sys.executable} -m pip install" in result.stdout
    assert "bootstrap_checkpoints" not in result.stderr


def test_combined_public_runner_import_preflights_before_pydantic() -> None:
    """B1: the common InstallConfig/install_agentkit import is also protected."""
    result = _run_isolated_script(
        """
        import importlib.abc
        import sys

        class BlockPydantic(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "pydantic" or fullname.startswith("pydantic."):
                    raise ModuleNotFoundError("No module named 'pydantic'")
                return None

        sys.meta_path.insert(0, BlockPydantic())
        try:
            from agentkit.backend.installer import InstallConfig, install_agentkit
        except RuntimeError as exc:
            print(type(exc).__name__)
            print(exc)
        else:
            raise AssertionError((InstallConfig, install_agentkit))
        """
    )

    assert result.returncode == 0, result.stderr
    assert "RuntimeDependencyError" in result.stdout
    assert "pydantic" in result.stdout
    assert f"{sys.executable} -m pip install" in result.stdout
    assert "runner" not in result.stderr


def test_unreadable_installed_metadata_is_a_declaration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A metadata read fault is diagnosed instead of escaping the preflight."""

    def _fail_metadata(_distribution_name: str) -> None:
        raise UnicodeError("broken METADATA encoding")

    monkeypatch.setattr("importlib.metadata.requires", _fail_metadata)

    with pytest.raises(
        DependencyDeclarationError,
        match="Cannot read Requires-Dist metadata.*UnicodeError.*broken METADATA encoding",
    ):
        declared_runtime_requirements()


def test_installer_cli_preflights_before_top_level_dependency_import() -> None:
    """B2: the CLI reaches the declaration-owned diagnosis without pydantic."""
    result = _run_isolated_script(
        """
        import importlib.abc
        import sys

        class BlockPydantic(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "pydantic" or fullname.startswith("pydantic."):
                    raise ModuleNotFoundError("No module named 'pydantic'")
                return None

        sys.meta_path.insert(0, BlockPydantic())
        from agentkit.backend.cli.main import main
        raise SystemExit(main(["register-project"]))
        """
    )

    assert result.returncode == 1
    assert "runtime dependency preflight failed" in result.stderr
    assert "pydantic" in result.stderr
    assert f"{sys.executable} -m pip install" in result.stderr


def test_installer_preflight_detection_uses_the_selected_verb_only() -> None:
    """An unrelated argument named like an installer verb must not trigger CP 1."""
    assert _is_installer_invocation(["register-project", "--project-root", "."])
    assert not _is_installer_invocation(["hook-errors", "register-project"])


def test_new_pyproject_dependency_is_checked_without_checker_change(
    tmp_path: Path,
) -> None:
    """AC 2: a new declaration line automatically enters the preflight."""
    source = Path("pyproject.toml").read_text(encoding="utf-8")
    missing_requirement = "ag3-206-declaration-probe>=1"
    modified = source.replace(
        "dependencies = [",
        f'dependencies = [\n    "{missing_requirement}",',
        1,
    )
    declaration = tmp_path / "pyproject.toml"
    declaration.write_text(modified, encoding="utf-8")

    report = check_runtime_dependencies(pyproject_path=declaration)

    assert not report.passed
    failure = next(
        item
        for item in report.failures
        if item.distribution == "ag3-206-declaration-probe"
    )
    assert failure.requirement == missing_requirement
    assert sys.executable in failure.install_command
    assert missing_requirement in failure.install_command


def test_dependency_report_measures_only_its_own_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration = tmp_path / "pyproject.toml"
    declaration.write_text("[project]\ndependencies = []\n", encoding="utf-8")
    ticks = iter((10.0, 10.25))
    monkeypatch.setattr(
        "agentkit.backend.installer.dependency_preflight.monotonic",
        lambda: next(ticks),
    )

    report = check_runtime_dependencies(pyproject_path=declaration)

    assert report.duration_ms == 250


def test_cp1_failure_duration_includes_preceding_dependency_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = make_config(
        tmp_path,
        bundle_store_root=tmp_path / "bundles",
        registration_repo=InMemoryRegistrationRepo(),
    )
    report = DependencyPreflightReport(
        declared_count=9,
        failures=(),
        duration_ms=17,
    )
    context = build_checkpoint_context(
        config,
        ExecutionMode.REGISTER,
        dependency_preflight=report,
    )
    monkeypatch.setattr("agentkit.__version__", "")
    monkeypatch.setattr(
        "agentkit.backend.installer.checkpoint_engine.result_builder.elapsed_ms",
        lambda _start: 3,
    )

    result = cp01_package_check(context)

    assert result.status is CheckpointStatus.FAILED
    assert result.duration_ms == 20


def test_failed_dependency_aborts_before_external_preflight_or_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC 1: CP 1 is the sole result and no later installer work starts."""
    root = tmp_path / "project"
    root.mkdir()
    config = make_config(
        root,
        bundle_store_root=tmp_path / "bundles",
        registration_repo=InMemoryRegistrationRepo(),
    )

    class _MustNotRun:
        def check(self, _config: object) -> None:
            raise AssertionError("VectorDB preflight ran after dependency failure")

    config = replace(config, vectordb_preflight=_MustNotRun())  # type: ignore[arg-type]
    requirement = "tomlkit==0.15.1"
    report = DependencyPreflightReport(
        declared_count=10,
        failures=(
            DependencyFailure(
                requirement=requirement,
                distribution="tomlkit",
                detail="declared distribution is not installed in this interpreter",
                install_command=f'{sys.executable} -m pip install "{requirement}"',
            ),
        ),
        duration_ms=17,
    )
    monkeypatch.setattr(
        "agentkit.backend.installer.dependency_preflight.check_runtime_dependencies",
        lambda: report,
    )

    result = run_checkpoint_install(config)

    assert not result.success
    assert not result.created_files
    assert len(result.checkpoint_results) == 1
    checkpoint = result.checkpoint_results[0]
    assert checkpoint.status is CheckpointStatus.FAILED
    assert checkpoint.reason == REASON_RUNTIME_DEPENDENCY_UNAVAILABLE
    assert checkpoint.duration_ms >= report.duration_ms
    assert "tomlkit" in (checkpoint.detail or "")
    assert requirement in (checkpoint.detail or "")
    assert not (root / ".agentkit").exists()
