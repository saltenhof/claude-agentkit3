"""Port-CONTRACT suite for ``CodeBackendPort`` (AG3-146 AC5).

Runs the SAME assertions, unchanged, against the GitHub adapter
(:class:`GitHubCodeBackendAdapter`) and a Non-GitHub test-double adapter
(:class:`FakeAzureDevOpsCodeBackendAdapter`) -- proving substitutability
(PO Directive III, Azure DevOps readiness, FK-12 §12.1). Both adapters are
pointed at the SAME local bare-repo fixture via each adapter's own
(adapter-internal) remote-binding seam, so the suite never touches a live
provider or the network.

``repo_probe`` is intentionally NOT exercised here: the GitHub adapter's
``repo_probe`` genuinely shells out to ``gh repo view`` (a real external
dependency with no test seam by design -- the mechanic is legitimately
provider-specific), so driving it here would make this contract suite depend
on ``gh`` being installed/authenticated and on network reachability. Its
behaviour is covered per-adapter instead, with ``subprocess``/``gh``
appropriately mocked (see ``tests/unit/integrations/github/test_adapter.py``
and the ``FakeAzureDevOpsCodeBackendAdapter`` unit test).
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.code_backend.provider_port import (
    CodeBackendCapability,
    CodeBackendPort,
    StoryRefWriteCredentialClass,
)
from agentkit.integration_clients.github.adapter import GitHubCodeBackendAdapter

from .code_backend_fakes import FakeAzureDevOpsCodeBackendAdapter

if TYPE_CHECKING:
    from pathlib import Path


def _run_git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607


def _init_bare_repo_with_commit(tmp_path: Path) -> tuple[Path, str]:
    """Create a local bare repo with one commit on ``main``.

    Returns:
        A ``(bare_repo_path, head_sha)`` pair.
    """
    bare = tmp_path / "bare.git"
    work = tmp_path / "work"
    _run_git("init", "--bare", str(bare))
    _run_git("clone", str(bare), str(work))
    _run_git("-C", str(work), "config", "user.email", "contract-test@example.com")
    _run_git("-C", str(work), "config", "user.name", "Contract Test")
    (work / "file.txt").write_text("hello", encoding="utf-8")
    _run_git("-C", str(work), "add", "file.txt")
    _run_git("-C", str(work), "commit", "-m", "init")
    _run_git("-C", str(work), "branch", "-M", "main")
    _run_git("-C", str(work), "push", "origin", "main")
    result = subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return bare, result.stdout.strip()


@pytest.fixture(params=["github", "azure_devops_fake"])
def code_backend_port(
    request: pytest.FixtureRequest, tmp_path: Path
) -> tuple[CodeBackendPort, str]:
    """Yield a ``(port, head_sha)`` pair for both adapters against one fixture repo."""
    bare_repo, head_sha = _init_bare_repo_with_commit(tmp_path)
    port: CodeBackendPort
    if request.param == "github":
        port = GitHubCodeBackendAdapter(
            owner="acme", repo="widgets", remote_url_override=str(bare_repo)
        )
    else:
        port = FakeAzureDevOpsCodeBackendAdapter(
            project="acme", repository="widgets", remote_url=str(bare_repo)
        )
    return port, head_sha


@pytest.mark.requires_git
class TestCodeBackendPortContract:
    """AC5: identical assertions against the GitHub adapter and a non-GitHub double."""

    def test_is_a_code_backend_port(
        self, code_backend_port: tuple[CodeBackendPort, str]
    ) -> None:
        port, _ = code_backend_port
        assert isinstance(port, CodeBackendPort)

    def test_ref_read_resolves_known_ref(
        self, code_backend_port: tuple[CodeBackendPort, str]
    ) -> None:
        port, head_sha = code_backend_port
        result = port.ref_read("main")
        assert result.resolved is True
        assert result.head_sha == head_sha

    def test_ref_read_fails_closed_for_unknown_ref(
        self, code_backend_port: tuple[CodeBackendPort, str]
    ) -> None:
        port, _ = code_backend_port
        result = port.ref_read("refs/heads/does-not-exist")
        assert result.resolved is False
        assert result.head_sha is None

    def test_capability_supported_never_raises_and_returns_bool(
        self, code_backend_port: tuple[CodeBackendPort, str]
    ) -> None:
        port, _ = code_backend_port
        for capability in CodeBackendCapability:
            assert isinstance(port.capability_supported(capability), bool)

    def test_compare_evidence_is_declared_not_available(
        self, code_backend_port: tuple[CodeBackendPort, str]
    ) -> None:
        port, _ = code_backend_port
        result = port.read_compare_evidence("main", "story/AG3-146")
        assert result.available is False
        assert result.base_ref == "main"
        assert result.head_ref == "story/AG3-146"

    def test_story_ref_write_credential_is_never_the_personal_token(
        self, code_backend_port: tuple[CodeBackendPort, str]
    ) -> None:
        """AG3-147 AC8: the story/* write credential is never the personal token.

        Neither adapter has a backend-managed service identity configured in
        this suite, so both fail closed (``resolved=False``) -- but crucially,
        NEITHER substitutes the personal developer token class.
        """
        port, _ = code_backend_port
        credential = port.resolve_story_ref_write_credential()
        assert (
            credential.credential_class
            is not StoryRefWriteCredentialClass.PERSONAL_DEVELOPER_TOKEN
        )
        if not credential.resolved:
            assert credential.credential_class is None

    def test_administer_ref_protection_never_raises_and_returns_result(
        self, code_backend_port: tuple[CodeBackendPort, str]
    ) -> None:
        """AG3-147 AC7/AC9: administration is fail-closed, never raises."""
        port, _ = code_backend_port
        result = port.administer_ref_protection("story/*")
        assert result.ref_pattern == "story/*"
        assert isinstance(result.administered, bool)
