"""Unit tests for the branch-plugin conformance self-test runner (FK-50 CP 10d.2).

Only the external boundaries — the thin ``SonarClient`` HTTP client and the
``ScannerHarness`` provisioning surface — are stubbed (MOCKS-Ausnahme). The
conformance LOGIC (step ordering, analysisId quality-gate read,
Accepted-inheritance / merge-sync checks, fail-closed on any failed step,
cleanup) runs for real.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentkit.installer.integration_checkpoints.branch_plugin_self_test import (
    SelfTestScan,
    run_branch_plugin_conformance_self_test,
)
from agentkit.integrations.sonar import SonarApiError, SonarHttpResponse


@dataclass
class _StubClient:
    green_analysis_ids: frozenset[str] = field(default_factory=frozenset)
    transitioned: list[str] = field(default_factory=list)

    def project_status(
        self, *, analysis_id: str | None = None, ce_task_id: str | None = None
    ) -> SonarHttpResponse:
        del ce_task_id
        status = "OK" if analysis_id in self.green_analysis_ids else "ERROR"
        return SonarHttpResponse(
            status_code=200, json_body={"projectStatus": {"status": status}}
        )

    def transition_issue(self, issue_key: str, transition: str) -> SonarHttpResponse:
        del transition
        self.transitioned.append(issue_key)
        return SonarHttpResponse(status_code=200, json_body={})


@dataclass
class _StubHarness:
    main_scan: SelfTestScan
    branch_scan: SelfTestScan
    branch_visible: bool = True
    accepted_on_branch: bool = True
    accepted_on_main: bool = True
    deleted: bool = False
    create_raises: bool = False

    def create_project(self, project_key: str) -> None:
        del project_key
        if self.create_raises:
            raise SonarApiError("create failed")

    def scan(self, project_key: str, branch: str) -> SelfTestScan:
        del project_key
        return self.main_scan if branch == "main" else self.branch_scan

    def branch_exists(self, project_key: str, branch: str) -> bool:
        del project_key, branch
        return self.branch_visible

    def issue_accepted_on_branch(self, project_key: str, branch: str, issue_key: str) -> bool:
        del project_key, issue_key
        return self.accepted_on_main if branch == "main" else self.accepted_on_branch

    def delete_project(self, project_key: str) -> None:
        del project_key
        self.deleted = True


def _scan(analysis_id: str, branch: str, *, issues: tuple[str, ...] = ("I1",)) -> SelfTestScan:
    return SelfTestScan(analysis_id=analysis_id, branch=branch, issue_keys=issues)


def _harness(**kw: object) -> _StubHarness:
    defaults: dict[str, object] = {
        "main_scan": _scan("AX-main", "main"),
        "branch_scan": _scan("AX-branch", "ak3-selftest-branch"),
    }
    defaults.update(kw)
    return _StubHarness(**defaults)  # type: ignore[arg-type]


def _green_client() -> _StubClient:
    return _StubClient(green_analysis_ids=frozenset({"AX-main", "AX-branch"}))


class TestConformanceSelfTest:
    def test_all_steps_pass(self) -> None:
        harness = _harness()
        assert run_branch_plugin_conformance_self_test(_green_client(), harness) is True
        assert harness.deleted is True  # cleanup ran

    def test_main_not_green_fails(self) -> None:
        client = _StubClient(green_analysis_ids=frozenset())  # nothing green
        assert run_branch_plugin_conformance_self_test(client, _harness()) is False

    def test_branch_not_visible_fails(self) -> None:
        harness = _harness(branch_visible=False)
        assert run_branch_plugin_conformance_self_test(_green_client(), harness) is False

    def test_accepted_not_inherited_to_branch_fails(self) -> None:
        harness = _harness(accepted_on_branch=False)
        assert run_branch_plugin_conformance_self_test(_green_client(), harness) is False

    def test_branch_accept_lost_after_sync_fails(self) -> None:
        harness = _harness(accepted_on_main=False)
        assert run_branch_plugin_conformance_self_test(_green_client(), harness) is False

    def test_api_error_during_steps_is_fail_closed_and_cleans_up(self) -> None:
        harness = _harness(create_raises=True)
        assert run_branch_plugin_conformance_self_test(_green_client(), harness) is False
        assert harness.deleted is True  # cleanup still runs in finally

    def test_no_issues_skips_accept_steps_but_still_green(self) -> None:
        harness = _harness(
            main_scan=_scan("AX-main", "main", issues=()),
            branch_scan=_scan("AX-branch", "ak3-selftest-branch", issues=()),
        )
        assert run_branch_plugin_conformance_self_test(_green_client(), harness) is True
