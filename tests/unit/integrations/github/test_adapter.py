"""Unit tests for the GitHub ``CodeBackendPort`` adapter (AG3-146).

Subprocess/``gh`` are mocked here (external system dependency, one of the two
permitted mock exceptions per project rules; mirrors
``tests/unit/integrations/github/test_client.py``). ``ref_read`` delegation is
tested against a stub ref-reader, isolating the adapter's own logic from
``git_protocol``'s real-git behaviour (covered separately in
``tests/unit/code_backend/test_git_protocol.py``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agentkit.backend.code_backend.provider_port import (
    CodeBackendCapability,
    RefReadResult,
)
from agentkit.integration_clients.github.adapter import GitHubCodeBackendAdapter


class _StubRefReader:
    """Records ``(remote, ref)`` calls and returns a canned :class:`RefReadResult`."""

    def __init__(self, canned: RefReadResult) -> None:
        self.canned = canned
        self.calls: list[tuple[str, str]] = []

    def read_head_sha(self, remote: str, ref: str) -> RefReadResult:
        self.calls.append((remote, ref))
        return self.canned


@pytest.mark.unit
class TestRepoProbe:
    """``repo_probe`` is the only capability that shells out to ``gh``."""

    def test_reports_unavailable_when_gh_missing(self) -> None:
        with patch(
            "agentkit.integration_clients.github.adapter.shutil.which",
            return_value=None,
        ):
            adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets")
            result = adapter.repo_probe()
        assert result.reachable is False
        assert "gh" in result.detail

    def test_reports_reachable_on_success(self) -> None:
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
            adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets")
            result = adapter.repo_probe()
        assert result.reachable is True
        assert "acme/widgets" in result.detail

    def test_reports_unreachable_on_nonzero_exit(self) -> None:
        with (
            patch(
                "agentkit.integration_clients.github.adapter.shutil.which",
                return_value="/usr/bin/gh",
            ),
            patch(
                "agentkit.integration_clients.github.adapter.subprocess.run"
            ) as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
            adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets")
            result = adapter.repo_probe()
        assert result.reachable is False
        assert "not found" in result.detail

    def test_reports_unreachable_on_subprocess_error(self) -> None:
        with (
            patch(
                "agentkit.integration_clients.github.adapter.shutil.which",
                return_value="/usr/bin/gh",
            ),
            patch(
                "agentkit.integration_clients.github.adapter.subprocess.run",
                side_effect=OSError("boom"),
            ),
        ):
            adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets")
            result = adapter.repo_probe()
        assert result.reachable is False
        assert "boom" in result.detail


@pytest.mark.unit
class TestRefRead:
    """``ref_read`` never needs ``gh`` -- it delegates to the git-protocol reader."""

    def test_delegates_with_derived_github_remote_url(self) -> None:
        stub = _StubRefReader(
            RefReadResult(ref="main", resolved=True, head_sha="abc123", detail="ok")
        )
        adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets", ref_reader=stub)
        result = adapter.ref_read("main")
        assert result.head_sha == "abc123"
        assert stub.calls == [("https://github.com/acme/widgets.git", "main")]

    def test_remote_url_override_takes_precedence(self) -> None:
        stub = _StubRefReader(
            RefReadResult(ref="main", resolved=True, head_sha="abc", detail="ok")
        )
        adapter = GitHubCodeBackendAdapter(
            owner="acme",
            repo="widgets",
            ref_reader=stub,
            remote_url_override="/tmp/bare.git",
        )
        adapter.ref_read("main")
        assert stub.calls == [("/tmp/bare.git", "main")]

    def test_works_when_gh_is_missing(self) -> None:
        """AC4: the ls-remote capability functions without gh installed."""
        stub = _StubRefReader(
            RefReadResult(ref="main", resolved=True, head_sha="abc", detail="ok")
        )
        with patch(
            "agentkit.integration_clients.github.adapter.shutil.which",
            return_value=None,
        ):
            adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets", ref_reader=stub)
            result = adapter.ref_read("main")
        assert result.resolved is True
        assert result.head_sha == "abc"


@pytest.mark.unit
class TestReadCompareEvidence:
    def test_declared_not_available(self) -> None:
        adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets")
        result = adapter.read_compare_evidence("main", "story/AG3-146")
        assert result.available is False
        assert result.base_ref == "main"
        assert result.head_ref == "story/AG3-146"


@pytest.mark.unit
class TestCapabilitySupported:
    """AC4: capability_supported is the deterministic, named availability finding."""

    def test_repo_probe_true_when_gh_present(self) -> None:
        with patch(
            "agentkit.integration_clients.github.adapter.shutil.which",
            return_value="/usr/bin/gh",
        ):
            adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets")
            assert adapter.capability_supported(CodeBackendCapability.REPO_PROBE) is True

    def test_repo_probe_false_when_gh_missing(self) -> None:
        with patch(
            "agentkit.integration_clients.github.adapter.shutil.which",
            return_value=None,
        ):
            adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets")
            assert adapter.capability_supported(CodeBackendCapability.REPO_PROBE) is False

    def test_ref_read_always_true_regardless_of_gh(self) -> None:
        with patch(
            "agentkit.integration_clients.github.adapter.shutil.which",
            return_value=None,
        ):
            adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets")
            assert adapter.capability_supported(CodeBackendCapability.REF_READ) is True

    def test_declared_capabilities_are_not_yet_supported(self) -> None:
        adapter = GitHubCodeBackendAdapter(owner="acme", repo="widgets")
        assert (
            adapter.capability_supported(CodeBackendCapability.COMPARE_EVIDENCE) is False
        )
        assert (
            adapter.capability_supported(
                CodeBackendCapability.REF_PROTECTION_ADMINISTRATION
            )
            is False
        )
