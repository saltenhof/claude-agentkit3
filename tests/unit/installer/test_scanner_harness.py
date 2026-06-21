"""Unit tests for the productive SonarClientScannerHarness (AG3-052 E5).

The conformance LOGIC (``run_branch_plugin_conformance_self_test``) runs for
real against the PRODUCTIVE ``SonarClientScannerHarness``; only the external
HTTP boundary (``SonarClient``) and the operational scanner runner (the LIVE
``sonar-scanner`` invocation, OOS §2.2) are stubbed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentkit.backend.installer.integration_checkpoints import (
    SelfTestScan,
    SonarClientScannerHarness,
    run_branch_plugin_conformance_self_test,
)
from agentkit.integration_clients.sonar import SonarHttpResponse


@dataclass
class _StubClient:
    branches: tuple[str, ...] = ("main", "ak3-selftest-branch")
    accepted_issue_keys: tuple[str, ...] = ()
    gate_status: str = "OK"
    created: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    transitioned: list[tuple[str, str]] = field(default_factory=list)

    def create_project(self, project_key: str, name: str) -> SonarHttpResponse:
        del name
        self.created.append(project_key)
        return SonarHttpResponse(status_code=200, json_body={})

    def delete_project(self, project_key: str) -> SonarHttpResponse:
        self.deleted.append(project_key)
        return SonarHttpResponse(status_code=200, json_body={})

    def project_branches(self, project_key: str) -> SonarHttpResponse:
        del project_key
        return SonarHttpResponse(
            status_code=200,
            json_body={"branches": [{"name": n} for n in self.branches]},
        )

    def search_issues(self, params: object) -> SonarHttpResponse:
        del params
        return SonarHttpResponse(
            status_code=200,
            json_body={"issues": [{"key": k} for k in self.accepted_issue_keys]},
        )

    def project_status(
        self, *, analysis_id: str | None = None, ce_task_id: str | None = None
    ) -> SonarHttpResponse:
        del analysis_id, ce_task_id
        return SonarHttpResponse(
            status_code=200, json_body={"projectStatus": {"status": self.gate_status}}
        )

    def transition_issue(self, issue_key: str, transition: str) -> SonarHttpResponse:
        self.transitioned.append((issue_key, transition))
        return SonarHttpResponse(status_code=200, json_body={})


def _runner(issue_keys: dict[str, tuple[str, ...]] | None = None):  # type: ignore[no-untyped-def]
    keys = issue_keys or {}

    def _run(project_key: str, branch: str) -> SelfTestScan:
        del project_key
        return SelfTestScan(
            analysis_id=f"AX-{branch}", branch=branch, issue_keys=keys.get(branch, ())
        )

    return _run


def test_harness_green_conformance_passes() -> None:
    client = _StubClient()
    harness = SonarClientScannerHarness(client=client, scan_runner=_runner())  # type: ignore[arg-type]
    assert run_branch_plugin_conformance_self_test(client, harness) is True  # type: ignore[arg-type]
    assert client.created == ["ak3-branch-plugin-conformance-selftest"]
    assert client.deleted == ["ak3-branch-plugin-conformance-selftest"]


def test_harness_branch_not_visible_fails() -> None:
    client = _StubClient(branches=("main",))
    harness = SonarClientScannerHarness(client=client, scan_runner=_runner())  # type: ignore[arg-type]
    assert run_branch_plugin_conformance_self_test(client, harness) is False  # type: ignore[arg-type]
    # Cleanup still runs even on a failing verdict.
    assert client.deleted == ["ak3-branch-plugin-conformance-selftest"]


def test_harness_accepted_inheritance_drives_transition_and_read() -> None:
    """Step 3/4: an accepted main issue must read as Accepted on the branch."""
    client = _StubClient(accepted_issue_keys=("ISSUE-1",))
    runner = _runner({"main": ("ISSUE-1",), "ak3-selftest-branch": ()})
    harness = SonarClientScannerHarness(client=client, scan_runner=runner)  # type: ignore[arg-type]
    assert run_branch_plugin_conformance_self_test(client, harness) is True  # type: ignore[arg-type]
    # The accept transition was actually issued for the main issue.
    assert ("ISSUE-1", "accept") in client.transitioned


def test_harness_accepted_not_inherited_fails() -> None:
    """If the Accepted issue does NOT read on the branch, the self-test fails."""
    client = _StubClient(accepted_issue_keys=())  # search returns no Accepted
    runner = _runner({"main": ("ISSUE-1",)})
    harness = SonarClientScannerHarness(client=client, scan_runner=runner)  # type: ignore[arg-type]
    assert run_branch_plugin_conformance_self_test(client, harness) is False  # type: ignore[arg-type]


def test_harness_red_main_scan_fails() -> None:
    client = _StubClient(gate_status="ERROR")
    harness = SonarClientScannerHarness(client=client, scan_runner=_runner())  # type: ignore[arg-type]
    assert run_branch_plugin_conformance_self_test(client, harness) is False  # type: ignore[arg-type]
