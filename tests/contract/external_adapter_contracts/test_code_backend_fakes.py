"""Direct unit coverage for ``FakeAzureDevOpsCodeBackendAdapter.repo_probe``.

``repo_probe`` is intentionally excluded from the shared, cross-adapter
contract suite (see ``test_code_backend_port_contract.py``) because the
GitHub adapter's ``repo_probe`` has a real ``gh``/network dependency. The
fake's own ``repo_probe`` has no such dependency (pure ``git ls-remote``), so
it is safe and hermetic to exercise directly here against a local bare-repo
fixture.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from .code_backend_fakes import FakeAzureDevOpsCodeBackendAdapter

if TYPE_CHECKING:
    from pathlib import Path


def _run_git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607


@pytest.mark.requires_git
class TestFakeAzureDevOpsRepoProbe:
    def test_reachable_when_remote_resolves(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare.git"
        work = tmp_path / "work"
        _run_git("init", "--bare", str(bare))
        _run_git("clone", str(bare), str(work))
        _run_git("-C", str(work), "config", "user.email", "fake-adapter-test@example.com")
        _run_git("-C", str(work), "config", "user.name", "Fake Adapter Test")
        (work / "file.txt").write_text("hello", encoding="utf-8")
        _run_git("-C", str(work), "add", "file.txt")
        _run_git("-C", str(work), "commit", "-m", "init")
        _run_git("-C", str(work), "push", "origin", "HEAD:main")

        adapter = FakeAzureDevOpsCodeBackendAdapter(
            project="acme", repository="widgets", remote_url=str(bare)
        )
        result = adapter.repo_probe()
        assert result.reachable is True

    def test_unreachable_when_remote_is_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.git"
        adapter = FakeAzureDevOpsCodeBackendAdapter(
            project="acme", repository="widgets", remote_url=str(missing)
        )
        result = adapter.repo_probe()
        assert result.reachable is False
