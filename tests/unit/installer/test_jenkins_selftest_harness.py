"""Unit tests for the Jenkins-backed CP10d branch-plugin self-test harness."""

from __future__ import annotations

from dataclasses import dataclass, field

from agentkit.backend.installer.integration_checkpoints import (
    JenkinsBranchPluginSelfTestHarness,
    run_branch_plugin_conformance_self_test,
)
from agentkit.integration_clients.jenkins import JenkinsHttpResponse
from agentkit.integration_clients.sonar import SonarHttpResponse


@dataclass
class _FakeJenkins:
    result: str = "SUCCESS"
    report_task: str = "projectKey=ak3-selftest\nceTaskId=ce-1\n"
    scanner_version: str = "5.0.1"
    expose_scanner_version_action: bool = True
    triggered: list[dict[str, str]] = field(default_factory=list)

    def trigger_build(
        self, pipeline: str, *, parameters: dict[str, str]
    ) -> JenkinsHttpResponse:
        del pipeline
        self.triggered.append(parameters)
        return JenkinsHttpResponse(
            status_code=201,
            headers={"location": "http://jenkins/queue/item/7/"},
        )

    def queue_item(self, queue_id: int) -> JenkinsHttpResponse:
        del queue_id
        return JenkinsHttpResponse(
            status_code=200, json_body={"executable": {"number": 11}}
        )

    def build_status(self, pipeline: str, build_number: int) -> JenkinsHttpResponse:
        del pipeline, build_number
        actions = (
            [{"SONAR_SCANNER_VERSION": self.scanner_version}]
            if self.expose_scanner_version_action
            else []
        )
        return JenkinsHttpResponse(
            status_code=200,
            json_body={
                "building": False,
                "result": self.result,
                "actions": actions,
            },
        )

    def build_artifact(
        self, pipeline: str, build_number: int, artifact_path: str
    ) -> JenkinsHttpResponse:
        del pipeline, build_number
        if artifact_path == ".scannerwork/sonar-scanner-version.txt":
            return JenkinsHttpResponse(status_code=200, text_body=self.scanner_version)
        return JenkinsHttpResponse(status_code=200, text_body=self.report_task)


@dataclass
class _FakeSonar:
    branches: tuple[str, ...] = ("main", "ak3-selftest-branch")
    created: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    selected_gates: list[tuple[str, str]] = field(default_factory=list)
    issue_queries: list[dict[str, str]] = field(default_factory=list)

    def create_project(self, project_key: str, name: str) -> SonarHttpResponse:
        del name
        self.created.append(project_key)
        return SonarHttpResponse(status_code=200)

    def qualitygates_show(self, name: str) -> SonarHttpResponse:
        del name
        return SonarHttpResponse(status_code=200)

    def qualitygates_create(self, name: str) -> SonarHttpResponse:
        del name
        return SonarHttpResponse(status_code=200)

    def qualitygates_select(
        self, *, project_key: str, gate_name: str
    ) -> SonarHttpResponse:
        self.selected_gates.append((project_key, gate_name))
        return SonarHttpResponse(status_code=200)

    def delete_project(self, project_key: str) -> SonarHttpResponse:
        self.deleted.append(project_key)
        return SonarHttpResponse(status_code=200)

    def ce_task(self, ce_task_id: str) -> SonarHttpResponse:
        del ce_task_id
        return SonarHttpResponse(
            status_code=200,
            json_body={"task": {"status": "SUCCESS", "analysisId": "analysis-1"}},
        )

    def project_status(
        self, *, analysis_id: str | None = None, ce_task_id: str | None = None
    ) -> SonarHttpResponse:
        del analysis_id, ce_task_id
        return SonarHttpResponse(
            status_code=200, json_body={"projectStatus": {"status": "OK"}}
        )

    def project_branches(self, project_key: str) -> SonarHttpResponse:
        del project_key
        return SonarHttpResponse(
            status_code=200,
            json_body={"branches": [{"name": branch} for branch in self.branches]},
        )

    def search_issues(self, params: dict[str, str]) -> SonarHttpResponse:
        self.issue_queries.append(params)
        branch = params.get("branch", "main")
        issue_key = params.get("issues") or f"issue-{branch}"
        return SonarHttpResponse(
            status_code=200,
            json_body={"issues": [{"key": issue_key}]},
        )

    def transition_issue(self, issue_key: str, transition: str) -> SonarHttpResponse:
        del issue_key, transition
        return SonarHttpResponse(status_code=200)


def test_jenkins_harness_runs_conformance_through_ci() -> None:
    sonar = _FakeSonar()
    jenkins = _FakeJenkins()
    harness = JenkinsBranchPluginSelfTestHarness(
        sonar_client=sonar,  # type: ignore[arg-type]
        jenkins_client=jenkins,  # type: ignore[arg-type]
        pipeline="ak3-pre-merge",
        sleep=lambda _seconds: None,
    )

    assert run_branch_plugin_conformance_self_test(sonar, harness) is True  # type: ignore[arg-type]
    assert sonar.created == ["ak3-branch-plugin-conformance-selftest"]
    assert sonar.selected_gates == [
        (
            "ak3-branch-plugin-conformance-selftest",
            "AgentKit3 CP10d Self-Test Gate",
        ),
    ]
    assert sonar.deleted == ["ak3-branch-plugin-conformance-selftest"]
    accepted_queries = [
        query for query in sonar.issue_queries if "resolutions" in query
    ]
    assert accepted_queries
    assert all("issues" not in query for query in accepted_queries)
    assert jenkins.triggered == [
        {
            "agentkit_mode": "cp10d_branch_plugin_self_test",
            "sonar_project_key": "ak3-branch-plugin-conformance-selftest",
            "sonar_branch": "main",
        },
        {
            "agentkit_mode": "cp10d_branch_plugin_self_test",
            "sonar_project_key": "ak3-branch-plugin-conformance-selftest",
            "sonar_branch": "ak3-selftest-branch",
        },
    ]


def test_jenkins_harness_fails_conformance_on_failed_build() -> None:
    sonar = _FakeSonar()
    harness = JenkinsBranchPluginSelfTestHarness(
        sonar_client=sonar,  # type: ignore[arg-type]
        jenkins_client=_FakeJenkins(result="FAILURE"),  # type: ignore[arg-type]
        pipeline="ak3-pre-merge",
        sleep=lambda _seconds: None,
    )

    assert run_branch_plugin_conformance_self_test(sonar, harness) is False  # type: ignore[arg-type]
    assert sonar.deleted == ["ak3-branch-plugin-conformance-selftest"]


def test_jenkins_harness_accepts_scanner_version_artifact() -> None:
    sonar = _FakeSonar()
    jenkins = _FakeJenkins(expose_scanner_version_action=False)
    harness = JenkinsBranchPluginSelfTestHarness(
        sonar_client=sonar,  # type: ignore[arg-type]
        jenkins_client=jenkins,  # type: ignore[arg-type]
        pipeline="ak3-pre-merge",
        sleep=lambda _seconds: None,
    )

    assert run_branch_plugin_conformance_self_test(sonar, harness) is True  # type: ignore[arg-type]
