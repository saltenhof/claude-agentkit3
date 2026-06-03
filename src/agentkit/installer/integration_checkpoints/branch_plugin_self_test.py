"""Community-Branch-Plugin conformance self-test runner (FK-50 §50.3 CP 10d.2).

The Community Branch Plugin is INOFFICIAL and only Trust-A-capable
(blocking, FK-33 §33.5.1) when this conformance self-test passes. It runs
at install time AND after every SonarQube-/plugin upgrade.

This is the PRODUCTIVE runner (no attrappe): it drives the FK-50 §50.3
conformance steps against a throwaway mini-project through the thin
``integrations.sonar`` client. Live-server provisioning (creating the
scanner run, deleting the project) is operational and is supplied via the
injected ``ScannerHarness`` — in tests only that external boundary is
stubbed (MOCKS-Ausnahme); the conformance LOGIC (step ordering, the
``analysisId`` quality-gate read, the Accepted-inheritance and merge-sync
checks, fail-closed on any failed step) runs for real.

Steps (FK-50 §50.3 CP 10d.2), all must pass:

1. create the mini-project, scan ``main`` -> must be GREEN;
2. scan a branch -> the branch analysis must appear;
3. set an issue on ``main`` to ``Accepted`` -> Accepted-inheritance onto
   the branch must hold (FK-33 §33.6.3);
4. set an issue on the BRANCH to ``Accepted`` -> Accepted stays consistent
   after merge/reference-branch sync against ``main``;
5. verify the quality gate by ``analysisId`` (never ``projectKey``);
6. delete the throwaway project.

Any failed step -> the self-test returns ``False`` (the plugin is not
gateable; the installer FAILs CP 10d and refuses to arm the green gate).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agentkit.integrations.sonar import SonarApiError

if TYPE_CHECKING:
    from agentkit.integrations.sonar import SonarClient

logger = logging.getLogger(__name__)

#: Throwaway mini-project key used for the conformance self-test.
_MINI_PROJECT_KEY = "ak3-branch-plugin-conformance-selftest"
_MAIN_BRANCH = "main"
_PROBE_BRANCH = "ak3-selftest-branch"
_GREEN = "OK"


@dataclass(frozen=True)
class SelfTestScan:
    """Result of one provisioned scan in the self-test harness.

    Attributes:
        analysis_id: The analysisId the scanner produced (FK-33 §33.6.3:
            the quality gate is verified BY this id, never by projectKey).
        branch: The branch this scan measured.
        issue_keys: Issue keys present on this scan (for the
            Accepted-transition steps).
    """

    analysis_id: str
    branch: str
    issue_keys: tuple[str, ...]


class ScannerHarness(Protocol):
    """External provisioning boundary for the conformance self-test.

    Only the live scanner/project-lifecycle operations are abstracted (they
    require a running SonarQube). The conformance LOGIC lives in
    :func:`run_branch_plugin_conformance_self_test`. Tests stub this
    Protocol; production supplies a real scanner-driving implementation.
    """

    def create_project(self, project_key: str) -> None:
        """Create the throwaway mini-project."""
        ...

    def scan(self, project_key: str, branch: str) -> SelfTestScan:
        """Run a scanner analysis for ``branch`` and return its coordinates."""
        ...

    def branch_exists(self, project_key: str, branch: str) -> bool:
        """Return whether the branch analysis is visible (branch plugin live)."""
        ...

    def issue_accepted_on_branch(
        self, project_key: str, branch: str, issue_key: str
    ) -> bool:
        """Return whether ``issue_key`` reads as Accepted on ``branch``."""
        ...

    def delete_project(self, project_key: str) -> None:
        """Delete the throwaway mini-project (cleanup, idempotent)."""
        ...


def run_branch_plugin_conformance_self_test(
    client: SonarClient,
    harness: ScannerHarness,
) -> bool:
    """Run the FK-50 §50.3 CP 10d.2 conformance self-test (fail-closed).

    Args:
        client: Thin ``integrations.sonar`` client (the scoped-token HTTP
            boundary used for the ``analysisId`` quality-gate read and the
            ``Administer Issues`` transitions).
        harness: The scanner/project-lifecycle provisioning boundary.

    Returns:
        ``True`` iff every conformance step passed; ``False`` otherwise
        (the plugin is not gateable). Cleanup runs even on failure.
    """
    try:
        return _run_steps(client, harness)
    except (SonarApiError, OSError) as exc:
        logger.error("branch-plugin conformance self-test errored: %s", exc)
        return False
    finally:
        _safe_delete(harness)


def _run_steps(client: SonarClient, harness: ScannerHarness) -> bool:
    harness.create_project(_MINI_PROJECT_KEY)

    # Step 1: main scan must be GREEN (verified by analysisId, not projectKey).
    main_scan = harness.scan(_MINI_PROJECT_KEY, _MAIN_BRANCH)
    if not _gate_green_by_analysis_id(client, main_scan.analysis_id):
        logger.error("self-test step 1 failed: main scan not green")
        return False

    # Step 2: a branch scan must produce a visible branch analysis.
    branch_scan = harness.scan(_MINI_PROJECT_KEY, _PROBE_BRANCH)
    if not harness.branch_exists(_MINI_PROJECT_KEY, _PROBE_BRANCH):
        logger.error("self-test step 2 failed: branch analysis not visible")
        return False

    # Step 3: accept a main issue -> inheritance onto the branch (FK-33 §33.6.3).
    if main_scan.issue_keys:
        main_issue = main_scan.issue_keys[0]
        client.transition_issue(main_issue, "accept")
        if not harness.issue_accepted_on_branch(
            _MINI_PROJECT_KEY, _PROBE_BRANCH, main_issue
        ):
            logger.error("self-test step 3 failed: Accepted not inherited to branch")
            return False

    # Step 4: accept a branch issue -> stays consistent after merge/sync.
    if branch_scan.issue_keys:
        branch_issue = branch_scan.issue_keys[0]
        client.transition_issue(branch_issue, "accept")
        if not harness.issue_accepted_on_branch(
            _MINI_PROJECT_KEY, _MAIN_BRANCH, branch_issue
        ):
            logger.error("self-test step 4 failed: branch Accepted lost after sync")
            return False

    # Step 5: re-verify the quality gate by analysisId (never projectKey).
    return _gate_green_by_analysis_id(client, branch_scan.analysis_id)


def _gate_green_by_analysis_id(client: SonarClient, analysis_id: str) -> bool:
    body = client.project_status(analysis_id=analysis_id).json_body
    project_status = body.get("projectStatus")
    if not isinstance(project_status, dict):
        return False
    return project_status.get("status") == _GREEN


def _safe_delete(harness: ScannerHarness) -> None:
    try:
        harness.delete_project(_MINI_PROJECT_KEY)
    except (SonarApiError, OSError) as exc:  # cleanup must not mask the verdict
        logger.warning("self-test cleanup (delete project) failed: %s", exc)


__all__ = [
    "ScannerHarness",
    "SelfTestScan",
    "run_branch_plugin_conformance_self_test",
]
