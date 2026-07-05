"""Regression tests for the installer's CP 2 repo probe (AG3-146 AC3).

CP 2's fail-closed behaviour (repo missing / ``gh`` missing / auth missing all
stay ``FAILED``, never a silent skip) must survive routing
:class:`GhCliRepoExistenceProbe` through the AG3-146 code-backend port instead
of a direct ``gh`` subprocess call. ``subprocess``/``shutil.which`` are mocked
here (external system dependency, permitted mock exception) at the
``integration_clients.github.adapter`` module -- the only place a ``gh``
subprocess may run now (AC3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
    REASON_REPO_UNREACHABLE,
    cp02_repo_check,
)
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
)
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.installer.repo_probe import GhCliRepoExistenceProbe

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.installer.runner import InstallConfig


def _build_config(tmp_path: Path) -> InstallConfig:
    return make_config(
        tmp_path,
        bundle_store_root=tmp_path / "bundles",
        registration_repo=InMemoryRegistrationRepo(),
        repo_existence_probe=GhCliRepoExistenceProbe(),
        github_owner="acme",
        github_repo="widgets",
    )


@pytest.mark.unit
class TestCp02RepoProbeRegression:
    """AG3-146 AC3: CP 2 stays fail-closed FAILED through the ported probe."""

    def test_repo_missing_stays_failed(self, tmp_path: Path) -> None:
        config = _build_config(tmp_path)
        with (
            patch(
                "agentkit.integration_clients.github.adapter.shutil.which",
                return_value="/usr/bin/gh",
            ),
            patch(
                "agentkit.integration_clients.github.adapter.subprocess.run"
            ) as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="repository not found"
            )
            result = cp02_repo_check(
                build_checkpoint_context(config, ExecutionMode.REGISTER)
            )
        assert result.status is CheckpointStatus.FAILED
        assert result.reason == REASON_REPO_UNREACHABLE
        assert "not found" in result.detail

    def test_gh_missing_stays_failed(self, tmp_path: Path) -> None:
        config = _build_config(tmp_path)
        with patch(
            "agentkit.integration_clients.github.adapter.shutil.which",
            return_value=None,
        ):
            result = cp02_repo_check(
                build_checkpoint_context(config, ExecutionMode.REGISTER)
            )
        assert result.status is CheckpointStatus.FAILED
        assert result.reason == REASON_REPO_UNREACHABLE
        assert "gh" in result.detail

    def test_auth_missing_stays_failed(self, tmp_path: Path) -> None:
        config = _build_config(tmp_path)
        with (
            patch(
                "agentkit.integration_clients.github.adapter.shutil.which",
                return_value="/usr/bin/gh",
            ),
            patch(
                "agentkit.integration_clients.github.adapter.subprocess.run"
            ) as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=4, stdout="", stderr="authentication required"
            )
            result = cp02_repo_check(
                build_checkpoint_context(config, ExecutionMode.REGISTER)
            )
        assert result.status is CheckpointStatus.FAILED
        assert result.reason == REASON_REPO_UNREACHABLE
        assert "authentication" in result.detail

    def test_repo_present_and_authenticated_passes(self, tmp_path: Path) -> None:
        config = _build_config(tmp_path)
        with (
            patch(
                "agentkit.integration_clients.github.adapter.shutil.which",
                return_value="/usr/bin/gh",
            ),
            patch(
                "agentkit.integration_clients.github.adapter.subprocess.run"
            ) as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = cp02_repo_check(
                build_checkpoint_context(config, ExecutionMode.REGISTER)
            )
        assert result.status is CheckpointStatus.PASS
