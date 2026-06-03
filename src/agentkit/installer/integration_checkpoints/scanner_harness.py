"""Productive ``ScannerHarness`` on the thin ``integrations.sonar`` client.

FK-50 §50.3 CP 10d.2 (AG3-052 E5): the Community Branch Plugin is only
Trust-A-capable when the conformance self-test passes. The conformance
LOGIC lives in :mod:`branch_plugin_self_test`; this module provides the
PRODUCTIVE :class:`ScannerHarness` it drives — no attrappe.

Split of responsibilities (CLAUDE.md: integrations = thin adapters):

* the SonarQube **Web-API** project-lifecycle / branch-visibility /
  Accepted-read operations go through the thin :class:`SonarClient`
  (``projects/create``, ``projects/delete``, ``project_branches/list``,
  ``issues/search``);
* the one genuinely operational step — running the ``sonar-scanner`` CLI
  against a LIVE server — is delegated to an injected ``ScanRunner``
  callable. A LIVE SonarQube server + scanner binary is the only OOS bit
  (§2.2: "Live-SonarQube-Server-Provisionierung"); in tests the
  ``ScanRunner`` and the HTTP boundary are stubbed.

The harness therefore EXISTS in productive code and is wired into the
installer (``runner._run_cp10d_sonarqube``); it is not merely logic around
an injected protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agentkit.integrations.sonar import SonarApiError

if TYPE_CHECKING:
    from agentkit.installer.integration_checkpoints.branch_plugin_self_test import (
        SelfTestScan,
    )
    from agentkit.integrations.sonar import SonarClient

#: Sonar resolution string for an Accepted (won't-fix family) issue.
_ACCEPTED_RESOLUTIONS = "ACCEPTED,WONTFIX,FALSE-POSITIVE"


class ScanRunner(Protocol):
    """Operational boundary: run one ``sonar-scanner`` analysis (OOS §2.2).

    Provisioning a scanner run requires a LIVE SonarQube server + the
    scanner binary; that is the only out-of-scope operational dependency.
    Production injects a real scanner-driving callable; tests stub it.
    """

    def __call__(self, project_key: str, branch: str) -> SelfTestScan:
        """Run the scanner for ``branch`` and return its coordinates."""
        ...


@dataclass(frozen=True)
class SonarClientScannerHarness:
    """Productive ``ScannerHarness`` (satisfies the self-test Protocol).

    Attributes:
        client: Thin ``integrations.sonar`` client (scoped token) used for
            all Web-API project-lifecycle / read operations.
        scan_runner: Injected operational scanner runner (the live-server
            ``sonar-scanner`` invocation, OOS §2.2).
        project_display_name: Display name for the throwaway mini-project.
    """

    client: SonarClient
    scan_runner: ScanRunner
    project_display_name: str = "AK3 Branch-Plugin Conformance Self-Test"

    def create_project(self, project_key: str) -> None:
        """Create the throwaway mini-project (``api/projects/create``)."""
        self.client.create_project(project_key, self.project_display_name)

    def scan(self, project_key: str, branch: str) -> SelfTestScan:
        """Run a scanner analysis for ``branch`` (operational, injected)."""
        return self.scan_runner(project_key, branch)

    def branch_exists(self, project_key: str, branch: str) -> bool:
        """Return whether ``branch`` is visible (branch plugin live)."""
        body = self.client.project_branches(project_key).json_body
        branches = body.get("branches", [])
        if not isinstance(branches, list):
            return False
        return any(
            isinstance(entry, dict) and entry.get("name") == branch
            for entry in branches
        )

    def issue_accepted_on_branch(
        self, project_key: str, branch: str, issue_key: str
    ) -> bool:
        """Return whether ``issue_key`` reads as Accepted on ``branch``."""
        body = self.client.search_issues(
            {
                "componentKeys": project_key,
                "branch": branch,
                "issues": issue_key,
                "resolutions": _ACCEPTED_RESOLUTIONS,
                "ps": "1",
            }
        ).json_body
        issues = body.get("issues", [])
        return isinstance(issues, list) and len(issues) >= 1

    def delete_project(self, project_key: str) -> None:
        """Delete the throwaway mini-project (idempotent cleanup)."""
        try:
            self.client.delete_project(project_key)
        except SonarApiError:
            # Cleanup must not mask the self-test verdict; a 404 on an
            # already-absent project is benign.
            return


__all__ = ["ScanRunner", "SonarClientScannerHarness"]
